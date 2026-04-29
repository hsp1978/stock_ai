"""
증권사 브로커 어댑터 패키지 (Phase 2.1)

실행 모드:
  PAPER    - 내부 페이퍼 트레이더 (현재 기본값)
  DRY_RUN  - 주문을 생성·로깅만, 외부 API 호출 없음
  APPROVAL - 주문을 승인 큐에 넣고 사용자 승인 대기
  LIVE     - 실제 증권사 API로 주문 제출 (Phase 2.2+ 필요)

환경변수 TRADING_MODE로 선택.
"""
from brokers.base import (
    BrokerInterface,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderSide,
    OrderType,
)
from brokers.paper_broker import PaperBroker
from brokers.dry_run_broker import DryRunBroker
from brokers.safety import TradingSafety
from brokers.factory import get_broker, get_trading_mode

__all__ = [
    "BrokerInterface",
    "OrderRequest",
    "OrderResult",
    "OrderStatus",
    "OrderSide",
    "OrderType",
    "PaperBroker",
    "DryRunBroker",
    "TradingSafety",
    "get_broker",
    "get_trading_mode",
]
