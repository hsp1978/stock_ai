"""리포트 자기 정합성 검사.

기존 테스트는 '함수가 무엇을 반환하는가'를 검증한다. 지금까지 감사에서 나온
결함들은 그 층에서 걸리지 않았다 — 각 함수는 자기 일을 정확히 했고, **결과물이
스스로와 모순**됐을 뿐이다.

    "종합 점수: +5.0 = 기술 -1.0 + 퀀트 +1.0 + ML +0.0 + 내부자 +0.0 + 도메인 +16.5"

여기서 실패하는 함수는 없다. 합이 안 맞을 뿐이다. 그런 종류를 잡는 층이 없어서
사람이 손으로 검산할 때까지 살아남았다 (2026-08-18 감사).

원칙: 모순된 리포트는 **실행 가능한 신호를 만들 수 없다**. 로그 한 줄로 남기면
아무도 읽지 않으므로(그게 죽은 필드를 만든 바로 그 습관이다), 위반을 발견하면
사용자에게 보이는 경로(warnings/key_risks)에 싣고 execution_ready를 내린다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# 부동소수 합산 오차 허용치. 점수는 소수 1자리로 표기되므로 그보다 작게 잡는다.
TOLERANCE = 0.05


@dataclass(frozen=True)
class Violation:
    """불변식 위반 1건."""

    code: str
    detail: str

    def __str__(self) -> str:  # 리포트에 그대로 실린다
        return f"{self.code}: {self.detail}"


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def _check_score_composition(strength: Dict[str, Any]) -> List[Violation]:
    """총점이 표기된 성분들의 합과 일치하는가."""
    out: List[Violation] = []

    total = _num(strength.get("total_score"))
    quant_contrib = _num(strength.get("quantitative_contribution"))
    narrative = _num(strength.get("narrative_contribution"))

    tech = _num((strength.get("technical") or {}).get("score"))
    quant = _num((strength.get("quantitative") or {}).get("score"))
    ml = _num((strength.get("ml_adjusted") or {}).get("contribution"))
    insider = _num((strength.get("insider") or {}).get("contribution"))

    # 정량 기여 = 기술 + 퀀트 + ML + 내부자
    if None not in (quant_contrib, tech, quant, ml, insider):
        parts = tech + quant + ml + insider
        if not _close(quant_contrib, parts):
            out.append(Violation(
                "QUANT_CONTRIBUTION_MISMATCH",
                f"quantitative_contribution {quant_contrib:+.2f} != "
                f"기술 {tech:+.2f} + 퀀트 {quant:+.2f} + ML {ml:+.2f} "
                f"+ 내부자 {insider:+.2f} = {parts:+.2f}",
            ))

    # 총점 = 정량 기여 + (상한 적용된) 정성 기여
    if None not in (total, quant_contrib, narrative):
        expected = quant_contrib + narrative
        if not _close(total, expected):
            out.append(Violation(
                "TOTAL_SCORE_MISMATCH",
                f"total_score {total:+.2f} != quantitative_contribution "
                f"{quant_contrib:+.2f} + narrative_contribution {narrative:+.2f} "
                f"= {expected:+.2f}",
            ))

    # 정성 기여는 상한을 넘을 수 없고, capped 플래그가 사실과 맞아야 한다
    cap = _num(strength.get("narrative_cap"))
    raw = _num(strength.get("narrative_raw"))
    if None not in (cap, narrative) and abs(narrative) > cap + TOLERANCE:
        out.append(Violation(
            "NARRATIVE_EXCEEDS_CAP",
            f"narrative_contribution {narrative:+.2f}의 절댓값이 "
            f"narrative_cap {cap:.2f}를 초과",
        ))
    if None not in (cap, raw) and "narrative_capped" in strength:
        should_cap = abs(raw) > cap + TOLERANCE
        if bool(strength["narrative_capped"]) != should_cap:
            out.append(Violation(
                "NARRATIVE_CAPPED_FLAG_WRONG",
                f"narrative_capped={strength['narrative_capped']} 인데 "
                f"raw {raw:+.2f} vs cap {cap:.2f}",
            ))

    return out


def _check_agent_counts(report: Dict[str, Any]) -> List[Violation]:
    """에이전트 수가 갈래별로 재검산되는가."""
    out: List[Violation] = []

    total = _num(report.get("agent_count"))
    valid = _num(report.get("valid_agent_count"))
    excluded = _num(report.get("excluded_failed_count"))
    if None not in (total, valid, excluded) and not _close(total, valid + excluded):
        out.append(Violation(
            "AGENT_COUNT_MISMATCH",
            f"agent_count {total:.0f} != valid {valid:.0f} + excluded {excluded:.0f}",
        ))

    # 신호 분포 합 = 유효 에이전트 수
    dist = report.get("signal_distribution") or {}
    if dist and valid is not None:
        dist_sum = sum(_num(v) or 0 for v in dist.values())
        if not _close(dist_sum, valid):
            out.append(Violation(
                "SIGNAL_DISTRIBUTION_MISMATCH",
                f"signal_distribution 합 {dist_sum:.0f} != valid_agent_count {valid:.0f}",
            ))

    return out


def _check_group_results(report: Dict[str, Any]) -> List[Violation]:
    """그룹별 인원이 참여/오류/제외로 재검산되는가.

    과거엔 '정상 제외'가 error_count로 잡혀 정상 동작이 장애로 보고됐다.
    """
    out: List[Violation] = []
    for name, grp in (report.get("group_results") or {}).items():
        if not isinstance(grp, dict):
            continue
        member = _num(grp.get("member_count"))
        counted = _num(grp.get("counted_in_vote"))
        errors = _num(grp.get("error_count"))
        excluded = _num(grp.get("excluded_count"))
        if None in (member, counted, errors, excluded):
            continue
        if not _close(member, counted + errors + excluded):
            out.append(Violation(
                "GROUP_MEMBER_COUNT_MISMATCH",
                f"[{name}] member_count {member:.0f} != 참여 {counted:.0f} "
                f"+ 오류 {errors:.0f} + 제외 {excluded:.0f}",
            ))
    return out


def _check_signal_bounds(report: Dict[str, Any]) -> List[Violation]:
    """신호/신뢰도가 정의된 범위 안에 있는가."""
    out: List[Violation] = []

    signal = (report.get("final_signal") or "").lower()
    if signal and signal not in ("buy", "sell", "neutral"):
        out.append(Violation("UNKNOWN_SIGNAL", f"final_signal={report.get('final_signal')!r}"))

    conf = _num(report.get("final_confidence"))
    if conf is not None and not (0.0 <= conf <= 10.0):
        out.append(Violation("CONFIDENCE_OUT_OF_RANGE", f"final_confidence={conf}"))

    return out


def check_report_invariants(report: Dict[str, Any]) -> List[Violation]:
    """리포트가 스스로와 모순되지 않는지 검사한다. 위반 목록을 반환."""
    if not isinstance(report, dict):
        return [Violation("NOT_A_REPORT", f"dict가 아님: {type(report).__name__}")]

    violations: List[Violation] = []
    strength = report.get("signal_strength")
    if isinstance(strength, dict):
        violations.extend(_check_score_composition(strength))
    violations.extend(_check_agent_counts(report))
    violations.extend(_check_group_results(report))
    violations.extend(_check_signal_bounds(report))
    return violations


def _strict_mode() -> bool:
    return (os.getenv("REPORT_INVARIANTS_STRICT", "") or "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def enforce_report_invariants(report: Dict[str, Any]) -> Dict[str, Any]:
    """검사 후 결과를 리포트에 반영한다 (in-place).

    위반이 있으면:
      - `invariant_violations`에 목록을 남기고
      - 사람이 보는 warnings/key_risks에 올리며
      - execution_ready를 내려 **모순된 리포트로 주문이 나가지 않게** 한다.

    REPORT_INVARIANTS_STRICT=1이면 예외를 던진다 (테스트/CI용).
    운영 기본값은 예외 없이 강등이다 — 산술 불일치 하나로 전체 스캔을
    죽이는 것은 과하고, 강등만으로도 '조용히 통과'는 막힌다.
    """
    violations = check_report_invariants(report)
    if not violations:
        report["invariant_violations"] = []
        return report

    messages = [str(v) for v in violations]
    report["invariant_violations"] = messages

    if _strict_mode():
        raise ValueError("리포트 불변식 위반: " + "; ".join(messages))

    warns = list(report.get("warnings") or [])
    for m in messages:
        tag = f"REPORT_INCONSISTENT · {m}"
        if tag not in warns:
            warns.append(tag)
    report["warnings"] = warns

    risks = list(report.get("key_risks") or [])
    head = "리포트 내부 정합성 위반 — 수치를 신뢰할 수 없음"
    if head not in risks:
        risks.insert(0, head)
    report["key_risks"] = risks

    # 모순된 리포트는 실행 가능한 신호가 될 수 없다.
    report["execution_ready"] = False
    for key in ("final_confidence", "confidence"):
        if isinstance(report.get(key), (int, float)):
            report[key] = min(float(report[key]), 3.0)

    print(f"[report_invariants] 위반 {len(messages)}건: {'; '.join(messages)}")
    return report
