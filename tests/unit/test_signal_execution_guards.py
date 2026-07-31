"""실행 가능성 게이트 테스트 (R/R 하한 · 매매 파라미터 · 국내 지수 스트레스).

2026-07-30 감사(111770.KS 리포트): R/R 0.20 경고가 출력되는데도 최종 신호가
buy였고, 진입가·손절가가 전부 없는 채로 '강한 매수'로 읽혔다. 동시에 KOSPI가
7/28 -10.84%, 월중 -32.6% 붕괴 중이었으나 macro 기여는 0이었다 — 거시 지표
수집 대상이 VIX·미국채·DXY·WTI·S&P500으로 전부 미국 지표였기 때문이다.
"""

import os
import sys

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

import macro_context  # noqa: E402
from enhanced_decision_maker import EnhancedDecisionMaker  # noqa: E402


class _Result:
    """AgentResult 최소 대역 — evidence만 쓴다."""

    def __init__(self, evidence, error=None):
        self.evidence = evidence
        self.error = error


def _sr(rr):
    return _Result([{"tool": "support_resistance_analysis", "result": {"risk_reward_ratio": rr}}])


# ── R/R 추출 ────────────────────────────────────────────────────


def test_min_risk_reward_takes_minimum():
    dm = EnhancedDecisionMaker.__new__(EnhancedDecisionMaker)
    assert dm._min_risk_reward([_sr(1.4), _sr(0.2), _sr(0.9)]) == 0.2


def test_min_risk_reward_ignores_failed_agents():
    dm = EnhancedDecisionMaker.__new__(EnhancedDecisionMaker)
    bad = _Result([{"tool": "support_resistance_analysis",
                    "result": {"risk_reward_ratio": 0.1}}], error="boom")
    assert dm._min_risk_reward([bad, _sr(1.2)]) == 1.2


def test_min_risk_reward_none_when_absent():
    dm = EnhancedDecisionMaker.__new__(EnhancedDecisionMaker)
    assert dm._min_risk_reward([_Result([{"tool": "other", "result": {}}])]) is None


# ── R/R 하드 게이트 ─────────────────────────────────────────────


def test_buy_downgraded_when_rr_below_min():
    """R/R 0.20 = 손실이 수익의 5배. 방향과 무관하게 진입 부적격."""
    dm = EnhancedDecisionMaker.__new__(EnhancedDecisionMaker)
    out = dm._apply_risk_reward_gate(
        {"signal": "buy", "confidence": 7.0, "reasoning": "강세", "conflicts": "없음"}, 0.20
    )

    assert out["signal"] == "neutral"
    assert out["confidence"] <= 3.0
    assert out["rr_downgraded"] is True
    assert "0.20" in out["conflicts"]


def test_buy_kept_when_rr_sufficient():
    dm = EnhancedDecisionMaker.__new__(EnhancedDecisionMaker)
    decision = {"signal": "buy", "confidence": 7.0, "reasoning": "r", "conflicts": "없음"}
    assert dm._apply_risk_reward_gate(decision, 1.5)["signal"] == "buy"


def test_sell_not_affected_by_rr_gate():
    """R/R은 매수 진입 기준이다 — 매도(청산) 신호까지 막으면 위험을 키운다."""
    dm = EnhancedDecisionMaker.__new__(EnhancedDecisionMaker)
    decision = {"signal": "sell", "confidence": 7.0, "reasoning": "r", "conflicts": "없음"}
    assert dm._apply_risk_reward_gate(decision, 0.2)["signal"] == "sell"


def test_missing_rr_does_not_gate():
    """도구가 안 돌았을 때 R/R 없음을 '불리'로 읽으면 전 종목이 막힌다."""
    dm = EnhancedDecisionMaker.__new__(EnhancedDecisionMaker)
    decision = {"signal": "buy", "confidence": 7.0, "reasoning": "r", "conflicts": "없음"}
    assert dm._apply_risk_reward_gate(decision, None)["signal"] == "buy"


def test_gate_threshold_is_configurable_constant():
    assert EnhancedDecisionMaker.MIN_RISK_REWARD == 0.8


# ── 국내 지수 스트레스 ──────────────────────────────────────────


def test_circuit_breaker_level_daily_drop_is_crash():
    """KRX 서킷브레이커 1단계가 -8%. 2026-07-28 실측 -10.84%."""
    assert macro_context._kr_market_stress(-10.84, -12.0, -18.0) == "crash"


