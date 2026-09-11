"""지표 해석 가드 — 같은 숫자를 도구와 서술이 다르게 읽던 문제.

2026-09 사후검증에서 나온 실제 오독 (전부 DB손해보험 2026-08-18 리포트):

| 근거 숫자 | 에이전트 서술 | 실제 |
|---|---|---|
| `reversion_probability: 1.04%` | "되돌림 가능성 높음" | 회귀확률 낮음 = 추세 지속 |
| `RSI 64.57` | "과매수 진입" | 기준 70 미달 |
| `연환산 변동성 64.0%` | "안정적" | S&P500 평균의 3~4배 |

같은 리포트에서 Hurst 0.639(trending)와 모멘텀 가속이 함께 나왔는데도 자체 모순을
감지하지 못했고, 매수 3명 전원이 적중한 신호가 약화됐다(실제 +11%).

여기서 고정하는 것:
  1. 임계값은 단일 출처(`indicator_thresholds`)이고 프롬프트에 실린다
  2. 도구가 숫자와 함께 **해석**을 내보낸다 (프롬프트만으로는 드리프트를 막지 못한다)
  3. 회귀확률 낮음 + Hurst trending 이면 평균회귀 매도 방향을 중립으로 되돌린다
  4. 서술이 근거 숫자와 모순되면 신뢰도를 깎고 사유를 남긴다
"""

import os
import sys

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "../..")
for _p in (
    os.path.join(_ROOT, "chart_agent_service"),
    os.path.join(_ROOT, "stock_analyzer"),
):
    if _p not in sys.path:  # noqa: E402
        sys.path.insert(0, _p)

from indicator_thresholds import (  # noqa: E402
    ADX_MODERATE,
    RSI_OVERBOUGHT,
    adx_label,
    prompt_threshold_table,
    rsi_label,
    volatility_label,
    volume_label,
)


# ── 임계값 단일 출처 ──────────────────────────────────────────────


def test_labels_match_the_cases_that_were_misread():
    """DB손해보험 리포트의 오독 3건이 라벨 단계에서 걸린다."""
    assert "과매수" not in rsi_label(64.57)        # 기준 70 미달
    assert "중립-강세" in rsi_label(64.57)
    assert "매우 높음" in volatility_label(64.0)   # "안정적"이 아니다
    assert "추세 없음" in adx_label(22.0)


def test_rsi_label_boundaries_follow_config():
    assert "과매수" in rsi_label(RSI_OVERBOUGHT + 0.1)
    assert "과매수" not in rsi_label(RSI_OVERBOUGHT)   # 경계값은 과매수 아님
    assert "과매도" in rsi_label(20.0)
    assert rsi_label(None) == "데이터 없음"


def test_volume_label_direction_is_not_inverted():
    """영원무역 사례 — 거래량 0.47x 를 '경고 수준 미달'로 서술했다."""
    assert "위축" in volume_label(0.47)
    assert "급증" in volume_label(2.0)
    assert volume_label(1.0) == "보통"


def test_adx_thresholds_are_exposed_for_prompts():
    table = prompt_threshold_table()

    assert f"{RSI_OVERBOUGHT}" in table
    assert f"{ADX_MODERATE}" in table
    assert "reversion_probability" in table
    # 회귀확률의 방향을 프롬프트가 명시한다 (이게 오독의 핵심이었다)
    assert "추세 지속" in table and "되돌림" in table


# ── 도구가 해석을 함께 내보낸다 ───────────────────────────────────


def _tools_from_prices(prices):
    import pandas as pd

    from analysis_tools import AnalysisTools

    df = pd.DataFrame({"Close": prices, "High": prices, "Low": prices,
                       "Volume": [1000] * len(prices)})
    tools = AnalysisTools.__new__(AnalysisTools)
    tools.ticker = "TEST"
    tools.df = df
    tools.close = df["Close"]
    tools.latest = df.iloc[-1]
    return tools


def test_mean_reversion_carries_its_own_reading():
    """숫자만 보내면 LLM이 Z-score 크기와 혼동한다."""
    import numpy as np

    prices = list(np.linspace(100, 150, 120))      # 강한 상승 추세
    tools = _tools_from_prices(prices)
    result = tools.mean_reversion_analysis()

    assert "reversion_reading" in result
    assert result["reversion_reading"] in (
        "낮음 → 추세 지속 우세", "높음 → 되돌림 경계", "중간",
    )
    # detail 에도 해석이 실려 프롬프트 요약에 들어간다
    assert result["reversion_reading"] in result["detail"]


