"""가격 소스 교차검증 — 폴백은 '다른 값'을 잡지 못한다.

다중 소스 폴백은 한 소스가 **죽었을 때** 다른 소스로 넘어가는 장치다. 두 소스가
서로 **다른 값**을 줄 때는 아무것도 걸리지 않는다. 가격이 틀리면 Z-score·ATR·
지지저항·R/R 이 전부 무의미해진다.

2026-09 사후검증의 불일치 사례:
  DB손해보험  공식 IR ₩68,400(9/3) vs 외부 위젯 ₩202,000(9/2) — 약 3배
  PLTR       시스템 진입가 $147.12 vs 당일 실제 범위 $139.53~$146.50
  영원무역     현재가·진입가 필드 자체가 리포트에 없음

여기서 고정하는 것:
  1. 같은 거래일 종가가 임계 이상 어긋나면 mismatch 로 보고한다
  2. 거래일이 다르면 가격 차이가 아니라 **소스 지연**으로 따로 보고한다
  3. 2차 소스가 응답하지 않으면 'ok' 가 아니라 `single_source`(미검증)다
  4. 불일치가 분석을 죽이지 않는다 — 상태로 보고하고 게이트가 판단한다
  5. 현재가는 리포트 필수 필드다
"""

import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "../..")
# 순서 주의: chart_agent_service 가 sys.path 앞에 있어야 한다. 두 패키지에 같은 이름의
# 모듈(news_analyzer 등)이 있어서, stock_analyzer 가 앞서면 service.py import 가 깨진다.
for _p in (
    os.path.join(_ROOT, "stock_analyzer"),
    os.path.join(_ROOT, "chart_agent_service"),
):
    if _p not in sys.path:  # noqa: E402
        sys.path.insert(0, _p)

import data_collector as dc  # noqa: E402
from data_collector_models import CacheEntry  # noqa: E402


def _frame(close, bar_date, history=None):
    """bar_date 를 최신봉으로 하는 프레임. history 로 이전 날짜 종가를 덧붙인다."""
    rows = list(history or [])
    rows.append((bar_date, close))
    idx = pd.to_datetime([d for d, _ in rows])
    return pd.DataFrame({"Close": [c for _, c in rows]}, index=idx)


class _Source:
    def __init__(self, name, close=None, bar_date="2026-09-10", fail=False, history=None):
        self.name = name
        self._close = close
        self._bar_date = bar_date
        self._fail = fail
        self._history = history

    def get_ohlcv(self, ticker, period="1y"):
        if self._fail:
            raise ConnectionError(f"{self.name} down")
        if self._close is None:
            return pd.DataFrame()
        return _frame(self._close, self._bar_date, self._history)


def _verify(primary_close, primary_source, secondaries, ticker="PLTR",
            primary_date="2026-09-10", primary_history=None):
    entry = CacheEntry.build(
        ticker, _frame(primary_close, primary_date, primary_history), primary_source
    )

    with (
        patch.object(dc, "fetch_ohlcv_with_meta", lambda t, p=None: entry),
        patch.object(dc, "_secondary_sources", lambda t, n: secondaries),
    ):
        dc.clear_price_verification_cache()
        return dc.verify_latest_close(ticker, use_cache=False)


# ── 판정 ──────────────────────────────────────────────────────────


def test_agreeing_sources_are_ok():
    result = _verify(147.12, "yfinance", [_Source("fdr", 147.30)])

    assert result.status == "ok"
    assert result.is_mismatch is False
    assert result.diff_pct == pytest.approx(0.122, abs=0.01)
    assert "yfinance" in result.detail and "fdr" in result.detail


def test_threefold_discrepancy_is_mismatch():
    """DB손해보험 사례 — ₩68,400 vs ₩202,000."""
    result = _verify(68400.0, "toss", [_Source("yfinance", 202000.0)])

    assert result.status == "mismatch"
    assert result.is_mismatch is True
    assert result.diff_pct and result.diff_pct > 60
    assert "가격 기반 지표 신뢰 불가" in result.detail


def test_small_gap_within_tolerance_stays_ok():
    result = _verify(100.0, "toss", [_Source("pykrx", 101.5)])
    assert result.status == "ok"

    beyond = _verify(100.0, "toss", [_Source("pykrx", 103.0)])
    assert beyond.status == "mismatch"


def test_compares_on_the_latest_common_trading_day():
    """실측 회귀 — 미국 종목에서 Toss 는 KST 날짜, yfinance 는 미국장 날짜로
    최신봉을 라벨링한다(2026-09-11 vs 2026-09-10). '최신 vs 최신'을 비교하면
    **모든 미국 종목이 매일 불일치**로 잡혀 경고가 상시 켜진다.
    """
    result = _verify(
        160.0, "toss", [_Source("yfinance", 150.0, bar_date="2026-09-10")],
        primary_date="2026-09-11",
        primary_history=[("2026-09-10", 150.2)],   # 공통 거래일 09-10
    )

    assert result.status == "ok"                  # 상시 경고가 아니다
    assert result.compared_bar_date == "2026-09-10"
    assert result.diff_pct == pytest.approx(0.133, abs=0.01)
    assert "2026-09-10 종가 비교" in result.detail
    assert "최신봉" in result.detail              # 지연 사실은 함께 남는다


