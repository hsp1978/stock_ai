"""리포트 정합성 결함 수정 회귀 테스트.

레포트 검토에서 확인된 5건의 결함에 대한 회귀 방지:
1. 소수(1명) buy 의견이 최종 buy 신호를 결정하는 집계 모순
2. 종합 점수 산술 breakdown 누락 (ML 기여 미표기)
3. 리스크 요약이 에이전트 본문 리스크(켈리 음수, R/R, 지정학)를 누락
4. ML 확률 → 신뢰도 직접 매핑 (58.4% → 5.84/10 과대평가)
5. KRW 종목 detail 문자열의 '$' 하드코딩
"""

import json
import os
import re
import sys
import types
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
import pytest

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

from enhanced_decision_maker import EnhancedDecisionMaker  # noqa: E402


@dataclass
class FakeAgentResult:
    agent_name: str
    signal: str
    confidence: float
    error: Optional[str] = None
    evidence: list = field(default_factory=list)
    reasoning: str = ""
    llm_provider: str = "test"
    execution_time: float = 0.0


def _result(name, signal, confidence, evidence=None, error=None):
    return FakeAgentResult(
        agent_name=name,
        signal=signal,
        confidence=confidence,
        evidence=evidence or [],
        error=error,
    )


def _tool_evidence(tool, score, signal, **extra):
    result = {"score": score, "signal": signal}
    result.update(extra)
    return {"tool": tool, "result": result}


def _quiet_dm(monkeypatch) -> EnhancedDecisionMaker:
    dm = EnhancedDecisionMaker()
    monkeypatch.setattr(
        dm,
        "_check_fundamental_risks",
        lambda ticker: {"warnings": [], "critical_risks": []},
    )
    monkeypatch.setattr(dm, "_apply_confidence_smoothing", lambda value: value)
    monkeypatch.setitem(sys.modules, "regime.detector", None)
    return dm


def _report_scenario_agents():
    """리포트 재현: buy 1(ML 5.84) / neutral 6, 지표 점수 기술 +6 퀀트 +4."""
    return [
        _result(
            "Technical Analyst", "neutral", 6.0,
            evidence=[
                _tool_evidence("trend_ma_analysis", 4.0, "buy"),
                _tool_evidence("rsi_divergence_analysis", 2.0, "neutral"),
            ],
        ),
        _result(
            "Quant Analyst", "neutral", 6.5,
            evidence=[
                _tool_evidence("fibonacci_retracement_analysis", 4.0, "buy"),
                _tool_evidence(
                    "support_resistance_analysis", 0.0, "neutral",
                    risk_reward_ratio=0.2,
                ),
            ],
        ),
        _result(
            "Risk Manager", "neutral", 5.0,
            evidence=[
                _tool_evidence(
                    "kelly_criterion_analysis", -1.0, "neutral",
                    kelly_full_pct=-2.1, win_rate=0.445, win_loss_ratio=1.19,
                ),
            ],
        ),
        _result("ML Specialist", "buy", 5.84),
        _result("Event Analyst", "neutral", 5.0),
        _result(
            "Geopolitical Analyst", "neutral", 7.5,
            evidence=[
                {
                    "tool": "geopolitical_analysis",
                    "result": {"risks": ["KRW 환율 변동 리스크", "일본 소비재 수요 둔화"]},
                },
            ],
        ),
        _result(
            "Value Investor", "neutral", 8.0,
            evidence=[
                {
                    "tool": "value_investing_analysis",
                    "result": {"roe": 0.027, "debt_to_equity": 180.0},
                },
            ],
        ),
    ]


def test_single_minority_buy_cannot_set_final_buy(monkeypatch):
    """buy 1명 / neutral 6명 + 지표 총점 >5 에서도 최종 buy가 나오면 안 된다."""
    dm = _quiet_dm(monkeypatch)
    output = dm.aggregate("950170.KQ", _report_scenario_agents())

    assert output["final_signal"] == "neutral"
    assert output["signal_distribution"] == {"buy": 1, "sell": 0, "neutral": 6}


