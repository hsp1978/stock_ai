"""KRX 펀더멘털 보강 테스트.

yfinance가 KDR 종목에서 결측/stale 재무 지표를 반환하는 문제(950170.KQ ROE
2.7% vs 공개 데이터 35%)에 대한 KRX 1차 소스 보강 검증.
"""

import json
import os
import sys
import types
from typing import Optional

import pandas as pd
import pytest

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

import krx_fundamentals  # noqa: E402
from krx_fundamentals import fetch_krx_fundamentals, is_krx_ticker  # noqa: E402


def _install_fake_pykrx(monkeypatch, df: Optional[pd.DataFrame]):
    fake_stock = types.ModuleType("pykrx.stock")
    fake_stock.get_market_fundamental = lambda start, end, code: df
    fake_pykrx = types.ModuleType("pykrx")
    fake_pykrx.stock = fake_stock
    monkeypatch.setitem(sys.modules, "pykrx", fake_pykrx)
    monkeypatch.setitem(sys.modules, "pykrx.stock", fake_stock)


def _krx_df(rows):
    """rows: list of dicts with BPS/PER/PBR/EPS/DIV/DPS."""
    df = pd.DataFrame(rows)
    df.index = pd.date_range("2026-06-25", periods=len(rows), freq="B")
    return df


def _set_credentials(monkeypatch):
    monkeypatch.setenv("KRX_ID", "user")
    monkeypatch.setenv("KRX_PW", "pw")


def test_is_krx_ticker():
    assert is_krx_ticker("950170.KQ")
    assert is_krx_ticker("005930.KS")
    assert not is_krx_ticker("AAPL")
    assert not is_krx_ticker(None)


def test_no_credentials_falls_back(monkeypatch):
    monkeypatch.delenv("KRX_ID", raising=False)
    monkeypatch.delenv("KRX_PW", raising=False)

    result = fetch_krx_fundamentals("950170.KQ")

    assert result["available"] is False
    assert "KRX_ID/KRX_PW" in result["reason"]


def test_non_krx_ticker_rejected(monkeypatch):
    _set_credentials(monkeypatch)
    result = fetch_krx_fundamentals("AAPL")
    assert result["available"] is False


def test_fetch_returns_roe_from_eps_bps(monkeypatch):
    _set_credentials(monkeypatch)
    _install_fake_pykrx(monkeypatch, _krx_df([
        {"BPS": 3413, "PER": 4.05, "PBR": 1.44, "EPS": 1212, "DIV": 2.0, "DPS": 100},
    ]))

    result = fetch_krx_fundamentals("950170.KQ")

    assert result["available"] is True
    assert result["per"] == pytest.approx(4.05)
    assert result["pbr"] == pytest.approx(1.44)
    assert result["roe"] == pytest.approx(1212 / 3413)  # ≈ 35.5%
    assert result["source"] == "krx"


def test_fetch_skips_zero_bps_rows(monkeypatch):
    _set_credentials(monkeypatch)
    _install_fake_pykrx(monkeypatch, _krx_df([
        {"BPS": 3400, "PER": 4.0, "PBR": 1.4, "EPS": 1200, "DIV": 2.0, "DPS": 100},
        {"BPS": 0, "PER": 0, "PBR": 0, "EPS": 0, "DIV": 0, "DPS": 0},  # 거래정지 행
    ]))

    result = fetch_krx_fundamentals("950170.KQ")

    assert result["available"] is True
    assert result["bps"] == pytest.approx(3400)


def test_fetch_handles_empty_dataframe(monkeypatch):
    _set_credentials(monkeypatch)
    _install_fake_pykrx(monkeypatch, pd.DataFrame())

    result = fetch_krx_fundamentals("950170.KQ")

    assert result["available"] is False


def test_fetch_handles_pykrx_exception(monkeypatch):
    _set_credentials(monkeypatch)
    fake_stock = types.ModuleType("pykrx.stock")

    def _boom(start, end, code):
        raise RuntimeError("Expecting value: line 1 column 1")

    fake_stock.get_market_fundamental = _boom
    fake_pykrx = types.ModuleType("pykrx")
    fake_pykrx.stock = fake_stock
    monkeypatch.setitem(sys.modules, "pykrx", fake_pykrx)

    result = fetch_krx_fundamentals("950170.KQ")

    assert result["available"] is False
    assert "KRX 조회 실패" in result["reason"]


