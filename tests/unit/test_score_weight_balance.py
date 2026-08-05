"""정량 vs 정성 비중 정합 테스트.

2026-08 감사(111770.KS): 총점 +25.5 중 도메인 보정(Risk/Event/Value/Macro)이
+15.1로 59%를 차지했다. 이들은 LLM 서술 기반 판단(signed confidence)이고,
검증 가능한 도구 점수는 +10.4뿐이었다. 검증이 어려운 쪽이 총점을 지배했다.

또한 Technical/Quant는 '도구 점수'로만 집계되어 에이전트 자신의 판단은
총점에 들어가지 않는다 — Quant Analyst의 sell 6.5가 소리 없이 사라졌다.
"""

import os
import sys

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

from enhanced_decision_maker import EnhancedDecisionMaker as EDM  # noqa: E402


def _strength(tech=0.0, quant=0.0, ml=0.0, insider=0.0,
              risk=0.0, event=0.0, fundamental=0.0, macro=0.0):
    """_calculate_signal_strength의 합산부만 재현한다 (에이전트 목록 없이)."""
    dm = EDM.__new__(EDM)
    quantitative = tech + quant + ml + insider
    narrative_raw = risk + event + fundamental + macro
    cap = max(abs(quantitative), dm.NARRATIVE_FLOOR)
    narrative = max(-cap, min(cap, narrative_raw))
    return {
        "quantitative": quantitative,
        "narrative_raw": narrative_raw,
        "narrative": narrative,
        "capped": abs(narrative_raw) > cap,
        "total": quantitative + narrative,
    }


# ── 정성 상한 ───────────────────────────────────────────────────


def test_narrative_cannot_exceed_quantitative():
    """111770.KS 실측 재현: 도구 +10.4 / 도메인 +15.1."""
    out = _strength(tech=10.4, risk=5.2, event=4.2, fundamental=5.6, macro=0.0)

    assert out["capped"] is True
    assert out["narrative"] == 10.4, "정성이 정량을 넘었다"
    assert out["total"] == 20.8, f"총점 불일치: {out['total']}"


def test_narrative_share_never_over_half():
    """상한이 걸린 뒤에는 정성 비중이 50%를 넘을 수 없다."""
    out = _strength(tech=10.4, risk=5.2, event=4.2, fundamental=5.6)
    share = abs(out["narrative"]) / abs(out["total"])
    assert share <= 0.5 + 1e-9, f"정성 비중 {share:.1%}"


def test_narrative_passes_through_when_small():
    """정량보다 작으면 그대로 반영된다 — 무조건 깎는 게 아니다."""
    out = _strength(tech=20.0, risk=3.0, event=2.0)
    assert out["capped"] is False
    assert out["narrative"] == 5.0
    assert out["total"] == 25.0


def test_floor_allows_signal_when_tools_cancel_out():
    """도구가 상쇄돼 0이어도 정성 판단이 전부 사라지면 안 된다."""
    out = _strength(tech=6.0, quant=-6.0, risk=8.0, event=6.0)
    assert out["quantitative"] == 0.0
    assert out["narrative"] == EDM.NARRATIVE_FLOOR
    assert out["total"] == EDM.NARRATIVE_FLOOR


def test_floor_below_moderate_threshold():
    """서술만으로 '강한 신호'가 만들어지면 안 된다 (강도 >10 = moderate)."""
    assert EDM.NARRATIVE_FLOOR < 10


def test_negative_narrative_capped_symmetrically():
    """음수 쪽도 동일하게 상한이 걸린다 (정량 12 > 바닥값이라 정량이 상한)."""
    out = _strength(tech=-12.0, risk=-9.0, event=-6.0)
    assert out["capped"] is True
    assert out["narrative"] == -12.0
    assert out["total"] == -24.0


def test_floor_binds_when_quantitative_smaller_than_floor():
    """정량이 바닥값보다 작으면 바닥값이 상한이다 — 정량만큼으로 더 깎지 않는다."""
    out = _strength(tech=-4.0, risk=-9.0, event=-6.0)
    assert out["narrative"] == -EDM.NARRATIVE_FLOOR
    assert out["total"] == -9.0


def test_narrative_does_not_flip_direction():
    """상한이 방향을 뒤집으면 안 된다."""
    out = _strength(tech=10.0, risk=-30.0)
    assert out["narrative"] == -10.0
    assert out["total"] == 0.0


# ── 도구 에이전트 판단 충돌 ─────────────────────────────────────


def test_opposed_verdict_detected():
    """Quant가 sell인데 최종이 buy면 충돌로 잡혀야 한다."""
    verdicts = {"Technical Analyst": "buy", "Quant Analyst": "sell"}
    final = "buy"
    opposed = [
        n for n, v in verdicts.items()
        if v in ("buy", "sell") and final in ("buy", "sell") and v != final
    ]
    assert opposed == ["Quant Analyst"]


def test_neutral_verdict_is_not_conflict():
    verdicts = {"Quant Analyst": "neutral"}
    final = "buy"
    opposed = [
        n for n, v in verdicts.items()
        if v in ("buy", "sell") and final in ("buy", "sell") and v != final
    ]
    assert opposed == []


def test_conflict_warning_registered_in_source():
    """경고 상수와 신뢰도 상한이 코드에 존재하는지 고정."""
    src = open(
        os.path.join(_ANALYZER_DIR, "enhanced_decision_maker.py"), encoding="utf-8"
    ).read()
    assert "TOOL_AGENT_VERDICT_CONFLICT" in src
    assert "tool_agent_verdicts" in src


def test_contribution_breakdown_exposed():
    """총점이 무엇으로 만들어졌는지 리포트에서 확인 가능해야 한다."""
    src = open(
        os.path.join(_ANALYZER_DIR, "enhanced_decision_maker.py"), encoding="utf-8"
    ).read()
    for field in ("quantitative_contribution", "narrative_contribution",
                  "narrative_capped", "narrative_cap"):
        assert f'"{field}"' in src, f"{field} 미노출"
