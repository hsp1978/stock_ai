"""
주문 라우터 — Multi-Agent의 entry_plan을 실제 OrderRequest로 변환하고,
TRADING_MODE에 따라 적절한 브로커/승인 큐로 전달.

핵심 흐름:
  entry_plan + account info → OrderRequest(들)
  → TradingSafety.require_all_checks
  → (paper/dry_run) 즉시 broker.place_order
  → (approval) 승인 큐에 적재 + 텔레그램 알림
  → (live) broker.place_order (Phase 2.2+)
  → AuditLog.log
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from brokers.base import (
    BrokerInterface, OrderRequest, OrderResult,
    OrderSide, OrderType, OrderStatus, TimeInForce,
    generate_client_order_id,
)
from brokers.factory import get_broker, get_trading_mode
from brokers.safety import get_safety, TradingSafety
from execution.approval_queue import get_approval_queue
from execution.audit_log import get_audit_log


@dataclass
class RoutingResult:
    """라우터 전체 처리 결과."""
    submitted_orders: List[OrderResult]
    queued_for_approval: List[int]   # approval_queue row ids
    blocked_by_safety: List[Tuple[OrderRequest, str]]
    trading_mode: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trading_mode": self.trading_mode,
            "submitted_count": len(self.submitted_orders),
            "queued_count": len(self.queued_for_approval),
            "blocked_count": len(self.blocked_by_safety),
            "submitted": [r.to_dict() for r in self.submitted_orders],
            "queued_ids": self.queued_for_approval,
            "blocked": [
                {"client_order_id": req.client_order_id, "ticker": req.ticker,
                 "reason": reason}
                for req, reason in self.blocked_by_safety
            ],
        }


class OrderRouter:
    """entry_plan → 브로커 주문 파이프라인."""

    def __init__(self,
                 broker: Optional[BrokerInterface] = None,
                 safety: Optional[TradingSafety] = None,
                 mode: Optional[str] = None):
        self.mode = (mode or get_trading_mode()).lower()
        self.broker = broker or get_broker(self.mode)
        self.safety = safety or get_safety()
        self.queue = get_approval_queue()
        self.audit = get_audit_log()

    # ─── entry_plan → OrderRequest 변환 ─────────────
    def build_requests_from_entry_plan(
        self,
        ticker: str,
        entry_plan: Dict[str, Any],
        account_size: Optional[float] = None,
        position_pct: Optional[float] = None,
        source: str = "multi_agent",
        reason: Optional[str] = None,
    ) -> List[OrderRequest]:
        """
        entry_plan의 분할 진입 전략을 OrderRequest 리스트로 변환.

        Args:
            entry_plan: {"order_type", "limit_price", "stop_loss", "take_profit",
                         "split_entry": [{"pct", "price", "trigger"}, ...]}
            account_size: 총 예수금 (미지정 시 브로커에서 조회)
            position_pct: 이 종목에 할당할 총 비중 (%). 미지정 시 MAX_POSITION_PCT의 절반

        Returns:
            분할 수만큼의 OrderRequest 리스트
        """
        if not entry_plan or entry_plan.get("entry_timing") == "wait":
            return []

        # 계좌/비중 결정
        if account_size is None:
            try:
                account = self.broker.get_account()
                account_size = float(
                    account.get("total_equity") or account.get("cash") or 0
                )
            except Exception:
                account_size = 0
        if account_size <= 0:
            return []

        if position_pct is None:
            position_pct = self.safety.max_position_pct / 2

        total_budget = account_size * (position_pct / 100)

        splits = entry_plan.get("split_entry") or []
        if not splits:
            # 분할 없는 경우 단일 주문
            splits = [{
                "pct": 100,
                "price": entry_plan.get("limit_price"),
                "trigger": "single entry",
            }]

        requests: List[OrderRequest] = []
        for i, split in enumerate(splits):
            pct = float(split.get("pct") or 0)
            if pct <= 0:
                continue
            price = split.get("price") or entry_plan.get("limit_price")
            if not price or price <= 0:
                continue

            tranche_budget = total_budget * (pct / 100)
            qty = int(tranche_budget / price)
            if qty <= 0:
                continue

            order_type_str = entry_plan.get("order_type", "limit")
            if order_type_str == "market":
                order_type = OrderType.MARKET
                limit_price = None
            else:
                order_type = OrderType.LIMIT
                limit_price = float(price)

            requests.append(OrderRequest(
                ticker=ticker,
                qty=qty,
                side=OrderSide.BUY,
                order_type=order_type,
                limit_price=limit_price,
                time_in_force=TimeInForce.DAY,
                client_order_id=generate_client_order_id(f"{ticker}T{i+1}"),
                source=source,
                reason=reason or f"Tranche {i+1}/{len(splits)}: {split.get('trigger', '')}",
                entry_plan_snapshot=entry_plan,
            ))

        return requests

    # ─── 메인 라우팅 ────────────────────────────────
    def route(self, order_requests: List[OrderRequest]) -> RoutingResult:
        """
        OrderRequest 리스트를 현재 TRADING_MODE에 따라 처리.
        """
        submitted: List[OrderResult] = []
        queued: List[int] = []
        blocked: List[Tuple[OrderRequest, str]] = []

        for req in order_requests:
            # 1) 안전 체크
            ok, reason = self.safety.require_all_checks(req)
            if not ok:
                self.audit.log(
                    req=req, result=None, trading_mode=self.mode,
                    safety_passed=False, safety_reason=reason,
                )
                blocked.append((req, reason))
                continue

            # 2) APPROVAL 모드: 큐에 적재
            if self.mode == "approval":
                try:
                    queue_id = self.queue.enqueue(req)
                    self.audit.log(
                        req=req, result=None, trading_mode=self.mode,
                        safety_passed=True, safety_reason=f"queued for approval (id={queue_id})",
                    )
                    queued.append(queue_id)
                    # 텔레그램 알림 (실패해도 무시)
                    self._notify_approval_pending(req, queue_id)
                except Exception as e:
                    result = OrderResult(
                        success=False, status=OrderStatus.ERROR,
                        client_order_id=req.client_order_id,
                        broker="approval_queue",
                        error_message=f"승인 큐 적재 실패: {e}",
                    )
                    submitted.append(result)
                continue

            # 3) paper/dry_run/live 모드: 브로커에 제출
            result = self._submit(req)
            submitted.append(result)

        return RoutingResult(
            submitted_orders=submitted,
            queued_for_approval=queued,
            blocked_by_safety=blocked,
            trading_mode=self.mode,
        )

    def _submit(self, req: OrderRequest) -> OrderResult:
        """브로커에 실제 제출 + 감사 로그 + 한도 카운터 업데이트."""
        try:
            result = self.broker.place_order(req)
        except Exception as e:
            result = OrderResult(
                success=False, status=OrderStatus.ERROR,
                client_order_id=req.client_order_id,
                broker=self.broker.name,
                error_message=f"브로커 예외: {e}",
            )

        self.audit.log(req=req, result=result, trading_mode=self.mode,
                       safety_passed=True, safety_reason="ok")

        if result.success:
            self.safety.record_successful_order(req)

        return result

    def execute_approved(self, queue_id: int) -> OrderResult:
        """
        APPROVAL 모드에서 사용자가 승인한 주문을 실제 브로커에 제출.
        승인 큐 → OrderRequest 복원 → 실제 브로커(paper 또는 live) 제출.
        """
        row = None
        for item in self.queue.get_pending():
            if item["id"] == queue_id:
                row = item
                break
        if not row:
            return OrderResult(
                success=False, status=OrderStatus.ERROR,
                client_order_id="",
                broker="approval_queue",
                error_message=f"큐에서 찾을 수 없음 (id={queue_id})",
            )

        # 승인 플래그 설정
        self.queue.approve(queue_id, responder="user")

        # 실제 실행용 브로커 — approval 모드 자체는 DryRun이지만
        # 승인 후에는 BROKER_NAME 또는 paper로 실행
        import os as _os
        exec_mode = _os.getenv("APPROVAL_EXEC_MODE", "paper")
        exec_broker = get_broker(exec_mode)

        req = self.queue.restore_request(row)
        try:
            result = exec_broker.place_order(req)
        except Exception as e:
            result = OrderResult(
                success=False, status=OrderStatus.ERROR,
                client_order_id=req.client_order_id,
                broker=exec_broker.name,
                error_message=f"승인 실행 중 예외: {e}",
            )

        self.audit.log(req=req, result=result, trading_mode=f"approval->{exec_mode}",
                       safety_passed=True, safety_reason="approved")
        if result.success:
            self.safety.record_successful_order(req)

        summary = f"{result.status} @ {result.avg_fill_price or req.limit_price or '?'}"
        self.queue.mark_executed(queue_id, result_summary=summary)

        return result

    # ─── 알림 ────────────────────────────────────────
    def _notify_approval_pending(self, req: OrderRequest, queue_id: int):
        """승인 대기 주문 알림 (텔레그램)."""
        try:
            from telegram_bot import send_telegram_html, inline_keyboard
            currency = "₩" if req.ticker.upper().endswith((".KS", ".KQ")) else "$"
            price_str = f"{currency}{req.limit_price:,.2f}" if req.limit_price else "시장가"
            text = (
                f"🔔 <b>주문 승인 요청</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>{req.ticker}</b> — {req.side.upper()} {req.qty}주 @ {price_str}\n"
                f"유형: {req.order_type}\n"
                f"출처: {req.source}\n"
                f"사유: {req.reason or '-'}\n"
                f"client_order_id: <code>{req.client_order_id}</code>\n"
                f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
            buttons = inline_keyboard([[
                {"text": "✅ 승인", "callback_data": f"approve:{queue_id}"},
                {"text": "❌ 거절", "callback_data": f"reject:{queue_id}"},
            ]])
            send_telegram_html(text, reply_markup=buttons)
        except Exception:
            pass  # 알림 실패는 큰 흐름을 막지 않음


# ─────────────────────────────────────────────────────────
#  편의 함수
# ─────────────────────────────────────────────────────────
def route_entry_plan(
    ticker: str,
    entry_plan: Dict[str, Any],
    account_size: Optional[float] = None,
    position_pct: Optional[float] = None,
    source: str = "multi_agent",
    reason: Optional[str] = None,
) -> RoutingResult:
    """
    entry_plan을 받아 한 번에 변환+라우팅.

    Multi-Agent 분석 완료 후 이 함수 한 번만 호출하면 현재 모드에 맞게 처리됨.
    """
    router = OrderRouter()
    requests = router.build_requests_from_entry_plan(
        ticker=ticker, entry_plan=entry_plan,
        account_size=account_size, position_pct=position_pct,
        source=source, reason=reason,
    )
    if not requests:
        return RoutingResult(
            submitted_orders=[], queued_for_approval=[],
            blocked_by_safety=[], trading_mode=router.mode,
        )
    return router.route(requests)