# ── Value Investor 통합 ─────────────────────────────────────────


def _fake_yf(monkeypatch, info):
    class FakeTicker:
        def __init__(self, ticker):
            self.info = info

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)


def _value_agent(monkeypatch, llm_confidence=8.0):
    import multi_agent as ma

    agent = ma.ValueInvestor(llm_provider="test")
    monkeypatch.setattr(agent, "_get_stock_name_for_agent", lambda ticker: None)
    monkeypatch.setattr(
        agent,
        "_call_llm",
        lambda prompt: json.dumps(
            {"signal": "neutral", "confidence": llm_confidence,
             "reasoning": "재무 지표 기반 분석. 밸류에이션 검토 완료. 관망 판단."}
        ),
    )
    return agent


def test_value_investor_replaces_stale_yfinance_roe_with_krx(monkeypatch):
    """yfinance ROE 2.7% vs KRX 35.5% (3배 이상 괴리) → KRX 값 채택 + 품질 경고."""
    _set_credentials(monkeypatch)
    _install_fake_pykrx(monkeypatch, _krx_df([
        {"BPS": 3413, "PER": 4.05, "PBR": 1.44, "EPS": 1212, "DIV": 2.0, "DPS": 100},
    ]))
    _fake_yf(monkeypatch, {
        "trailingPE": None,  # yfinance 결측
        "priceToBook": None,
        "returnOnEquity": 0.027,  # stale
        "debtToEquity": 75.5,
        "profitMargins": 0.016,
        "currentPrice": 4910,
    })

    agent = _value_agent(monkeypatch)
    result = agent.analyze("950170.KQ", analysis_tools=None)

    tool_result = result.evidence[0]["result"]
    assert tool_result["roe"] == pytest.approx(1212 / 3413)
    assert tool_result["roe_source"] == "krx (yfinance 괴리로 대체)"
    assert tool_result["pe_ratio"] == pytest.approx(4.05)   # 결측 채움
    assert tool_result["pb_ratio"] == pytest.approx(1.44)
    assert any("괴리" in w for w in tool_result["data_quality_warnings"])
    assert result.confidence <= 4.0  # 품질 경고 → 신뢰도 캡


def test_value_investor_krx_fills_missing_roe_without_warning(monkeypatch):
    """yfinance ROE 결측이면 KRX 값으로 채우되 품질 경고는 아님 (소스 노트만)."""
    _set_credentials(monkeypatch)
    _install_fake_pykrx(monkeypatch, _krx_df([
        {"BPS": 3413, "PER": 4.05, "PBR": 1.44, "EPS": 1212, "DIV": 2.0, "DPS": 100},
    ]))
    _fake_yf(monkeypatch, {
        "trailingPE": None,
        "priceToBook": None,
        "returnOnEquity": None,
        "debtToEquity": 75.5,
        "profitMargins": 0.016,
        "currentPrice": 4910,
    })

    agent = _value_agent(monkeypatch)
    result = agent.analyze("950170.KQ", analysis_tools=None)

    tool_result = result.evidence[0]["result"]
    assert tool_result["roe"] == pytest.approx(1212 / 3413)
    assert tool_result["roe_source"] == "krx"
    assert not tool_result["data_quality_warnings"]
    assert any("KRX" in n for n in tool_result["data_source_notes"])
    assert result.confidence == pytest.approx(8.0)  # 캡 없음


def test_value_investor_us_ticker_skips_krx(monkeypatch):
    """미국 종목은 KRX 조회를 시도하지 않고 소스 노트도 남기지 않는다."""
    monkeypatch.delenv("KRX_ID", raising=False)
    monkeypatch.delenv("KRX_PW", raising=False)
    _fake_yf(monkeypatch, {
        "trailingPE": 20.0,
        "priceToBook": 5.0,
        "returnOnEquity": 0.25,
        "debtToEquity": 80.0,
        "profitMargins": 0.22,
        "currentPrice": 200.0,
    })

    agent = _value_agent(monkeypatch)
    result = agent.analyze("AAPL", analysis_tools=None)

    tool_result = result.evidence[0]["result"]
    assert tool_result["krx_fundamentals"]["available"] is False
    assert not any("KRX" in n for n in tool_result["data_source_notes"])
    assert tool_result["roe"] == pytest.approx(0.25)
