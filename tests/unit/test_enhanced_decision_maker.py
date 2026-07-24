"""
EnhancedDecisionMaker consistency tests.

Focus:
- failed/zero-confidence agents must not dilute valid votes as neutral
- ML sell confidence must remain bearish in the numeric strength model
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

from enhanced_decision_maker import EnhancedDecisionMaker  # noqa: E402
from signal_normalizer import normalize_signal  # noqa: E402


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


def _result(name: str, signal: str, confidence: float, error: Optional[str] = None, evidence=None):
    return FakeAgentResult(
        agent_name=name,
        signal=signal,
        confidence=confidence,
        error=error,
        evidence=evidence or [],
    )


def _quiet_dm(monkeypatch) -> EnhancedDecisionMaker:
    dm = EnhancedDecisionMaker()
    monkeypatch.setattr(
        dm,
        "_check_fundamental_risks",
        lambda ticker: {"warnings": [], "critical_risks": []},
    )
    monkeypatch.setattr(dm, "_apply_confidence_smoothing", lambda value: value)
    # Avoid yfinance regime fetch during unit tests. The aggregate code catches import errors.
    monkeypatch.setitem(sys.modules, "regime.detector", None)
    return dm


def _neutral_decision(signal_counts, *args, **kwargs):
    return {
        "signal": "neutral",
        "confidence": 4.0,
        "conflicts": "없음",
        "reasoning": "unit test decision",
        "risks": [],
    }


def test_zero_confidence_agents_are_excluded_from_vote(monkeypatch):
    dm = _quiet_dm(monkeypatch)
    captured = {}

    def _capture_counts(signal_counts, *args, **kwargs):
        captured["signal_counts"] = dict(signal_counts)
        return _neutral_decision(signal_counts)

    monkeypatch.setattr(dm, "_make_final_decision", _capture_counts)

    output = dm.aggregate(
        "AAPL",
        [
            _result("Technical Analyst", "buy", 8.0),
            _result("Quant Analyst", "neutral", 0.0),
            _result("Risk Manager", "neutral", 0.0, error="timeout"),
        ],
    )

    assert captured["signal_counts"] == {"buy": 1, "sell": 0, "neutral": 0}
    assert output["signal_distribution"] == {"buy": 1, "sell": 0, "neutral": 0}
    assert output["valid_agent_count"] == 1
    assert output["excluded_failed_count"] == 2


def test_all_zero_confidence_agents_mark_system_failure_without_neutral_votes():
    dm = EnhancedDecisionMaker()

    output = dm.aggregate(
        "AAPL",
        [
            _result("Technical Analyst", "neutral", 0.0),
            _result("Quant Analyst", "neutral", 0.0),
        ],
    )

    assert output["system_failure"] is True
    assert output["signal_distribution"] == {"buy": 0, "sell": 0, "neutral": 0}
    assert output["valid_agent_count"] == 0
    assert output["excluded_failed_count"] == 2


def test_ml_sell_signal_contributes_negative_strength(monkeypatch):
    dm = _quiet_dm(monkeypatch)
    captured = {}

    def _capture_strength(signal_counts, signal_strength, *args, **kwargs):
        captured["signal_strength"] = signal_strength
        return _neutral_decision(signal_counts)

    monkeypatch.setattr(dm, "_make_final_decision", _capture_strength)

    dm.aggregate(
        "AAPL",
        [
            _result(
                "ML Specialist",
                "sell",
                8.0,
                evidence=[
                    {
                        "result": {
                            "ensemble": {
                                "models": {
                                    "model_a": {"test_accuracy": 0.62},
                                },
                            },
                        },
                    },
                ],
            ),
        ],
    )

    strength = captured["signal_strength"]
    assert strength["ml_adjusted"]["contribution"] < 0
    assert strength["total_score"] < 0


def test_signal_normalizer_handles_case_and_korean_variants():
    assert normalize_signal("STRONG_BUY") == "buy"
    assert normalize_signal("Bullish") == "buy"
    assert normalize_signal("매수") == "buy"
    assert normalize_signal("STRONG SELL") == "sell"
    assert normalize_signal("매도") == "sell"
    assert normalize_signal("resize") == "neutral"


def test_non_tool_agents_contribute_to_signal_strength(monkeypatch):
    dm = _quiet_dm(monkeypatch)
    captured = {}

    def _capture_strength(signal_counts, signal_strength, *args, **kwargs):
        captured["signal_strength"] = signal_strength
        return _neutral_decision(signal_counts)

    monkeypatch.setattr(dm, "_make_final_decision", _capture_strength)

    dm.aggregate(
        "AAPL",
        [
            _result("Value Investor", "SELL", 8.0),
            _result("Geopolitical Analyst", "SELL", 6.0),
            _result("Risk Manager", "SELL", 7.0),
            _result("Event Analyst", "BUY", 4.0),
        ],
    )

    domain = captured["signal_strength"]["domain_contributions"]
    assert domain["fundamental"] < 0
    assert domain["macro"] < 0
    assert domain["risk"] < 0
    assert domain["event"] > 0
    assert captured["signal_strength"]["total_score"] < 0


def test_reflect_guard_downgrades_final_signal_on_three_group_conflict(monkeypatch):
    dm = _quiet_dm(monkeypatch)

    def _forced_buy(signal_counts, *args, **kwargs):
        return {
            "signal": "buy",
            "confidence": 8.0,
            "conflicts": "없음",
            "reasoning": "forced buy for reflect guard test",
            "risks": [],
        }

    monkeypatch.setattr(dm, "_make_final_decision", _forced_buy)

    output = dm.aggregate(
        "AAPL",
        [
            _result("Technical Analyst", "sell", 8.0),
            _result("Value Investor", "sell", 8.0),
            _result("Event Analyst", "sell", 8.0),
            _result("Risk Manager", "neutral", 5.0),
        ],
    )

    assert output["final_signal"] == "neutral"
    assert output["final_confidence"] <= 3.0
    assert "REFLECT_INCONSISTENT_3_SELL_VS_FINAL_BUY" in output["reflect_flags"]


def _tech_quant_directions(dm, tech_score, quant_score):
    """Run _calculate_signal_strength with only tech/quant tool sums set."""
    tech_analysis = {
        "total_score": tech_score,
        "buy_count": 0,
        "sell_count": 0,
        "neutral_count": 0,
        "avg_strength": abs(tech_score),
    }
    quant_analysis = {
        "total_score": quant_score,
        "buy_count": 0,
        "sell_count": 0,
        "neutral_count": 0,
        "avg_strength": abs(quant_score),
    }
    strength = dm._calculate_signal_strength(
        tech_analysis, quant_analysis,
        risk_scores=[], ml_scores=[], event_scores=[],
    )
    return strength["technical"]["direction"], strength["quantitative"]["direction"]


def test_group_direction_deadzone_suppresses_noise_conflict():
    """미세한 반대 부호(±2 이내)는 방향 neutral → 기술/퀀트 충돌로 판정되지 않는다."""
    dm = EnhancedDecisionMaker()

    # 개별 도구는 전부 neutral(|score|<=2)인데 합계만 미세하게 엇갈리는 상황
    tech_dir, quant_dir = _tech_quant_directions(dm, tech_score=0.8, quant_score=-0.5)
    assert tech_dir == "neutral"
    assert quant_dir == "neutral"

    conflicts = []
    if tech_dir != quant_dir and tech_dir != "neutral" and quant_dir != "neutral":
        conflicts.append("충돌")
    assert conflicts == []


def test_group_direction_deadzone_boundary_is_exclusive():
    """정확히 ±2는 데드존 안(neutral), 초과해야 방향이 확정된다."""
    dm = EnhancedDecisionMaker()

    at_boundary_tech, at_boundary_quant = _tech_quant_directions(dm, 2.0, -2.0)
    assert at_boundary_tech == "neutral"
    assert at_boundary_quant == "neutral"

    beyond_tech, beyond_quant = _tech_quant_directions(dm, 2.1, -2.1)
    assert beyond_tech == "buy"
    assert beyond_quant == "sell"


def test_group_direction_real_conflict_still_reported():
    """양쪽 모두 데드존 초과로 뚜렷이 엇갈리면 충돌은 그대로 유지된다."""
    dm = EnhancedDecisionMaker()

    tech_dir, quant_dir = _tech_quant_directions(dm, tech_score=8.0, quant_score=-7.0)
    assert tech_dir == "buy"
    assert quant_dir == "sell"
    assert tech_dir != quant_dir


def test_final_decision_includes_shared_decision_context(monkeypatch):
    dm = _quiet_dm(monkeypatch)

    output = dm.aggregate(
        "AAPL",
        [
            _result(
                "Technical Analyst",
                "buy",
                8.0,
                evidence=[
                    {
                        "tool": "trend",
                        "result": {"score": 12.0, "signal": "buy"},
                    }
                ],
            ),
        ],
    )

    assert output["horizon_days"] == 7
    assert output["decision_schema_version"] == "decision_context.v1"
    assert output["decision_context"]["source"] == "multi_agent"
    assert output["decision_context"]["role"] == "deep_validation"
    assert output["decision_context"]["horizon_days"] == 7
    assert output["decision_context"]["signal"] == output["final_signal"]