def test_monthly_collapse_is_crash_even_on_rebound_day():
    """급락장 반등일에 melt_up으로 읽으면 가장 위험한 날 경고가 사라진다.

    2026-07-31 실측: 일간 +13.95%, 월간 -24.8%.
    """
    assert macro_context._kr_market_stress(13.95, -5.65, -24.8) == "crash"


def test_moderate_drop_is_stressed():
    assert macro_context._kr_market_stress(-3.5, -4.0, -6.0) == "stressed"


def test_calm_market_is_normal():
    assert macro_context._kr_market_stress(0.4, 1.2, 2.0) == "normal"


def test_unknown_when_no_data():
    assert macro_context._kr_market_stress(None, None, None) == "unknown"


def test_kr_indices_registered():
    """수집 대상에 국내 지수가 있어야 한다 — 이게 빠져서 macro가 0이었다."""
    assert macro_context.MACRO_TICKERS["kospi"] == "^KS11"
    assert macro_context.MACRO_TICKERS["kosdaq"] == "^KQ11"


def test_summary_warns_on_kr_crash():
    text = macro_context._build_summary(
        20.0, "neutral", 4.0, "neutral", "neutral", "neutral", "neutral",
        kr_stress="crash", kospi_1d=-10.84,
    )
    assert "급락" in text and "부적합" in text


def test_summary_silent_when_kr_normal():
    text = macro_context._build_summary(
        20.0, "neutral", 4.0, "neutral", "neutral", "neutral", "neutral",
        kr_stress="normal", kospi_1d=0.3,
    )
    assert "급락" not in text


# ── 실행 가능성 판정 (2026-07-31 회귀 수정) ──────────────────────
#
# PR #19는 aggregate() 안에서 execution_ready를 판정했다. 그런데 orchestrator는
# aggregate() 반환 뒤에 entry_plan을 붙이므로(multi_agent 4단계), 판정 시점에는
# 계획이 항상 없었다 → 모든 매수·매도의 신뢰도가 5.0으로 깎였다.


def test_ready_when_plan_complete():
    d = EnhancedDecisionMaker.apply_execution_readiness({
        "final_signal": "buy", "final_confidence": 8.2,
        "entry_plan": {"limit_price": 36.06, "stop_loss": 33.29},
    })
    assert d["execution_ready"] is True
    assert d["final_confidence"] == 8.2, "완비된 계획인데 신뢰도가 깎였다"
    assert "NO_ENTRY_PLAN_NOT_EXECUTABLE" not in (d.get("warnings") or [])


def test_not_ready_when_stop_missing():
    """진입가만 있고 손절이 없으면 실행 불가 — 실제로 ATR 부재 시 발생한다."""
    d = EnhancedDecisionMaker.apply_execution_readiness({
        "final_signal": "buy", "final_confidence": 8.2,
        "entry_plan": {"limit_price": 36.06, "stop_loss": None},
    })
    assert d["execution_ready"] is False
    assert d["final_confidence"] == 5.0
    assert "NO_ENTRY_PLAN_NOT_EXECUTABLE" in d["warnings"]


def test_neutral_not_capped():
    """관망은 실행 대상이 아니므로 상한을 걸지 않는다."""
    d = EnhancedDecisionMaker.apply_execution_readiness({
        "final_signal": "neutral", "final_confidence": 8.2, "entry_plan": None,
    })
    assert d["final_confidence"] == 8.2


def test_warning_not_duplicated_on_repeat_call():
    d = {"final_signal": "buy", "final_confidence": 8.2, "entry_plan": {}}
    EnhancedDecisionMaker.apply_execution_readiness(d)
    EnhancedDecisionMaker.apply_execution_readiness(d)
    assert d["warnings"].count("NO_ENTRY_PLAN_NOT_EXECUTABLE") == 1


def test_aggregate_does_not_decide_readiness():
    """aggregate()는 execution_ready를 확정하지 않는다 — 회귀 방지."""
    import inspect

    src = inspect.getsource(EnhancedDecisionMaker.aggregate)
    assert "execution_ready" not in src, (
        "aggregate() 안에서 판정하면 entry_plan이 아직 없어 항상 False가 된다"
    )
