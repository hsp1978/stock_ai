"""
Rule-based 시장 체제 탐지기 (Step 7).

detect_market_regime(): VIX·ATR%·VHF·ADX·20d 모멘텀 기반 5-state Regime 판정
fetch_market_features(): yfinance로 SPX/KOSPI 데이터 수집 → MarketFeatures
aggregate_tools_regime_aware(): 도구 점수에 regime 가중치 적용
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from regime.models import (
    REGIME_WEIGHTS,
    TOOL_CATEGORY,
    MacroContext,
    MarketFeatures,
    Regime,
)

logger = logging.getLogger(__name__)


# ── VHF 계산 ─────────────────────────────────────────────────────────


def compute_vhf(close: pd.Series, period: int = 28) -> float:
    """Vertical Horizontal Filter — 추세 vs 횡보 판별."""
    if len(close) < period + 1:
        return 0.35  # 데이터 부족 시 neutral 기본값

    rolling_max = close.rolling(period).max()
    rolling_min = close.rolling(period).min()
    abs_changes = close.diff().abs().rolling(period).sum()

    numerator = (rolling_max - rolling_min).iloc[-1]
    denominator = abs_changes.iloc[-1]

    if denominator == 0 or np.isnan(denominator):
        return 0.35
    return float(numerator / denominator)


# ── Regime 판정 ───────────────────────────────────────────────────────


def detect_market_regime(ctx: MacroContext, mkt: MarketFeatures) -> Regime:
    """
    거시·기술 특성으로 현재 시장 체제를 판정한다.

    우선순위:
    1. VIX > 30 OR ATR% > 3.5% → VOLATILE
    2. VHF > 0.4 AND ADX > 25 → STRONG_UP/DOWN
    3. VHF < 0.3 AND |KOSPI mom| < 3% → RANGING
    4. else → NORMAL
    """
    # 1. 고변동성
    if ctx.vix > 30 or mkt.atr_pct > 3.5:
        return Regime.VOLATILE

    # 2. 강한 추세
    if mkt.vhf > 0.4 and mkt.adx > 25:
        if mkt.kospi_momentum_20d > 0.05 and mkt.spx_momentum_20d > 0.05:
            return Regime.STRONG_UPTREND
        if mkt.kospi_momentum_20d < -0.05 and mkt.spx_momentum_20d < -0.05:
            return Regime.STRONG_DOWNTREND

    # 3. 횡보
    if mkt.vhf < 0.3 and abs(mkt.kospi_momentum_20d) < 0.03:
        return Regime.RANGING

    return Regime.NORMAL


# ── 시장 데이터 수집 ──────────────────────────────────────────────────


def fetch_market_features(period: str = "3mo") -> MarketFeatures:
    """SPX/KOSPI 가격 데이터로 MarketFeatures 계산."""
    try:
        import yfinance as yf

        spx = yf.Ticker("^GSPC").history(period=period, auto_adjust=True)
        kospi = yf.Ticker("^KS11").history(period=period, auto_adjust=True)

        def _momentum_20d(hist: pd.DataFrame) -> float:
            if hist.empty or len(hist) < 21:
                return 0.0
            close = hist["Close"].dropna()
            if len(close) < 21:
                return 0.0
            return float(close.iloc[-1] / close.iloc[-21] - 1)

        def _atr_pct(hist: pd.DataFrame) -> float:
            if hist.empty or len(hist) < 15:
                return 1.5
            tr = pd.concat(
                [
                    hist["High"] - hist["Low"],
                    (hist["High"] - hist["Close"].shift(1)).abs(),
                    (hist["Low"] - hist["Close"].shift(1)).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = float(tr.ewm(span=14, adjust=False).mean().iloc[-1])
            price = float(hist["Close"].iloc[-1])
            return atr / price * 100 if price > 0 else 1.5

        def _adx(hist: pd.DataFrame, period: int = 14) -> float:
            if hist.empty or len(hist) < period + 1:
                return 20.0
            h, lo, c = hist["High"], hist["Low"], hist["Close"]
            plus_dm = h.diff().clip(lower=0)
            minus_dm = (-lo.diff()).clip(lower=0)
            atr_ser = pd.concat(
                [
                    h - lo,
                    (h - c.shift(1)).abs(),
                    (lo - c.shift(1)).abs(),
                ],
                axis=1,
            ).max(axis=1)
            smoothed_atr = atr_ser.ewm(span=period, adjust=False).mean()
            plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / smoothed_atr
            minus_di = (
                100 * minus_dm.ewm(span=period, adjust=False).mean() / smoothed_atr
            )
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
            return float(dx.ewm(span=period, adjust=False).mean().iloc[-1])

        spx_mom = _momentum_20d(spx)
        kospi_mom = _momentum_20d(kospi)
        vhf = compute_vhf(spx["Close"].dropna()) if not spx.empty else 0.35
        adx = _adx(spx)
        atr_pct = _atr_pct(spx)

        return MarketFeatures(
            vhf=vhf,
            adx=adx,
            atr_pct=atr_pct,
            kospi_momentum_20d=kospi_mom,
            spx_momentum_20d=spx_mom,
        )
    except Exception as exc:
        logger.warning("fetch_market_features failed: %s", exc)
        return MarketFeatures()


# ── Regime-aware 도구 점수 집계 ────────────────────────────────────────


def aggregate_tools_regime_aware(
    tool_outputs: dict,
    regime: Regime,
) -> float:
    """
    도구별 점수에 Regime 가중치를 적용하여 합산한다.

    Args:
        tool_outputs: {tool_name: ToolResult or dict with 'score' key}
        regime: 현재 시장 체제

    Returns:
        가중 합산 점수 (float)
    """
    weights = REGIME_WEIGHTS[regime]
    total = 0.0
    for tool_name, result in tool_outputs.items():
        score = (
            result.get("score", 0)
            if isinstance(result, dict)
            else getattr(result, "score", 0)
        )
        category = TOOL_CATEGORY.get(tool_name, "fundamental")
        total += float(score) * weights[category]
    return total


# ── 에이전트 그룹 수준 가중치 (Step 8 이전 간소화 버전) ──────────────────

# 에이전트 이름 → 카테고리 매핑 (Step 8에서 AgentGroup으로 격상)
_AGENT_CATEGORY: dict[str, str] = {
    "Technical Analyst": "momentum",
    "Quant Analyst": "momentum",
    "Risk Manager": "fundamental",
    "ML Specialist": "momentum",
    "Event Analyst": "fundamental",
    "Geopolitical Analyst": "fundamental",
    "Value Investor": "fundamental",
    "Decision Maker": "fundamental",
}


def apply_regime_weights_to_agents(
    agent_results: list,
    regime: Regime,
) -> float:
    """
    에이전트별 confidence에 Regime 가중치를 적용해 신호 점수를 반환한다.

    Returns:
        가중 신호 점수 (양수 → buy 방향, 음수 → sell 방향)
    """
    weights = REGIME_WEIGHTS[regime]
    total = 0.0

    for result in agent_results:
        if getattr(result, "error", None) or getattr(result, "confidence", 0) <= 0:
            continue
        signal = getattr(result, "signal", "neutral").lower()
        score = 1.0 if signal == "buy" else -1.0 if signal == "sell" else 0.0
        conf = float(getattr(result, "confidence", 0))
        category = _AGENT_CATEGORY.get(getattr(result, "agent_name", ""), "fundamental")
        w = weights[category]
        total += score * conf * w

    return total
