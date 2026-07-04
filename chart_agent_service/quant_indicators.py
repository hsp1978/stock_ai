"""
Quant-only indicator analysis.

This module intentionally avoids news, disclosures, fundamentals, events, and
LLM interpretation. It turns OHLCV-derived statistics into a structured
quantitative bias report that can be shown independently from the multi-agent
investment decision.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd


MIN_OBSERVATIONS = 60
ANNUALIZATION_DAYS = 252


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if np.isnan(value) or np.isinf(value):
        return default
    return value


def _round(value: Any, digits: int = 2) -> float | None:
    value = _safe_float(value)
    return round(value, digits) if value is not None else None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _pct_return(close: pd.Series, periods: int) -> float | None:
    if len(close) <= periods:
        return None
    prev = _safe_float(close.iloc[-periods - 1])
    cur = _safe_float(close.iloc[-1])
    if not prev or cur is None:
        return None
    return (cur / prev - 1.0) * 100.0


def _latest(df: pd.DataFrame, col: str) -> float | None:
    if col not in df.columns:
        return None
    series = df[col].dropna()
    if series.empty:
        return None
    return _safe_float(series.iloc[-1])


def _direction(score: float, weight: float) -> str:
    ratio = score / weight if weight > 0 else 0.5
    if ratio >= 0.65:
        return "buy"
    if ratio <= 0.40:
        return "sell"
    return "neutral"


def _hurst_exponent(returns: pd.Series) -> float | None:
    returns = returns.dropna()
    if len(returns) < 60:
        return None

    n = len(returns)
    max_k = min(int(np.log2(n)), 8)
    rs_points: list[tuple[float, float]] = []

    for k in range(2, max_k + 1):
        size = 2 ** k
        if size > n:
            break
        block_count = n // size
        rs_values = []
        for i in range(block_count):
            block = returns.iloc[i * size:(i + 1) * size].to_numpy()
            block_std = float(np.std(block, ddof=1))
            if block_std <= 0:
                continue
            centered = block - float(np.mean(block))
            cumulative = np.cumsum(centered)
            r_value = float(np.max(cumulative) - np.min(cumulative))
            rs_values.append(r_value / block_std)
        if rs_values:
            rs_points.append((float(np.log(size)), float(np.log(np.mean(rs_values)))))

    if len(rs_points) < 2:
        return None
    x = [point[0] for point in rs_points]
    y = [point[1] for point in rs_points]
    return _safe_float(np.polyfit(x, y, 1)[0])


def _max_drawdown(close: pd.Series, window: int = 120) -> float | None:
    close = close.dropna().tail(window)
    if len(close) < 2:
        return None
    running_max = close.cummax()
    drawdown = close / running_max - 1.0
    return _safe_float(drawdown.min() * 100.0)


def _drop_datetime_timezone(series: pd.Series) -> pd.Series:
    """Normalize DatetimeIndex timezone before joining separate data sources."""
    series = series.copy()
    if isinstance(series.index, pd.DatetimeIndex):
        if series.index.tz is not None:
            series.index = series.index.tz_convert(None)
        else:
            series.index = series.index.tz_localize(None)
        series.index = series.index.normalize()
    return series


def _beta_alpha(stock_returns: pd.Series, benchmark_returns: pd.Series) -> dict[str, Any]:
    stock_returns = _drop_datetime_timezone(stock_returns)
    benchmark_returns = _drop_datetime_timezone(benchmark_returns)
    joined = pd.concat(
        [stock_returns.rename("stock"), benchmark_returns.rename("benchmark")],
        axis=1,
    ).dropna().tail(120)
    if len(joined) < 40:
        return {"available": False}

    benchmark_var = float(np.var(joined["benchmark"], ddof=1))
    if benchmark_var <= 0:
        return {"available": False}

    covariance = float(np.cov(joined["stock"], joined["benchmark"])[0, 1])
    beta = covariance / benchmark_var
    correlation = float(joined["stock"].corr(joined["benchmark"]))
    stock_60d = (float((1 + joined["stock"].tail(60)).prod()) - 1.0) * 100.0
    benchmark_60d = (float((1 + joined["benchmark"].tail(60)).prod()) - 1.0) * 100.0
    alpha_60d = stock_60d - beta * benchmark_60d
    excess_60d = stock_60d - benchmark_60d

    return {
        "available": True,
        "beta": round(beta, 3),
        "correlation": round(correlation, 3),
        "stock_return_60d": round(stock_60d, 2),
        "benchmark_return_60d": round(benchmark_60d, 2),
        "alpha_60d": round(alpha_60d, 2),
        "excess_return_60d": round(excess_60d, 2),
    }


def analyze_quant_indicators(
    ticker: str,
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Return a quant-only indicator report for one ticker."""
    ticker = ticker.upper().strip()
    invalid_reasons: list[str] = []
    warnings: list[str] = []
    strengths: list[str] = []

    if df is None or df.empty:
        return {
            "ticker": ticker,
            "status": "invalid",
            "error": "OHLCV data is empty",
            "invalid_reasons": ["empty_ohlcv"],
        }

    work = df.copy()
    if "Close" not in work.columns:
        return {
            "ticker": ticker,
            "status": "invalid",
            "error": "Close column is missing",
            "invalid_reasons": ["missing_close"],
        }

    work = work.sort_index()
    close = pd.to_numeric(work["Close"], errors="coerce").dropna()
    volume = pd.to_numeric(work.get("Volume", pd.Series(index=work.index)), errors="coerce")
    returns = close.pct_change().dropna()

    if len(close) < MIN_OBSERVATIONS:
        invalid_reasons.append(f"need_at_least_{MIN_OBSERVATIONS}_bars")

    current_price = _safe_float(close.iloc[-1])
    if current_price is None or current_price <= 0:
        invalid_reasons.append("invalid_current_price")

    if volume.dropna().tail(20).eq(0).all():
        invalid_reasons.append("zero_recent_volume")

    if invalid_reasons:
        return {
            "ticker": ticker,
            "status": "invalid",
            "as_of": datetime.now().isoformat(),
            "invalid_reasons": invalid_reasons,
            "row_count": len(close),
        }

    # 1. Momentum, max 25
    period_returns = {
        "1d": _pct_return(close, 1),
        "5d": _pct_return(close, 5),
        "20d": _pct_return(close, 20),
        "60d": _pct_return(close, 60),
        "120d": _pct_return(close, 120),
    }
    weighted_return = (
        (period_returns["5d"] or 0) * 0.15
        + (period_returns["20d"] or 0) * 0.35
        + (period_returns["60d"] or 0) * 0.35
        + (period_returns["120d"] or 0) * 0.15
    )
    acceleration = (period_returns["20d"] or 0) - ((period_returns["60d"] or 0) / 3.0)
    momentum_score = 12.5 + weighted_return * 0.55 + _clamp(acceleration, -8, 8) * 0.45
    momentum_score = _clamp(momentum_score, 0, 25)
    if weighted_return >= 8 and acceleration > 0:
        strengths.append("multi_period_momentum")
    if weighted_return <= -8:
        warnings.append("negative_multi_period_momentum")

    # 2. Mean reversion, max 15
    z20 = z60 = None
    if len(close) >= 20:
        std20 = _safe_float(close.tail(20).std())
        if std20 and std20 > 0:
            z20 = (current_price - float(close.tail(20).mean())) / std20
    if len(close) >= 60:
        std60 = _safe_float(close.tail(60).std())
        if std60 and std60 > 0:
            z60 = (current_price - float(close.tail(60).mean())) / std60
    z_values = [z for z in (z20, z60) if z is not None]
    avg_z = float(np.mean(z_values)) if z_values else 0.0
    rsi = _latest(work, "RSI")
    bbu = next((c for c in work.columns if c.startswith("BBU_")), None)
    bbl = next((c for c in work.columns if c.startswith("BBL_")), None)
    bbu_v = _latest(work, bbu) if bbu else None
    bbl_v = _latest(work, bbl) if bbl else None
    bb_percent = None
    if bbu_v is not None and bbl_v is not None and bbu_v > bbl_v:
        bb_percent = (current_price - bbl_v) / (bbu_v - bbl_v)

    mean_score = 8.0
    if -2.5 <= avg_z <= -0.75:
        mean_score += min(5.0, abs(avg_z) * 2.1)
        strengths.append("controlled_pullback")
    elif avg_z < -2.5:
        mean_score += 2.0
        warnings.append("extreme_downside_deviation")
    elif avg_z >= 1.5:
        mean_score -= min(6.0, (avg_z - 1.0) * 3.0)
        warnings.append("extended_above_mean")
    elif abs(avg_z) <= 0.5:
        mean_score += 1.0
    if rsi is not None:
        if 35 <= rsi <= 55:
            mean_score += 1.5
        elif rsi < 28:
            mean_score += 1.0
            warnings.append("rsi_deep_oversold")
        elif rsi > 75:
            mean_score -= 3.0
            warnings.append("rsi_overheated")
    mean_score = _clamp(mean_score, 0, 15)

    # 3. Volatility, max 20
    vol20 = _safe_float(returns.tail(20).std() * np.sqrt(ANNUALIZATION_DAYS) * 100.0)
    vol60 = _safe_float(returns.tail(60).std() * np.sqrt(ANNUALIZATION_DAYS) * 100.0)
    rolling_vol = returns.rolling(20).std().dropna() * np.sqrt(ANNUALIZATION_DAYS) * 100.0
    vol_percentile = None
    if vol20 is not None and len(rolling_vol) >= 20:
        vol_percentile = float((rolling_vol < vol20).sum() / len(rolling_vol) * 100.0)
    atr = _latest(work, "ATR")
    atr_pct = atr / current_price * 100.0 if atr and current_price else None
    if vol20 is None:
        volatility_score = 10.0
    elif 12 <= vol20 <= 35:
        volatility_score = 18.0
    elif 35 < vol20 <= 50:
        volatility_score = 13.0
    elif 50 < vol20 <= 80:
        volatility_score = 7.0
        warnings.append("high_annualized_volatility")
    elif vol20 > 80:
        volatility_score = 3.0
        warnings.append("extreme_annualized_volatility")
    else:
        volatility_score = 12.0
        warnings.append("very_low_volatility")
    if vol20 and vol60 and vol20 > vol60 * 1.3:
        volatility_score -= 3.0
        warnings.append("volatility_expanding")
    volatility_score = _clamp(volatility_score, 0, 20)

    # 4. Trend statistics, max 15
    hurst = _hurst_exponent(returns.tail(252))
    autocorr_1 = _safe_float(returns.autocorr(lag=1)) if len(returns) > 5 else None
    sma20 = _latest(work, "SMA_20")
    sma60 = _latest(work, "SMA_60")
    sma120 = _latest(work, "SMA_120")
    adx_col = next((c for c in work.columns if c.startswith("ADX_")), None)
    dmp_col = next((c for c in work.columns if c.startswith("DMP_")), None)
    dmn_col = next((c for c in work.columns if c.startswith("DMN_")), None)
    adx = _latest(work, adx_col) if adx_col else None
    dmp = _latest(work, dmp_col) if dmp_col else None
    dmn = _latest(work, dmn_col) if dmn_col else None
    ma_slope_20 = None
    if "SMA_20" in work.columns and len(work["SMA_20"].dropna()) > 5:
        sma20_series = work["SMA_20"].dropna()
        prev_sma20 = _safe_float(sma20_series.iloc[-6])
        if prev_sma20:
            ma_slope_20 = (_safe_float(sma20_series.iloc[-1], 0.0) / prev_sma20 - 1.0) * 100.0

    trend_score = 7.5
    if sma20 and sma60 and current_price > sma20 > sma60:
        trend_score += 3.0
        strengths.append("price_above_key_moving_averages")
    elif sma20 and sma60 and current_price < sma20 < sma60:
        trend_score -= 3.0
        warnings.append("price_below_key_moving_averages")
    if sma120 and current_price < sma120:
        trend_score -= 1.5
        warnings.append("below_long_term_average")
    if ma_slope_20 is not None:
        trend_score += _clamp(ma_slope_20, -3.0, 3.0) * 0.7
    if adx and adx >= 25:
        if dmp is not None and dmn is not None and dmp > dmn:
            trend_score += 2.0
            strengths.append("adx_positive_trend")
        elif dmp is not None and dmn is not None and dmp < dmn:
            trend_score -= 2.0
            warnings.append("adx_negative_trend")
    if hurst is not None:
        if hurst > 0.58 and (autocorr_1 or 0) > 0:
            trend_score += 1.5
        elif hurst < 0.42:
            trend_score -= 0.5
    trend_score = _clamp(trend_score, 0, 15)

    # 5. Volume confirmation, max 10
    vol_latest = _safe_float(volume.dropna().iloc[-1]) if not volume.dropna().empty else None
    vol_ma20 = _latest(work, "Volume_SMA_20")
    vol_ratio = vol_latest / vol_ma20 if vol_latest and vol_ma20 else None
    obv = pd.to_numeric(work.get("OBV", pd.Series(index=work.index)), errors="coerce").dropna()
    obv_change_20 = None
    if len(obv) > 20 and abs(float(obv.iloc[-21])) > 0:
        obv_change_20 = (float(obv.iloc[-1]) - float(obv.iloc[-21])) / abs(float(obv.iloc[-21])) * 100.0
    price_return_20 = period_returns["20d"] or 0.0
    vwap_dist_20 = _latest(work, "VWAP_DIST_20")

    volume_score = 5.0
    if vol_ratio is not None:
        if 1.1 <= vol_ratio <= 2.5 and price_return_20 > 0:
            volume_score += 2.5
            strengths.append("volume_confirms_price")
        elif vol_ratio > 2.5:
            volume_score += 1.0
            warnings.append("volume_spike")
        elif vol_ratio < 0.6:
            volume_score -= 1.0
    if obv_change_20 is not None:
        if obv_change_20 > 5 and price_return_20 >= 0:
            volume_score += 2.0
        elif obv_change_20 > 5 and price_return_20 < 0:
            volume_score += 1.0
            strengths.append("possible_accumulation")
        elif obv_change_20 < -5:
            volume_score -= 2.0
            warnings.append("obv_distribution")
    if vwap_dist_20 is not None:
        if -1.0 <= vwap_dist_20 <= 4.0:
            volume_score += 0.8
        elif vwap_dist_20 < -3.0:
            volume_score -= 1.0
            warnings.append("below_vwap20")
    volume_score = _clamp(volume_score, 0, 10)

    # 6. Benchmark relative strength, max 15
    benchmark = {"available": False}
    benchmark_score = 7.5
    if benchmark_df is not None and not benchmark_df.empty and "Close" in benchmark_df.columns:
        benchmark_close = pd.to_numeric(benchmark_df["Close"], errors="coerce").dropna()
        benchmark = _beta_alpha(returns, benchmark_close.pct_change().dropna())
        if benchmark.get("available"):
            excess = float(benchmark.get("excess_return_60d", 0.0))
            alpha = float(benchmark.get("alpha_60d", 0.0))
            beta = float(benchmark.get("beta", 1.0))
            benchmark_score = 7.5 + _clamp(excess, -15, 15) * 0.25 + _clamp(alpha, -10, 10) * 0.25
            if beta > 2.0:
                benchmark_score -= 2.0
                warnings.append("high_market_beta")
            elif 0.4 <= beta <= 1.3 and excess > 0:
                benchmark_score += 1.0
            if excess > 5:
                strengths.append("benchmark_outperformance")
    benchmark_score = _clamp(benchmark_score, 0, 15)

    # 7. Risk penalty, 0 to -20
    max_dd = _max_drawdown(close)
    downside = returns[returns < 0]
    downside_vol = _safe_float(downside.tail(60).std() * np.sqrt(ANNUALIZATION_DAYS) * 100.0) if len(downside) else None
    var_95 = _safe_float(np.percentile(returns.tail(120), 5) * 100.0) if len(returns) >= 20 else None
    cvar_95 = None
    if var_95 is not None:
        tail_losses = returns.tail(120)[returns.tail(120) * 100.0 <= var_95]
        if not tail_losses.empty:
            cvar_95 = _safe_float(tail_losses.mean() * 100.0)
    mean_daily = _safe_float(returns.tail(120).mean())
    std_daily = _safe_float(returns.tail(120).std())
    sharpe = mean_daily / std_daily * np.sqrt(ANNUALIZATION_DAYS) if mean_daily is not None and std_daily and std_daily > 0 else None
    sortino = None
    downside_std = _safe_float(downside.tail(120).std()) if len(downside) else None
    if mean_daily is not None and downside_std and downside_std > 0:
        sortino = mean_daily / downside_std * np.sqrt(ANNUALIZATION_DAYS)

    risk_penalty = 0.0
    if max_dd is not None:
        if max_dd <= -35:
            risk_penalty -= 7.0
            warnings.append("deep_drawdown")
        elif max_dd <= -20:
            risk_penalty -= 4.0
    if downside_vol is not None:
        if downside_vol > 50:
            risk_penalty -= 5.0
            warnings.append("large_downside_volatility")
        elif downside_vol > 35:
            risk_penalty -= 3.0
    if var_95 is not None and var_95 < -4.0:
        risk_penalty -= 3.0
        warnings.append("large_daily_var")
    if sharpe is not None:
        if sharpe < -0.5:
            risk_penalty -= 4.0
        elif sharpe > 1.0:
            strengths.append("positive_risk_adjusted_return")
    risk_penalty = _clamp(risk_penalty, -20, 0)

    components = {
        "momentum": {
            "score": round(momentum_score, 2),
            "weight": 25,
            "direction": _direction(momentum_score, 25),
            "returns": {k: _round(v) for k, v in period_returns.items()},
            "weighted_return": round(weighted_return, 2),
            "acceleration": round(acceleration, 2),
        },
        "mean_reversion": {
            "score": round(mean_score, 2),
            "weight": 15,
            "direction": _direction(mean_score, 15),
            "z20": _round(z20, 3),
            "z60": _round(z60, 3),
            "avg_z": _round(avg_z, 3),
            "rsi": _round(rsi),
            "bollinger_percent": _round(bb_percent, 3),
        },
        "volatility": {
            "score": round(volatility_score, 2),
            "weight": 20,
            "direction": _direction(volatility_score, 20),
            "annualized_vol_20d": _round(vol20),
            "annualized_vol_60d": _round(vol60),
            "vol_percentile": _round(vol_percentile),
            "atr_pct": _round(atr_pct),
        },
        "trend": {
            "score": round(trend_score, 2),
            "weight": 15,
            "direction": _direction(trend_score, 15),
            "hurst": _round(hurst, 3),
            "autocorr_1": _round(autocorr_1, 4),
            "adx": _round(adx),
            "ma_slope_20": _round(ma_slope_20),
            "price_vs_sma": {
                "sma20": "above" if sma20 and current_price > sma20 else "below" if sma20 else None,
                "sma60": "above" if sma60 and current_price > sma60 else "below" if sma60 else None,
                "sma120": "above" if sma120 and current_price > sma120 else "below" if sma120 else None,
            },
        },
        "volume": {
            "score": round(volume_score, 2),
            "weight": 10,
            "direction": _direction(volume_score, 10),
            "volume_ratio": _round(vol_ratio, 3),
            "obv_change_20": _round(obv_change_20),
            "vwap_dist_20": _round(vwap_dist_20),
        },
        "benchmark": {
            "score": round(benchmark_score, 2),
            "weight": 15,
            "direction": _direction(benchmark_score, 15),
            **benchmark,
        },
    }

    raw_score = (
        momentum_score
        + mean_score
        + volatility_score
        + trend_score
        + volume_score
        + benchmark_score
    )
    quant_score = round(_clamp(raw_score + risk_penalty, 0, 100), 1)

    if quant_score >= 80:
        grade = "A"
    elif quant_score >= 65:
        grade = "B"
    elif quant_score >= 50:
        grade = "C"
    elif quant_score >= 35:
        grade = "D"
    else:
        grade = "F"

    if quant_score >= 70:
        signal = "buy"
        signal_label = "BUY BIAS"
    elif quant_score <= 40:
        signal = "sell"
        signal_label = "SELL/AVOID BIAS"
    else:
        signal = "neutral"
        signal_label = "NEUTRAL"

    component_directions = [c["direction"] for c in components.values()]
    dominant_count = max(component_directions.count("buy"), component_directions.count("sell"), component_directions.count("neutral"))
    agreement = dominant_count / len(component_directions)
    data_quality = _clamp(len(close) / 180.0, 0.5, 1.0)
    confidence = round(_clamp(3.0 + agreement * 4.0 + data_quality * 3.0, 0, 10), 1)

    if vol20 and vol20 > 60:
        regime = "high_volatility"
    elif hurst and hurst > 0.58 and adx and adx >= 22:
        regime = "trending"
    elif abs(avg_z) >= 1.25 or (hurst and hurst < 0.42):
        regime = "mean_reversion"
    else:
        regime = "balanced"

    return {
        "ticker": ticker,
        "status": "ok",
        "as_of": datetime.now().isoformat(),
        "row_count": len(close),
        "current_price": round(current_price, 4),
        "quant_score": quant_score,
        "grade": grade,
        "signal": signal,
        "signal_label": signal_label,
        "confidence": confidence,
        "regime": regime,
        "raw_score": round(raw_score, 2),
        "risk_penalty": round(risk_penalty, 2),
        "components": components,
        "risk": {
            "max_drawdown_120d": _round(max_dd),
            "downside_volatility": _round(downside_vol),
            "var_95_daily": _round(var_95),
            "cvar_95_daily": _round(cvar_95),
            "sharpe_120d": _round(sharpe, 3),
            "sortino_120d": _round(sortino, 3),
            "penalty": round(risk_penalty, 2),
        },
        "strengths": sorted(set(strengths)),
        "warnings": sorted(set(warnings)),
        "invalid_reasons": [],
        "methodology": {
            "scope": "ohlcv_quant_only",
            "excludes": ["news", "disclosures", "fundamentals", "events", "llm_opinion"],
            "weights": {
                "momentum": 25,
                "mean_reversion": 15,
                "volatility": 20,
                "trend": 15,
                "volume": 10,
                "benchmark": 15,
                "risk_penalty_max": -20,
            },
        },
    }
