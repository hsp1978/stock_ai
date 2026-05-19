"""주가 분석 모듈 회귀 테스트."""

import os
import sys

import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from backtest_engine import backtest_composite_signal  # noqa: E402
from entry_plan import build_entry_plan  # noqa: E402
from ml_predictor import _build_target  # noqa: E402


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
