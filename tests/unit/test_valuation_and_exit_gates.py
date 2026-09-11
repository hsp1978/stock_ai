"""펀더멘털 게이트 · 고베타 손절 · 출구 규칙 없는 주문 차단.

2026-09 사후검증(분석 8건, 4~5개월 경과)에서 나온 실패 3건을 고정한다.

  PLTR   P/E 225 · Beta 2.09 → "특별한 리스크 없음" → 2개월 후 -26%,
         손절 -9.9%가 일상 변동 범위여서 6월 조정에 청산
  SKAI   EPS -438 · EBITDA 마진 -28.1% → 스크리너 A등급 1순위 → 고점 대비 -60%.
         손절·익절 없이 "보유 10일"만 제시 → 같은 진입에서 +54% vs -40%
  삼영무역 순현금 > 시가총액 → 지표 부재로 미인식 → +31% 미포착

공통 구조는 이 프로젝트가 반복해 고쳐온 것과 같다: **경고 문자열이 신호를 막지
못한다.** R/R 하드 게이트(#19)와 같은 규약으로 처리한다.
"""

import os
import sys

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "../..")
for _p in (
    os.path.join(_ROOT, "stock_analyzer"),
    os.path.join(_ROOT, "chart_agent_service"),
):
    if _p not in sys.path:  # noqa: E402
        sys.path.insert(0, _p)

from enhanced_decision_maker import EnhancedDecisionMaker, _as_float  # noqa: E402


# ── 펀더멘털 게이트 ───────────────────────────────────────────────


def _buy_decision():
    return {
        "signal": "buy",
        "confidence": 8.0,
        "execution_ready": True,
        "conflicts": "없음",
        "risks": ["특별한 리스크 없음"],
    }


def test_critical_fundamental_risk_downgrades_buy_to_neutral():
    """P/E 극단 같은 critical risk 는 방향 판단과 무관하게 매수를 막는다."""
    dm = EnhancedDecisionMaker()
    out = dm._apply_valuation_gate(
        _buy_decision(),
        {"critical_risks": ["P/E 225.0 > 200: 극단 고평가", "Beta 2.09: 고변동성"]},
    )

    assert out["signal"] == "neutral"
    assert out["confidence"] <= 3.0
    assert out["execution_ready"] is False
    assert "펀더멘털 게이트" in out["conflicts"]
    # 강등 사유가 사용자에게 보이는 경로에 실린다
    assert any("P/E 225.0" in r for r in out["risks"])
    assert "특별한 리스크 없음" not in out["risks"]


def test_gate_is_noop_without_critical_risks():
    dm = EnhancedDecisionMaker()
    before = _buy_decision()
    out = dm._apply_valuation_gate(dict(before), {"critical_risks": []})

    assert out["signal"] == "buy" and out["confidence"] == 8.0


def test_loss_making_company_with_negative_ebitda_is_flagged():
    """SKAI 케이스 — 적자 + EBITDA 마이너스 조합."""
    dm = EnhancedDecisionMaker()
    assert dm.EBITDA_MARGIN_FLOOR == -0.10

    # 게이트는 critical_risks 문자열을 그대로 받아 강등한다
    out = dm._apply_valuation_gate(
        _buy_decision(),
        {"critical_risks": ["EPS -438.00 적자 + EBITDA 마진 -28.1% — 투기 등급"]},
    )
    assert out["signal"] == "neutral"


def test_as_float_rejects_none_nan_and_strings():
    assert _as_float(1.5) == 1.5
    assert _as_float("3") == 3.0
    assert _as_float(None) is None
    assert _as_float(float("nan")) is None
    assert _as_float("N/A") is None
    assert _as_float(True) is None     # bool 은 숫자로 취급하지 않는다


# ── 고베타 손절 확대 ──────────────────────────────────────────────


def _tools(stop_loss, take_profit, beta=None, price=100.0):
    tools = [
        {
            "tool": "risk_position_sizing",
            "final_levels": {"stop_loss": stop_loss, "take_profit": take_profit},
        },
        {"tool": "volatility_regime_analysis", "atr_pct": 2.0},
    ]
    if beta is not None:
        tools.append({"tool": "beta_correlation_analysis", "beta": beta})
    return tools


def test_high_beta_widens_stop_and_keeps_rr_ratio():
    """PLTR 케이스 — Beta 2.09 에 -10% 손절은 노이즈에 걸린다."""
    from entry_plan import build_entry_plan

    plan = build_entry_plan(
        ticker="PLTR",
        signal="buy",
        confidence=7.0,
        current_price=100.0,
        tool_results=_tools(stop_loss=90.0, take_profit=120.0, beta=2.09),
        trading_style="swing",
    )

    # 손절 폭 10% → 2.0배(상한) 확대 = 20%
    assert plan["stop_loss"] == pytest.approx(80.0, abs=0.5)
    # R/R 2.0 설계가 유지된다 (익절도 같은 비율로)
    assert plan["take_profit"] == pytest.approx(140.0, abs=1.0)
    assert plan["invalidation_price"] == plan["stop_loss"]
    assert any("Beta 2.09" in n for n in plan["notes"])
    # 수량 축소 필요성이 명시된다 (주당 리스크가 2배가 됐다)
    assert any("수량" in n for n in plan["notes"])


def test_normal_beta_leaves_stop_untouched():
    from entry_plan import build_entry_plan

    plan = build_entry_plan(
        ticker="IBM",
        signal="buy",
        confidence=7.0,
        current_price=100.0,
        tool_results=_tools(stop_loss=90.0, take_profit=120.0, beta=1.1),
        trading_style="swing",
    )

    assert plan["stop_loss"] == 90.0 and plan["take_profit"] == 120.0
    assert not any("Beta" in n for n in plan["notes"])


def test_missing_beta_is_not_an_error():
    from entry_plan import build_entry_plan

    plan = build_entry_plan(
        ticker="IBM",
        signal="buy",
        confidence=7.0,
        current_price=100.0,
        tool_results=_tools(stop_loss=90.0, take_profit=120.0, beta=None),
        trading_style="swing",
    )
    assert plan["stop_loss"] == 90.0


# ── 손절 없는 진입 계획 → 주문 거부 ───────────────────────────────


def test_entry_plan_without_stop_loss_produces_no_orders():
    """SKAI 케이스 — 청산 규칙 없는 포지션이 만들어지지 않는다."""
    from execution.order_router import OrderRouter

    router = OrderRouter.__new__(OrderRouter)   # __init__ 우회 (브로커 불필요)
    plan = {
        "entry_timing": "immediate",
        "order_type": "limit",
        "limit_price": 100.0,
        "stop_loss": None,
        "take_profit": 120.0,
        "split_entry": [{"pct": 100, "price": 100.0}],
    }

    requests = router.build_requests_from_entry_plan("SKAI", plan, account_size=10_000)

    assert requests == []
    # 거부 사유가 계획에 남는다 — 빈 리스트만으로는 '주문할 게 없었다'와 구별되지 않는다
    assert any("손절가 미설정" in n for n in plan["notes"])
