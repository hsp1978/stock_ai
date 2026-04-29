"""
진입 계획(Entry Plan) 생성 모듈.

분석 결과를 바탕으로 "언제, 얼마에, 몇 번에 나눠 매수할지"에 대한
구체적이고 실행 가능한 계획을 생성합니다.

출력 구조:
{
  "order_type": "market" | "limit" | "wait",
  "entry_timing": "immediate" | "pullback" | "breakout_confirm" | "wait",
  "limit_price": float or None,  # 지정가 (호가단위로 정합)
  "stop_loss": float,
  "take_profit": float,
  "invalidation_price": float,   # 이 가격 이하면 분석 무효
  "split_entry": [{"pct": int, "trigger": str, "price": float}, ...],
  "expected_holding_days": int,
  "notes": [str, ...],
}
"""
from __future__ import annotations

from typing import Dict, List, Optional

from tick_size import round_to_tick


# 투자 스타일별 기본 보유 기간
_HOLDING_DAYS_BY_STYLE = {
    "scalping": 2,
    "swing": 10,
    "longterm": 60,
}


def build_entry_plan(
    ticker: str,
    signal: str,
    confidence: float,
    current_price: float,
    tool_results: List[Dict],
    trading_style: str = "swing",
) -> Dict:
    """
    분석 결과에서 구체적 진입 계획 생성.

    Args:
        ticker: 종목 티커
        signal: "buy" | "sell" | "neutral"
        confidence: 0-10
        current_price: 현재가
        tool_results: 16개 도구의 분석 결과 리스트
        trading_style: "scalping" | "swing" | "longterm"

    Returns:
        진입 계획 딕셔너리
    """
    # 기본 구조
    plan: Dict = {
        "order_type": "wait",
        "entry_timing": "wait",
        "limit_price": None,
        "stop_loss": None,
        "take_profit": None,
        "invalidation_price": None,
        "split_entry": [],
        "expected_holding_days": _HOLDING_DAYS_BY_STYLE.get(trading_style, 10),
        "notes": [],
    }

    # neutral/sell이면 매매 보류 권장
    if signal != "buy":
        plan["notes"].append("매수 신호 아님 — 진입 계획 미생성")
        return plan

    # 도구별 결과 인덱싱
    by_tool = {r.get("tool", ""): r for r in tool_results if isinstance(r, dict)}

    # ─── 손절/익절 (risk_position_sizing에서 이미 호가단위 정합됨) ───
    risk = by_tool.get("risk_position_sizing", {})
    final_levels = risk.get("final_levels") or {}
    plan["stop_loss"] = final_levels.get("stop_loss") or risk.get("stop_loss")
    plan["take_profit"] = final_levels.get("take_profit") or risk.get("take_profit")
    plan["invalidation_price"] = plan["stop_loss"]

    # ─── 주문 유형 결정 ───
    # 1) RSI 과매수(>70)면 풀백 대기
    # 2) 볼린저 스퀴즈 중이면 돌파 확인 후
    # 3) 거래량 부족이면 보류
    # 4) 그 외: 지정가 매수 (현재가 - 0.3*ATR)
    order_type = "market"
    entry_timing = "immediate"

    rsi_data = by_tool.get("rsi_divergence_analysis", {})
    rsi_val = rsi_data.get("current_rsi")
    if rsi_val is not None and rsi_val > 70:
        order_type = "limit"
        entry_timing = "pullback"
        plan["notes"].append(f"RSI {rsi_val:.1f} 과매수 — 풀백 대기 권장")

    bb_data = by_tool.get("bollinger_squeeze_analysis", {})
    if bb_data.get("is_squeeze"):
        order_type = "limit"
        entry_timing = "breakout_confirm"
        plan["notes"].append("볼린저 스퀴즈 중 — 방향성 돌파 확인 후 진입")

    trend_data = by_tool.get("trend_ma_analysis", {})
    if trend_data.get("alignment") == "breakout_weak":
        order_type = "wait"
        entry_timing = "wait"
        plan["notes"].append("거래량 부족한 돌파 — 진입 보류")

    # ATR 기반 풀백 가격
    atr_pct = None
    vol_regime = by_tool.get("volatility_regime_analysis", {})
    if isinstance(vol_regime, dict):
        atr_pct = vol_regime.get("atr_pct")

    if entry_timing == "pullback" and atr_pct:
        # 현재가에서 0.3 ATR 하락 대기
        pullback_target = current_price * (1 - 0.3 * atr_pct / 100)
        plan["limit_price"] = round_to_tick(pullback_target, ticker, side="down")
    elif entry_timing == "immediate":
        # 시장가 진입이지만 최악 체결가 기준을 명시 (현재가 +0.1 ATR)
        if atr_pct:
            worst_fill = current_price * (1 + 0.1 * atr_pct / 100)
            plan["limit_price"] = round_to_tick(worst_fill, ticker, side="up")
            order_type = "limit"  # 안전하게 지정가 권장
        else:
            plan["limit_price"] = round_to_tick(current_price, ticker, side="nearest")
    elif entry_timing == "breakout_confirm":
        # 볼린저 상단 돌파 확인가
        bb_upper = bb_data.get("upper_band")
        if bb_upper:
            plan["limit_price"] = round_to_tick(bb_upper * 1.005, ticker, side="up")
        else:
            plan["limit_price"] = round_to_tick(current_price, ticker, side="up")

    plan["order_type"] = order_type
    plan["entry_timing"] = entry_timing

    # ─── 분할 진입 전략 (신뢰도 기반) ───
    if entry_timing != "wait" and plan["limit_price"]:
        target_price = plan["limit_price"]
        if confidence >= 8:
            # 높은 신뢰도: 즉시 60% + 조정 시 40%
            plan["split_entry"] = [
                {
                    "pct": 60,
                    "trigger": "즉시 (지정가)",
                    "price": round_to_tick(target_price, ticker, side="nearest"),
                },
                {
                    "pct": 40,
                    "trigger": "RSI 50 하회 또는 20일선 터치",
                    "price": round_to_tick(target_price * 0.97, ticker, side="down"),
                },
            ]
        elif confidence >= 6:
            # 중간 신뢰도: 3분할
            plan["split_entry"] = [
                {
                    "pct": 40,
                    "trigger": "즉시 (지정가)",
                    "price": round_to_tick(target_price, ticker, side="nearest"),
                },
                {
                    "pct": 30,
                    "trigger": "추가 1% 하락 시",
                    "price": round_to_tick(target_price * 0.99, ticker, side="down"),
                },
                {
                    "pct": 30,
                    "trigger": "지지선 또는 20일선 도달",
                    "price": round_to_tick(target_price * 0.97, ticker, side="down"),
                },
            ]
        else:
            # 낮은 신뢰도: 보수적 소량 진입만
            plan["split_entry"] = [
                {
                    "pct": 30,
                    "trigger": "즉시 (소량 탐색 진입)",
                    "price": round_to_tick(target_price, ticker, side="nearest"),
                },
                {
                    "pct": 0,
                    "trigger": "추가 진입 보류 — 신호 강화 확인 후 결정",
                    "price": None,
                },
            ]
            plan["notes"].append(
                f"신뢰도 {confidence:.1f}/10 낮음 — 탐색 진입만 권장, 전량 진입 금지"
            )

    # ─── 보유 기간 (거래 스타일 + Kelly 기반 보정) ───
    kelly = by_tool.get("kelly_criterion_analysis", {})
    if kelly.get("avg_holding_days"):
        # 실제 백테스트 평균 보유일이 있다면 우선
        plan["expected_holding_days"] = int(kelly.get("avg_holding_days"))

    # ─── Trend/MeanReversion regime에 따른 보유기간 조정 ───
    regime_data = by_tool.get("correlation_regime_analysis", {})
    regime = regime_data.get("regime")
    if regime == "trending":
        plan["expected_holding_days"] = max(plan["expected_holding_days"], 14)
        plan["notes"].append("추세장 — 추세 종료까지 보유 (목표 14일+)")
    elif regime == "mean_reverting":
        plan["expected_holding_days"] = min(plan["expected_holding_days"], 7)
        plan["notes"].append("평균 회귀장 — 단기 보유 (7일 이내)")

    return plan


