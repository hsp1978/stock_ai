"""
pykrx 외국인/공매도 + DART 공시 분석 도구 단위 테스트 (P2)

테스트 시나리오:
- 외국인 소진율 높고 상승 → BUY 신호
- 공매도 비율 높고 상승 → SELL 신호
- DART 호재 공시 우세 → BUY 신호
- DART 악재 공시 우세 → SELL 신호
- DART_API_KEY 없음 → neutral 안전 응답
- 미국 주식 → "한국 주식 전용" neutral 반환
"""

import os
import sys
from unittest.mock import patch

import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from analysis_tools import AnalysisTools  # noqa: E402


def _make_ohlcv(n: int = 50) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": 50_000, "High": 51_000, "Low": 49_000, "Close": 50_000, "Volume": 1_000_000},
        index=idx,
    )


# ── pykrx 외국인/공매도 도구 ─────────────────────────────────────────


def test_institutional_flow_us_stock_neutral():
    """미국 주식 → 한국 전용 도구이므로 neutral."""
    tools = AnalysisTools("AAPL", _make_ohlcv())
    result = tools.institutional_flow_analysis()
    assert result["signal"] == "neutral"
    assert "한국" in result["detail"]


def test_institutional_flow_high_foreign_buy():
    """외국인 소진율 높고 상승 → BUY 신호."""
    mock_foreign = {"exhaustion_rate": 92.0, "rate_change": 1.5, "trend": "increasing", "score": 4}
    mock_short = {"short_balance": 100, "short_ratio": 0.5, "ratio_change": -0.1, "trend": "decreasing", "score": 2}

    tools = AnalysisTools("005930.KS", _make_ohlcv())
    with patch("data_sources.pykrx_source.PykrxSource.get_foreign_holding_info", return_value=mock_foreign), \
         patch("data_sources.pykrx_source.PykrxSource.get_short_selling_info", return_value=mock_short):
        result = tools.institutional_flow_analysis()

    assert result["signal"] == "buy"
    assert result["score"] > 0


def test_institutional_flow_high_short_sell():
    """공매도 비율 높고 상승 → SELL 신호."""
    mock_foreign = {"exhaustion_rate": 40.0, "rate_change": -0.5, "trend": "decreasing", "score": 0}
    mock_short = {"short_balance": 5_000_000, "short_ratio": 6.0, "ratio_change": 0.8, "trend": "increasing", "score": -4}

    tools = AnalysisTools("005380.KS", _make_ohlcv())
    with patch("data_sources.pykrx_source.PykrxSource.get_foreign_holding_info", return_value=mock_foreign), \
         patch("data_sources.pykrx_source.PykrxSource.get_short_selling_info", return_value=mock_short):
        result = tools.institutional_flow_analysis()

    assert result["signal"] == "sell"
    assert result["score"] < 0


# ── DART 공시 분석 도구 ─────────────────────────────────────────────


def test_dart_disclosure_us_stock_neutral():
    """미국 주식 → 한국 전용 도구이므로 neutral."""
    tools = AnalysisTools("AAPL", _make_ohlcv())
    result = tools.dart_disclosure_analysis()
    assert result["signal"] == "neutral"
    assert "한국" in result["detail"]


def test_dart_no_api_key_neutral():
    """DART_API_KEY 없음 → neutral 안전 응답."""
    tools = AnalysisTools("005930.KS", _make_ohlcv())
    with patch.dict(os.environ, {"DART_API_KEY": ""}, clear=False):
        result = tools.dart_disclosure_analysis()
    assert result["signal"] == "neutral"
    assert result["score"] == 0


def test_dart_positive_disclosures_buy():
    """호재 공시 우세 → BUY 신호."""
    mock_disclosures = [
        {"report_nm": "자사주 취득 결정", "classified": "positive", "rcept_no": "1", "rcept_dt": "20260514", "corp_name": "삼성전자"},
        {"report_nm": "신규 계약 체결", "classified": "positive", "rcept_no": "2", "rcept_dt": "20260513", "corp_name": "삼성전자"},
        {"report_nm": "배당금 지급 결정", "classified": "positive", "rcept_no": "3", "rcept_dt": "20260512", "corp_name": "삼성전자"},
        {"report_nm": "사업보고서", "classified": "neutral", "rcept_no": "4", "rcept_dt": "20260511", "corp_name": "삼성전자"},
    ]
    tools = AnalysisTools("005930.KS", _make_ohlcv())
    with patch("dart_client.fetch_recent_disclosures", return_value=mock_disclosures):
        result = tools.dart_disclosure_analysis()

    assert result["signal"] == "buy"
    assert result["score"] > 0
    assert result["positive"] == 3


def test_dart_negative_disclosures_sell():
    """악재 공시 우세 → SELL 신호."""
    mock_disclosures = [
        {"report_nm": "유상증자 결정", "classified": "negative", "rcept_no": "1", "rcept_dt": "20260514", "corp_name": "테스트"},
        {"report_nm": "횡령 사실 확인", "classified": "negative", "rcept_no": "2", "rcept_dt": "20260513", "corp_name": "테스트"},
        {"report_nm": "영업정지 처분", "classified": "negative", "rcept_no": "3", "rcept_dt": "20260512", "corp_name": "테스트"},
    ]
    tools = AnalysisTools("005380.KS", _make_ohlcv())
    with patch("dart_client.fetch_recent_disclosures", return_value=mock_disclosures):
        result = tools.dart_disclosure_analysis()

    assert result["signal"] == "sell"
    assert result["score"] < 0
    assert result["negative"] == 3


# ── DART classify_disclosure 단위 테스트 ─────────────────────────────

def test_classify_disclosure_positive():
    """호재 키워드 포함 → positive."""
    from dart_client import classify_disclosure
    assert classify_disclosure("자사주 취득 결정") == "positive"
    assert classify_disclosure("배당금 지급 결정") == "positive"


def test_classify_disclosure_negative():
    """악재 키워드 포함 → negative."""
    from dart_client import classify_disclosure
    assert classify_disclosure("불성실공시법인 지정") == "negative"
    assert classify_disclosure("유상증자 결정") == "negative"


def test_classify_disclosure_neutral():
    """키워드 없으면 → neutral."""
    from dart_client import classify_disclosure
    assert classify_disclosure("사업보고서") == "neutral"
    assert classify_disclosure("주요사항보고서") == "neutral"


# ── 도구 등록 검증 ────────────────────────────────────────────────────

def test_new_tools_in_tool_map():
    """2개 신규 도구가 _tool_map에 등록됨."""
    from analysis_tools import ChartAnalysisAgent
    agent = ChartAnalysisAgent("005930.KS", _make_ohlcv())
    assert "institutional_flow_analysis" in agent._tool_map
    assert "dart_disclosure_analysis" in agent._tool_map
