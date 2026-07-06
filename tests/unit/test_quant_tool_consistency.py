"""퀀트 도구·멀티에이전트 정합성 감사(2026-07) 수정 회귀 테스트.

발견 결함:
1. ML 정확도 키 불일치 (ml_pipeline_fix "accuracy" vs DM "test_accuracy")
   → 정확도 가중치 규칙 사문화
2. 피보나치: 가산 전용 점수로 sell 도달 불가 (구조적 매수 편향)
3. 변동성 체제: 점수 범위상 buy/sell 도달 불가한 죽은 신호 분기
4. 평균회귀: |z|<0.5 상시 +1 드리프트
5. 베타: 한국 종목도 SPY 벤치마크 고정, IR 가점 비대칭
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

from analysis_tools import AnalysisTools  # noqa: E402
from enhanced_decision_maker import EnhancedDecisionMaker  # noqa: E402


def _df_from_closes(closes, volume=50_000):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": np.full(len(closes), float(volume)),
        },
        index=pd.date_range("2025-06-01", periods=len(closes), freq="B"),
    )


# ── 피보나치 대칭성 ───────────────────────────────────────────


def test_fibonacci_sell_reachable_on_deep_retracement():
    """되돌림 78.6% 초과(추세 붕괴 임박)에서 sell이 나와야 한다."""
    # 고점 100 형성 후 52까지 하락 (저점 50 근처) → 되돌림 ≈ 96%
    closes = list(np.linspace(60, 100, 60)) + list(np.linspace(100, 52, 60))
    tools = AnalysisTools("TEST", _df_from_closes(closes))
    result = tools.fibonacci_retracement_analysis()

    assert result["current_retracement"] > 0.786
    assert result["score"] < 0
    assert result["signal"] == "sell"


def test_fibonacci_buy_on_shallow_retracement():
    """얕은 되돌림(강한 추세 지속)에서 buy가 나와야 한다."""
    closes = list(np.linspace(50, 100, 120))  # 지속 상승, 현재가 고점 근처
    tools = AnalysisTools("TEST", _df_from_closes(closes))
    result = tools.fibonacci_retracement_analysis()

    assert result["current_retracement"] < 0.236
    assert result["score"] > 2
    assert result["signal"] == "buy"


# ── 변동성 체제 비방향성 ─────────────────────────────────────


def test_volatility_regime_is_explicitly_non_directional():
    closes = 100 + np.cumsum(np.random.default_rng(7).normal(0, 1, 120))
    df = _df_from_closes(closes)
    # ATR 지표 주입 (calculate_indicators 없이 단독 테스트)
    df["ATR"] = (df["High"] - df["Low"]).rolling(14).mean()
    tools = AnalysisTools("TEST", df)
    result = tools.volatility_regime_analysis()

    assert result["signal"] == "neutral"
    assert result.get("directional") is False
    # 절대(연환산) vs 상대(퍼센타일) 라벨 기준 명시 확인
    assert "절대기준" in result["detail"]
    assert "상대기준" in result["detail"]


# ── 평균회귀 드리프트 제거 ───────────────────────────────────


def test_mean_reversion_no_positive_drift_near_mean():
    """평균 근처(|z|<0.5)는 0점이어야 한다 (과거 +1 드리프트 제거)."""
    rng = np.random.default_rng(11)
    closes = 100 + rng.normal(0, 0.3, 120)  # 평균 100 주변 잡음
    tools = AnalysisTools("TEST", _df_from_closes(closes))
    result = tools.mean_reversion_analysis()

    if abs(result["avg_z_score"]) < 0.5:
        assert result["score"] == 0
        assert result["signal"] == "neutral"


# ── 베타 벤치마크 선택 ───────────────────────────────────────


def test_beta_benchmark_symbol_by_market():
    assert AnalysisTools._beta_benchmark_symbol("005930.KS") == "^KS11"
    assert AnalysisTools._beta_benchmark_symbol("950170.KQ") == "^KQ11"
    assert AnalysisTools._beta_benchmark_symbol("AAPL") == "SPY"


# ── DM: ML 정확도 키 이원화 수용 ─────────────────────────────


@dataclass
class FakeAgentResult:
    agent_name: str
    signal: str
    confidence: float
    error: Optional[str] = None
    evidence: list = field(default_factory=list)
    reasoning: str = ""
    llm_provider: str = "test"
    execution_time: float = 0.0


def _quiet_dm(monkeypatch) -> EnhancedDecisionMaker:
    dm = EnhancedDecisionMaker()
    monkeypatch.setattr(
        dm, "_check_fundamental_risks",
        lambda ticker: {"warnings": [], "critical_risks": []},
    )
    monkeypatch.setattr(dm, "_apply_confidence_smoothing", lambda v: v)
    monkeypatch.setitem(sys.modules, "regime.detector", None)
    return dm


def _ml_agent_with_accuracy_key(key: str, acc: float):
    return FakeAgentResult(
        agent_name="ML Specialist",
        signal="buy",
        confidence=2.0,
        evidence=[
            {
                "tool": "ml_ensemble",
                "result": {
                    "ensemble": {"up_probability": 0.6, "model_count": 2},
                    "models": {
                        "model_a": {key: acc, "status": "success"},
                        "model_b": {key: acc, "status": "success"},
                    },
                },
            }
        ],
    )


def test_dm_reads_ml_accuracy_from_pipeline_fix_key(monkeypatch):
    """ml_pipeline_fix의 'accuracy' 키도 추출돼 가중치 규칙이 작동해야 한다."""
    dm = _quiet_dm(monkeypatch)
    captured = {}

    def _capture(signal_counts, signal_strength, *args, **kwargs):
        captured["strength"] = signal_strength
        return {"signal": "neutral", "confidence": 3.0, "conflicts": "없음",
                "reasoning": "t", "risks": []}

    monkeypatch.setattr(dm, "_make_final_decision", _capture)

    # 정확도 52% → 50-55% 구간 → ml_weight 0.3
    dm.aggregate("AAPL", [_ml_agent_with_accuracy_key("accuracy", 0.52)])
    assert captured["strength"]["ml_adjusted"]["weight"] == 0.3

    # 레거시 test_accuracy 키도 동일 동작
    dm.aggregate("AAPL", [_ml_agent_with_accuracy_key("test_accuracy", 0.52)])
    assert captured["strength"]["ml_adjusted"]["weight"] == 0.3


def test_dm_ignores_ml_signal_below_50pct_accuracy(monkeypatch):
    dm = _quiet_dm(monkeypatch)
    captured = {}

    def _capture(signal_counts, signal_strength, *args, **kwargs):
        captured["strength"] = signal_strength
        return {"signal": "neutral", "confidence": 3.0, "conflicts": "없음",
                "reasoning": "t", "risks": []}

    monkeypatch.setattr(dm, "_make_final_decision", _capture)
    dm.aggregate("AAPL", [_ml_agent_with_accuracy_key("accuracy", 0.45)])

    assert captured["strength"]["ml_adjusted"]["weight"] == 0.0
    assert captured["strength"]["ml_adjusted"]["contribution"] == 0


# ── DM: 변동성 키워드 부정문 오탐 방지 ───────────────────────


def test_volatility_check_ignores_negated_mentions(monkeypatch):
    dm = _quiet_dm(monkeypatch)
    agents = [
        FakeAgentResult("Technical Analyst", "neutral", 5.0,
                        reasoning="현재 고변동성 우려는 없음. 안정적 추세."),
        FakeAgentResult("Quant Analyst", "neutral", 5.0,
                        reasoning="변동성 증가 조짐은 관찰되지 않음."),
    ]
    check = dm._check_volatility(agents)
    assert check["is_high"] is False

    agents_hot = [
        FakeAgentResult("Technical Analyst", "neutral", 5.0,
                        reasoning="고변동성 구간 진입. 주의 필요."),
        FakeAgentResult("Quant Analyst", "neutral", 5.0,
                        reasoning="변동성 증가 뚜렷. 리스크 확대."),
    ]
    check_hot = dm._check_volatility(agents_hot)
    assert check_hot["is_high"] is True
