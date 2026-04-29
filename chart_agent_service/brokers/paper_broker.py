"""
PaperBroker — 기존 paper_trader.py를 BrokerInterface로 감싼 어댑터.

실제 자금 이동 없이 시뮬레이션만 수행. 테스트/검증 용도.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Any

from brokers.base import (
    OrderRequest, OrderResult,
    OrderStatus, OrderSide, OrderType,
)


class PaperBroker:
    """paper_trader 모듈을 BrokerInterface로 감싼 어댑터."""

    name = "paper"

    def __init__(self):
        # 기존 paper_trader.py의 함수들 import
        # (주의: 순환 참조 방지 위해 런타임 import)
        pass

    def _execute(self, ticker: str, action: str, qty: int, price: float,
                 reason: str = "", **stops) -> Dict[str, Any]:
        from paper_trader import execute_paper_order
        return execute_paper_order(ticker, action, qty, price, reason, **stops)

    def place_order(self, req: OrderRequest) -> OrderResult:
        # market 주문이면 최신 가격 조회, limit이면 limit_price 사용
        price = req.limit_price
        if req.order_type == OrderType.MARKET:
            price = self._latest_price(req.ticker) or req.limit_price or 0

        if not price or price <= 0:
            return OrderResult(
                success=False,
                status=OrderStatus.ERROR,
                client_order_id=req.client_order_id,
                broker=self.name,
                error_message="체결 가격을 결정할 수 없음 (limit_price 또는 시장가 조회 필요)",
            )

        action = "BUY" if req.side == OrderSide.BUY else "SELL"
        entry_plan = req.entry_plan_snapshot or {}

        # paper_trader의 주문 실행 (trailing_stop 등 부가 정보 전달)
        order = self._execute(
            ticker=req.ticker,
            action=action,
            qty=req.qty,
            price=price,
            reason=req.reason or f"PaperBroker via {req.source}",
            stop_loss_price=float(entry_plan.get("stop_loss") or 0),
            take_profit_price=float(entry_plan.get("take_profit") or 0),
        )

        status_map = {
            "filled": OrderStatus.FILLED,
            "pending": OrderStatus.ACCEPTED,
            "rejected": OrderStatus.REJECTED,
        }
        order_status = order.get("status", "pending")
        mapped_status = status_map.get(order_status, OrderStatus.ACCEPTED)

        success = mapped_status not in (OrderStatus.REJECTED, OrderStatus.ERROR)

        return OrderResult(
            success=success,
            status=mapped_status,
            client_order_id=req.client_order_id,
            broker_order_id=f"PAPER-{req.client_order_id}",
            broker=self.name,
            filled_qty=order.get("qty", 0) if success else 0,
            avg_fill_price=price if success else None,
            error_message=order.get("reject_reason"),
            raw_response=order,
        )

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        # 페이퍼 브로커는 즉시 체결하므로 취소 개념 없음
        return OrderResult(
            success=False,
            status=OrderStatus.ERROR,
            client_order_id="",
            broker_order_id=broker_order_id,
            broker=self.name,
            error_message="PaperBroker는 즉시 체결하여 취소 불가",
        )

    def get_order_status(self, broker_order_id: str) -> OrderResult:
        # paper_trader는 order_history에 기록만, 주문 ID 추적 미지원
        return OrderResult(
            success=False,
            status=OrderStatus.ERROR,
            client_order_id="",
            broker_order_id=broker_order_id,
            broker=self.name,
            error_message="PaperBroker 상태 조회 미지원 (order_history 직접 참조)",
        )

    def get_positions(self) -> List[Dict[str, Any]]:
        from paper_trader import get_portfolio_status
        status = get_portfolio_status()
        positions = status.get("positions", {})
        return [
            {
                "ticker": ticker,
                "qty": p.get("qty"),
                "avg_entry_price": p.get("entry_price"),
                "current_price": p.get("current_price"),
                "unrealized_pnl": p.get("pnl"),
                "unrealized_pnl_pct": p.get("pnl_pct"),
                "entry_date": p.get("entry_date"),
            }
            for ticker, p in positions.items()
        ]

    def get_account(self) -> Dict[str, Any]:
        from paper_trader import get_portfolio_status
        status = get_portfolio_status()
        return {
            "broker": self.name,
            "total_equity": status.get("total_equity"),
            "cash": status.get("cash"),
            "position_value": status.get("position_value"),
            "total_pnl_pct": status.get("total_pnl_pct"),
            "open_positions": status.get("open_positions"),
            "win_rate_pct": status.get("win_rate_pct"),
        }

    def is_market_open(self) -> bool:
        # 페이퍼 브로커는 항상 허용
        return True

    def health_check(self) -> Dict[str, Any]:
        return {"ok": True, "latency_ms": 0, "message": "Paper broker — 항상 정상"}

    def _latest_price(self, ticker: str):
        """간단한 최신가 조회 (yfinance)."""
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            hist = t.history(period="1d")
            if hist is not None and not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            return None
        return None
