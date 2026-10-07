"""단일 경로(`compute_composite_score`) R/R 하드 게이트 테스트.

2026-10-02 GLW: 지지/저항 R/R 0.20 인데 도구 평균 1.61 로 `final_signal: BUY`.
같은 결과의 LLM 결론은 '관망'이었고, 멀티에이전트 판정은 R/R 게이트로 관망이었다.
게이트가 `EnhancedDecisionMaker` 에만 있어 단일 경로 BUY 가 scan_agent 신호로
기록·알림 대상이 됐다.
"""

import os
import sys

import pandas as pd

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

import analysis_tools  # noqa: E402
from analysis_tools import ChartAnalysisAgent  # noqa: E402
from enhanced_decision_maker import EnhancedDecisionMaker  # noqa: E402


def _ohlcv(n: int = 30) -> pd.DataFrame:
    close = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "Open": close,
            "High": [c + 1 for c in close],
            "Low": [c - 1 for c in close],
            "Close": close,
            "Volume": [1_000_000] * n,
        },
        index=pd.date_range("2026-06-01", periods=n, freq="B", tz="UTC"),
    )


def _agent(score: float, rr: float | None, with_sr: bool = True) -> ChartAnalysisAgent:
    """모든 방향성 도구가 `score` 이고, 지지/저항 도구가 R/R `rr` 를 낸 agent."""
    agent = ChartAnalysisAgent("GLW", _ohlcv())
    signal = "buy" if score > 0 else ("sell" if score < 0 else "neutral")
    results = [
        {"tool": f"stub_tool_{i}", "name": f"stub {i}", "signal": signal, "score": score}
        for i in range(12)
    ]
    if with_sr:
        results.append(
            {
                "tool": "support_resistance_analysis",
                "name": "지지/저항선 분석",
                "signal": signal,
                "score": score,
                "risk_reward_ratio": rr,
            }
        )
    agent.tool_results = results
    return agent


def test_buy_with_low_rr_is_downgraded_to_hold():
    """GLW 재현: 평균은 매수 임계를 넘지만 R/R 0.20 → 관망."""
    result = _agent(1.61, 0.2).compute_composite_score()
    assert result["final_signal"] == "HOLD"
    gate = result["rr_gate"]
    assert gate["downgraded"] is True
    assert gate["pre_gate_signal"] == "BUY"
    assert gate["risk_reward"] == 0.2
    assert "0.20" in gate["reason"]


def test_downgrade_keeps_composite_score():
    """강등은 신호에만 — 점수를 바꾸면 임계 분포 진단이 오염된다."""
    result = _agent(1.61, 0.2).compute_composite_score()
    assert result["composite_score"] == 1.61


def test_buy_with_adequate_rr_stays_buy():
    result = _agent(1.61, 1.5).compute_composite_score()
    assert result["final_signal"] == "BUY"
    assert result["rr_gate"]["downgraded"] is False
    assert result["rr_gate"]["status"] == "checked"


def test_rr_at_threshold_is_not_gated():
    """하한은 '미달'에서만 막는다 (멀티에이전트와 같은 `<`)."""
    result = _agent(1.61, analysis_tools.MIN_RISK_REWARD).compute_composite_score()
    assert result["final_signal"] == "BUY"


def test_sell_is_not_gated():
    """R/R 은 진입(매수) 적격 판단이다. 매도 신호는 건드리지 않는다."""
    result = _agent(-1.0, 0.2).compute_composite_score()
    assert result["final_signal"] == "SELL"
    assert result["rr_gate"]["downgraded"] is False


def test_missing_rr_does_not_gate_but_is_reported():
    """도구가 없거나 R/R 계산 불가(0)일 때 '불리'로 읽으면 전 종목이 막힌다.

    대신 `unavailable` 로 남긴다 — 미검증을 '통과'로 덮지 않는다 (CLAUDE.md §13).
    """
    for agent in (_agent(1.61, None, with_sr=False), _agent(1.61, 0)):
        result = agent.compute_composite_score()
        assert result["final_signal"] == "BUY"
        assert result["rr_gate"]["status"] == "unavailable"
        assert result["rr_gate"]["risk_reward"] is None


def test_failed_sr_tool_is_ignored():
    agent = _agent(1.61, 0.2)
    agent.tool_results[-1]["error"] = "boom"
    result = agent.compute_composite_score()
    assert result["final_signal"] == "BUY"
    assert result["rr_gate"]["status"] == "unavailable"


def test_threshold_matches_multi_agent_gate():
    """두 경로가 다른 하한을 쓰면 같은 종목이 한쪽에선 매수, 한쪽에선 관망이 된다."""
    assert analysis_tools.MIN_RISK_REWARD == EnhancedDecisionMaker.MIN_RISK_REWARD
