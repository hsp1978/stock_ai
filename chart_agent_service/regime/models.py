"""
시장 체제 모델 (Step 7).

Regime      : 5-state 열거형
MacroContext: VIX 등 거시 지표
MarketFeatures: VHF·ADX·ATR%·20d 모멘텀
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Regime(str, Enum):
    STRONG_UPTREND = "strong_uptrend"
    STRONG_DOWNTREND = "strong_downtrend"
    RANGING = "ranging"
    VOLATILE = "volatile"
    NORMAL = "normal"


@dataclass
class MacroContext:
    """거시 지표 컨텍스트."""

    vix: float = 20.0
    vix_prev: float = 0.0  # 스파이크 감지용 (0 이면 미사용)
    us10y: Optional[float] = None
    dxy_trend: str = "stable"  # "rising" | "falling" | "stable"


@dataclass
class MarketFeatures:
    """기술적 시장 특성."""

    vhf: float = 0.35
    adx: float = 20.0
    atr_pct: float = 1.5  # ATR / 현재가 (%)
    kospi_momentum_20d: float = 0.0  # KOSPI 20 영업일 수익률
    spx_momentum_20d: float = 0.0  # S&P500 20 영업일 수익률


# ── Regime → 카테고리별 가중치 ──────────────────────────────────────

REGIME_WEIGHTS: dict[Regime, dict[str, float]] = {
    Regime.STRONG_UPTREND: {
        "momentum": 1.5,
        "mean_reversion": 0.3,
        "fundamental": 1.0,
    },
    Regime.STRONG_DOWNTREND: {
        "momentum": 1.2,
        "mean_reversion": 0.5,
        "fundamental": 1.0,
    },
    Regime.RANGING: {
        "momentum": 0.4,
        "mean_reversion": 1.5,
        "fundamental": 1.2,
    },
    Regime.VOLATILE: {
        "momentum": 0.3,
        "mean_reversion": 0.3,
        "fundamental": 1.8,
    },
    Regime.NORMAL: {
        "momentum": 1.0,
        "mean_reversion": 1.0,
        "fundamental": 1.0,
    },
}

# ── 도구 → 카테고리 매핑 ─────────────────────────────────────────────

TOOL_CATEGORY: dict[str, str] = {
    # momentum
    "trend_ma": "momentum",
    "macd_momentum": "momentum",
    "macd_rsi_cross": "momentum",
    "adx_trend_strength": "momentum",
    "momentum_rank": "momentum",
    "macd": "momentum",
    "ema_cross": "momentum",
    # mean_reversion
    "rsi_divergence": "mean_reversion",
    "rsi_mfi_combined": "mean_reversion",
    "bollinger_squeeze": "mean_reversion",
    "mean_reversion": "mean_reversion",
    "stochastic": "mean_reversion",
    "rsi": "mean_reversion",
    "mfi": "mean_reversion",
    "bollinger": "mean_reversion",
    # fundamental
    "volume_analysis": "fundamental",
    "support_resistance": "fundamental",
    "fibonacci": "fundamental",
    "candlestick": "fundamental",
    "insider_trading": "fundamental",
    "options_pcr": "fundamental",
    "fundamental": "fundamental",
    "macro": "fundamental",
}
