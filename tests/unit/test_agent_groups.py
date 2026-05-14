"""
에이전트 4-그룹 분할 단위 테스트 (EXECUTION_PLAN Step 8)

테스트 시나리오:
- 8 에이전트 mixed → 4 group 결과
- Technical 그룹 2명 모두 실패 → group neutral, error_count=2
- 3 그룹 SELL + 1 그룹 BUY → reflect inconsistent flag
- 그룹 내 confidence-weighted vote 정확성
"""

import os
import sys
from dataclasses import dataclass
from typing import Optional

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

from agent_groups import (  # noqa: E402
    AgentGroup,
    AGENT_TO_GROUP,
    GroupResult,
    aggregate_by_group,
    group_weighted_score,
    reflect,
)


# ── 더미 AgentResult ─────────────────────────────────────────────────


@dataclass
class FakeAgentResult:
    agent_name: str
    signal: str
    confidence: float
    error: Optional[str] = None
    reasoning: str = ""
    evidence: list = None
    llm_provider: str = "test"
    execution_time: float = 0.0

    def __post_init__(self):
        if self.evidence is None:
            self.evidence = []


def _make(name: str, signal: str, conf: float, error: Optional[str] = None):
    return FakeAgentResult(agent_name=name, signal=signal, confidence=conf, error=error)


# ── AGENT_TO_GROUP 매핑 검증 ─────────────────────────────────────────


def test_agent_to_group_covers_all_8_agents():
    """AGENT_TO_GROUP에 8개 에이전트가 모두 매핑됨."""
    assert len(AGENT_TO_GROUP) == 8
    groups = set(AGENT_TO_GROUP.values())
    assert AgentGroup.TECHNICAL in groups
    assert AgentGroup.FUNDAMENTAL in groups
    assert AgentGroup.MACRO in groups
    assert AgentGroup.RISK in groups


# ── aggregate_by_group ───────────────────────────────────────────────


def test_aggregate_by_group_4_groups():
    """8 에이전트 혼합 → 4개 그룹 결과 생성."""
    results = [
        _make("Technical Analyst", "buy", 8.0),
        _make("Quant Analyst", "buy", 7.0),
        _make("Value Investor", "sell", 5.0),
        _make("Decision Maker", "neutral", 4.0),
        _make("Event Analyst", "buy", 6.0),
        _make("Geopolitical Analyst", "neutral", 3.0),
        _make("Risk Manager", "sell", 7.0),
        _make("ML Specialist", "buy", 6.5),
    ]
    groups = aggregate_by_group(results)
    assert len(groups) == 4
    assert AgentGroup.TECHNICAL in groups
    assert AgentGroup.FUNDAMENTAL in groups
    assert AgentGroup.MACRO in groups
    assert AgentGroup.RISK in groups


def test_aggregate_technical_all_fail():
    """Technical 그룹 2명 모두 실패 → signal=neutral, error_count=2."""
    results = [
        _make("Technical Analyst", "buy", 0.0, error="timeout"),
        _make("Quant Analyst", "buy", 7.0, error="timeout"),
    ]
    groups = aggregate_by_group(results)
    tech = groups[AgentGroup.TECHNICAL]
    assert tech.signal == "neutral"
    assert tech.confidence == 0.0
    assert tech.error_count == 2
    assert tech.member_results == []


def test_weighted_vote_buy_majority():
    """Technical 그룹: BUY 2명(conf 8+7) → 그룹 신호 buy."""
    results = [
        _make("Technical Analyst", "buy", 8.0),
        _make("Quant Analyst", "buy", 7.0),
    ]
    groups = aggregate_by_group(results)
    tech = groups[AgentGroup.TECHNICAL]
    assert tech.signal == "buy"
    # avg_confidence = (8+7)/2 = 7.5
    assert abs(tech.confidence - 7.5) < 0.01


def test_weighted_vote_mixed_signals():
    """MACRO 그룹: buy(6)+neutral(3) → avg_score = (1.0*6 + 0*3)/(6+3) = 0.67 → buy."""
    results = [
        _make("Event Analyst", "buy", 6.0),
        _make("Geopolitical Analyst", "neutral", 3.0),
    ]
    groups = aggregate_by_group(results)
    macro = groups[AgentGroup.MACRO]
    assert macro.signal == "buy"


def test_weighted_vote_confidence_weighting():
    """MACRO 그룹: sell(high conf) vs buy(low conf) → sell이 우세."""
    results = [
        _make("Event Analyst", "sell", 9.0),
        _make("Geopolitical Analyst", "buy", 2.0),
    ]
    groups = aggregate_by_group(results)
    macro = groups[AgentGroup.MACRO]
    # avg_score = (-1*9 + 1*2)/(9+2) = -7/11 = -0.636 → sell
    assert macro.signal == "sell"


