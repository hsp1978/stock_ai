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
from trading_costs import TradingCosts
from tick_size import round_to_tick


EXECUTION_MODEL_NOTE = (
    "Signals are evaluated on the confirmed close and filled at the next bar open "
    "to avoid same-close look-ahead bias."
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
    trading_costs: Optional[dict] = None  # 거래비용 정보 (slippage/commission/tax)
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
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
        if self.trading_costs:
            d["trading_costs"] = self.trading_costs
        if self.notes:
            d["notes"] = self.notes
        return d


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
        # Step 10: rf 차감 Sharpe (is_korean 여부는 ticker 패턴으로 추론)
        try:
            from backtest_metrics import compute_sharpe
            from config import settings
            _is_kr = any(
                str(getattr(result, "ticker", "") or "").upper().endswith(s)
                for s in (".KS", ".KQ")
            )
            _rf = settings.ANNUAL_RISK_FREE_RATE_KR if _is_kr else settings.ANNUAL_RISK_FREE_RATE_US
            result.sharpe_ratio = compute_sharpe(daily_ret, _rf)
        except Exception:
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


def _execution_fill(
    df: pd.DataFrame,
    signal_idx: int,
    ticker: str,
    costs: TradingCosts,
    side: str,
) -> Tuple[float, object, str]:
    """Return next-bar fill price/date/source for a close-confirmed signal."""
    fill_idx = signal_idx + 1
    if fill_idx >= len(df):
        raise IndexError("next bar unavailable for execution")

    source = "next_open"
    if "Open" in df.columns and not pd.isna(df["Open"].iloc[fill_idx]):
        raw_price = float(df["Open"].iloc[fill_idx])
    else:
        raw_price = float(df["Close"].iloc[fill_idx])
        source = "next_close_fallback"

    if side == "entry":
        fill_price = round_to_tick(costs.apply_entry(raw_price), ticker, side="up")
    else:
        fill_price = round_to_tick(costs.apply_exit(raw_price), ticker, side="down")
    return fill_price, df.index[fill_idx], source


def _append_execution_note(result: BacktestResult) -> BacktestResult:
    if EXECUTION_MODEL_NOTE not in result.notes:
        result.notes.append(EXECUTION_MODEL_NOTE)
    return result


def _apply_evaluation_start(df: pd.DataFrame, evaluation_start=None) -> pd.DataFrame:
    if evaluation_start is None or df.empty:
        return df
    return df.loc[df.index >= evaluation_start].copy()


def _strategy_padding_lookback(strategy: str) -> int:
    if strategy == "sma_cross":
        return 100
    if strategy == "bollinger_reversion":
        return 30
    if strategy == "rsi_reversion":
        return RSI_PERIOD + 5
    return max(SMA_PERIODS) if SMA_PERIODS else 100


def _padded_slice(
    df: pd.DataFrame,
    start_idx: int,
    end_idx: int,
    lookback: int,
) -> Tuple[pd.DataFrame, int]:
    padded_start = max(0, start_idx - max(0, lookback))
    return df.iloc[padded_start:end_idx].copy(), start_idx - padded_start


def _signal_series(values, index: pd.Index) -> pd.Series:
    return pd.Series(values, index=index).fillna(False).astype(bool)


def _next_fill_raw_price(df: pd.DataFrame, fill_idx: int) -> tuple[float, str]:
    if "Open" in df.columns and not pd.isna(df["Open"].iat[fill_idx]):
        return float(df["Open"].iat[fill_idx]), "next_open"
    return float(df["Close"].iat[fill_idx]), "next_close_fallback"


def _run_long_only_state_machine(
    ticker: str,
    df: pd.DataFrame,
    entry_signal: pd.Series,
    exit_signal: pd.Series,
    strategy_name: str,
    costs: TradingCosts,
) -> BacktestResult:
    """Run a long-only state machine using vectorized signals and ndarray prices."""
    if df.empty:
        return BacktestResult(strategy=strategy_name, ticker=ticker)

    close = df["Close"].to_numpy(dtype=float, copy=False)
    if "ATR" in df.columns:
        atr = df["ATR"].to_numpy(dtype=float, copy=False)
    else:
        atr = close * 0.02
    entry_flags = entry_signal.reindex(df.index, fill_value=False).to_numpy(dtype=bool, copy=False)
    exit_flags = exit_signal.reindex(df.index, fill_value=False).to_numpy(dtype=bool, copy=False)
    index = df.index

    cash = ACCOUNT_SIZE
    position = 0
    entry_price = 0.0
    entry_date = None
    entry_signal_date = None
    entry_fill_source = None
    trades = []
    equity = []

    for i in range(1, max(len(df) - 1, 1)):
        price = float(close[i])
        date = index[i]
        equity.append(cash + position * price)

        if entry_flags[i] and position == 0:
            raw_price, fill_source = _next_fill_raw_price(df, i + 1)
            fill_price = round_to_tick(costs.apply_entry(raw_price), ticker, side="up")
            risk_amt = cash * (RISK_PER_TRADE_PCT / 100)
            atr_val = float(atr[i]) if not np.isnan(atr[i]) else price * 0.02
            stop_dist = atr_val * ATR_STOP_MULTIPLIER
            qty = int(risk_amt / stop_dist) if stop_dist > 0 else 0
            if qty > 0 and qty * fill_price <= cash:
                position = qty
                entry_price = fill_price
                entry_date = index[i + 1]
                entry_signal_date = date
                entry_fill_source = fill_source
                cash -= qty * fill_price

        elif exit_flags[i] and position > 0:
            raw_price, fill_source = _next_fill_raw_price(df, i + 1)
            fill_price = round_to_tick(costs.apply_exit(raw_price), ticker, side="down")
            pnl = (fill_price - entry_price) * position
            cash += position * fill_price
            fill_date = index[i + 1]
            holding = (fill_date - entry_date).days if entry_date is not None else 0
            trades.append({
                "entry_signal_date": str(entry_signal_date)[:10],
                "entry_date": str(entry_date)[:10],
                "exit_signal_date": str(date)[:10],
                "exit_date": str(fill_date)[:10],
                "entry_price": round(entry_price, 4),
                "exit_price": round(fill_price, 4),
                "entry_fill_price_source": entry_fill_source,
                "exit_fill_price_source": fill_source,
                "fill_price_source": fill_source,
                "qty": position,
                "pnl": round(pnl, 2),
                "return_pct": round((fill_price / entry_price - 1) * 100, 2),
                "holding_days": holding,
            })
            position = 0

    if len(df) >= 2:
        equity.append(cash + position * float(close[-1]))

    equity_series = pd.Series(equity, index=df.index[1:len(equity) + 1])
    result = _compute_stats(equity_series, trades, strategy_name, ticker)
    result.trading_costs = costs.to_dict()
    return _append_execution_note(result)


def backtest_sma_cross(ticker: str, df: pd.DataFrame,
                       fast_period: int = None, slow_period: int = None,
                       costs: Optional[TradingCosts] = None,
                       evaluation_start=None) -> BacktestResult:
    if fast_period is None:
        fast_period = SMA_PERIODS[0] if len(SMA_PERIODS) >= 2 else 20
    if slow_period is None:
        slow_period = SMA_PERIODS[1] if len(SMA_PERIODS) >= 2 else 50
    if costs is None:
        costs = TradingCosts.for_ticker(ticker)

    df = df.copy()
    sma_f = f"SMA_{fast_period}"
    sma_s = f"SMA_{slow_period}"
    if sma_f not in df.columns:
        df[sma_f] = df["Close"].rolling(fast_period).mean()
    if sma_s not in df.columns:
        df[sma_s] = df["Close"].rolling(slow_period).mean()

    df = df.dropna(subset=[sma_f, sma_s]).copy()
    df = _apply_evaluation_start(df, evaluation_start)
    if df.empty:
        return BacktestResult(strategy=f"SMA_Cross_{fast_period}_{slow_period}", ticker=ticker)

    entry_signal = (df[sma_f].shift(1) <= df[sma_s].shift(1)) & (df[sma_f] > df[sma_s])
    exit_signal = (df[sma_f].shift(1) >= df[sma_s].shift(1)) & (df[sma_f] < df[sma_s])
    return _run_long_only_state_machine(
        ticker,
        df,
        _signal_series(entry_signal, df.index),
        _signal_series(exit_signal, df.index),
        f"SMA_Cross_{fast_period}_{slow_period}",
        costs,
    )


def backtest_rsi_reversion(ticker: str, df: pd.DataFrame,
                           oversold: int = None, overbought: int = None,
                           costs: Optional[TradingCosts] = None,
                           evaluation_start=None) -> BacktestResult:
    if oversold is None:
        oversold = RSI_OVERSOLD
    if overbought is None:
        overbought = RSI_OVERBOUGHT
    if costs is None:
        costs = TradingCosts.for_ticker(ticker)
    df = df.copy()
    if "RSI" not in df.columns:
        return BacktestResult(strategy=f"RSI_Reversion_{oversold}_{overbought}", ticker=ticker)

    df = df.dropna(subset=["RSI"]).copy()
    df = _apply_evaluation_start(df, evaluation_start)
    if df.empty:
        return BacktestResult(strategy=f"RSI_Reversion_{oversold}_{overbought}", ticker=ticker)

    entry_signal = df["RSI"] < oversold
    exit_signal = df["RSI"] > overbought
    return _run_long_only_state_machine(
        ticker,
        df,
        _signal_series(entry_signal, df.index),
        _signal_series(exit_signal, df.index),
        f"RSI_Reversion_{oversold}_{overbought}",
        costs,
    )


def backtest_composite_signal(ticker: str, df: pd.DataFrame, tool_results: list,
                              costs: Optional[TradingCosts] = None) -> BacktestResult:
    if costs is None:
        costs = TradingCosts.for_ticker(ticker)
    df = df.copy().dropna(subset=["Close"])
    if df.empty or not tool_results:
        return BacktestResult(strategy="Composite_Signal", ticker=ticker)

    # tool_results는 현재 시점 1회 실행 결과다. 이를 과거 봉마다 재사용하면
    # 미래 정보를 과거에 주입하는 look-ahead bias가 되므로 거래 재현을 하지 않는다.
    equity_series = pd.Series([ACCOUNT_SIZE] * len(df), index=df.index)
    result = _compute_stats(equity_series, [], "Composite_Signal_CurrentOnly", ticker)
    result.trading_costs = costs.to_dict()
    result.notes.append(
        "현재 시점 tool_results만 제공되어 복합 시그널 과거 백테스트를 생략함 "
        "(look-ahead bias 방지)."
    )
    return result


def backtest_bollinger_reversion(ticker: str, df: pd.DataFrame,
                                  bb_period: int = None, bb_std: float = None,
                                  costs: Optional[TradingCosts] = None,
                                  evaluation_start=None) -> BacktestResult:
    """볼린저밴드 반전 전략: 하단 돌파 매수 → 상단 근접 매도"""
    if bb_period is None:
        bb_period = BOLLINGER_PERIOD
    if bb_std is None:
        bb_std = BOLLINGER_STD
    if costs is None:
        costs = TradingCosts.for_ticker(ticker)

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
    df = _apply_evaluation_start(df, evaluation_start)
    if df.empty:
        return BacktestResult(strategy=f"Bollinger_Reversion_{bb_period}_{bb_std}", ticker=ticker)

    band_width = df[bbu_col] - df[bbl_col]
    bb_position = np.where(
        band_width.to_numpy(dtype=float) != 0,
        (df["Close"].to_numpy(dtype=float) - df[bbl_col].to_numpy(dtype=float))
        / band_width.to_numpy(dtype=float),
        0.5,
    )
    entry_signal = df["Close"] < df[bbl_col]
    exit_signal = pd.Series(bb_position, index=df.index) > 0.8
    return _run_long_only_state_machine(
        ticker,
        df,
        _signal_series(entry_signal, df.index),
        _signal_series(exit_signal, df.index),
        f"Bollinger_Reversion_{bb_period}_{bb_std}",
        costs,
    )


def optimize_strategy_params(ticker: str, df: pd.DataFrame, strategy: str = "rsi_reversion",
                              n_trials: int = 50, evaluation_start=None) -> dict:
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

    opt_df = df.copy()
    sma_cache: set[int] = set()

    def _ensure_sma(period: int) -> None:
        if period in sma_cache:
            return
        col = f"SMA_{period}"
        if col not in opt_df.columns:
            opt_df[col] = opt_df["Close"].rolling(period).mean()
        sma_cache.add(period)

    def objective(trial):
        if strategy == "sma_cross":
            fast = trial.suggest_int("fast_period", 5, 30)
            slow = trial.suggest_int("slow_period", fast + 5, 100)
            _ensure_sma(fast)
            _ensure_sma(slow)
            result = backtest_sma_cross(ticker, opt_df, fast, slow, evaluation_start=evaluation_start)
        elif strategy == "rsi_reversion":
            oversold = trial.suggest_int("oversold", 20, 35)
            overbought = trial.suggest_int("overbought", 65, 80)
            if oversold >= overbought - 10:
                return -999
            result = backtest_rsi_reversion(ticker, opt_df, oversold, overbought, evaluation_start=evaluation_start)
        elif strategy == "bollinger_reversion":
            bb_period = trial.suggest_int("bb_period", 10, 30)
            bb_std = trial.suggest_float("bb_std", 1.5, 3.0)
            result = backtest_bollinger_reversion(ticker, opt_df, bb_period, bb_std, evaluation_start=evaluation_start)
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
        _ensure_sma(best_params["fast_period"])
        _ensure_sma(best_params["slow_period"])
        final_result = backtest_sma_cross(
            ticker, opt_df, best_params["fast_period"], best_params["slow_period"],
            evaluation_start=evaluation_start,
        )
    elif strategy == "rsi_reversion":
        final_result = backtest_rsi_reversion(
            ticker, opt_df, best_params["oversold"], best_params["overbought"],
            evaluation_start=evaluation_start,
        )
    elif strategy == "bollinger_reversion":
        final_result = backtest_bollinger_reversion(
            ticker, opt_df, best_params["bb_period"], best_params["bb_std"],
            evaluation_start=evaluation_start,
        )
    else:
        final_result = BacktestResult(strategy=strategy, ticker=ticker)

    return {
        "ticker": ticker,
        "strategy": strategy,
        "best_params": best_params,
        "best_sharpe": round(best_value, 3),
        "n_trials": n_trials,
        "evaluation_start": str(evaluation_start)[:10] if evaluation_start is not None else None,
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

        lookback = _strategy_padding_lookback(strategy)
        train_df, train_padding = _padded_slice(df, start_idx, train_end_idx, lookback)
        test_df, test_padding = _padded_slice(df, train_end_idx, test_end_idx, lookback)
        train_eval_start = df.index[start_idx]
        test_eval_start = df.index[train_end_idx]

        if len(train_df) < 50 or len(test_df) < 10:
            continue

        # 학습 구간에서 파라미터 최적화
        opt_result = optimize_strategy_params(
            ticker,
            train_df,
            strategy,
            n_trials=20,
            evaluation_start=train_eval_start,
        )
        if opt_result.get("error"):
            continue

        best_params = opt_result["best_params"]

        # 테스트 구간에서 백테스트
        if strategy == "sma_cross":
            fast = best_params["fast_period"]
            slow = best_params["slow_period"]
            test_result = backtest_sma_cross(
                ticker, test_df, fast, slow, evaluation_start=test_eval_start
            )
        elif strategy == "rsi_reversion":
            test_result = backtest_rsi_reversion(
                ticker,
                test_df,
                best_params["oversold"],
                best_params["overbought"],
                evaluation_start=test_eval_start,
            )
        elif strategy == "bollinger_reversion":
            test_result = backtest_bollinger_reversion(
                ticker,
                test_df,
                best_params["bb_period"],
                best_params["bb_std"],
                evaluation_start=test_eval_start,
            )
        else:
            continue

        results.append({
            "split": i + 1,
            "train_start": str(train_eval_start)[:10],
            "train_end": str(df.index[train_end_idx - 1])[:10],
            "test_start": str(test_eval_start)[:10],
            "test_end": str(test_df.index[-1])[:10],
            "train_padding_bars": train_padding,
            "test_padding_bars": test_padding,
            "indicator_lookback_bars": lookback,
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
