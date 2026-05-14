"""
KRX / NYSE 거래일 보정 유틸리티 (Step 11).

pandas_market_calendars를 사용해 휴장일을 제외한 영업일만 반환.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Literal

import pandas as pd
import pandas_market_calendars as mcal  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

MarketCode = Literal["KRX", "NYSE"]


@lru_cache(maxsize=2)
def get_calendar(market: MarketCode):
    """KRX/NYSE 캘린더 (LRU 캐시로 1회만 생성)."""
    code = "XKRX" if market == "KRX" else "NYSE"
    return mcal.get_calendar(code)


def get_valid_trading_days(
    market: MarketCode,
    start: date,
    end: date,
) -> pd.DatetimeIndex:
    """start~end 범위의 유효 거래일 DatetimeIndex (UTC 정규화)."""
    cal = get_calendar(market)
    schedule = cal.schedule(start_date=start, end_date=end)
    if schedule.empty:
        return pd.DatetimeIndex([])
    return mcal.date_range(schedule, frequency="1D").normalize().unique()


def reindex_to_trading_days(
    df: pd.DataFrame,
    market: MarketCode,
    forward_fill: bool = False,
) -> pd.DataFrame:
    """
    DataFrame을 유효 거래일만 남도록 reindex한다.

    forward_fill=False (기본): 휴장일 row 제거
    forward_fill=True        : 휴장일에 직전 영업일 가격 채움
    """
    if df.empty:
        return df
    start = df.index.min()
    end = df.index.max()
    if hasattr(start, "date"):
        start = start.date()
    if hasattr(end, "date"):
        end = end.date()
    valid = get_valid_trading_days(market, start, end)
    if valid.empty:
        return df
    # timezone 통일
    if df.index.tzinfo is None:
        valid = valid.tz_localize(None)
    else:
        valid = valid.tz_convert(df.index.tzinfo)
    result = df.reindex(valid)
    if forward_fill:
        result = result.ffill()
    return result


def is_trading_day(market: MarketCode, dt: datetime | None = None) -> bool:
    """dt가 해당 시장의 거래일인지 확인한다 (기본값: 현재 UTC)."""
    dt = dt or datetime.now(timezone.utc)
    cal = get_calendar(market)
    schedule = cal.schedule(start_date=dt.date(), end_date=dt.date())
    return not schedule.empty


def get_market_session(market: MarketCode, dt: datetime | None = None) -> str:
    """
    현재 시간 기준 시장 세션 상태를 반환한다.

    Returns:
        "pre_open" | "regular" | "post_close" | "closed"
    """
    dt = dt or datetime.now(timezone.utc)
    if not is_trading_day(market, dt):
        return "closed"

    cal = get_calendar(market)
    schedule = cal.schedule(start_date=dt.date(), end_date=dt.date())
    if schedule.empty:
        return "closed"

    mkt_open = schedule.iloc[0]["market_open"]
    mkt_close = schedule.iloc[0]["market_close"]

    # timezone 통일 (UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    mkt_open = mkt_open.to_pydatetime()
    mkt_close = mkt_close.to_pydatetime()
    if mkt_open.tzinfo is None:
        mkt_open = mkt_open.replace(tzinfo=timezone.utc)
    if mkt_close.tzinfo is None:
        mkt_close = mkt_close.replace(tzinfo=timezone.utc)

    if dt < mkt_open:
        return "pre_open"
    if dt <= mkt_close:
        return "regular"
    return "post_close"
