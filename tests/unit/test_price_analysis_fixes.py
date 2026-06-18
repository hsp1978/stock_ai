"""주가 분석 모듈 회귀 테스트."""

import os
import sys

import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from backtest_engine import (  # noqa: E402
    backtest_composite_signal,
    backtest_sma_cross,
    _padded_slice,
)
from entry_plan import build_entry_plan  # noqa: E402
from ml_predictor import (  # noqa: E402
    _build_features,
    _build_target,
    _latest_feature_frame,
    _split_train_test_with_gap,
)
from trading_costs import ZERO_COSTS  # noqa: E402


def _ohlcv(rows: int = 80) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=rows, freq="B")
    close = pd.Series(range(100, 100 + rows), index=idx, dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": 1_000_000,
            "ATR": 2.0,
        },
        index=idx,
    )


def test_ml_target_leaves_unknown_future_rows_unlabeled():
    df = _ohlcv(20)
    target = _build_target(df, horizon=5)

    assert target.tail(5).isna().all()
    assert target.iloc[:-5].notna().all()


def test_ml_latest_prediction_feature_uses_latest_valid_row_not_last_labeled_row():
    df = _ohlcv(120)
    features = _build_features(df)
    target = _build_target(df, horizon=5)
    combined = pd.concat([features, target.rename("target")], axis=1).dropna()
    X = combined.drop("target", axis=1)

    latest_features, latest_date = _latest_feature_frame(features, list(X.columns))

    assert combined.index[-1] == df.index[-6]
    assert latest_features.index[-1] == df.index[-1]
    assert latest_date == df.index[-1]


def test_ml_time_split_purges_prediction_horizon_gap():
    X = pd.DataFrame({"x": range(100)})
    y = pd.Series([0, 1] * 50)

    X_train, X_test, y_train, y_test, meta = _split_train_test_with_gap(X, y, horizon=5)

    assert X_train.index[-1] == 74
    assert X_test.index[0] == 80
    assert len(y_train) == len(X_train)
    assert len(y_test) == len(X_test)
    assert meta["purge_gap"] == 5


def test_entry_plan_accepts_bollinger_alias_keys():
    plan = build_entry_plan(
        ticker="AAPL",
        signal="buy",
        confidence=7.0,
        current_price=100.0,
        tool_results=[
            {
                "tool": "risk_position_sizing",
                "final_levels": {"stop_loss": 95.0, "take_profit": 112.0},
            },
            {
                "tool": "bollinger_squeeze_analysis",
                "squeeze": True,
                "bb_upper": 105.0,
            },
        ],
    )

    assert plan["entry_timing"] == "breakout_confirm"
    assert plan["limit_price"] is not None
    assert plan["limit_price"] >= 105.0


def test_composite_backtest_current_tool_results_are_not_replayed():
    df = _ohlcv(100)
    tool_results = [{"tool": "trend_ma_analysis", "score": 7, "signal": "buy"}]

    first = backtest_composite_signal("AAPL", df, tool_results).to_dict()
    second = backtest_composite_signal("AAPL", df, tool_results).to_dict()

    assert first == second
    assert first["strategy"] == "Composite_Signal_CurrentOnly"
    assert first["total_trades"] == 0
    assert "look-ahead bias" in first["notes"][0]


def test_sma_backtest_fills_signal_on_next_open_not_same_close():
    df = _ohlcv(5)
    df["Open"] = [100.0, 100.0, 111.0, 100.0, 90.0]
    df["Close"] = [100.0, 105.0, 106.0, 104.0, 103.0]
    df["ATR"] = 10.0
    df["SMA_1"] = [0.0, 2.0, 2.0, 0.0, 0.0]
    df["SMA_2"] = [1.0, 1.0, 1.0, 1.0, 1.0]

    result = backtest_sma_cross("AAPL", df, fast_period=1, slow_period=2, costs=ZERO_COSTS)

    assert result.total_trades == 1
    trade = result.trades[0]
    assert trade["entry_signal_date"] == str(df.index[1])[:10]
    assert trade["entry_date"] == str(df.index[2])[:10]
    assert trade["entry_price"] == 111.0
    assert trade["exit_signal_date"] == str(df.index[3])[:10]
    assert trade["exit_date"] == str(df.index[4])[:10]
    assert trade["exit_price"] == 90.0
    assert trade["entry_fill_price_source"] == "next_open"
    assert trade["exit_fill_price_source"] == "next_open"


def test_sma_backtest_does_not_execute_last_bar_signal_without_next_open():
    df = _ohlcv(4)
    df["ATR"] = 10.0
    df["SMA_1"] = [0.0, 0.0, 0.0, 2.0]
    df["SMA_2"] = [1.0, 1.0, 1.0, 1.0]

    result = backtest_sma_cross("AAPL", df, fast_period=1, slow_period=2, costs=ZERO_COSTS)

    assert result.total_trades == 0


def test_walk_forward_padding_preserves_indicator_warmup_at_eval_start():
    df = _ohlcv(120)
    padded, padding = _padded_slice(df, start_idx=80, end_idx=100, lookback=50)
    padded["SMA_50"] = padded["Close"].rolling(50).mean()

    assert padding == 50
    assert padded.index[0] == df.index[30]
    assert pd.notna(padded.loc[df.index[80], "SMA_50"])
