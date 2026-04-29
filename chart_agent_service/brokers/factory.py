"""
브로커 팩토리 — TRADING_MODE 환경변수에 따라 적절한 어댑터 반환.

TRADING_MODE:
  paper    - PaperBroker (기본값)
  dry_run  - DryRunBroker
  approval - ApprovalBroker (2.1 후반부 + order_router 통합)
  live     - LIVE 모드 (Phase 2.2+ 에서 Alpaca/KIS 어댑터 반환)

LIVE 모드 사용 시 BROKER_NAME 환경변수로 구체적 증권사 선택:
  BROKER_NAME=alpaca
  BROKER_NAME=kis
"""
from __future__ import annotations

import os
from typing import Optional

from brokers.base import BrokerInterface


VALID_MODES = {"paper", "dry_run", "approval", "live"}


def get_trading_mode() -> str:
    """현재 TRADING_MODE 환경변수 반환. 유효하지 않으면 paper로 폴백."""
    mode = os.getenv("TRADING_MODE", "paper").lower()
    if mode not in VALID_MODES:
        return "paper"
    return mode


def get_broker(mode: Optional[str] = None) -> BrokerInterface:
    """
    현재 모드에 맞는 브로커 인스턴스 반환.

    Args:
        mode: 명시적으로 모드를 지정할 경우. None이면 환경변수 사용.
    """
    mode = (mode or get_trading_mode()).lower()

    if mode == "dry_run":
        from brokers.dry_run_broker import DryRunBroker
        return DryRunBroker()

    if mode == "approval":
        # Approval은 실제로 PaperBroker(또는 DryRun)을 감싸는 래퍼.
        # order_router에서 승인 큐를 관리하므로 여기서는 DryRunBroker 반환.
        # 승인 후 실제 실행 브로커는 별도로 결정됨.
        from brokers.dry_run_broker import DryRunBroker
        return DryRunBroker()

    if mode == "live":
        broker_name = os.getenv("BROKER_NAME", "").lower()
        if broker_name == "alpaca":
            try:
                from brokers.alpaca_broker import AlpacaBroker
                broker = AlpacaBroker()
                # 자격증명 없으면 dry_run으로 안전 폴백 (실수로 LIVE 설정 방지)
                if broker._credentials_present():
                    return broker
            except ImportError:
                pass
        if broker_name == "kis":
            try:
                from brokers.kis_broker import KISBroker  # type: ignore
                return KISBroker()
            except ImportError:
                pass
        # LIVE 요청인데 브로커 미구현/자격증명 없음 → DryRun 폴백 (안전)
        from brokers.dry_run_broker import DryRunBroker
        return DryRunBroker()

    # 기본: paper
    from brokers.paper_broker import PaperBroker
    return PaperBroker()