def test_score_breakdown_arithmetic_is_reconcilable(monkeypatch):
    """reasoning의 breakdown 성분 합이 종합 점수와 일치해야 한다."""
    dm = _quiet_dm(monkeypatch)
    output = dm.aggregate("950170.KQ", _report_scenario_agents())

    match = re.search(
        r"종합 점수: ([+-][\d.]+) = 기술 ([+-][\d.]+) \+ 퀀트 ([+-][\d.]+) "
        r"\+ ML ([+-][\d.]+) \+ 내부자 ([+-][\d.]+) \+ 도메인 ([+-][\d.]+)",
        output["reasoning"],
    )
    assert match, f"breakdown 형식 불일치: {output['reasoning']}"
    total = float(match.group(1))
    parts = sum(float(match.group(i)) for i in range(2, 7))
    # 각 성분이 소수 1자리로 반올림되므로 오차 허용
    assert abs(total - parts) < 0.3


def test_agent_reported_risks_promoted_to_key_risks(monkeypatch):
    """켈리 음수·R/R 열위·지정학·밸류 리스크가 핵심 리스크에 반영돼야 한다."""
    dm = _quiet_dm(monkeypatch)
    output = dm.aggregate("950170.KQ", _report_scenario_agents())

    risks = output["key_risks"]
    joined = " | ".join(risks)
    assert "특별한 리스크 없음" not in risks
    assert "켈리 비중 음수" in joined
    assert "손익비 불리" in joined
    assert "지정학: KRW 환율 변동 리스크" in joined
    assert "저ROE" in joined
    assert "높은 부채비율" in joined


def test_negative_kelly_gates_buy_confidence(monkeypatch):
    """다수결 buy라도 켈리 음수면 신뢰도 상한 3.0 + 경고를 남긴다."""
    dm = _quiet_dm(monkeypatch)
    agents = [
        _result(
            "Technical Analyst", "buy", 8.0,
            evidence=[_tool_evidence("trend_ma_analysis", 8.0, "buy")],
        ),
        _result(
            "Quant Analyst", "buy", 7.0,
            evidence=[_tool_evidence("momentum_rank_analysis", 6.0, "buy")],
        ),
        _result(
            "Risk Manager", "neutral", 5.0,
            evidence=[
                _tool_evidence(
                    "kelly_criterion_analysis", -1.0, "neutral",
                    kelly_full_pct=-2.1, win_rate=0.445, win_loss_ratio=1.19,
                ),
            ],
        ),
    ]
    output = dm.aggregate("AAPL", agents)

    assert output["final_signal"] == "buy"
    assert output["final_confidence"] <= 3.0
    assert "KELLY_NEGATIVE_NO_BET" in (output["warnings"] or [])


def test_two_supporting_agents_can_still_set_buy(monkeypatch):
    """정상 케이스: 매수 2명 + 가중 우세 + 점수 >5 이면 buy 유지 (과차단 방지)."""
    dm = _quiet_dm(monkeypatch)
    agents = [
        _result(
            "Technical Analyst", "buy", 7.0,
            evidence=[_tool_evidence("trend_ma_analysis", 5.0, "buy")],
        ),
        _result(
            "Quant Analyst", "buy", 6.0,
            evidence=[_tool_evidence("momentum_rank_analysis", 4.0, "buy")],
        ),
        _result("Risk Manager", "neutral", 5.0),
        _result("Event Analyst", "neutral", 5.0),
        _result("Value Investor", "neutral", 5.0),
    ]
    output = dm.aggregate("AAPL", agents)

    assert output["final_signal"] == "buy"


# ── ML Specialist 신뢰도 캘리브레이션 ──────────────────────────


def _install_fake_ml_pipeline(monkeypatch, up_probability, avg_accuracy=0.62):
    fake_ml = types.ModuleType("ml_pipeline_fix")

    def enhanced_ml_ensemble(ticker, df, debug=False):
        return {
            "ensemble": {
                "prediction": "UP",
                "up_probability": up_probability,
                "model_count": 5,
                "avg_accuracy": avg_accuracy,
                "models": {},
            },
            "warnings": [],
        }

    fake_ml.enhanced_ml_ensemble = enhanced_ml_ensemble
    monkeypatch.setitem(sys.modules, "ml_pipeline_fix", fake_ml)

    fake_dc = types.ModuleType("data_collector")
    fake_dc.fetch_ohlcv = lambda ticker: pd.DataFrame({"Close": [1.0]})
    fake_dc.calculate_indicators = lambda df: df
    monkeypatch.setitem(sys.modules, "data_collector", fake_dc)


