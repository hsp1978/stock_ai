"""
에이전트 4-그룹 분할 (Step 8).

Technical / Fundamental / Macro / Risk 4개 도메인 그룹으로 8개 에이전트를 분할.
그룹 내 confidence-weighted vote → GroupResult.
한 도메인 에이전트 실패에도 다른 그룹 신호는 유지.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal, TypedDict

import numpy as np

if TYPE_CHECKING:
    from multi_agent import AgentResult


class AgentGroup(str, Enum):
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    MACRO = "macro"
    RISK = "risk"


# 에이전트 이름 → 그룹 매핑
AGENT_TO_GROUP: dict[str, AgentGroup] = {
    "Technical Analyst": AgentGroup.TECHNICAL,
    "Quant Analyst": AgentGroup.TECHNICAL,
    "Value Investor": AgentGroup.FUNDAMENTAL,
    "Decision Maker": AgentGroup.FUNDAMENTAL,
    "Event Analyst": AgentGroup.MACRO,
    "Geopolitical Analyst": AgentGroup.MACRO,
    "Risk Manager": AgentGroup.RISK,
    "ML Specialist": AgentGroup.RISK,
}


@dataclass
class GroupResult:
    """그룹 내 confidence-weighted vote 결과."""

    group: AgentGroup
    signal: Literal["buy", "sell", "neutral"]
    confidence: float
    member_count: int
    member_results: list[str]  # 참여 에이전트 이름
    error_count: int

    def to_dict(self) -> dict:
        return {
            "group": self.group.value,
            "signal": self.signal,
            "confidence": round(self.confidence, 2),
            "member_count": self.member_count,
            "member_results": self.member_results,
            "error_count": self.error_count,
        }


# ── 헬퍼 ─────────────────────────────────────────────────────────────


def _signal_score(s: str) -> float:
    return {"buy": 1.0, "sell": -1.0, "neutral": 0.0}.get(s.lower(), 0.0)


# ── 그룹 가중 투표 ────────────────────────────────────────────────────


def _weighted_vote(group: AgentGroup, members: list[AgentResult]) -> GroupResult:
    """그룹 내 유효 에이전트의 confidence-weighted 다수결."""
    valid = [r for r in members if not r.error and r.confidence > 0]
    if not valid:
        return GroupResult(
            group=group,
            signal="neutral",
            confidence=0.0,
            member_count=len(members),
            member_results=[],
            error_count=len(members),
        )

    weighted_sum = sum(_signal_score(r.signal) * r.confidence for r in valid)
    conf_total = sum(r.confidence for r in valid)
    avg_score = weighted_sum / conf_total
    avg_conf = conf_total / len(valid)
    signal: Literal["buy", "sell", "neutral"] = (
        "buy" if avg_score > 0.3 else "sell" if avg_score < -0.3 else "neutral"
    )

    return GroupResult(
        group=group,
        signal=signal,
        confidence=avg_conf,
        member_count=len(members),
        member_results=[r.agent_name for r in valid],
        error_count=len(members) - len(valid),
    )


# ── 공개 API ─────────────────────────────────────────────────────────


def aggregate_by_group(
    agent_results: list[AgentResult],
) -> dict[AgentGroup, GroupResult]:
    """8 에이전트를 4 그룹으로 분할하고 각 그룹의 신호를 산출한다."""
    buckets: dict[AgentGroup, list[AgentResult]] = defaultdict(list)
    for r in agent_results:
        grp = AGENT_TO_GROUP.get(r.agent_name)
        if grp:
            buckets[grp].append(r)

    return {grp: _weighted_vote(grp, members) for grp, members in buckets.items()}


def reflect(
    group_results: dict[AgentGroup, GroupResult],
    final_signal: str,
) -> list[str]:
    """
    그룹 신호와 최종 신호의 일관성을 검사한다 (sanity check).

    3개 이상의 그룹이 한 방향이면서 최종 신호가 반대면 플래그를 반환.
    """
    sell_count = sum(1 for r in group_results.values() if r.signal == "sell")
    buy_count = sum(1 for r in group_results.values() if r.signal == "buy")
    flags: list[str] = []

    if sell_count >= 3 and final_signal.lower() == "buy":
        flags.append("REFLECT_INCONSISTENT_3_SELL_VS_FINAL_BUY")
    if buy_count >= 3 and final_signal.lower() == "sell":
        flags.append("REFLECT_INCONSISTENT_3_BUY_VS_FINAL_SELL")

    return flags


def group_weighted_score(
    group_results: dict[AgentGroup, GroupResult],
    regime_weights: dict[str, float] | None = None,
) -> float:
    """
    그룹 신호를 regime 가중치로 합산한다.

    regime_weights: {"momentum": 1.5, "mean_reversion": 0.3, "fundamental": 1.0}
    없으면 모두 1.0으로 처리.
    """

    # 그룹 → 카테고리 매핑
    _GROUP_CATEGORY: dict[AgentGroup, str] = {
        AgentGroup.TECHNICAL: "momentum",
        AgentGroup.FUNDAMENTAL: "fundamental",
        AgentGroup.MACRO: "fundamental",
        AgentGroup.RISK: "fundamental",
    }

    weights = regime_weights or {}
    total = 0.0
    for grp, result in group_results.items():
        cat = _GROUP_CATEGORY.get(grp, "fundamental")
        w = weights.get(cat, 1.0)
        total += _signal_score(result.signal) * result.confidence * w

    return total


# ── Step 12: Variance-aware aggregation ──────────────────────────────


class VarianceAggResult(TypedDict):
    mean_score: float
    std: float
    agreement: Literal["high", "medium", "low"]


def aggregate_with_variance(
    group_results: dict[AgentGroup, GroupResult],
    regime_weights: dict[str, float] | None = None,
) -> VarianceAggResult:
    """
    그룹별 점수의 가중 분산을 계산한다.

    agreement 기준:
    - std < 1.5 → "high"   (그룹 간 일치)
    - std < 3.0 → "medium"
    - std ≥ 3.0 → "low"    (그룹 간 충돌)

    Returns:
        mean_score : 가중 평균 신호 점수
        std        : 가중 표준편차
        agreement  : "high" | "medium" | "low"
    """
    _GROUP_CATEGORY: dict[AgentGroup, str] = {
        AgentGroup.TECHNICAL: "momentum",
        AgentGroup.FUNDAMENTAL: "fundamental",
        AgentGroup.MACRO: "fundamental",
        AgentGroup.RISK: "fundamental",
    }
    w_map = regime_weights or {}

    scores: list[float] = []
    weights: list[float] = []

    for grp, result in group_results.items():
        cat = _GROUP_CATEGORY.get(grp, "fundamental")
        w = w_map.get(cat, 1.0)
        s = _signal_score(result.signal) * result.confidence
        scores.append(s)
        weights.append(w)

    if not scores:
        return VarianceAggResult(mean_score=0.0, std=0.0, agreement="high")

    scores_arr = np.array(scores)
    weights_arr = np.array(weights)
    mean_score = float(np.average(scores_arr, weights=weights_arr))
    variance = float(np.average((scores_arr - mean_score) ** 2, weights=weights_arr))
    std = float(np.sqrt(variance))

    agreement: Literal["high", "medium", "low"]
    if std < 1.5:
        agreement = "high"
    elif std < 3.0:
        agreement = "medium"
    else:
        agreement = "low"

    return VarianceAggResult(mean_score=mean_score, std=std, agreement=agreement)
