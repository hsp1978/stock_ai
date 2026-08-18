"""리포트 출력 필드 레지스트리 — 죽은 필드를 막는다.

`regime_weighted_score`는 계산되어 리포트에 실렸지만 코드 전체에서 읽는 곳이
없었다. `close_thread_connection()`도 정의만 되고 호출부가 없었다. 둘 다
"있으니 동작하겠지"라는 착시를 만들었고, 후자는 7일 만에 fd를 고갈시켰다.

소비자 없는 출력은 **없는 것보다 나쁘다** — 기능이 있다는 인상을 주면서
아무 일도 하지 않기 때문이다.

여기에 필드를 선언하고, `tests/unit/test_report_schema.py`가 다음을 강제한다:
  1. aggregate()가 내는 키와 이 레지스트리가 정확히 일치
  2. `consumed` 필드는 실제로 읽는 코드가 존재
  3. `diagnostic` 필드는 왜 소비자가 없어도 되는지 사유를 남김
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal


@dataclass(frozen=True)
class FieldSpec:
    purpose: Literal["consumed", "diagnostic"]
    note: str


def _c(note: str) -> FieldSpec:
    return FieldSpec("consumed", note)


def _d(note: str) -> FieldSpec:
    """소비자가 없어도 되는 진단용 필드. 사유가 반드시 있어야 한다."""
    return FieldSpec("diagnostic", note)


REPORT_FIELDS: Dict[str, FieldSpec] = {
    # ── 판정 결과 ────────────────────────────────────────────────────
    "final_signal": _c("텔레그램·주문 라우터·WebUI가 읽는 최종 방향"),
    "final_confidence": _c("신뢰도 임계 필터"),
    "consensus": _c("리포트 본문 표기"),
    "conflicts": _c("리포트 본문 표기"),
    "reasoning": _c("리포트 본문 표기"),
    "key_risks": _c("리포트 본문·알림 표기"),

    # ── 에이전트 집계 ────────────────────────────────────────────────
    "agent_count": _c("리포트 헤더"),
    "valid_agent_count": _c("표본 수 판단"),
    "excluded_failed_count": _c("실패 분리 표기"),
    "signal_distribution": _c("합의도 표기"),
    "group_results": _c("그룹별 표결 표기"),

    # ── 메타 ─────────────────────────────────────────────────────────
    "analyzed_at": _c("신선도 판단"),
    "horizon_days": _c("신호 추적(signal_outcomes) 기록"),
    "decision_schema_version": _c("스키마 호환 분기"),
    "decision_context": _c("의사결정 컨텍스트 저장"),
    "currency": _c("금액 표기 통화"),
    "market_info": _c("시장·세션 표기"),

    # ── 점수 내역 ────────────────────────────────────────────────────
    "signal_strength": _c("총점·강도·정량/정성 내역 표기"),

    # ── 실행 가능성 ──────────────────────────────────────────────────
    "min_risk_reward": _c("R/R 하드 게이트"),
    "volatility_status": _c("고변동성 강등 판정"),
    "fundamental_risks": _c("실적 블랙아웃 게이트 입력"),
    "warnings": _c("리포트·알림 표기"),
    "invariant_violations": _c("정합성 위반 표기 — enforce_report_invariants"),

    # ── 진단용 (소비자 없음이 의도된 것) ─────────────────────────────
    "technical_analysis": _d(
        "도구 원본 점수. 총점은 signal_strength로 전달되며, 이 필드는 "
        "사후 디버깅용 원본 보존."
    ),
    "quant_analysis": _d("위와 동일 — 퀀트 도구 원본 점수."),
    "tool_agent_verdicts": _d(
        "Technical/Quant 에이전트 자체 판단. 총점에는 들어가지 않고 "
        "최종 신호와 충돌 시 신뢰도 상한 판정에만 쓰인 뒤 기록으로 남는다."
    ),
    "regime": _d("시장 국면 기록. 가중치는 group_results 경로로 이미 반영됨."),
    "regime_weighted_score": _d(
        "그룹 신호의 regime 가중 합. total_score와 스케일이 달라 판정에 "
        "쓰지 않는다(used_in_decision=False). 국면 가중치 튜닝용 관측값."
    ),
    "reflect_flags": _d(
        "그룹 다수 vs 최종 신호 불일치 플래그. 강등은 _apply_reflect_guard가 "
        "이미 수행했고, 이 필드는 그 판정의 근거 기록."
    ),
    "signal_std": _d("에이전트 분산. 강등은 variance penalty가 수행 후 기록."),
    "agreement_level": _d("합의 수준 라벨. signal_std와 동일하게 사후 기록."),
}


# 소비자를 찾을 때 뒤지는 모듈 (리포트를 읽는 쪽)
CONSUMER_GLOBS = (
    "stock_analyzer/webui.py",
    "stock_analyzer/report_format.py",
    "stock_analyzer/local_engine.py",
    "stock_analyzer/multi_agent.py",
    "stock_analyzer/telegram_bot.py",
    "stock_analyzer/enhanced_decision_maker.py",
    "stock_analyzer/report_invariants.py",
    "chart_agent_service/service.py",
    "chart_agent_service/signal_tracker.py",
    "chart_agent_service/db.py",
    "chart_agent_service/telegram_bot.py",
    "chart_agent_service/decision_context.py",
)
