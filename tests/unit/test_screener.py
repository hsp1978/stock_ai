"""한국 주식 스크리너 회귀 테스트."""

import os
import sys
from datetime import datetime as real_datetime
from datetime import timedelta

import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import screener  # noqa: E402
from decision_context import build_decision_context  # noqa: E402


def _ohlcv(rows: int = 80, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=rows, freq="B")
    close = pd.Series([start + i * step for i in range(rows)], index=idx, dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=idx,
    )


def test_ma_alignment_uses_latest_row_not_full_column_nan():
    df = screener._calc_indicators_lite(_ohlcv(80))

    points, reason = screener._score_ma_alignment(df)

    assert points == screener.SCORE_WEIGHTS["ma_alignment"]
    assert reason == "MA 정배열"


def test_rsi_strong_uptrend_is_100_not_nan():
    df = screener._calc_indicators_lite(_ohlcv(40))

    assert df["RSI"].tail(3).notna().all()
    assert df["RSI"].iloc[-1] == 100.0


def test_calc_indicators_lite_adds_vwap_columns():
    df = screener._calc_indicators_lite(_ohlcv(80, step=0.0))

    assert {"VWAP_20", "VWAP_60", "VWAP_DIST_20", "VWAP_SLOPE_20"}.issubset(df.columns)
    assert round(df["VWAP_20"].iloc[-1], 3) == 100.0
    assert round(df["VWAP_DIST_20"].iloc[-1], 3) == 0.0


def test_vwap_support_scores_near_vwap():
    df = screener._calc_indicators_lite(_ohlcv(80, step=0.0))

    points, reason = screener._score_vwap_support(df)

    assert points == screener.SCORE_WEIGHTS["vwap_support"]
    assert "VWAP20 지지" in reason


def test_vwap_breakdown_penalizes_meaningful_break():
    raw = _ohlcv(80, step=0.0)
    close_loc = raw.columns.get_loc("Close")
    open_loc = raw.columns.get_loc("Open")
    high_loc = raw.columns.get_loc("High")
    low_loc = raw.columns.get_loc("Low")
    for offset, close in enumerate([99.0, 98.0, 97.0, 96.0, 95.0, 94.0]):
        row_idx = len(raw) - 6 + offset
        raw.iloc[row_idx, close_loc] = close
        raw.iloc[row_idx, open_loc] = close + 0.5
        raw.iloc[row_idx, high_loc] = close + 1.0
        raw.iloc[row_idx, low_loc] = close - 1.0
    df = screener._calc_indicators_lite(raw)

    points, reason = screener._penalty_vwap_breakdown(df)

    assert points == -screener.PENALTY_WEIGHTS["vwap_breakdown"]
    assert "VWAP20 하회" in reason


def test_macd_cross_ten_bars_ago_keeps_minimum_freshness_score():
    idx = pd.date_range("2025-01-01", periods=30, freq="B")
    df = pd.DataFrame(index=idx)
    df["MACD_signal"] = 0.0
    df["MACD"] = -1.0
    # _score_macd_cross는 tail(15)를 보며, 10봉 전 cross는 tail 위치 4→5 전환이다.
    df.iloc[-10:, df.columns.get_loc("MACD")] = 1.0

    points, reason = screener._score_macd_cross(df)

    assert round(points, 1) == 20.0
    assert reason == "골든크로스 10봉 전 발생"


def test_run_id_has_microsecond_resolution(monkeypatch):
    class FakeDateTime:
        calls = 0

        @classmethod
        def now(cls):
            cls.calls += 1
            return real_datetime(2026, 5, 19, 15, 35, 0) + timedelta(microseconds=cls.calls)

        @classmethod
        def fromisoformat(cls, value):
            return real_datetime.fromisoformat(value)

    monkeypatch.setattr(screener, "datetime", FakeDateTime)
    monkeypatch.setattr(screener, "load_kr_universe", lambda min_market_cap: pd.DataFrame())

    first = screener.run_screener(save_db=False)
    second = screener.run_screener(save_db=False)

    assert first["run_id"].endswith("_000001")
    assert second["run_id"].endswith("_000002")
    assert first["run_id"] != second["run_id"]