# ── 도구 간 교차 가드 ─────────────────────────────────────────────


def test_low_reversion_probability_with_trending_hurst_cancels_sell():
    """DB손해보험 조합 — 회귀확률 1.04% + Hurst 0.639 인데 매도."""
    from analysis_tools import apply_cross_tool_guards

    results = [
        {"tool": "mean_reversion_analysis", "signal": "sell", "score": -3,
         "reversion_probability": 0.0104, "detail": "평균Z=2.10, 회귀확률=1.0%"},
        {"tool": "correlation_regime_analysis", "signal": "buy", "score": 2,
         "hurst_exponent": 0.639},
    ]

    apply_cross_tool_guards(results)
    mr = results[0]

    assert mr["signal"] == "neutral"
    assert "추세 지속 우세" in mr["cross_tool_guard"]
    assert "회귀확률 1.0%" in mr["cross_tool_guard"]
    # 점수는 건드리지 않는다 — 임계 재정합 없는 점수 조정은 이중 보정이 된다
    assert mr["score"] == -3


def test_guard_leaves_high_reversion_probability_sell_alone():
    from analysis_tools import apply_cross_tool_guards

    results = [
        {"tool": "mean_reversion_analysis", "signal": "sell", "score": -3,
         "reversion_probability": 0.75, "detail": ""},
        {"tool": "correlation_regime_analysis", "signal": "sell", "score": -1,
         "hurst_exponent": 0.62},
    ]
    apply_cross_tool_guards(results)

    assert results[0]["signal"] == "sell"
    assert "cross_tool_guard" not in results[0]


def test_guard_needs_both_tools_and_tolerates_missing_fields():
    from analysis_tools import apply_cross_tool_guards

    only_one = [{"tool": "mean_reversion_analysis", "signal": "sell",
                 "reversion_probability": 0.01}]
    assert apply_cross_tool_guards(only_one)[0]["signal"] == "sell"

    missing = [
        {"tool": "mean_reversion_analysis", "signal": "sell",
         "reversion_probability": None},
        {"tool": "correlation_regime_analysis", "hurst_exponent": 0.7},
    ]
    assert apply_cross_tool_guards(missing)[0]["signal"] == "sell"


# ── 서술 모순 검증 ────────────────────────────────────────────────


def _agent():
    from multi_agent import QuantAnalyst

    return QuantAnalyst(llm_provider="ollama")


def _evidence(**facts):
    return [{"tool": "mean_reversion_analysis", "result": facts}]


def test_detects_reversion_probability_contradiction():
    """DB손해보험 실제 문구 — 회귀확률 1.04% 인데 '되돌림 가능성 높음'."""
    issues = _agent()._check_reasoning_contradictions(
        "평균 회귀 지표에서 되돌림 가능성이 높게 나타납니다. 따라서 매도 우위입니다.",
        _evidence(reversion_probability=0.0104),
    )

    assert len(issues) == 1
    assert "회귀확률 1.0%" in issues[0]


def test_detects_rsi_and_volatility_contradictions():
    agent = _agent()

    rsi_issues = agent._check_reasoning_contradictions(
        "RSI가 과매수 구간에 진입했습니다.", _evidence(current_rsi=64.57)
    )
    assert rsi_issues and "과매수 기준" in rsi_issues[0]

    vol_issues = agent._check_reasoning_contradictions(
        "변동성은 안정적인 수준입니다.", _evidence(annualized_volatility=64.0)
    )
    assert vol_issues and "64.0%" in vol_issues[0]


def test_no_false_positive_when_narrative_matches_numbers():
    agent = _agent()

    assert agent._check_reasoning_contradictions(
        "RSI 75로 과매수 구간입니다.", _evidence(current_rsi=75.0)
    ) == []
    assert agent._check_reasoning_contradictions(
        "회귀확률 80%로 되돌림 가능성이 높습니다.",
        _evidence(reversion_probability=0.80),
    ) == []
    assert agent._check_reasoning_contradictions(
        "추세가 지속될 가능성이 높습니다.", _evidence(reversion_probability=0.01)
    ) == []
    assert agent._check_reasoning_contradictions("", _evidence()) == []


def test_threshold_table_is_injected_into_prompt():
    agent = _agent()
    prompt = agent._build_prompt("005830.KS", _evidence(current_rsi=64.57))

    assert "지표 해석 기준" in prompt
    assert "reversion_probability" in prompt