# ── reflect sanity check ─────────────────────────────────────────────


def test_reflect_3_sell_vs_final_buy():
    """3 그룹 SELL + 1 그룹 BUY, final=buy → REFLECT_INCONSISTENT 플래그."""
    group_results = {
        AgentGroup.TECHNICAL: GroupResult(
            group=AgentGroup.TECHNICAL,
            signal="sell",
            confidence=7.0,
            member_count=2,
            member_results=["Technical Analyst", "Quant Analyst"],
            error_count=0,
        ),
        AgentGroup.FUNDAMENTAL: GroupResult(
            group=AgentGroup.FUNDAMENTAL,
            signal="sell",
            confidence=6.0,
            member_count=2,
            member_results=["Value Investor"],
            error_count=0,
        ),
        AgentGroup.MACRO: GroupResult(
            group=AgentGroup.MACRO,
            signal="sell",
            confidence=5.0,
            member_count=2,
            member_results=["Event Analyst"],
            error_count=0,
        ),
        AgentGroup.RISK: GroupResult(
            group=AgentGroup.RISK,
            signal="buy",
            confidence=8.0,
            member_count=2,
            member_results=["ML Specialist"],
            error_count=0,
        ),
    }
    flags = reflect(group_results, "buy")
    assert "REFLECT_INCONSISTENT_3_SELL_VS_FINAL_BUY" in flags


def test_reflect_no_inconsistency():
    """3 그룹 BUY + 1 그룹 SELL, final=buy → 플래그 없음."""
    group_results = {
        AgentGroup.TECHNICAL: GroupResult(
            group=AgentGroup.TECHNICAL,
            signal="buy",
            confidence=7.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
        AgentGroup.FUNDAMENTAL: GroupResult(
            group=AgentGroup.FUNDAMENTAL,
            signal="buy",
            confidence=6.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
        AgentGroup.MACRO: GroupResult(
            group=AgentGroup.MACRO,
            signal="buy",
            confidence=5.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
        AgentGroup.RISK: GroupResult(
            group=AgentGroup.RISK,
            signal="sell",
            confidence=4.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
    }
    flags = reflect(group_results, "buy")
    assert flags == []


def test_reflect_3_buy_vs_final_sell():
    """3 그룹 BUY, final=sell → REFLECT_INCONSISTENT_3_BUY_VS_FINAL_SELL."""
    group_results = {
        AgentGroup.TECHNICAL: GroupResult(
            group=AgentGroup.TECHNICAL,
            signal="buy",
            confidence=8.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
        AgentGroup.FUNDAMENTAL: GroupResult(
            group=AgentGroup.FUNDAMENTAL,
            signal="buy",
            confidence=7.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
        AgentGroup.MACRO: GroupResult(
            group=AgentGroup.MACRO,
            signal="buy",
            confidence=6.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
        AgentGroup.RISK: GroupResult(
            group=AgentGroup.RISK,
            signal="neutral",
            confidence=5.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
    }
    flags = reflect(group_results, "sell")
    assert "REFLECT_INCONSISTENT_3_BUY_VS_FINAL_SELL" in flags


# ── group_weighted_score ─────────────────────────────────────────────


def test_group_weighted_score_uptrend():
    """STRONG_UPTREND 가중치: Technical(momentum ×1.5)이 유리."""
    group_results = {
        AgentGroup.TECHNICAL: GroupResult(
            group=AgentGroup.TECHNICAL,
            signal="buy",
            confidence=6.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
        AgentGroup.FUNDAMENTAL: GroupResult(
            group=AgentGroup.FUNDAMENTAL,
            signal="sell",
            confidence=4.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
    }
    uptrend_weights = {"momentum": 1.5, "mean_reversion": 0.3, "fundamental": 1.0}
    score = group_weighted_score(group_results, uptrend_weights)
    # Technical buy: 1.0 * 6.0 * 1.5 = 9.0
    # Fundamental sell: -1.0 * 4.0 * 1.0 = -4.0
    # total = 5.0
    assert abs(score - 5.0) < 0.01


def test_group_weighted_score_no_weights():
    """가중치 없으면 모두 1.0× 적용."""
    group_results = {
        AgentGroup.TECHNICAL: GroupResult(
            group=AgentGroup.TECHNICAL,
            signal="buy",
            confidence=5.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
        AgentGroup.RISK: GroupResult(
            group=AgentGroup.RISK,
            signal="sell",
            confidence=3.0,
            member_count=2,
            member_results=[],
            error_count=0,
        ),
    }
    score = group_weighted_score(group_results, None)
    # 1*5 + (-1)*3 = 2.0
    assert abs(score - 2.0) < 0.01
