"""리포트(Markdown export)용 순수 포맷 함수.

webui.py는 streamlit 의존이라 단위 테스트에서 import가 무겁다. 화면과 export가
같은 데이터를 쓰도록, 포맷 로직만 여기로 분리한다.

2026-08-03 추가 배경: V2는 진입가·손절·익절을 정상 생성하고 WebUI 화면도
표시하는데, Markdown export 템플릿에만 해당 섹션이 없어 "매수 신호인데 매매
파라미터가 전무"한 리포트가 나갔다.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_ORDER_TYPE_KR = {"market": "시장가", "limit": "지정가", "wait": "대기"}
_TIMING_KR = {
    "immediate": "즉시",
    "pullback": "풀백 대기",
    "breakout_confirm": "돌파 확인",
    "wait": "대기",
}


def is_kr_ticker(ticker: str) -> bool:
    t = (ticker or "").upper()
    return t.endswith(".KS") or t.endswith(".KQ")


def format_price(value: Optional[float], ticker: str) -> str:
    if value is None:
        return "—"
    if is_kr_ticker(ticker):
        return f"₩{value:,.0f}"
    return f"${value:,.2f}"


def format_entry_plan_markdown(ticker: str, final_decision: Dict[str, Any]) -> str:
    """매매 파라미터 섹션을 Markdown으로 만든다.

    계획이 없을 때 섹션을 통째로 생략하면 '실행 가능한 신호'처럼 읽히므로,
    없다는 사실과 사유를 명시한다.
    """
    signal = str(final_decision.get("final_signal") or "").lower()
    plan = final_decision.get("entry_plan") or {}
    lines = ["## 📋 실전 진입 계획", ""]

    if not plan:
        reason = final_decision.get("entry_plan_error") or "진입 계획 미생성"
        if signal in ("buy", "sell"):
            lines.append(f"> ⚠️ **매매 파라미터 없음 — 실행 불가** ({reason})")
        else:
            lines.append(f"- 방향성 신호가 아니어서 진입 계획을 생성하지 않음 ({reason})")
        return "\n".join(lines) + "\n"

    if plan.get("entry_timing") == "wait":
        lines.append("> ⏸ **진입 보류 권장**")
        lines.append("")
        for note in plan.get("notes") or []:
            lines.append(f"- {note}")
        return "\n".join(lines) + "\n"

    order = _ORDER_TYPE_KR.get(plan.get("order_type"), plan.get("order_type") or "?")
    timing = _TIMING_KR.get(plan.get("entry_timing"), plan.get("entry_timing") or "?")
    lines.append(f"- **주문**: {order} · {timing}")
    lines.append(f"- **진입가**: {format_price(plan.get('limit_price'), ticker)}")
    lines.append(f"- **🛑 손절**: {format_price(plan.get('stop_loss'), ticker)}")
    lines.append(f"- **🎯 익절**: {format_price(plan.get('take_profit'), ticker)}")

    if plan.get("expected_holding_days"):
        lines.append(f"- **예상 보유**: {plan['expected_holding_days']}일")
    if plan.get("invalidation_price") is not None:
        lines.append(
            f"- **🚨 무효화 가격**: {format_price(plan['invalidation_price'], ticker)}"
            " (이 가격 이하면 분석 무효)"
        )

    splits = [s for s in (plan.get("split_entry") or []) if s.get("pct")]
    if splits:
        parts = [
            f"{s['pct']}% @ {format_price(s.get('price'), ticker)}" for s in splits
        ]
        lines.append(f"- **분할 진입**: {' → '.join(parts)}")

    notes = plan.get("notes") or []
    if notes:
        lines.append("")
        for note in notes:
            lines.append(f"> {note}")

    return "\n".join(lines) + "\n"


def format_execution_status_markdown(final_decision: Dict[str, Any]) -> str:
    """실행 가능성·손익비를 한 줄로 요약한다.

    리포트만 보고 '계획이 실제로 생성됐는지'를 알 수 있어야 한다.
    """
    ready = final_decision.get("execution_ready")
    rr = final_decision.get("min_risk_reward")
    bits = []
    if ready is True:
        bits.append("실행 가능 ✅")
    elif ready is False:
        bits.append("실행 불가 ⚠️ (진입가/손절 미산출)")
    if isinstance(rr, (int, float)):
        bits.append(f"손익비(R/R) {rr:.2f}")
    warnings = final_decision.get("warnings") or []
    gated = [w for w in warnings if str(w).startswith("RR_BELOW_MIN")]
    if gated:
        bits.append("R/R 하한 미달로 매수 차단됨")
    if not bits:
        return ""
    return "- **실행 상태**: " + " · ".join(bits) + "\n"
