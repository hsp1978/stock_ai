"""리포트 자기 정합성 검사기 테스트.

기준 사례는 005830.KS 실측이다 — 어떤 함수도 실패하지 않았는데 결과물의
산술이 맞지 않았다. 그 층을 잡는 것이 이 검사기의 목적이다.
"""

import os
import sys

import pytest

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _ANALYZER_DIR)

from report_invariants import (  # noqa: E402
    check_report_invariants,
    enforce_report_invariants,
)


def _codes(report) -> set[str]:
    return {v.code for v in check_report_invariants(report)}


def _sound_report() -> dict:
    """모든 불변식을 만족하는 리포트."""
    return {
        "final_signal": "neutral",
        "final_confidence": 5.0,
        "agent_count": 7,
        "valid_agent_count": 6,
        "excluded_failed_count": 1,
        "signal_distribution": {"buy": 3, "sell": 1, "neutral": 2},
        "signal_strength": {
            "technical": {"score": -1.0},
            "quantitative": {"score": 1.0},
            "ml_adjusted": {"contribution": 0.0},
            "insider": {"contribution": 0.0},
            "quantitative_contribution": 0.0,
            "narrative_raw": 16.5,
            "narrative_contribution": 5.0,
            "narrative_cap": 5.0,
            "narrative_capped": True,
            "total_score": 5.0,
        },
        "group_results": {
            "risk": {
                "member_count": 2,
                "counted_in_vote": 1,
                "error_count": 0,
                "excluded_count": 1,
            }
        },
    }


def test_sound_report_has_no_violations():
    assert check_report_invariants(_sound_report()) == []


# ── 실측 결함 재현 ───────────────────────────────────────────────────


def test_catches_the_005830_total_score_mismatch():
    """총점이 성분 합과 다르면 잡아야 한다.

    실측: 도메인 원값 16.5가 반영된 것처럼 표기됐으나 총점은 5.0.
    """
    report = _sound_report()
    # 캡이 적용되지 않은 채 총점만 5.0으로 남은 상태를 재현
    report["signal_strength"]["narrative_contribution"] = 16.5
    report["signal_strength"]["narrative_cap"] = 5.0

    codes = _codes(report)
    assert "TOTAL_SCORE_MISMATCH" in codes
    assert "NARRATIVE_EXCEEDS_CAP" in codes


def test_catches_quantitative_contribution_drift():
    report = _sound_report()
    report["signal_strength"]["quantitative_contribution"] = 3.0  # 실제 합은 0.0
    assert "QUANT_CONTRIBUTION_MISMATCH" in _codes(report)


def test_catches_wrong_capped_flag():
    report = _sound_report()
    report["signal_strength"]["narrative_capped"] = False  # raw 16.5 > cap 5.0
    assert "NARRATIVE_CAPPED_FLAG_WRONG" in _codes(report)


def test_catches_group_member_count_mismatch():
    """정상 제외가 오류로 잡히던 결함이 되살아나면 합이 깨진다."""
    report = _sound_report()
    report["group_results"]["risk"]["error_count"] = 1
    report["group_results"]["risk"]["excluded_count"] = 1  # 1+1+1 != 2
    assert "GROUP_MEMBER_COUNT_MISMATCH" in _codes(report)


def test_catches_agent_count_mismatch():
    report = _sound_report()
    report["excluded_failed_count"] = 3  # 6 + 3 != 7
    assert "AGENT_COUNT_MISMATCH" in _codes(report)


def test_catches_signal_distribution_mismatch():
    report = _sound_report()
    report["signal_distribution"] = {"buy": 3, "sell": 1, "neutral": 5}  # 합 9 != 6
    assert "SIGNAL_DISTRIBUTION_MISMATCH" in _codes(report)


def test_catches_out_of_range_confidence():
    report = _sound_report()
    report["final_confidence"] = 12.0
    assert "CONFIDENCE_OUT_OF_RANGE" in _codes(report)


# ── 강등 동작 ────────────────────────────────────────────────────────


def test_violation_blocks_execution_and_surfaces_to_user():
    """모순된 리포트는 실행 가능한 신호가 될 수 없다."""
    report = _sound_report()
    report["final_signal"] = "buy"
    report["final_confidence"] = 9.0
    report["execution_ready"] = True
    report["signal_strength"]["total_score"] = 99.0  # 성분 합과 불일치

    enforce_report_invariants(report)

    assert report["execution_ready"] is False
    assert report["final_confidence"] <= 3.0
    assert report["invariant_violations"]
    # 로그가 아니라 사람이 보는 경로에 실려야 한다
    assert any("REPORT_INCONSISTENT" in w for w in report["warnings"])
    assert any("정합성 위반" in r for r in report["key_risks"])


def test_sound_report_is_left_alone():
    report = _sound_report()
    report["execution_ready"] = True
    enforce_report_invariants(report)

    assert report["execution_ready"] is True
    assert report["final_confidence"] == 5.0
    assert report["invariant_violations"] == []


def test_strict_mode_raises(monkeypatch):
    monkeypatch.setenv("REPORT_INVARIANTS_STRICT", "1")
    report = _sound_report()
    report["signal_strength"]["total_score"] = 99.0

    with pytest.raises(ValueError, match="불변식 위반"):
        enforce_report_invariants(report)


def test_partial_report_does_not_false_positive():
    """필드가 없는 리포트(수집 실패 등)를 위반으로 몰지 않는다."""
    assert check_report_invariants({"final_signal": "neutral"}) == []
    assert check_report_invariants({}) == []