def test_mismatch_is_detected_on_the_common_day_even_with_lag():
    result = _verify(
        200.0, "toss", [_Source("yfinance", 68.0, bar_date="2026-09-10")],
        primary_date="2026-09-11",
        primary_history=[("2026-09-10", 202.0)],
    )

    assert result.status == "mismatch"
    assert result.compared_bar_date == "2026-09-10"
    assert "가격 기반 지표 신뢰 불가" in result.detail


def test_no_common_trading_day_is_reported_as_such():
    result = _verify(
        68400.0, "toss", [_Source("yfinance", 66000.0, bar_date="2026-03-02")]
    )

    assert result.status == "bar_date_mismatch"
    assert result.is_mismatch is True
    assert "공통 거래일 없음" in result.detail
    assert result.diff_pct is None


def test_no_secondary_source_is_unverified_not_ok():
    result = _verify(100.0, "toss", [_Source("yfinance", fail=True),
                                     _Source("fdr", close=None)])

    assert result.status == "single_source"
    assert "교차검증 불가" in result.detail
    assert "yfinance" in result.detail          # 실패 사유를 버리지 않는다


def test_primary_failure_is_unavailable():
    def _boom(ticker, period=None):
        raise dc.DataStaleError("all sources exhausted")

    with patch.object(dc, "fetch_ohlcv_with_meta", _boom):
        dc.clear_price_verification_cache()
        result = dc.verify_latest_close("PLTR", use_cache=False)

    assert result.status == "unavailable"
    assert "검증 불가" in result.detail


def test_result_is_cached_within_ttl():
    calls = []
    entry = CacheEntry.build("PLTR", _frame(100.0, "2026-09-10"), "toss")

    def _counted(ticker, period=None):
        calls.append(ticker)
        return entry

    with (
        patch.object(dc, "fetch_ohlcv_with_meta", _counted),
        patch.object(dc, "_secondary_sources", lambda t, n: [_Source("fdr", 100.1)]),
    ):
        dc.clear_price_verification_cache()
        first = dc.verify_latest_close("PLTR")
        second = dc.verify_latest_close("PLTR")

    assert first.status == second.status == "ok"
    assert len(calls) == 1          # 스캔마다 재검증하지 않는다


def test_secondary_source_excludes_the_primary():
    """1차 소스를 다시 물어보면 항상 일치한다 — 검증이 아니다."""
    names = [getattr(s, "name", "") for s in dc._secondary_sources("005930.KS", "pykrx")]
    assert "pykrx" not in names
    assert names, "한국 종목은 pykrx 외에 FDR/yfinance 가 남아야 한다"


# ── 리포트 표기 ───────────────────────────────────────────────────


def test_report_shows_current_price_and_mismatch_warning():
    from report_format import format_entry_plan_markdown

    decision = {
        "final_signal": "buy",
        "current_price": 68400.0,
        "price_verification": {
            "status": "mismatch",
            "detail": "toss 68,400.00 vs yfinance 202,000.00 (차이 66.14%)",
        },
        "entry_plan": {
            "order_type": "limit", "entry_timing": "immediate",
            "limit_price": 68000.0, "stop_loss": 64000.0, "take_profit": 76000.0,
        },
    }
    md = format_entry_plan_markdown("005830.KS", decision)

    assert "현재가" in md
    assert "소스 불일치" in md


def test_report_says_so_when_current_price_is_missing():
    """영원무역 사례 — 현재가 필드 자체가 없었다."""
    from report_format import format_entry_plan_markdown

    md = format_entry_plan_markdown("111770.KS", {
        "final_signal": "buy",
        "entry_plan": {"order_type": "limit", "entry_timing": "immediate",
                       "limit_price": 50000.0, "stop_loss": 47000.0},
    })

    assert "현재가" in md and "검산 불가" in md


def test_composite_score_carries_current_price():
    """리포트가 현재가를 싣도록 종합 결과에 포함한다."""
    from analysis_tools import ChartAnalysisAgent

    prices = [100.0 + i for i in range(60)]
    df = pd.DataFrame({"Close": prices, "High": prices, "Low": prices,
                       "Volume": [1000] * 60})
    agent = ChartAnalysisAgent.__new__(ChartAnalysisAgent)
    agent.ticker = "TEST"
    agent.df = df
    agent.tool_results = [
        {"tool": "trend_ma_analysis", "signal": "buy", "score": 3},
    ]

    composite = agent.compute_composite_score()
    assert composite["current_price"] == pytest.approx(159.0)


# ── ops 헬스 연동 ─────────────────────────────────────────────────


def test_data_health_flags_price_mismatch_as_degraded():
    import service

    verification = dc.PriceVerification(
        ticker="PLTR", status="mismatch", primary_source="toss",
        primary_close=68400.0, secondary_source="yfinance",
        secondary_close=202000.0, diff_pct=66.14, detail="불일치",
    )
    dc.clear_price_verification_cache()
    dc._store_verification(
        f"PLTR|{dc.DEFAULT_HISTORY_PERIOD}",
        dc.datetime.now(dc.timezone.utc),
        verification,
    )

    payload = service._price_verification_for("PLTR")
    assert payload["status"] == "mismatch"
    assert payload["diff_pct"] == 66.14

    # 캐시가 없는 티커는 None — 헬스체크가 네트워크를 새로 타지 않는다
    assert service._price_verification_for("NOCACHE") is None
