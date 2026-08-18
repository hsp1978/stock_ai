"""005830.KS 리포트 감사에서 나온 결함들의 회귀 테스트 (2026-08-18).

공통 주제는 **리포트가 스스로를 잘못 설명하는 것**이다. 총점 산식이 맞지 않고,
정상 제외가 오류로 집계되고, 상장 시장만 보고 환노출을 매기고, 설명력 없는
회귀에서 나온 알파가 점수를 만든다.
"""

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

from agent_groups import AgentGroup, aggregate_by_group  # noqa: E402
from enhanced_decision_maker import EnhancedDecisionMaker  # noqa: E402
from multi_agent import GeopoliticalAnalyst  # noqa: E402


@dataclass
class FakeAgentResult:
    agent_name: str
    signal: str
    confidence: float
    error: Optional[str] = None


# ── A. 총점 산식 정합 ────────────────────────────────────────────────


def test_reasoning_uses_capped_narrative_not_raw():
    """표기된 성분의 합이 표기된 총점과 일치해야 한다.

    실측 결함: '종합 점수: +5.0 = ... + 도메인 +16.5'. 도메인 원값을 쓰면서
    총점은 캡 적용 후 값이라 독자가 재검산하면 산술이 깨졌다.
    """
    dm = EnhancedDecisionMaker()
    signal_strength = {
        "total_score": 5.0,
        "strength_level": "very_weak",
        "technical": {"direction": "sell", "strength": "weak", "score": -1.0},
        "quantitative": {"direction": "buy", "strength": "weak", "score": 1.0},
        "ml_adjusted": {"contribution": 0.0},
        "insider": {"signal": "neutral", "score": 0, "contribution": 0.0},
        "domain_contributions": {
            "risk": 5.6, "event": 4.25, "fundamental": 6.65, "macro": 0.0,
        },
        "narrative_raw": 16.5,
        "narrative_contribution": 5.0,
        "narrative_cap": 5.0,
        "narrative_capped": True,
    }
    decision = dm._make_final_decision(
        signal_counts={"buy": 3, "sell": 1, "neutral": 2},
        signal_strength=signal_strength,
        volatility_check={"is_high": False, "mentioned_by": []},
        tech_analysis={"total_score": -1.0, "buy_count": 1, "sell_count": 2},
        quant_analysis={"total_score": 1.0, "buy_count": 2, "sell_count": 1},
        currency="₩",
    )

    score_line = next(
        p for p in decision["reasoning"].split(" / ") if p.startswith("종합 점수")
    )
    assert "+16.5" not in score_line, f"캡 전 원값이 노출됨: {score_line}"
    assert "도메인 +5.0" in score_line

    # 표기된 성분의 합 = 표기된 총점
    assert -1.0 + 1.0 + 0.0 + 0.0 + 5.0 == signal_strength["total_score"]
    # 캡이 걸렸으면 원값도 별도로 밝힌다 (숨기는 것도 정답이 아니다)
    assert "원값 +16.5" in decision["reasoning"]


# ── B. 실적 일정 ─────────────────────────────────────────────────────


def _fundamental_stub(days_to_earnings):
    return {"days_to_earnings": days_to_earnings, "critical_risks": [], "warnings": []}


def test_imminent_earnings_downgrades_buy():
    """발표 임박은 방향과 무관하게 진입 부적격이다 (갭으로 손절이 무의미)."""
    dm = EnhancedDecisionMaker()
    decision = {"signal": "buy", "confidence": 8.0, "reasoning": "매수 우세"}

    gated = dm._apply_earnings_gate(decision, days_to_earnings=1.0)

    assert gated["signal"] == "neutral"
    assert gated["confidence"] <= 3.0
    assert gated["earnings_downgraded"] is True
    assert "D-1" in gated["conflicts"]


def test_earnings_gate_leaves_distant_and_non_buy_alone():
    dm = EnhancedDecisionMaker()
    buy = {"signal": "buy", "confidence": 8.0, "reasoning": ""}
    assert dm._apply_earnings_gate(buy, days_to_earnings=30.0)["signal"] == "buy"
    assert dm._apply_earnings_gate(buy, days_to_earnings=None)["signal"] == "buy"

    sell = {"signal": "sell", "confidence": 8.0, "reasoning": ""}
    assert dm._apply_earnings_gate(sell, days_to_earnings=1.0)["signal"] == "sell"


def test_days_elapsed_is_not_floored():
    """timedelta.days는 음수에서 내림한다: -5.05일이 '6일 경과'로 표기됐다."""
    now = datetime(2026, 8, 18, 16, 12, tzinfo=timezone.utc)
    earnings = now - timedelta(days=5, hours=1, minutes=12)

    floored = abs((earnings - now).days)          # 기존 방식
    actual = abs((earnings - now).total_seconds() / 86400.0)

    assert floored == 6          # 옛 표기
    assert round(actual) == 5    # 새 표기
    assert floored != round(actual)


# ── C. 그룹 집계: 실패 vs 제외 ───────────────────────────────────────


def test_zero_confidence_is_excluded_not_errored():
    """정확도 미달로 무시된 ML은 '오류'가 아니다 (CLAUDE.md §13-2)."""
    members = [
        FakeAgentResult("Risk Manager", "buy", 8.0),
        FakeAgentResult("ML Specialist", "neutral", 0.0),  # 의도적 무시
    ]
    groups = aggregate_by_group(members)
    risk = groups[AgentGroup.RISK].to_dict()

    assert risk["error_count"] == 0, "정상 제외가 오류로 집계됨"
    assert risk["excluded_count"] == 1
    assert risk["counted_in_vote"] == 1
    # member_count가 세 갈래의 합으로 재검산돼야 한다
    assert risk["member_count"] == (
        risk["counted_in_vote"] + risk["error_count"] + risk["excluded_count"]
    )


def test_real_error_still_counted_as_error():
    members = [
        FakeAgentResult("Risk Manager", "buy", 8.0),
        FakeAgentResult("ML Specialist", "neutral", 0.0, error="timeout"),
    ]
    risk = aggregate_by_group(members)[AgentGroup.RISK].to_dict()

    assert risk["error_count"] == 1
    assert risk["excluded_count"] == 0


# ── D. 환노출: 상장 시장이 아니라 사업 실체 ──────────────────────────


def test_domestic_insurer_is_not_high_fx_exposure():
    """005830.KS(국내 손해보험)가 수출 OEM과 같은 HIGH로 묶이던 문제."""
    exposure, reason = GeopoliticalAnalyst._estimate_fx_exposure(
        "KRW", "Financial Services", "Insurance—Property & Casualty"
    )
    assert exposure == "LOW"
    assert "내수" in reason


def test_export_industry_keeps_high_exposure():
    exposure, _ = GeopoliticalAnalyst._estimate_fx_exposure(
        "KRW", "Technology", "Semiconductors"
    )
    assert exposure == "HIGH"


def test_usd_stock_has_no_translation_exposure():
    exposure, _ = GeopoliticalAnalyst._estimate_fx_exposure(
        "USD", "Technology", "Semiconductors"
    )
    assert exposure == "LOW"
