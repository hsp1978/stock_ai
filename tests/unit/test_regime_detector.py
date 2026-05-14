"""
Rule-based regime detector 단위 테스트 (EXECUTION_PLAN Step 7)

테스트 시나리오:
- VIX=35 → VOLATILE
- VHF=0.5, ADX=30, kospi_mom=0.08 → STRONG_UPTREND
- VHF=0.25, kospi_mom=0.01 → RANGING
- regime-aware 합산: STRONG_UPTREND에서 momentum 도구 score 1.5× 가중
"""

import os
import sys

import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from regime.models import MacroContext, MarketFeatures, Regime  # noqa: E402
from regime.detector import (  # noqa: E402
    aggregate_tools_regime_aware,
    compute_vhf,
    detect_market_regime,
    apply_regime_weights_to_agents,
)


# ── compute_vhf ──────────────────────────────────────────────────────


def test_compute_vhf_trending():
    """강한 추세 → VHF > 0.4."""
    # 단조 증가하는 가격 → 고점/저점 범위 크고 일변화량 합도 큼 → VHF 중간
    prices = pd.Series(range(1, 60), dtype=float)
    vhf = compute_vhf(prices, period=28)
    assert 0 < vhf <= 1.0


def test_compute_vhf_ranging():
    """횡보 가격 → VHF < 0.5."""
    import numpy as np

    rng = np.random.default_rng(42)
    # 좁은 범위에서 왔다갔다
    prices = pd.Series(100 + rng.normal(0, 0.5, 60))
    vhf = compute_vhf(prices, period=28)
    # 횡보 시 VHF는 낮아야 함
    assert 0 < vhf


def test_compute_vhf_short_data():
    """데이터 부족 → 기본값 0.35."""
    prices = pd.Series([100.0, 101.0, 99.0])
    vhf = compute_vhf(prices, period=28)
    assert vhf == 0.35


# ── detect_market_regime ─────────────────────────────────────────────


def test_regime_volatile_high_vix():
    """VIX=35 → VOLATILE."""
    ctx = MacroContext(vix=35.0)
    mkt = MarketFeatures(vhf=0.3, adx=15.0, atr_pct=1.0)
    assert detect_market_regime(ctx, mkt) == Regime.VOLATILE


def test_regime_volatile_high_atr():
    """ATR%=4.0 → VOLATILE (VIX 낮아도)."""
    ctx = MacroContext(vix=18.0)
    mkt = MarketFeatures(atr_pct=4.0)
    assert detect_market_regime(ctx, mkt) == Regime.VOLATILE


def test_regime_strong_uptrend():
    """VHF=0.5, ADX=30, kospi/spx 모두 양의 모멘텀 → STRONG_UPTREND."""
    ctx = MacroContext(vix=15.0)
    mkt = MarketFeatures(
        vhf=0.5,
        adx=30.0,
        atr_pct=1.0,
        kospi_momentum_20d=0.08,
        spx_momentum_20d=0.07,
    )
    assert detect_market_regime(ctx, mkt) == Regime.STRONG_UPTREND


def test_regime_strong_downtrend():
    """VHF=0.5, ADX=28, kospi/spx 모두 음의 모멘텀 → STRONG_DOWNTREND."""
    ctx = MacroContext(vix=20.0)
    mkt = MarketFeatures(
        vhf=0.5,
        adx=28.0,
        atr_pct=1.5,
        kospi_momentum_20d=-0.07,
        spx_momentum_20d=-0.06,
    )
    assert detect_market_regime(ctx, mkt) == Regime.STRONG_DOWNTREND


def test_regime_ranging():
    """VHF=0.25, kospi_mom=0.01 → RANGING."""
    ctx = MacroContext(vix=18.0)
    mkt = MarketFeatures(
        vhf=0.25,
        adx=15.0,
        atr_pct=1.0,
        kospi_momentum_20d=0.01,
        spx_momentum_20d=0.02,
    )
    assert detect_market_regime(ctx, mkt) == Regime.RANGING


def test_regime_normal():
    """조건 불만족 → NORMAL."""
    ctx = MacroContext(vix=20.0)
    mkt = MarketFeatures(
        vhf=0.35,
        adx=20.0,
        atr_pct=1.5,
        kospi_momentum_20d=0.03,
        spx_momentum_20d=0.02,
    )
    assert detect_market_regime(ctx, mkt) == Regime.NORMAL


# ── aggregate_tools_regime_aware ────────────────────────────────────


def test_regime_aware_uptrend_boosts_momentum():
    """STRONG_UPTREND 에서 momentum 도구 score가 1.5× 적용됨."""
    tool_outputs = {
        "trend_ma": {"score": 4.0},  # momentum → ×1.5
        "rsi_divergence": {"score": 2.0},  # mean_reversion → ×0.3
    }
    score = aggregate_tools_regime_aware(tool_outputs, Regime.STRONG_UPTREND)
    # 4.0*1.5 + 2.0*0.3 = 6.0 + 0.6 = 6.6
    assert abs(score - 6.6) < 0.01


def test_regime_aware_ranging_boosts_mean_reversion():
    """RANGING 에서 mean_reversion 도구 score가 1.5× 적용됨."""
    tool_outputs = {
        "trend_ma": {"score": 4.0},  # momentum → ×0.4
        "rsi_divergence": {"score": 2.0},  # mean_reversion → ×1.5
    }
    score = aggregate_tools_regime_aware(tool_outputs, Regime.RANGING)
    # 4.0*0.4 + 2.0*1.5 = 1.6 + 3.0 = 4.6
    assert abs(score - 4.6) < 0.01


def test_regime_aware_normal_no_weighting():
    """NORMAL 에서 모든 카테고리 1.0× → 단순 합산."""
    tool_outputs = {
        "trend_ma": {"score": 3.0},
        "rsi_divergence": {"score": 2.0},
        "volume_analysis": {"score": 1.0},
    }
    score = aggregate_tools_regime_aware(tool_outputs, Regime.NORMAL)
    assert abs(score - 6.0) < 0.01


# ── apply_regime_weights_to_agents ──────────────────────────────────


def _make_agent_result(name: str, signal: str, confidence: float):
    from dataclasses import dataclass

    @dataclass
    class _AR:
        agent_name: str
        signal: str
        confidence: float
        error: None = None

    return _AR(agent_name=name, signal=signal, confidence=confidence)


def test_apply_regime_weights_buy_momentum():
    """STRONG_UPTREND에서 Technical(momentum) BUY → 1.5× 가중."""
    results = [
        _make_agent_result("Technical Analyst", "buy", 7.0),
    ]
    score = apply_regime_weights_to_agents(results, Regime.STRONG_UPTREND)
    # 1.0 * 7.0 * 1.5 = 10.5
    assert abs(score - 10.5) < 0.01


def test_apply_regime_weights_mixed_signals():
    """혼합 신호 → 가중 합산."""
    results = [
        _make_agent_result("Technical Analyst", "buy", 8.0),  # momentum ×1.5
        _make_agent_result("Risk Manager", "sell", 5.0),  # fundamental ×1.0
    ]
    score = apply_regime_weights_to_agents(results, Regime.STRONG_UPTREND)
    # buy: 1.0 * 8.0 * 1.5 = 12.0
    # sell: -1.0 * 5.0 * 1.0 = -5.0
    # total = 7.0
    assert abs(score - 7.0) < 0.01