def test_naver_market_sum_page_parses_market_cap_100m():
    html = """
    <html><body>
      <table class="type_2">
        <tr>
          <td>1</td><td><a href="/item/main.naver?code=005930">삼성전자</a></td>
          <td>70,000</td><td>상승</td><td>1.0%</td><td>100</td>
          <td>2,500</td><td>5,969,783</td>
        </tr>
        <tr>
          <td>2</td><td><a href="/item/main.naver?code=000660">SK하이닉스</a></td>
          <td>180,000</td><td>하락</td><td>-1.0%</td><td>5,000</td>
          <td>1,999</td><td>728,002</td>
        </tr>
      </table>
      <table class="Nnavi"><tr><td><a href="/sise/sise_market_sum.naver?sosok=0&page=3">3</a></td></tr></table>
    </body></html>
    """

    rows, last_page = screener._parse_naver_market_sum_page(
        html,
        market_name="KOSPI",
        suffix=".KS",
        min_market_cap=200_000_000_000,
    )

    assert last_page == 3
    assert rows == [
        {
            "ticker": "005930.KS",
            "name": "삼성전자",
            "market": "KOSPI",
            "market_cap": 250_000_000_000.0,
        }
    ]


def test_korean_screener_keeps_pykrx_priority_without_yfinance_prefetch(monkeypatch):
    import data_collector
    import yfinance

    universe = pd.DataFrame(
        [
            {
                "ticker": "005930.KS",
                "name": "삼성전자",
                "market": "KOSPI",
                "market_cap": 400_000_000_000_000,
            }
        ]
    )
    prefetch_calls = []

    class FakeTicker:
        def __init__(self, ticker):
            self.ticker = ticker
            self.info = {}

    monkeypatch.setattr(screener, "load_kr_universe", lambda min_market_cap: universe)
    monkeypatch.setattr(data_collector, "clear_ohlcv_cache", lambda: None)
    monkeypatch.setattr(data_collector, "prefetch_ohlcv_batch", lambda tickers, period: prefetch_calls.append(tickers))
    monkeypatch.setattr(data_collector, "fetch_ohlcv", lambda ticker, period: _ohlcv(140))
    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)

    result = screener.run_screener(top_n=1, save_db=False)

    assert prefetch_calls == []
    assert result["analyzed_count"] == 1
    assert result["results"][0]["ticker"] == "005930.KS"
    assert result["results"][0]["horizon_days"] == 7
    assert result["results"][0]["decision_context"]["source"] == "screener"
    assert result["results"][0]["decision_context"]["role"] == "candidate_discovery"


def test_screener_multiagent_divergence_includes_reason_codes():
    agreement = screener._determine_agreement(
        "A",
        "neutral",
        3.0,
        screener_score=80.0,
        ma_decision={
            "final_signal": "neutral",
            "final_confidence": 3.0,
            "agreement_level": "low",
            "volatility_status": {"is_high": True},
            "key_risks": ["고변동성 구간"],
        },
        screener_row={"penalties": [{"name": "rsi_overbought"}]},
    )

    assert agreement["status"] == "divergent"
    assert agreement["level"] == "partial_match"
    assert agreement["horizon_days"] == 7
    assert agreement["primary"]["role"] == "candidate_discovery"
    assert agreement["secondary"]["role"] == "deep_validation"
    assert "AGENT_DISAGREEMENT" in agreement["reason_codes"]
    assert "HIGH_VOLATILITY" in agreement["reason_codes"]


def test_signal_aggregator_context_scales_conviction_and_wait_action():
    context = build_decision_context(
        source="signal_aggregator",
        role="execution",
        signal="wait",
        confidence=0.8,
        reasoning="execution decision",
    )

    assert context["signal"] == "neutral"
    assert context["confidence"] == 8.0


def test_screener_neutral_multiagent_sell_label_is_explicit():
    agreement = screener._determine_agreement(
        "D",
        "sell",
        8.0,
        screener_score=30.0,
        ma_decision={
            "final_signal": "sell",
            "final_confidence": 8.0,
            "reasoning": "risk-off",
        },
    )

    assert agreement["level"] == "aligned_weak"
    assert agreement["label"] == "MA 매도 확인"
    assert agreement["secondary"]["signal"] == "sell"
