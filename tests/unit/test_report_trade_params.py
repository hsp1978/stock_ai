"""리포트 매매 파라미터 노출 + 신뢰도·강도 정합 테스트.

2026-07-30 감사(111770.KS): "buy 신호인데 진입가·손절가·익절가·수량이 전무"
→ 원인은 V2 미생성이 아니라 Markdown export 템플릿에 섹션 자체가 없던 것.
   (V2는 생성하고 WebUI 화면은 표시하고 있었다.)
같은 감사: "신뢰도 4.55 vs 신호 강도 strong" — 둘이 독립 계산되어 모순.
"""

import os
import sys

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _ANALYZER_DIR)

from enhanced_decision_maker import EnhancedDecisionMaker as EDM  # noqa: E402
from report_format import (  # noqa: E402
    format_entry_plan_markdown,
    format_execution_status_markdown,
    format_price,
)

_PLAN = {
    "order_type": "limit",
    "entry_timing": "breakout_confirm",
    "limit_price": 89800,
    "stop_loss": 83800,
    "take_profit": 109100,
    "expected_holding_days": 14,
    "invalidation_price": 81000,
    "split_entry": [{"pct": 40, "price": 89800}, {"pct": 60, "price": 87000}],
    "notes": ["볼린저 스퀴즈 중 — 방향성 돌파 확인 후 진입"],
}


# ── 통화 포맷 ───────────────────────────────────────────────────


def test_kr_ticker_uses_won_without_decimals():
    assert format_price(89800, "111770.KS") == "₩89,800"


def test_us_ticker_uses_dollar_with_decimals():
    assert format_price(36.06, "IONQ") == "$36.06"


def test_none_price_renders_dash():
    assert format_price(None, "IONQ") == "—"


# ── 진입 계획 섹션 ──────────────────────────────────────────────


def test_markdown_contains_all_trade_params():
    """감사에서 '전무'로 지적된 항목이 전부 나와야 한다."""
    md = format_entry_plan_markdown("111770.KS", {"final_signal": "buy", "entry_plan": _PLAN})

    assert "₩89,800" in md, "진입가 누락"
    assert "₩83,800" in md, "손절 누락"
    assert "₩109,100" in md, "익절 누락"
    assert "14일" in md
    assert "₩81,000" in md, "무효화 가격 누락"
    assert "40% @ ₩89,800" in md and "60% @ ₩87,000" in md, "분할 진입 누락"
    assert "돌파 확인" in md and "지정가" in md


def test_missing_plan_is_stated_not_omitted():
    """계획이 없을 때 섹션을 생략하면 실행 가능한 신호처럼 읽힌다."""
    md = format_entry_plan_markdown("IONQ", {
        "final_signal": "buy", "entry_plan": None,
        "entry_plan_error": "진입 계획 생성 실패",
    })

    assert "실행 불가" in md
    assert "진입 계획 생성 실패" in md


def test_neutral_without_plan_is_not_alarming():
    md = format_entry_plan_markdown("IONQ", {"final_signal": "neutral", "entry_plan": None})
    assert "실행 불가" not in md


def test_wait_timing_renders_hold_notice():
    md = format_entry_plan_markdown("IONQ", {
        "final_signal": "buy",
        "entry_plan": {"entry_timing": "wait", "notes": ["조건 미충족"]},
    })
    assert "진입 보류" in md and "조건 미충족" in md


# ── 실행 상태 요약 ──────────────────────────────────────────────


def test_execution_status_shows_ready_and_rr():
    line = format_execution_status_markdown({"execution_ready": True, "min_risk_reward": 1.42})
    assert "실행 가능" in line and "1.42" in line


def test_execution_status_flags_rr_gate():
    line = format_execution_status_markdown({
        "execution_ready": False, "min_risk_reward": 0.18,
        "warnings": ["RR_BELOW_MIN_0.8"],
    })
    assert "실행 불가" in line and "차단" in line


def test_execution_status_empty_when_unknown():
    assert format_execution_status_markdown({}) == ""


# ── 신뢰도 · 강도 정합 ─────────────────────────────────────────


def test_low_confidence_caps_strong():
    """감사 지적: 신뢰도 4.55인데 강도 strong."""
    assert EDM.cap_strength_by_confidence("strong", 4.55) == "weak"


def test_low_confidence_caps_very_strong():
    assert EDM.cap_strength_by_confidence("very_strong", 2.0) == "weak"


def test_high_confidence_keeps_strong():
    assert EDM.cap_strength_by_confidence("strong", 7.7) == "strong"


def test_boundary_confidence_keeps_label():
    assert EDM.cap_strength_by_confidence("strong", 5.0) == "strong"


def test_already_weak_not_raised():
    """상한이지 하한이 아니다 — very_weak를 weak로 올리면 안 된다."""
    assert EDM.cap_strength_by_confidence("very_weak", 1.0) == "very_weak"


def test_insider_label_also_capped():
    """내부자 특수 라벨도 낮은 신뢰도에서 '강한 신호'로 표기할 수 없다."""
    assert EDM.cap_strength_by_confidence("strong_buy_signal", 3.0) == "weak"


def test_unknown_label_passes_through():
    assert EDM.cap_strength_by_confidence("mystery", 1.0) == "mystery"
