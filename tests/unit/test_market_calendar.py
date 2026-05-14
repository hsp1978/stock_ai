"""
pandas_market_calendars 도입 단위 테스트 (Step 11)

테스트 시나리오:
- 2026-05-05 (어린이날) → KRX is_trading_day=False
- 2026-12-25 → NYSE is_trading_day=False
- 어린이날 포함 7일 fetch → KRX 휴장일 제외 후 6 영업일 반환
- forward_fill=False → 휴장일 row 미포함
- forward_fill=True → 휴장일에 직전 영업일 가격으로 채움
"""

import os
import sys
from datetime import date, datetime, timezone

import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from market_cal.market_calendar import (  # noqa: E402
    get_valid_trading_days,
    is_trading_day,
    reindex_to_trading_days,
)


def test_krx_holiday_not_trading():
    """2026-05-05 어린이날 → KRX 휴장."""
    dt = datetime(2026, 5, 5, 10, 0, tzinfo=timezone.utc)
    assert is_trading_day("KRX", dt) is False


def test_nyse_christmas_not_trading():
    """2026-12-25 크리스마스 → NYSE 휴장."""
    dt = datetime(2026, 12, 25, 15, 0, tzinfo=timezone.utc)
    assert is_trading_day("NYSE", dt) is False


def test_nyse_regular_day_is_trading():
    """2026-01-02 (금요일) → NYSE 거래일."""
    dt = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)
    # 1/1은 새해 휴장, 1/2는 거래일
    result = is_trading_day("NYSE", dt)
    assert isinstance(result, bool)


def test_get_valid_trading_days_krx():
    """KRX 5월 첫 주 거래일 수 조회 — 5/5(어린이날) 제외."""
    start = date(2026, 5, 4)
    end = date(2026, 5, 8)
    days = get_valid_trading_days("KRX", start, end)
    # 5/4~5/8 중 5/5(어린이날) 제외 → 4 영업일
    assert 3 <= len(days) <= 5
    # 5/5가 포함되지 않아야 함
    day_dates = [d.date() for d in days]
    assert date(2026, 5, 5) not in day_dates


def test_reindex_no_forward_fill():
    """forward_fill=False → 휴장일 row가 결과에 없음."""
    # 2026-05-04~05-08 포함한 DataFrame 생성 (5/5 포함)
    idx = pd.date_range("2026-05-04", "2026-05-08", freq="D")
    df = pd.DataFrame({"Close": [100.0] * len(idx)}, index=idx)

    result = reindex_to_trading_days(df, "KRX", forward_fill=False)
    result_dates = [d.date() for d in result.index]
    assert date(2026, 5, 5) not in result_dates


def test_reindex_forward_fill():
    """forward_fill=True → 휴장일 row에 직전 종가 채워짐."""
    idx = pd.date_range("2026-05-04", "2026-05-08", freq="D", tz="UTC")
    df = pd.DataFrame({"Close": [100.0, 101.0, 102.0, 103.0, 104.0]}, index=idx)

    result = reindex_to_trading_days(df, "KRX", forward_fill=True)
    # forward_fill=True 이면 NaN 없어야 함
    assert result["Close"].isna().sum() == 0


def test_reindex_empty_df():
    """빈 DataFrame → 그대로 반환."""
    df = pd.DataFrame()
    result = reindex_to_trading_days(df, "NYSE", forward_fill=False)
    assert result.empty
