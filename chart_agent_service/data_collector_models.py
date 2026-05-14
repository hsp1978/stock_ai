"""
OHLCV 캐시 모델 및 예외 정의 (Step 3).
"""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

import pandas as pd

SourceName = Literal["yfinance", "fdr", "pykrx"]

# period → 대략적인 일수 매핑 (pykrx / FDR 날짜 계산용)
PERIOD_DAYS: dict[str, int] = {
    "1d": 2,
    "5d": 7,
    "1mo": 35,
    "3mo": 95,
    "6mo": 185,
    "1y": 370,
    "2y": 740,
    "5y": 1830,
    "10y": 3660,
    "ytd": 370,
    "max": 7300,
}

INTRADAY_PERIODS: frozenset[str] = frozenset(
    {"1m", "2m", "5m", "15m", "30m", "60m", "90m"}
)


class DataStaleError(Exception):
    """모든 데이터 소스가 실패했거나 데이터가 오래됨."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


def _compute_hash(df: pd.DataFrame) -> str:
    """OHLCV 데이터의 SHA256 해시 (16자 prefix)."""
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    raw = df[cols].to_csv(index=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass
class CacheEntry:
    """TTL 메타데이터를 포함한 OHLCV 캐시 엔트리."""

    ticker: str
    data: pd.DataFrame
    fetched_at: datetime
    source: SourceName
    auto_adjust: bool
    row_count: int
    latest_bar_date: date
    data_hash: str
    retry_count: int = 0

    @classmethod
    def build(
        cls,
        ticker: str,
        df: pd.DataFrame,
        source: SourceName,
        retry_count: int = 0,
    ) -> "CacheEntry":
        last_idx = df.index[-1]
        latest_bar_date = (
            last_idx.date()
            if hasattr(last_idx, "date")
            else date.fromisoformat(str(last_idx)[:10])
        )
        return cls(
            ticker=ticker.upper(),
            data=df.copy(),
            fetched_at=datetime.now(timezone.utc),
            source=source,
            auto_adjust=True,
            row_count=len(df),
            latest_bar_date=latest_bar_date,
            data_hash=_compute_hash(df),
            retry_count=retry_count,
        )
