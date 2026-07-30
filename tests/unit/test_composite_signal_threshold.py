"""composite score → 신호 판정 임계값 스케일 정합 테스트.

2026-07-30 진단: `compute_composite_score`가 '도구 평균'(실측 [-1.00, +2.04])에
'합계' 스케일 잔재인 ±2.0을 적용해 40일간 BUY 1건 / SELL 0건이었다.
알림 임계는 2026-07 커밋에서 이미 평균 스케일로 고쳤지만, binding 쪽인
신호 판정 임계가 남아 알림 임계를 넘긴 817건이 전부 HOLD로 기록됐다.
"""

import os
import sys

import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import config  # noqa: E402
from analysis_tools import ChartAnalysisAgent  # noqa: E402


def _ohlcv(n: int = 30) -> pd.DataFrame:
    """AnalysisTools 초기화를 통과할 최소 OHLCV (지표는 쓰지 않는다)."""
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


def _agent_with_scores(scores: list[float]) -> ChartAnalysisAgent:
    """방향성 도구 점수만 주입한 agent — run_all_tools를 우회한다."""
    agent = ChartAnalysisAgent("TEST.KQ", _ohlcv())
    agent.tool_results = [
        {
            "tool": f"stub_tool_{i}",
            "name": f"stub {i}",
            "signal": "buy" if s > 0 else ("sell" if s < 0 else "neutral"),
            "score": s,
        }
        for i, s in enumerate(scores)
    ]
    return agent


def _signal_for_mean(mean_score: float) -> str:
    """평균이 정확히 mean_score가 되는 도구 집합으로 판정 결과를 얻는다."""
    result = _agent_with_scores([mean_score] * 12).compute_composite_score()
    assert result["composite_score"] == round(mean_score, 2)
    return result["final_signal"]


def test_observed_p90_produces_buy():
    """실측 p90(+1.14)~p95(+1.37) 구간에서 BUY가 나와야 한다.

    과거 ±2.0에서는 이 구간 전체가 HOLD였다 (26,041 스캔 중 BUY 7건).
    """
    assert _signal_for_mean(1.37) == "BUY"


def test_observed_p10_produces_sell():
    """실측 최솟값이 -1.00이므로 SELL 컷은 그 안쪽이어야 한다."""
    assert _signal_for_mean(-0.75) == "SELL"


def test_median_stays_hold():
    """실측 중앙값(+0.41)은 여전히 관망이어야 한다 — 과도 발신 방지."""
    assert _signal_for_mean(0.41) == "HOLD"


def test_thresholds_come_from_config(monkeypatch):
    """임계값이 하드코딩이 아니라 config에서 온다."""
    monkeypatch.setattr("analysis_tools.SIGNAL_BUY_THRESHOLD", 5.0)
    monkeypatch.setattr("analysis_tools.SIGNAL_SELL_THRESHOLD", -5.0)

    assert _agent_with_scores([1.37] * 12).compute_composite_score()["final_signal"] == "HOLD"


def test_sell_threshold_is_reachable():
    """SELL 컷이 실측 최솟값(-1.00) 밖이면 구조적으로 발생 불가."""
    assert config.SIGNAL_SELL_THRESHOLD > -1.0


def test_buy_cut_above_median():
    """BUY 컷이 중앙값 아래로 내려가면 절반이 매수 신호가 된다."""
    assert config.SIGNAL_BUY_THRESHOLD > 0.41
