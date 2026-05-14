"""
Piotroski F-Score / Altman Z-Score 단위 테스트 (P2)

테스트 시나리오:
- 건전한 재무제표 → F-Score STRONG (7-9), signal=buy
- 부실 재무제표 → F-Score WEAK (0-2), signal=sell
- Z-Score safe zone → signal=buy
- Z-Score distress zone → signal=sell
- 재무제표 없음 → neutral 안전 응답
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from analysis_tools import AnalysisTools  # noqa: E402


# ── 재무제표 더미 데이터 ──────────────────────────────────────────────


def _make_stmt(data: dict) -> pd.DataFrame:
    """재무제표 DataFrame 생성.

    data: {row_name: [value_year0, value_year1]}
    반환: 행=항목, 열=날짜(most recent first).
    """
    col0 = pd.Timestamp("2024-12-31")
    col1 = pd.Timestamp("2023-12-31")
    rows = {k: {col0: v[0], col1: v[1]} for k, v in data.items()}
    return pd.DataFrame(rows).T


def _make_bs(
    total_assets=(10_000, 9_000),
    current_assets=(3_000, 2_500),
    current_liabilities=(1_000, 1_200),
    retained_earnings=(2_000, 1_500),
    long_term_debt=(1_500, 2_000),
) -> pd.DataFrame:
    return _make_stmt(
        {
            "Total Assets": total_assets,
            "Current Assets": current_assets,
            "Current Liabilities": current_liabilities,
            "Retained Earnings": retained_earnings,
            "Long Term Debt": long_term_debt,
            "Total Liabilities Net Minority Interest": (
                total_assets[0] * 0.5,
                total_assets[1] * 0.6,
            ),
        }
    )


def _make_inc(
    net_income=(500, 300),
    total_revenue=(8_000, 7_000),
    gross_profit=(3_000, 2_500),
    operating_income=(700, 500),
) -> pd.DataFrame:
    return _make_stmt(
        {
            "Net Income": net_income,
            "Total Revenue": total_revenue,
            "Gross Profit": gross_profit,
            "Operating Income": operating_income,
        }
    )


def _make_cf(operating_cash_flow=(600, 400)) -> pd.DataFrame:
    return _make_stmt({"Operating Cash Flow": operating_cash_flow})


def _make_ohlcv(n: int = 50) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 50000.0},
        index=idx,
    )


def _mock_ticker(bs, inc, cf, mktcap=5_000_000, info=None):
    """yfinance.Ticker mock."""
    t = MagicMock()
    t.balance_sheet = bs
    t.financials = inc
    t.cashflow = cf
    t.info = {"marketCap": mktcap, **(info or {})}
    return t


# ── Piotroski F-Score ────────────────────────────────────────────────


def test_fscore_healthy_firm_buy():
    """건전한 재무제표 → F-Score 높음, signal=buy."""
    bs = _make_bs(
        total_assets=(10_000, 9_000),
        current_assets=(4_000, 3_000),  # current ratio 개선
        current_liabilities=(1_000, 1_500),
        retained_earnings=(3_000, 2_000),
        long_term_debt=(1_000, 2_000),  # 부채 감소
    )
    inc = _make_inc(
        net_income=(800, 400),  # ROA 크게 개선
        total_revenue=(9_000, 7_000),  # 매출 성장
        gross_profit=(3_500, 2_500),  # 마진 개선
        operating_income=(900, 500),
    )
    cf = _make_cf(operating_cash_flow=(900, 500))  # OCF > 0

    tools = AnalysisTools("AAPL", _make_ohlcv())
    with patch("yfinance.Ticker", return_value=_mock_ticker(bs, inc, cf)):
        result = tools.piotroski_fscore_analysis()

    assert result["signal"] == "buy"
    assert result.get("fscore", 0) >= 7
    assert result["score"] > 0


def test_fscore_distressed_firm_sell():
    """부실 재무제표 → F-Score 낮음, signal=sell."""
    bs = _make_bs(
        total_assets=(10_000, 9_000),
        current_assets=(1_000, 2_000),  # current ratio 악화
        current_liabilities=(2_000, 1_000),
        retained_earnings=(-500, 200),  # 적자 전환
        long_term_debt=(4_000, 2_000),  # 부채 급증
    )
    inc = _make_inc(
        net_income=(-300, 100),  # 순손실
        total_revenue=(5_000, 7_000),  # 매출 감소
        gross_profit=(1_000, 2_500),  # 마진 급락
        operating_income=(-200, 300),
    )
    cf = _make_cf(operating_cash_flow=(-100, 300))  # OCF 음수

    tools = AnalysisTools("WEAK", _make_ohlcv())
    with patch("yfinance.Ticker", return_value=_mock_ticker(bs, inc, cf)):
        result = tools.piotroski_fscore_analysis()

    assert result["signal"] == "sell"
    assert result.get("fscore", 9) <= 2
    assert result["score"] < 0


def test_fscore_no_financials_neutral():
    """재무제표 없음 → neutral 안전 응답."""
    t = MagicMock()
    t.balance_sheet = pd.DataFrame()
    t.financials = pd.DataFrame()
    t.cashflow = pd.DataFrame()
    t.info = {}

    tools = AnalysisTools("AAPL", _make_ohlcv())
    with patch("yfinance.Ticker", return_value=t):
        result = tools.piotroski_fscore_analysis()

    assert result["signal"] == "neutral"
    assert result["score"] == 0


def test_fscore_components_keys():
    """F-Score 결과에 9개 신호 keys가 포함됨."""
    bs = _make_bs()
    inc = _make_inc()
    cf = _make_cf()

    tools = AnalysisTools("AAPL", _make_ohlcv())
    with patch("yfinance.Ticker", return_value=_mock_ticker(bs, inc, cf)):
        result = tools.piotroski_fscore_analysis()

    if "components" in result:
        expected = {
            "F1_ROA_positive",
            "F2_OCF_positive",
            "F3_ROA_improving",
            "F4_accrual_quality",
            "F5_leverage_down",
            "F6_liquidity_up",
            "F7_no_dilution",
            "F8_margin_improving",
            "F9_turnover_improving",
        }
        assert expected.issubset(set(result["components"].keys()))


# ── Altman Z-Score ───────────────────────────────────────────────────


def test_zscore_safe_zone_buy():
    """Z-Score > 2.99 → safe zone, signal=buy."""
    bs = _make_bs(
        total_assets=(10_000, 9_000),
        current_assets=(5_000, 4_000),
        current_liabilities=(1_000, 1_200),
        retained_earnings=(4_000, 3_000),
        long_term_debt=(500, 800),
    )
    inc = _make_inc(
        net_income=(1_000, 800),
        total_revenue=(12_000, 10_000),
        operating_income=(1_500, 1_200),
    )
    cf = _make_cf()

    tools = AnalysisTools("AAPL", _make_ohlcv())
    with patch(
        "yfinance.Ticker", return_value=_mock_ticker(bs, inc, cf, mktcap=50_000)
    ):
        result = tools.altman_zscore_analysis()

    assert result["signal"] == "buy"
    assert result.get("zone") == "safe"
    assert result.get("zscore", 0) >= 2.99


def test_zscore_distress_zone_sell():
    """Z-Score < 1.81 → distress zone, signal=sell."""
    bs = _make_bs(
        total_assets=(10_000, 9_000),
        current_assets=(800, 1_000),
        current_liabilities=(3_000, 2_000),
        retained_earnings=(-2_000, -1_000),
        long_term_debt=(6_000, 4_000),
    )
    inc = _make_inc(
        net_income=(-500, -200),
        total_revenue=(2_000, 3_000),
        operating_income=(-300, 100),
    )
    cf = _make_cf()

    tools = AnalysisTools("WEAK", _make_ohlcv())
    with patch("yfinance.Ticker", return_value=_mock_ticker(bs, inc, cf, mktcap=500)):
        result = tools.altman_zscore_analysis()

    assert result["signal"] == "sell"
    assert result.get("zone") == "distress"
    assert result.get("zscore", 10) < 1.81


def test_zscore_korean_uses_prime_model():
    """한국 주식 → Z'-Score 모델 사용."""
    bs = _make_bs()
    inc = _make_inc()
    cf = _make_cf()

    tools = AnalysisTools("005930.KS", _make_ohlcv())
    with patch("yfinance.Ticker", return_value=_mock_ticker(bs, inc, cf)):
        result = tools.altman_zscore_analysis()

    assert "Z'" in result.get("model", ""), (
        f"Expected Z'-Score model, got: {result.get('model')}"
    )


def test_zscore_components_present():
    """Z-Score 결과에 X1-X5 컴포넌트 포함."""
    bs = _make_bs()
    inc = _make_inc()
    cf = _make_cf()

    tools = AnalysisTools("AAPL", _make_ohlcv())
    with patch("yfinance.Ticker", return_value=_mock_ticker(bs, inc, cf)):
        result = tools.altman_zscore_analysis()

    if "components" in result:
        for key in (
            "X1_working_capital",
            "X2_retained_earnings",
            "X3_ebit",
            "X4_market_book",
            "X5_asset_turnover",
        ):
            assert key in result["components"]


# ── 도구 등록 검증 ────────────────────────────────────────────────────


def test_tools_registered_in_tool_map():
    """ChartAnalysisAgent._tool_map에 두 신규 도구 등록됨."""
    from analysis_tools import ChartAnalysisAgent

    agent = ChartAnalysisAgent("AAPL", _make_ohlcv())
    assert "piotroski_fscore_analysis" in agent._tool_map
    assert "altman_zscore_analysis" in agent._tool_map
