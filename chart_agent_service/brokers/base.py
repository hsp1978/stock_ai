"""
브로커 인터페이스 및 공통 데이터 구조.

모든 증권사 어댑터는 BrokerInterface를 준수하여
`service.py`/`order_router.py`가 동일한 API로 다룰 수 있게 함.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Protocol, List, Dict, Any


# 리터럴 대신 상수 문자열 사용 (Python 3.10+ Literal 호환 고려)
class OrderSide:
    BUY = "buy"
    SELL = "sell"


class OrderType:
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus:
    PENDING = "pending"        # 제출 전
    SUBMITTED = "submitted"    # 브로커에 제출됨
    ACCEPTED = "accepted"      # 브로커 수락
    FILLED = "filled"          # 전량 체결
    PARTIAL = "partial"        # 부분 체결
    CANCELLED = "cancelled"    # 취소됨
    REJECTED = "rejected"      # 브로커 거절
    ERROR = "error"            # 시스템 에러


class TimeInForce:
    DAY = "day"
    GTC = "gtc"    # Good-Till-Cancel
    IOC = "ioc"    # Immediate-Or-Cancel
    FOK = "fok"    # Fill-Or-Kill


def generate_client_order_id(ticker: str = "") -> str:
    """idempotency key 생성 — 10초 내 중복 주문 방지용."""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    prefix = (ticker or "ORD").replace(".", "").upper()[:6]
    return f"{prefix}-{ts}-{suffix}"


@dataclass
class OrderRequest:
    """
    브로커 중립적 주문 요청 스펙.

    모든 필드는 검증 전이며, safety.py와 broker에서 추가 검증됨.
    """
    ticker: str
    qty: int
    side: str                          # OrderSide.BUY | OrderSide.SELL
    order_type: str = OrderType.MARKET  # OrderType.*
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = TimeInForce.DAY
    client_order_id: Optional[str] = None  # 비어있으면 자동 생성
    # 메타데이터 (audit/트레이스용)
    source: str = "manual"             # "multi_agent" | "entry_plan" | "manual"
    reason: Optional[str] = None
    entry_plan_snapshot: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.client_order_id:
            self.client_order_id = generate_client_order_id(self.ticker)
        # 기본 검증
        if self.qty <= 0:
            raise ValueError(f"qty must be positive: {self.qty}")
        if self.side not in (OrderSide.BUY, OrderSide.SELL):
            raise ValueError(f"invalid side: {self.side}")
        if self.order_type not in (OrderType.MARKET, OrderType.LIMIT, OrderType.STOP, OrderType.STOP_LIMIT):
            raise ValueError(f"invalid order_type: {self.order_type}")
        if self.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and self.limit_price is None:
            raise ValueError(f"{self.order_type} requires limit_price")
        if self.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and self.stop_price is None:
            raise ValueError(f"{self.order_type} requires stop_price")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def estimated_cost(self) -> Optional[float]:
        """주문 예상 금액 (시장가는 None)."""
        price = self.limit_price or self.stop_price
        if price is None:
            return None
        return price * self.qty


@dataclass
class OrderResult:
    """
    주문 제출 결과.

    success=False여도 raw_response에 브로커 응답 보존.
    """
    success: bool
    status: str                        # OrderStatus.*
    client_order_id: str
    broker_order_id: Optional[str] = None
    broker: str = "unknown"            # "paper" | "dry_run" | "alpaca" | "kis"
    filled_qty: int = 0
    avg_fill_price: Optional[float] = None
    error_message: Optional[str] = None
    submitted_at: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.submitted_at is None:
            self.submitted_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BrokerInterface(Protocol):
    """
    증권사 어댑터가 준수해야 할 프로토콜.

    모든 메서드는 예외를 발생시키지 않고 OrderResult에 에러를 담아 반환.
    (네트워크 장애 등 복구 가능 에러를 상위에서 처리하기 위함)
    """

    name: str  # "paper" | "dry_run" | "alpaca" | "kis"

    def place_order(self, req: OrderRequest) -> OrderResult:
        """주문 제출."""
        ...

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        """주문 취소."""
        ...

    def get_order_status(self, broker_order_id: str) -> OrderResult:
        """주문 상태 조회."""
        ...

    def get_positions(self) -> List[Dict[str, Any]]:
        """현재 보유 포지션."""
        ...

    def get_account(self) -> Dict[str, Any]:
        """계좌 요약 (현금/자산/구매력)."""
        ...

    def is_market_open(self) -> bool:
        """거래 가능 시간 여부."""
        ...

    def health_check(self) -> Dict[str, Any]:
        """브로커 연결 상태. {"ok": bool, "latency_ms": int, "message": str}"""
        ...
