"""
Decision context helpers shared by screener and multi-agent outputs.

The goal is to keep candidate-discovery signals and deep-validation signals
comparable: same signal vocabulary, same horizon, and explicit divergence
reasons when BUY/SELL/HOLD changes between modules.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


SCHEMA_VERSION = "decision_context.v1"


def default_horizon_days() -> int:
    """Return the shared decision horizon used for signal comparison."""
    try:
        value = int(os.getenv("DECISION_HORIZON_DAYS", "7"))
    except (TypeError, ValueError):
        value = 7
    return value if value > 0 else 7


def normalize_trade_signal(signal: Any) -> str:
    """Normalize common BUY/SELL/HOLD variants to buy/sell/neutral."""
    raw = (
        str(signal or "")
        .strip()
        .replace("-", "_")
        .replace(" ", "_")
        .lower()
    )
    if raw in {
        "buy",
        "strong_buy",
        "bullish",
        "bull",
        "long",
        "buy_now",
        "buy_on_dip",
        "accumulate",
        "매수",
        "강한_매수",
        "상승",
    }:
        return "buy"
    if raw in {
        "sell",
        "strong_sell",
        "bearish",
        "bear",
        "short",
        "reduce",
        "매도",
        "강한_매도",
        "하락",
    }:
        return "sell"
    if raw in {"neutral", "hold", "wait", "resize", "none", "no_action", "관망", "보유", "대기", "중립"}:
        return "neutral"
    return "neutral"


def _safe_confidence(value: Any) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        conf = 0.0
    return round(max(0.0, min(10.0, conf)), 1)


def _grade_score_floor(grade: str) -> float:
    return {"S": 90.0, "A": 80.0, "B": 70.0, "C": 55.0, "D": 30.0}.get(
        str(grade or "D").upper(),
        30.0,
    )


def screener_signal_from_score(score: Any, grade: str = "") -> str:
    """
    Screener is a candidate-discovery module, not a sell engine.

    S/A/B or 65+ means short-horizon buy candidate. C/D means no actionable
    candidate and is represented as neutral so downstream modules can decide.
    """
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = _grade_score_floor(grade)
    grade = str(grade or "").upper()
    if grade in {"S", "A", "B"} or numeric_score >= 65.0:
        return "buy"
    return "neutral"


def build_decision_context(
    *,
    source: str,
    role: str,
    signal: Any,
    confidence: Any,
    horizon_days: Optional[int] = None,
    reasoning: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a compact, comparable decision context."""
    horizon = horizon_days or default_horizon_days()
    normalized_confidence = _safe_confidence(confidence)
    if source in {"signal_aggregator", "signal_agg", "aggregator"} and normalized_confidence <= 1.0:
        normalized_confidence = _safe_confidence(normalized_confidence * 10.0)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "role": role,
        "signal": normalize_trade_signal(signal),
        "confidence": normalized_confidence,
        "horizon_days": horizon,
        "reasoning": reasoning or "",
        "metadata": metadata or {},
    }


