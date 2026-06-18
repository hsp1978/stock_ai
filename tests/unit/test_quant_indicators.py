import os
import sys

import numpy as np
import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from quant_indicators import analyze_quant_indicators  # noqa: E402


def _quant_df(rows: int = 180, slope: float = 0.2) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=rows, freq="B")
    base = 100 + np.arange(rows) * slope + np.sin(np.arange(rows) / 5) * 1.5
    volume = np.linspace(1_000_000, 1_250_000, rows)
    df = pd.DataFrame(
        {
            "Open": base * 0.998,
            "High": base * 1.01,
            "Low": base * 0.99,
            "Close": base,
            "Volume": volume,
        },
        index=idx,
    )
    for period in (20, 60, 120):
        df[f"SMA_{period}"] = df["Close"].rolling(period, min_periods=period).mean()

    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    rs = gain.ewm(alpha=1 / 14, min_periods=14).mean() / loss.ewm(alpha=1 / 14, min_periods=14).mean()
    df["RSI"] = 100 - (100 / (1 + rs))

    mid = df["Close"].rolling(20, min_periods=20).mean()
    std = df["Close"].rolling(20, min_periods=20).std()
    df["BBU_20_2"] = mid + 2 * std
    df["BBL_20_2"] = mid - 2 * std
    df["ATR"] = (df["High"] - df["Low"]).ewm(span=14, adjust=False).mean()
    df["Volume_SMA_20"] = df["Volume"].rolling(20, min_periods=20).mean()
    df["OBV"] = (np.sign(df["Close"].diff()).fillna(0) * df["Volume"]).cumsum()
    df["VWAP_DIST_20"] = 1.0
    df["ADX_14"] = 28.0
    df["DMP_14"] = 30.0
    df["DMN_14"] = 15.0
    return df


def test_quant_indicator_report_has_expected_sections():
    df = _quant_df()
    benchmark = _quant_df(slope=0.1)

    result = analyze_quant_indicators("TEST", df, benchmark_df=benchmark)

    assert result["status"] == "ok"
    assert 0 <= result["quant_score"] <= 100
    assert result["signal_label"] in {"BUY BIAS", "NEUTRAL", "SELL/AVOID BIAS"}
    assert set(result["components"]) == {
        "momentum",
        "mean_reversion",
        "volatility",
        "trend",
        "volume",
        "benchmark",
    }
    assert result["methodology"]["scope"] == "ohlcv_quant_only"


def test_quant_indicator_rejects_short_history():
    result = analyze_quant_indicators("SHORT", _quant_df(rows=40))

    assert result["status"] == "invalid"
    assert "need_at_least_60_bars" in result["invalid_reasons"]


def test_quant_indicator_handles_timezone_mismatch_for_benchmark():
    stock_df = _quant_df()
    benchmark_df = _quant_df()
    benchmark_df.index = benchmark_df.index.tz_localize("UTC") + pd.Timedelta(hours=9)

    result = analyze_quant_indicators("TZTEST", stock_df, benchmark_df=benchmark_df)

    assert result["status"] == "ok"
    assert result["components"]["benchmark"]["available"] is True
