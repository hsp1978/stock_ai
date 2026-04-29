"""
DryRun 브로커 - 주문을 생성·로깅만 하고 외부 API는 호출하지 않음.

Phase 2 운영 안정화 기간에 "만약 실제 LIVE였다면 어떤 주문이 제출됐을까?" 를
기록하는 용도. audit_log에 모든 시도를 남겨 나중에 검증 가능.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Any

from brokers.base import (
    BrokerInterface, OrderRequest, OrderResult,
    OrderStatus, OrderSide,
)


class DryRunBroker:
    """실제 주문 없이 로그만 남기는 브로커."""

    name = "dry_run"

    def __init__(self):
        self._orders: Dict[str, OrderRequest] = {}
        self._results: Dict[str, OrderResult] = {}

    def place_order(self, req: OrderRequest) -> OrderResult:
        """주문을 가상으로 '제출'하고 ACCEPTED 상태로 반환.

        주의: 실제 체결되지 않으므로 filled_qty=0, avg_fill_price=None.
        audit_log 에서 raw_response로 원 주문 스펙을 조회할 수 있음.
        """
        broker_order_id = f"DRY-{req.client_order_id}"
        self._orders[broker_order_id] = req

        result = OrderResult(
            success=True,
            status=OrderStatus.ACCEPTED,
            client_order_id=req.client_order_id,
            broker_order_id=broker_order_id,
            broker=self.name,
            filled_qty=0,
            avg_fill_price=None,
            error_message=None,
            raw_response={
                "mode": "dry_run",
                "note": "실제 주문 제출 없음. 감사 로그 전용.",
                "request": req.to_dict(),
                "logged_at": datetime.now().isoformat(),
            },
        )
        self._results[broker_order_id] = result
        return result

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        if broker_order_id not in self._orders:
            return OrderResult(
                success=False,
                status=OrderStatus.ERROR,
                client_order_id="",
                broker=self.name,
                error_message=f"주문 ID를 찾을 수 없음: {broker_order_id}",
            )
        req = self._orders[broker_order_id]
        result = OrderResult(
            success=True,
            status=OrderStatus.CANCELLED,
            client_order_id=req.client_order_id,
            broker_order_id=broker_order_id,
            broker=self.name,
            raw_response={"mode": "dry_run", "cancelled_at": datetime.now().isoformat()},
        )
        self._results[broker_order_id] = result
        return result

    def get_order_status(self, broker_order_id: str) -> OrderResult:
        if broker_order_id in self._results:
            return self._results[broker_order_id]
        return OrderResult(
            success=False,
            status=OrderStatus.ERROR,
            client_order_id="",
            broker=self.name,
            error_message=f"주문 ID를 찾을 수 없음: {broker_order_id}",
        )

    def get_positions(self) -> List[Dict[str, Any]]:
        """DryRun은 포지션 개념 없음. 빈 리스트 반환."""
        return []

    def get_account(self) -> Dict[str, Any]:
        return {
            "broker": self.name,
            "note": "DryRun 모드 — 실제 계좌 정보 아님",
            "simulated_orders_count": len(self._orders),
        }

    def is_market_open(self) -> bool:
        """DryRun은 항상 허용 (실험 목적)."""
        return True

    def health_check(self) -> Dict[str, Any]:
        return {"ok": True, "latency_ms": 0, "message": "DryRun broker — 항상 정상"}