def build_screener_context(
    *,
    score: Any,
    grade: str,
    breakdown: Optional[Dict[str, Any]] = None,
    penalties: Optional[list] = None,
    horizon_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Build candidate-discovery context from a screener row."""
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = _grade_score_floor(grade)
    signal = screener_signal_from_score(numeric_score, grade)
    confidence = numeric_score / 10.0
    return build_decision_context(
        source="screener",
        role="candidate_discovery",
        signal=signal,
        confidence=confidence,
        horizon_days=horizon_days,
        reasoning=f"스크리너 {numeric_score:.1f}점 {str(grade or 'D').upper()}등급",
        metadata={
            "score": round(max(0.0, min(100.0, numeric_score)), 1),
            "grade": str(grade or "D").upper(),
            "positive_factors": sorted((breakdown or {}).keys()),
            "penalty_factors": [
                item.get("name")
                for item in (penalties or [])
                if isinstance(item, dict) and item.get("name")
            ],
        },
    )


def build_multi_agent_context(
    final_decision: Optional[Dict[str, Any]],
    *,
    horizon_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Build deep-validation context from a multi-agent final decision."""
    fd = final_decision or {}
    return build_decision_context(
        source="multi_agent",
        role="deep_validation",
        signal=fd.get("final_signal", fd.get("signal", "neutral")),
        confidence=fd.get("final_confidence", fd.get("confidence", 0.0)),
        horizon_days=horizon_days or fd.get("horizon_days"),
        reasoning=fd.get("reasoning", ""),
        metadata={
            "consensus": fd.get("consensus"),
            "agreement_level": fd.get("agreement_level"),
            "signal_std": fd.get("signal_std"),
            "valid_agent_count": fd.get("valid_agent_count"),
            "excluded_failed_count": fd.get("excluded_failed_count"),
            "key_risks": fd.get("key_risks") or [],
            "warnings": fd.get("warnings") or [],
        },
    )


def _append_reason(reasons: list[str], code: str) -> None:
    if code not in reasons:
        reasons.append(code)


def infer_divergence_reasons(
    primary: Dict[str, Any],
    secondary: Optional[Dict[str, Any]],
    *,
    secondary_decision: Optional[Dict[str, Any]] = None,
    screener_row: Optional[Dict[str, Any]] = None,
) -> list[str]:
    """Infer compact reason codes for module-level signal differences."""
    reasons: list[str] = []
    secondary = secondary or {}
    fd = secondary_decision or {}

    if primary.get("horizon_days") != secondary.get("horizon_days"):
        _append_reason(reasons, "HORIZON_MISMATCH")

    if _safe_confidence(secondary.get("confidence")) < 5.0:
        _append_reason(reasons, "LOW_MA_CONFIDENCE")

    if fd.get("agreement_level") == "low":
        _append_reason(reasons, "AGENT_DISAGREEMENT")

    try:
        if fd.get("signal_std") is not None and float(fd["signal_std"]) >= 0.7:
            _append_reason(reasons, "HIGH_SIGNAL_VARIANCE")
    except (TypeError, ValueError):
        pass

    if (fd.get("volatility_status") or {}).get("is_high"):
        _append_reason(reasons, "HIGH_VOLATILITY")

    if (fd.get("fundamental_risks") or {}).get("critical_risks"):
        _append_reason(reasons, "CRITICAL_FUNDAMENTAL_RISK")

    risk_text = " ".join(str(x) for x in (fd.get("key_risks") or []))
    if "P/E" in risk_text or "Beta" in risk_text:
        _append_reason(reasons, "VALUATION_OR_BETA_RISK")
    if "고변동성" in risk_text or "volatility" in risk_text.lower():
        _append_reason(reasons, "HIGH_VOLATILITY")
    if "기술적" in risk_text and "퀀트" in risk_text:
        _append_reason(reasons, "FACTOR_CONFLICT")
    if "ML 정확도" in risk_text:
        _append_reason(reasons, "LOW_ML_VALIDITY")
    if "신호 강도" in risk_text or "weak signal" in risk_text.lower():
        _append_reason(reasons, "WEAK_SIGNAL_STRENGTH")

    penalties = []
    if screener_row:
        penalties = screener_row.get("penalties") or screener_row.get("screener_penalties") or []
    for item in penalties:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if name in {"high_volatility", "rsi_overbought", "macd_deadcross", "below_ma120"}:
            _append_reason(reasons, f"SCREENER_{str(name).upper()}")

    if not reasons and normalize_trade_signal(primary.get("signal")) != normalize_trade_signal(secondary.get("signal")):
        _append_reason(reasons, "DIFFERENT_MODEL_SCOPE")

    return reasons[:5]


def compare_decision_contexts(
    primary: Dict[str, Any],
    secondary: Optional[Dict[str, Any]],
    *,
    secondary_decision: Optional[Dict[str, Any]] = None,
    screener_row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compare candidate discovery and deep validation contexts.

    The returned level keeps the legacy screener UI buckets while adding
    status/reason codes for auditability.
    """
    if not secondary:
        return {
            "status": "pending",
            "level": "pending",
            "label": "미분석",
            "emoji": "⏳",
            "description": "Multi-Agent 분석 대기 중",
            "reason_codes": [],
            "horizon_days": primary.get("horizon_days", default_horizon_days()),
            "primary": primary,
            "secondary": None,
        }

    p_sig = normalize_trade_signal(primary.get("signal"))
    s_sig = normalize_trade_signal(secondary.get("signal"))
    s_conf = _safe_confidence(secondary.get("confidence"))
    horizon = primary.get("horizon_days", default_horizon_days())
    reasons = infer_divergence_reasons(
        primary,
        secondary,
        secondary_decision=secondary_decision,
        screener_row=screener_row,
    )

    if p_sig == "buy" and s_sig == "buy" and s_conf >= 7.0:
        level, label, emoji, status = "strong_match", "강한 일치", "🟢🟢", "aligned"
        desc = f"{horizon}일 horizon에서 스크리너 후보와 Multi-Agent 매수 확증이 일치"
    elif p_sig == "buy" and s_sig == "buy":
        level, label, emoji, status = "partial_match", "부분 일치", "🟢", "aligned"
        desc = f"{horizon}일 horizon에서 둘 다 매수지만 Multi-Agent 확신도는 7 미만"
    elif p_sig == "buy" and s_sig == "neutral":
        level, label, emoji, status = "partial_match", "심층 보류", "🟡", "divergent"
        desc = f"{horizon}일 horizon에서 스크리너는 후보이나 Multi-Agent는 관망"
    elif p_sig == "buy" and s_sig == "sell":
        level, label, emoji, status = "conflict", "신호 충돌", "⚠️", "divergent"
        desc = f"{horizon}일 horizon에서 스크리너 후보와 Multi-Agent 매도 의견 충돌"
    elif p_sig == "neutral" and s_sig == "buy":
        level, label, emoji, status = "unexpected_buy", "이례적 매수", "🟡", "divergent"
        desc = f"{horizon}일 horizon에서 스크리너는 약하지만 Multi-Agent는 매수"
    elif p_sig == "neutral" and s_sig == "sell":
        level, label, emoji, status = "aligned_weak", "MA 매도 확인", "🔴", "aligned"
        desc = f"{horizon}일 horizon에서 스크리너는 매수 후보가 아니고 Multi-Agent는 매도/회피"
    elif p_sig == "neutral" and s_sig == "neutral":
        level, label, emoji, status = "aligned_weak", "동반 약세", "⚪", "aligned"
        desc = f"{horizon}일 horizon에서 두 모듈 모두 매수 후보로 보지 않음"
    else:
        level, label, emoji, status = "neutral", "일치도 보통", "🔵", "mixed"
        desc = f"{horizon}일 horizon 기준 모듈 판단 보통 수준"

    if reasons:
        desc = f"{desc} · 사유: {', '.join(reasons)}"

    return {
        "status": status,
        "level": level,
        "label": label,
        "emoji": emoji,
        "description": desc,
        "reason_codes": reasons,
        "horizon_days": horizon,
        "primary": primary,
        "secondary": secondary,
    }