def test_ml_confidence_capped_by_probability_edge(monkeypatch):
    """상승확률 58.4%는 엣지 8.4%뿐 — 신뢰도 5.84가 아닌 1.7로 캘리브레이션."""
    from multi_agent import MLSpecialist

    _install_fake_ml_pipeline(monkeypatch, up_probability=0.584)

    agent = MLSpecialist(llm_provider="test")
    monkeypatch.setattr(agent, "_get_stock_name_for_agent", lambda ticker: None)
    monkeypatch.setattr(
        agent,
        "_call_llm",
        lambda prompt: json.dumps(
            {"signal": "buy", "confidence": 5.84, "reasoning": "확률 58.4%로 상승 예상. 모델 5개 합의. 정확도 양호."}
        ),
    )

    result = agent.analyze("AAPL", analysis_tools=None)

    assert result.confidence == pytest.approx(1.7, abs=0.05)
    assert "캘리브레이션" in result.reasoning


def test_ml_confidence_within_edge_not_modified(monkeypatch):
    """확률 엣지 이내의 신뢰도는 하향하지 않는다."""
    from multi_agent import MLSpecialist

    _install_fake_ml_pipeline(monkeypatch, up_probability=0.80)

    agent = MLSpecialist(llm_provider="test")
    monkeypatch.setattr(agent, "_get_stock_name_for_agent", lambda ticker: None)
    monkeypatch.setattr(
        agent,
        "_call_llm",
        lambda prompt: json.dumps(
            {"signal": "buy", "confidence": 5.0, "reasoning": "확률 80%로 강한 상승 신호. 모델 합의 견고. 정확도 우수."}
        ),
    )

    result = agent.analyze("AAPL", analysis_tools=None)

    assert result.confidence == pytest.approx(5.0)
    assert "캘리브레이션" not in result.reasoning


# ── Value Investor 데이터 품질 교차검증 ─────────────────────────


def test_value_investor_flags_inconsistent_roe(monkeypatch):
    """ROE 2.7% vs PBR/PER 암시 ROE 35% 괴리 시 데이터 품질 경고 + 신뢰도 캡."""
    import multi_agent as ma

    class FakeTicker:
        def __init__(self, ticker):
            self.info = {
                "trailingPE": 4.05,
                "forwardPE": 4.0,
                "priceToBook": 1.44,
                "returnOnEquity": 0.027,  # 암시 ROE 35.6% 대비 13배 괴리
                "debtToEquity": 40.0,
                "profitMargins": 0.016,
                "currentPrice": 4910,
            }

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    agent = ma.ValueInvestor(llm_provider="test")
    monkeypatch.setattr(agent, "_get_stock_name_for_agent", lambda ticker: None)
    monkeypatch.setattr(
        agent,
        "_call_llm",
        lambda prompt: json.dumps(
            {"signal": "buy", "confidence": 8.0, "reasoning": "PER 4배 저평가. 재무 건전. 안전마진 충분."}
        ),
    )

    result = agent.analyze("950170.KQ", analysis_tools=None)

    tool_result = result.evidence[0]["result"]
    assert tool_result["data_quality_warnings"], "ROE 괴리 경고가 있어야 한다"
    assert tool_result["implied_roe"] == pytest.approx(1.44 / 4.05, rel=1e-6)
    assert result.confidence <= 4.0
    assert "데이터 품질 경고" in result.reasoning


# ── 통화 포맷 ────────────────────────────────────────────────


def _sample_ohlcv(rows=130, base=5000.0):
    rng = np.random.default_rng(42)
    closes = base + np.cumsum(rng.normal(0, 30, rows))
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 50,
            "Low": closes - 50,
            "Close": closes,
            "Volume": rng.integers(10_000, 100_000, rows).astype(float),
        },
        index=pd.date_range("2025-01-01", periods=rows, freq="B"),
    )
    return df


def test_fibonacci_detail_uses_krw_for_korean_ticker():
    from analysis_tools import AnalysisTools

    tools = AnalysisTools("950170.KQ", _sample_ohlcv())
    result = tools.fibonacci_retracement_analysis()

    assert "$" not in result["detail"], result["detail"]
    assert "₩" in result["detail"]


def test_fibonacci_detail_uses_usd_for_us_ticker():
    from analysis_tools import AnalysisTools

    tools = AnalysisTools("AAPL", _sample_ohlcv(base=200.0))
    result = tools.fibonacci_retracement_analysis()

    assert "$" in result["detail"]
    assert "₩" not in result["detail"]
