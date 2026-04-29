"""
데이터 소스 공통 인터페이스.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, List, Dict, Any

import pandas as pd


@dataclass
class Quote:
    """최신 호가 스냅샷."""
    ticker: str
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    timestamp: str  # ISO8601
    last_price: Optional[float] = None


@dataclass
class OHLCVBar:
    """단일 OHLCV 바."""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class DataSource(Protocol):
    """데이터 소스 어댑터가 준수할 프로토콜."""

    name: str

    def get_ohlcv(self, ticker: str, period: str = "1y",
                  interval: str = "1d") -> pd.DataFrame:
        """
        과거 OHLCV DataFrame 반환.
        컬럼: Open, High, Low, Close, Volume (yfinance 호환).
        """
        ...

    def get_latest_price(self, ticker: str) -> Optional[float]:
        """최신 가격 (실패 시 None)."""
        ...

    def get_quote(self, ticker: str) -> Optional[Quote]:
        """최신 호가 (지원 안 하면 None)."""
        ...

    def health_check(self) -> Dict[str, Any]:
        """{"ok": bool, "latency_ms": int, "message": str}"""
        ...
