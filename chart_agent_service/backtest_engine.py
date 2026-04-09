"""
백테스트 엔진
- SMA 크로스 전략 / RSI 역추세 전략 / 복합 시그널 전략
- 수익률, 샤프비율, MDD, 승률 산출
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from config import (
    SMA_PERIODS, RSI_PERIOD, ACCOUNT_SIZE,
    RISK_PER_TRADE_PCT, ATR_STOP_MULTIPLIER, TAKE_PROFIT_RR_RATIO,
)


@dataclass
class BacktestResult:
    strategy: str
    ticker: str
    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    avg_holding_days: float = 0.0
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "ticker": self.ticker,
            "total_return_pct": round(self.total_return_pct, 2),
            "annualized_return_pct": round(self.annualized_return_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "win_rate_pct": round(self.win_rate_pct, 1),
            "total_trades": self.total_trades,
            "profit_factor": round(self.profit_factor, 2),
            "avg_holding_days": round(self.avg_holding_days, 1),
            "equity_curve_len": len(self.equity_curve),
        }


def _compute_stats(equity: pd.Series, trades: list, strategy: str, ticker: str) -> BacktestResult:
    result = BacktestResult(strategy=strategy, ticker=ticker)
    if equity.empty or len(equity) < 2:
        return result

    result.equity_curve = equity.tolist()
    total_ret = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    result.total_return_pct = total_ret

    n_days = len(equity)
    if n_days > 1:
        result.annualized_return_pct = ((equity.iloc[-1] / equity.iloc[0]) ** (252 / n_days) - 1) * 100

    daily_ret = equity.pct_change().dropna()
    if len(daily_ret) > 1 and daily_ret.std() > 0:
        result.sharpe_ratio = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252))

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    result.max_drawdown_pct = float(drawdown.min()) * 100

    if trades:
        result.total_trades = len(trades)
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        result.win_rate_pct = len(wins) / len(trades) * 100

        gross_profit = sum(t["pnl"] for t in wins) if wins else 0
        gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 1e-10
        result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        holding_days = [t.get("holding_days", 0) for t in trades]
        result.avg_holding_days = np.mean(holding_days) if holding_days else 0

    result.trades = trades
    return result


def backtest_sma_cross(ticker: str, df: pd.DataFrame,
                       fast_period: int = None, slow_period: int = None) -> BacktestResult:
    if fast_period is None:
        fast_period = SMA_PERIODS[0] if len(SMA_PERIODS) >= 2 else 20
    if slow_period is None:
        slow_period = SMA_PERIODS[1] if len(SMA_PERIODS) >= 2 else 50

    df = df.copy()
    sma_f = f"SMA_{fast_period}"
    sma_s = f"SMA_{slow_period}"
    if sma_f not in df.columns:
        df[sma_f] = df["Close"].rolling(fast_period).mean()
    if sma_s not in df.columns:
        df[sma_s] = df["Close"].rolling(slow_period).mean()

    df = df.dropna(subset=[sma_f, sma_s]).copy()
    if df.empty:
        return BacktestResult(strategy=f"SMA_Cross_{fast_period}_{slow_period}", ticker=ticker)

    cash = ACCOUNT_SIZE
    position = 0
    entry_price = 0.0
    entry_date = None
    trades = []
    equity = []

    for i in range(1, len(df)):
        prev_fast = float(df[sma_f].iloc[i - 1])
        prev_slow = float(df[sma_s].iloc[i - 1])
        curr_fast = float(df[sma_f].iloc[i])
        curr_slow = float(df[sma_s].iloc[i])
        price = float(df["Close"].iloc[i])
        date = df.index[i]

        if prev_fast <= prev_slow and curr_fast > curr_slow and position == 0:
            risk_amt = cash * (RISK_PER_TRADE_PCT / 100)
            atr_val = float(df["ATR"].iloc[i]) if "ATR" in df.columns and not pd.isna(df["ATR"].iloc[i]) else price * 0.02
            stop_dist = atr_val * ATR_STOP_MULTIPLIER
            qty = int(risk_amt / stop_dist) if stop_dist > 0 else 0
            if qty > 0 and qty * price <= cash:
                position = qty
                entry_price = price
                entry_date = date
                cash -= qty * price

        elif prev_fast >= prev_slow and curr_fast < curr_slow and position > 0:
            pnl = (price - entry_price) * position
            cash += position * price
            holding = (date - entry_date).days if entry_date else 0
            trades.append({
                "entry_date": str(entry_date)[:10],
                "exit_date": str(date)[:10],
                "entry_price": round(entry_price, 2),
                "exit_price": round(price, 2),
                "qty": position,
                "pnl": round(pnl, 2),
                "return_pct": round((price / entry_price - 1) * 100, 2),
                "holding_days": holding,
            })
            position = 0

        port_value = cash + position * price
        equity.append(port_value)

    equity_series = pd.Series(equity, index=df.index[1:len(equity) + 1])
    return _compute_stats(equity_series, trades, f"SMA_Cross_{fast_period}_{slow_period}", ticker)


def backtest_rsi_reversion(ticker: str, df: pd.DataFrame,
                           oversold: int = 30, overbought: int = 70) -> BacktestResult:
    df = df.copy()
    if "RSI" not in df.columns:
        return BacktestResult(strategy=f"RSI_Reversion_{oversold}_{overbought}", ticker=ticker)

    df = df.dropna(subset=["RSI"]).copy()
    if df.empty:
        return BacktestResult(strategy=f"RSI_Reversion_{oversold}_{overbought}", ticker=ticker)

    cash = ACCOUNT_SIZE
    position = 0
    entry_price = 0.0
    entry_date = None
    trades = []
    equity = []

    for i in range(1, len(df)):
        rsi = float(df["RSI"].iloc[i])
        price = float(df["Close"].iloc[i])
        date = df.index[i]

        if rsi < oversold and position == 0:
            risk_amt = cash * (RISK_PER_TRADE_PCT / 100)
            atr_val = float(df["ATR"].iloc[i]) if "ATR" in df.columns and not pd.isna(df["ATR"].iloc[i]) else price * 0.02
            stop_dist = atr_val * ATR_STOP_MULTIPLIER
            qty = int(risk_amt / stop_dist) if stop_dist > 0 else 0
            if qty > 0 and qty * price <= cash:
                position = qty
                entry_price = price
                entry_date = date
                cash -= qty * price

        elif rsi > overbought and position > 0:
            pnl = (price - entry_price) * position
            cash += position * price
            holding = (date - entry_date).days if entry_date else 0
            trades.append({
                "entry_date": str(entry_date)[:10],
                "exit_date": str(date)[:10],
                "entry_price": round(entry_price, 2),
                "exit_price": round(price, 2),
                "qty": position,
                "pnl": round(pnl, 2),
                "return_pct": round((price / entry_price - 1) * 100, 2),
                "holding_days": holding,
            })
            position = 0

        port_value = cash + position * price
        equity.append(port_value)

    equity_series = pd.Series(equity, index=df.index[1:len(equity) + 1])
    return _compute_stats(equity_series, trades, f"RSI_Reversion_{oversold}_{overbought}", ticker)


def backtest_composite_signal(ticker: str, df: pd.DataFrame, tool_results: list) -> BacktestResult:
    df = df.copy().dropna(subset=["Close"])
    if df.empty or not tool_results:
        return BacktestResult(strategy="Composite_Signal", ticker=ticker)

    scores_by_tool = {}
    for r in tool_results:
        scores_by_tool[r.get("tool", "")] = r.get("score", 0)
    avg_score = np.mean(list(scores_by_tool.values()))

    cash = ACCOUNT_SIZE
    position = 0
    entry_price = 0.0
    entry_date = None
    trades = []
    equity = []

    lookback = min(60, len(df))
    sim_df = df.tail(lookback)

    for i in range(1, len(sim_df)):
        price = float(sim_df["Close"].iloc[i])
        date = sim_df.index[i]

        sim_score = avg_score * (0.8 + 0.4 * np.random.random())

        if sim_score > 2 and position == 0:
            risk_amt = cash * (RISK_PER_TRADE_PCT / 100)
            atr_val = float(sim_df["ATR"].iloc[i]) if "ATR" in sim_df.columns and not pd.isna(sim_df["ATR"].iloc[i]) else price * 0.02
            stop_dist = atr_val * ATR_STOP_MULTIPLIER
            qty = int(risk_amt / stop_dist) if stop_dist > 0 else 0
            if qty > 0 and qty * price <= cash:
                position = qty
                entry_price = price
                entry_date = date
                cash -= qty * price

        elif (sim_score < -2 or (position > 0 and price < entry_price * (1 - ATR_STOP_MULTIPLIER * 0.02))) and position > 0:
            pnl = (price - entry_price) * position
            cash += position * price
            holding = (date - entry_date).days if entry_date else 0
            trades.append({
                "entry_date": str(entry_date)[:10],
                "exit_date": str(date)[:10],
                "entry_price": round(entry_price, 2),
                "exit_price": round(price, 2),
                "qty": position,
                "pnl": round(pnl, 2),
                "return_pct": round((price / entry_price - 1) * 100, 2),
                "holding_days": holding,
            })
            position = 0

        port_value = cash + position * price
        equity.append(port_value)

    equity_series = pd.Series(equity, index=sim_df.index[1:len(equity) + 1])
    return _compute_stats(equity_series, trades, "Composite_Signal", ticker)


def run_all_backtests(ticker: str, df: pd.DataFrame, tool_results: list = None) -> dict:
    results = {}
    results["sma_cross"] = backtest_sma_cross(ticker, df).to_dict()
    results["rsi_reversion"] = backtest_rsi_reversion(ticker, df).to_dict()
    if tool_results:
        results["composite_signal"] = backtest_composite_signal(ticker, df, tool_results).to_dict()
    best = max(results.values(), key=lambda x: x.get("sharpe_ratio", 0))
    return {
        "ticker": ticker,
        "strategies": results,
        "best_strategy": best["strategy"],
        "best_sharpe": best["sharpe_ratio"],
    }
