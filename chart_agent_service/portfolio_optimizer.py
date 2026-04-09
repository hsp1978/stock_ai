"""
포트폴리오 최적화 모듈
- 마코위츠 평균-분산 최적화
- 리스크 패리티
- 팩터 랭킹 (크로스섹션)
- 상관관계 / 베타 분석
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Optional
import yfinance as yf

from config import ACCOUNT_SIZE


def _fetch_returns(tickers: list[str], period: str = "1y") -> pd.DataFrame:
    prices = pd.DataFrame()
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period=period)
            if not hist.empty:
                prices[t] = hist["Close"]
        except Exception:
            pass
    return prices.pct_change().dropna()


def markowitz_optimize(tickers: list[str], period: str = "1y",
                       risk_free_rate: float = 0.05) -> dict:
    returns = _fetch_returns(tickers, period)
    if returns.empty or len(returns.columns) < 2:
        return {"error": "데이터 부족", "tickers": tickers}

    mu = returns.mean() * 252
    cov = returns.cov() * 252
    n = len(tickers)
    valid_tickers = returns.columns.tolist()

    def neg_sharpe(w):
        port_ret = np.dot(w, mu)
        port_vol = np.sqrt(np.dot(w.T, np.dot(cov, w)))
        return -(port_ret - risk_free_rate) / port_vol if port_vol > 0 else 0

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(0, 0.4)] * n
    x0 = np.ones(n) / n

    result = minimize(neg_sharpe, x0, method="SLSQP", bounds=bounds, constraints=constraints)

    weights = result.x
    port_ret = float(np.dot(weights, mu))
    port_vol = float(np.sqrt(np.dot(weights.T, np.dot(cov, weights))))
    sharpe = (port_ret - risk_free_rate) / port_vol if port_vol > 0 else 0

    allocation = {}
    for i, t in enumerate(valid_tickers):
        if weights[i] > 0.001:
            allocation[t] = {
                "weight_pct": round(weights[i] * 100, 2),
                "amount": round(ACCOUNT_SIZE * weights[i], 2),
                "expected_return_pct": round(float(mu.iloc[i]) * 100, 2),
                "volatility_pct": round(float(np.sqrt(cov.iloc[i, i])) * 100, 2),
            }

    return {
        "method": "markowitz_max_sharpe",
        "portfolio_return_pct": round(port_ret * 100, 2),
        "portfolio_volatility_pct": round(port_vol * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "account_size": ACCOUNT_SIZE,
        "allocation": allocation,
        "correlation_matrix": {
            t1: {t2: round(float(returns[t1].corr(returns[t2])), 3) for t2 in valid_tickers}
            for t1 in valid_tickers
        },
    }


def risk_parity_optimize(tickers: list[str], period: str = "1y") -> dict:
    returns = _fetch_returns(tickers, period)
    if returns.empty or len(returns.columns) < 2:
        return {"error": "데이터 부족", "tickers": tickers}

    cov = returns.cov() * 252
    n = len(returns.columns)
    valid_tickers = returns.columns.tolist()

    def risk_parity_obj(w):
        port_vol = np.sqrt(np.dot(w.T, np.dot(cov.values, w)))
        if port_vol == 0:
            return 0
        marginal = np.dot(cov.values, w) / port_vol
        risk_contrib = w * marginal
        target = port_vol / n
        return np.sum((risk_contrib - target) ** 2)

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(0.01, 0.5)] * n
    x0 = np.ones(n) / n

    result = minimize(risk_parity_obj, x0, method="SLSQP", bounds=bounds, constraints=constraints)
    weights = result.x

    mu = returns.mean() * 252
    port_ret = float(np.dot(weights, mu))
    port_vol = float(np.sqrt(np.dot(weights.T, np.dot(cov.values, weights))))

    allocation = {}
    for i, t in enumerate(valid_tickers):
        allocation[t] = {
            "weight_pct": round(weights[i] * 100, 2),
            "amount": round(ACCOUNT_SIZE * weights[i], 2),
        }

    return {
        "method": "risk_parity",
        "portfolio_return_pct": round(port_ret * 100, 2),
        "portfolio_volatility_pct": round(port_vol * 100, 2),
        "account_size": ACCOUNT_SIZE,
        "allocation": allocation,
    }


def compute_factor_ranking(cached_results: dict) -> list[dict]:
    if not cached_results:
        return []

    rows = []
    for ticker, data in cached_results.items():
        r = data.get("result", {})
        if not r:
            continue
        row = {
            "ticker": ticker,
            "composite_score": r.get("composite_score", 0),
            "confidence": r.get("confidence", 0),
            "signal": r.get("final_signal", "HOLD"),
        }

        for ts in r.get("tool_summaries", []):
            tool_name = ts.get("tool", "")
            row[f"score_{tool_name}"] = ts.get("score", 0)

        momentum_score = row.get("score_momentum_rank_analysis", 0)
        mean_rev_score = row.get("score_mean_reversion_analysis", 0)
        volatility_score = row.get("score_volatility_regime_analysis", 0)
        trend_score = row.get("score_trend_ma_analysis", 0)
        volume_score = row.get("score_volume_profile_analysis", 0)

        row["factor_momentum"] = momentum_score
        row["factor_value"] = mean_rev_score
        row["factor_volatility"] = volatility_score
        row["factor_trend"] = trend_score
        row["factor_volume"] = volume_score

        row["weighted_factor_score"] = round(
            momentum_score * 0.25 +
            mean_rev_score * 0.15 +
            trend_score * 0.25 +
            volume_score * 0.15 +
            volatility_score * 0.10 +
            row["composite_score"] * 0.10,
            2
        )
        rows.append(row)

    rows.sort(key=lambda x: x["weighted_factor_score"], reverse=True)

    for i, row in enumerate(rows):
        row["rank"] = i + 1
        row["percentile"] = round((1 - i / max(len(rows), 1)) * 100, 1)

    return rows


def compute_correlation_beta(tickers: list[str], benchmark: str = "SPY",
                             period: str = "1y") -> dict:
    all_tickers = list(set(tickers + [benchmark]))
    returns = _fetch_returns(all_tickers, period)
    if benchmark not in returns.columns:
        return {"error": f"{benchmark} 데이터 없음"}

    bench_ret = returns[benchmark]
    bench_var = float(bench_ret.var())
    results = {}

    for t in tickers:
        if t not in returns.columns or t == benchmark:
            continue
        t_ret = returns[t]
        beta = float(t_ret.cov(bench_ret) / bench_var) if bench_var > 0 else 0
        alpha = float((t_ret.mean() - beta * bench_ret.mean()) * 252)
        corr = float(t_ret.corr(bench_ret))
        tracking_error = float((t_ret - beta * bench_ret).std() * np.sqrt(252))
        results[t] = {
            "beta": round(beta, 3),
            "alpha_annualized": round(alpha * 100, 2),
            "correlation": round(corr, 3),
            "tracking_error_pct": round(tracking_error * 100, 2),
            "r_squared": round(corr ** 2, 3),
        }

    pair_corr = {}
    stock_tickers = [t for t in tickers if t in returns.columns and t != benchmark]
    for i, t1 in enumerate(stock_tickers):
        for t2 in stock_tickers[i + 1:]:
            pair_corr[f"{t1}/{t2}"] = round(float(returns[t1].corr(returns[t2])), 3)

    portfolio_beta = np.mean([v["beta"] for v in results.values()]) if results else 0

    hedge_ratio = {}
    if portfolio_beta != 0:
        for t in stock_tickers:
            b = results[t]["beta"]
            hedge_ratio[t] = round(-b / portfolio_beta, 3)

    return {
        "benchmark": benchmark,
        "period": period,
        "individual": results,
        "pair_correlations": pair_corr,
        "portfolio_beta": round(portfolio_beta, 3),
        "hedge_ratios": hedge_ratio,
    }
