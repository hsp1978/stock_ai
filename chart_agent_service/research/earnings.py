"""다음 실적 발표까지 남은 일수.

`stock_analyzer/enhanced_decision_maker.py` 의 실적 점검에서 옮겨 왔다 (그 모듈은 신호
판정용이라 폐기 대상). 거기서 고친 두 결함을 그대로 지킨다:

- yfinance `earningsTimestamp` 는 **직전** 실적일이다. 다음 실적일은
  `earningsTimestampStart`/`End` 에 있다 (2026-08 수정 전엔 임박 실적을 한 번도 못 잡았다).
- `timedelta.days` 는 음수에서 내림한다(-5.05일 → -6). 실수 일수를 쓴다.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

_CACHE_TTL_SEC = 12 * 3600
_cache: dict[str, tuple[float, Optional[float]]] = {}
_lock = threading.Lock()


def _market_tz(ticker: str) -> ZoneInfo:
    t = ticker.upper()
    return ZoneInfo("Asia/Seoul" if t.endswith((".KS", ".KQ")) else "America/New_York")


def days_to_next_earnings(
    info: dict[str, Any], ticker: str, now: Optional[datetime] = None
) -> Optional[float]:
    """yfinance info 에서 다음 실적일까지의 실수 일수. 미래 일정이 없으면 None."""
    tz = _market_tz(ticker)
    now_market = (now or datetime.now(timezone.utc)).astimezone(tz)

    def _days(ts: Any) -> Optional[float]:
        if not ts:
            return None
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None
        return (dt.astimezone(tz) - now_market).total_seconds() / 86400.0

    future = [
        d
        for d in (
            _days(info.get("earningsTimestampStart")),
            _days(info.get("earningsTimestampEnd")),
            _days(info.get("earningsTimestamp")),
        )
        if d is not None and d >= 0
    ]
    return min(future) if future else None


_EARNINGS_KEYS = ("earningsTimestampStart", "earningsTimestampEnd", "earningsTimestamp")


class EarningsDataMissing(LookupError):
    """소스가 이 종목의 실적일을 아예 주지 않는다 — '예정 없음'(None)과 다르다.

    실측(2026-10-08): yfinance 는 한국 종목(049430.KQ, 328130.KQ)에 실적 키를 주지 않는다.
    None 으로 돌려주면 '실적 일정 없음'으로 읽혀 임박 실적을 놓친다.
    """


def _yf_info(ticker: str) -> dict[str, Any]:
    import yfinance as yf

    return yf.Ticker(ticker).info or {}


def fetch_days_to_earnings(
    ticker: str, info_fetcher: Callable[[str], dict] = _yf_info
) -> Optional[float]:
    """캐시(12시간) 후 조회. 조회 실패는 예외로 올린다 — '일정 없음'(None)과 구분한다."""
    key = ticker.upper()
    now = time.time()
    with _lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL_SEC:
        cached_at, days = hit
        # 캐시 시점 이후 흐른 시간만큼 줄인다 — 12시간 묵은 'D-1' 은 사실 D-0.5 다
        return None if days is None else max(0.0, days - (now - cached_at) / 86400.0)
    info = info_fetcher(ticker)
    if not any(info.get(k) for k in _EARNINGS_KEYS):
        raise EarningsDataMissing(f"{key}: 실적일 데이터 없음 (소스 미제공)")
    days = days_to_next_earnings(info, ticker)
    with _lock:
        _cache[key] = (now, days)
    return days


def clear_cache() -> None:
    with _lock:
        _cache.clear()