def format_entry_plan_text(plan: Dict, currency: str = "$") -> str:
    """사용자 친화적 한국어 포맷."""
    if plan.get("entry_timing") == "wait":
        notes = " / ".join(plan.get("notes") or ["조건 충족 시 재평가"])
        return f"⏸ 진입 보류: {notes}"

    lines = []
    order_type_kr = {
        "market": "시장가 주문",
        "limit": "지정가 주문",
        "wait": "대기",
    }.get(plan["order_type"], plan["order_type"])

    timing_kr = {
        "immediate": "즉시 진입",
        "pullback": "풀백 대기",
        "breakout_confirm": "돌파 확인 후",
        "wait": "대기",
    }.get(plan["entry_timing"], plan["entry_timing"])

    lines.append(f"📋 주문 유형: {order_type_kr} ({timing_kr})")
    if plan["limit_price"]:
        lines.append(f"💰 권장 진입가: {currency}{plan['limit_price']:,.2f}")
    if plan["stop_loss"]:
        lines.append(f"🛑 손절가: {currency}{plan['stop_loss']:,.2f}")
    if plan["take_profit"]:
        lines.append(f"🎯 익절가: {currency}{plan['take_profit']:,.2f}")
    lines.append(f"⏱ 예상 보유: {plan['expected_holding_days']}일")

    if plan.get("split_entry"):
        lines.append("📊 분할 진입:")
        for i, split in enumerate(plan["split_entry"], 1):
            if split["pct"] > 0 and split.get("price"):
                lines.append(
                    f"  {i}차 {split['pct']}% @ {currency}{split['price']:,.2f} — {split['trigger']}"
                )
            else:
                lines.append(f"  {i}차 — {split['trigger']}")

    if plan.get("notes"):
        lines.append("📝 참고:")
        for note in plan["notes"]:
            lines.append(f"  • {note}")

    return "\n".join(lines)
