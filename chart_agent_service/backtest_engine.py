"""
백테스트 엔진
- SMA 크로스 전략 / RSI 역추세 전략 / 볼린저 반전 전략 / 복합 시그널 전략
- HyperOpt (Optuna 파라미터 최적화, Freqtrade 스타일)
- Walk-Forward 백테스트 (vectorbt/Qlib 스타일)
- 수익률, 샤프비율, MDD, 승률 산출
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional, Tuple, List

from config import (
    SMA_PERIODS, RSI_PERIOD, ACCOUNT_SIZE,
    RISK_PER_TRADE_PCT, ATR_STOP_MULTIPLIER, TAKE_PROFIT_RR_RATIO,
    BOLLINGER_PERIOD, BOLLINGER_STD,
    RSI_OVERSOLD, RSI_OVERBOUGHT,
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
                           oversold: int = None, overbought: int = None) -> BacktestResult:
    if oversold is None:
        oversold = RSI_OVERSOLD
    if overbought is None:
        overbought = RSI_OVERBOUGHT
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


def backtest_bollinger_reversion(ticker: str, df: pd.DataFrame,
                                  bb_period: int = None, bb_std: float = None) -> BacktestResult:
    """볼린저밴드 반전 전략: 하단 돌파 매수 → 상단 근접 매도"""
    if bb_period is None:
        bb_period = BOLLINGER_PERIOD
    if bb_std is None:
        bb_std = BOLLINGER_STD

    df = df.copy()
    bbu_col = f"BBU_{bb_period}_{bb_std}"
    bbl_col = f"BBL_{bb_period}_{bb_std}"
    bbm_col = f"BBM_{bb_period}_{bb_std}"

    # 볼린저 밴드 재계산 (파라미터가 다를 수 있음)
    sma = df["Close"].rolling(bb_period).mean()
    std = df["Close"].rolling(bb_period).std()
    df[bbu_col] = sma + bb_std * std
    df[bbl_col] = sma - bb_std * std
    df[bbm_col] = sma

    df = df.dropna(subset=[bbu_col, bbl_col]).copy()
    if df.empty:
        return BacktestResult(strategy=f"Bollinger_Reversion_{bb_period}_{bb_std}", ticker=ticker)

    cash = ACCOUNT_SIZE
    position = 0
    entry_price = 0.0
    entry_date = None
    trades = []
    equity = []

    for i in range(1, len(df)):
        price = float(df["Close"].iloc[i])
        bbu = float(df[bbu_col].iloc[i])
        bbl = float(df[bbl_col].iloc[i])
        date = df.index[i]

        # 진입: 가격이 하단 밴드 아래로 떨어졌을 때
        if price < bbl and position == 0:
            risk_amt = cash * (RISK_PER_TRADE_PCT / 100)
            atr_val = float(df["ATR"].iloc[i]) if "ATR" in df.columns and not pd.isna(df["ATR"].iloc[i]) else price * 0.02
            stop_dist = atr_val * ATR_STOP_MULTIPLIER
            qty = int(risk_amt / stop_dist) if stop_dist > 0 else 0
            if qty > 0 and qty * price <= cash:
                position = qty
                entry_price = price
                entry_date = date
                cash -= qty * price

        # 청산: 가격이 상단 밴드 근처(80% 이상)에 도달했을 때
        elif position > 0:
            bb_position = (price - bbl) / (bbu - bbl) if bbu != bbl else 0.5
            if bb_position > 0.8:
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
    return _compute_stats(equity_series, trades, f"Bollinger_Reversion_{bb_period}_{bb_std}", ticker)


def optimize_strategy_params(ticker: str, df: pd.DataFrame, strategy: str = "rsi_reversion",
                              n_trials: int = 50) -> dict:
    """Optuna를 사용한 전략 파라미터 최적화 (Freqtrade 스타일)

    Args:
        strategy: "sma_cross", "rsi_reversion", "bollinger_reversion"
        n_trials: 최적화 시행 횟수
    """
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        return {"error": "optuna 미설치 (pip install optuna)"}

    def objective(trial):
        if strategy == "sma_cross":
            fast = trial.suggest_int("fast_period", 5, 30)
            slow = trial.suggest_int("slow_period", fast + 5, 100)
            result = backtest_sma_cross(ticker, df, fast, slow)
        elif strategy == "rsi_reversion":
            oversold = trial.suggest_int("oversold", 20, 35)
            overbought = trial.suggest_int("overbought", 65, 80)
            if oversold >= overbought - 10:
                return -999
            result = backtest_rsi_reversion(ticker, df, oversold, overbought)
        elif strategy == "bollinger_reversion":
            bb_period = trial.suggest_int("bb_period", 10, 30)
            bb_std = trial.suggest_float("bb_std", 1.5, 3.0)
            result = backtest_bollinger_reversion(ticker, df, bb_period, bb_std)
        else:
            return -999

        # Sharpe Ratio를 목표로 최대화
        sharpe = result.sharpe_ratio
        return sharpe if not np.isnan(sharpe) else -999

    study = optuna.create_study(direction="maximize", study_name=f"{ticker}_{strategy}")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best_params = study.best_params
    best_value = study.best_value

    # 최적 파라미터로 재실행
    if strategy == "sma_cross":
        final_result = backtest_sma_cross(ticker, df, best_params["fast_period"], best_params["slow_period"])
    elif strategy == "rsi_reversion":
        final_result = backtest_rsi_reversion(ticker, df, best_params["oversold"], best_params["overbought"])
    elif strategy == "bollinger_reversion":
        final_result = backtest_bollinger_reversion(ticker, df, best_params["bb_period"], best_params["bb_std"])
    else:
        final_result = BacktestResult(strategy=strategy, ticker=ticker)

    return {
        "ticker": ticker,
        "strategy": strategy,
        "best_params": best_params,
        "best_sharpe": round(best_value, 3),
        "n_trials": n_trials,
        "result": final_result.to_dict(),
    }


def backtest_walk_forward(ticker: str, df: pd.DataFrame, strategy: str = "rsi_reversion",
                          train_window: int = 252, test_window: int = 63,
                          n_splits: int = 5) -> dict:
    """Walk-Forward 백테스트 (vectorbt/Qlib 스타일)

    Args:
        train_window: 학습 윈도우 (거래일 수)
        test_window: 테스트 윈도우 (거래일 수)
        n_splits: 총 분할 수
    """
    df = df.copy()
    total_length = len(df)
    step = (total_length - train_window - test_window) // max(n_splits - 1, 1)
    if step <= 0:
        step = test_window

    results = []
    all_trades = []
    all_equity = []

    for i in range(n_splits):
        start_idx = i * step
        train_end_idx = start_idx + train_window
        test_end_idx = min(train_end_idx + test_window, total_length)

        if train_end_idx >= total_length:
            break

        train_df = df.iloc[start_idx:train_end_idx]
        test_df = df.iloc[train_end_idx:test_end_idx]

        if len(train_df) < 50 or len(test_df) < 10:
            continue

        # 학습 구간에서 파라미터 최적화
        opt_result = optimize_strategy_params(ticker, train_df, strategy, n_trials=20)
        if opt_result.get("error"):
            continue

        best_params = opt_result["best_params"]

        # 테스트 구간에서 백테스트
        if strategy == "sma_cross":
            test_result = backtest_sma_cross(ticker, test_df, best_params["fast_period"], best_params["slow_period"])
        elif strategy == "rsi_reversion":
            test_result = backtest_rsi_reversion(ticker, test_df, best_params["oversold"], best_params["overbought"])
        elif strategy == "bollinger_reversion":
            test_result = backtest_bollinger_reversion(ticker, test_df, best_params["bb_period"], best_params["bb_std"])
        else:
            continue

        results.append({
            "split": i + 1,
            "train_start": str(train_df.index[0])[:10],
            "train_end": str(train_df.index[-1])[:10],
            "test_start": str(test_df.index[0])[:10],
            "test_end": str(test_df.index[-1])[:10],
            "best_params": best_params,
            "train_sharpe": opt_result["best_sharpe"],
            "test_sharpe": test_result.sharpe_ratio,
            "test_return_pct": test_result.total_return_pct,
            "test_max_drawdown_pct": test_result.max_drawdown_pct,
            "test_trades": test_result.total_trades,
        })

        all_trades.extend(test_result.trades)
        all_equity.extend(test_result.equity_curve)

    if not results:
        return {"error": "백테스트 실행 실패 (데이터 부족)", "ticker": ticker}

    # 전체 통계
    avg_test_sharpe = np.mean([r["test_sharpe"] for r in results])
    avg_test_return = np.mean([r["test_return_pct"] for r in results])
    avg_train_sharpe = np.mean([r["train_sharpe"] for r in results])

    overfitting_ratio = avg_train_sharpe / avg_test_sharpe if avg_test_sharpe != 0 else 999

    return {
        "ticker": ticker,
        "strategy": strategy,
        "walk_forward_splits": len(results),
        "train_window": train_window,
        "test_window": test_window,
        "avg_train_sharpe": round(avg_train_sharpe, 3),
        "avg_test_sharpe": round(avg_test_sharpe, 3),
        "avg_test_return_pct": round(avg_test_return, 2),
        "overfitting_ratio": round(overfitting_ratio, 2),
        "total_test_trades": len(all_trades),
        "splits": results,
    }


def run_all_backtests(ticker: str, df: pd.DataFrame, tool_results: list = None) -> dict:
    results = {}
    results["sma_cross"] = backtest_sma_cross(ticker, df).to_dict()
    results["rsi_reversion"] = backtest_rsi_reversion(ticker, df).to_dict()
    results["bollinger_reversion"] = backtest_bollinger_reversion(ticker, df).to_dict()
    if tool_results:
        results["composite_signal"] = backtest_composite_signal(ticker, df, tool_results).to_dict()
    best = max(results.values(), key=lambda x: x.get("sharpe_ratio", 0))
    return {
        "ticker": ticker,
        "strategies": results,
        "best_strategy": best["strategy"],
        "best_sharpe": best["sharpe_ratio"],
    }
