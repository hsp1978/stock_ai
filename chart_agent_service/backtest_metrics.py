"""
백테스트 보정 지표 모음 (Step 10).

모든 지표는 무위험 수익률(rf)을 차감한다.

compute_sharpe():  rf 차감 Sharpe ratio
compute_sortino(): rf 차감 Sortino ratio
compute_calmar():  CAGR / MaxDD
compute_max_dd():  최대 드로우다운
compute_all():     전체 지표 한번에
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _daily_rf(annual_rf_pct: float) -> float:
    """연율 rf(%) → 일별 rf (소수)."""
    return annual_rf_pct / 252 / 100


def compute_sharpe(
    daily_returns: pd.Series,
    annual_rf_pct: float = 0.0,
) -> float:
    """
    rf 차감 Sharpe ratio (연율화).

    Args:
        daily_returns:  일별 수익률 (소수, e.g. 0.01 = 1%)
        annual_rf_pct:  연율 무위험 수익률 (%)
    """
    rf_d = _daily_rf(annual_rf_pct)
    excess = daily_returns - rf_d
    std = excess.std()
    if std < 1e-10 or np.isnan(std):
        return float("nan")
    return float(excess.mean() / std * np.sqrt(252))


def compute_sortino(
    daily_returns: pd.Series,
    annual_rf_pct: float = 0.0,
) -> float:
    """
    rf 차감 Sortino ratio (하방 표준편차 기반).
    """
    rf_d = _daily_rf(annual_rf_pct)
    excess = daily_returns - rf_d
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float("inf")
    dstd = downside.std()
    if dstd < 1e-10 or np.isnan(dstd):
        return float("nan")
    return float(excess.mean() / dstd * np.sqrt(252))


def compute_max_dd(daily_returns: pd.Series) -> float:
    """최대 드로우다운 (음수, e.g. -0.25 = -25%)."""
    if daily_returns.empty:
        return 0.0
    cum = (1 + daily_returns).cumprod()
    peak = cum.expanding().max()
    dd = (cum - peak) / peak
    return float(dd.min())


def compute_calmar(daily_returns: pd.Series) -> float:
    """
    Calmar ratio = CAGR / |MaxDD|.

    CAGR: (1 + r)^(252/n) - 1
    """
    n = len(daily_returns)
    if n == 0:
        return float("nan")
    cagr = float((1 + daily_returns).prod() ** (252 / n) - 1)
    max_dd = compute_max_dd(daily_returns)
    if max_dd == 0:
        return float("inf")
    return float(cagr / abs(max_dd))


def compute_all(
    daily_returns: pd.Series,
    annual_rf_pct: float = 0.0,
    slippage_bps: float = 5.0,
    commission_pct: float = 0.015,
    is_korean: bool = False,
) -> dict:
    """
    모든 지표를 한 번에 계산해 dict로 반환한다.

    Args:
        daily_returns:  일별 수익률 (거래비용 제외 raw)
        annual_rf_pct:  연율 rf (%)
        slippage_bps:   슬리피지 (basis points, KRX 대형주 기본 5bp)
        commission_pct: 수수료 (%)
        is_korean:      True → KRX 거래세 적용
    """
    from config import settings

    krx_tax = settings.KRX_TRADING_TAX_PCT if is_korean else 0.0
    total_cost_pct = slippage_bps / 10_000 + commission_pct / 100 + krx_tax / 100

    # 거래비용 차감 (매 거래일 단순 적용 — 보수적 추정)
    adj_returns = daily_returns - total_cost_pct

    n = len(adj_returns)
    total_return = float((1 + adj_returns).prod() - 1) if n > 0 else 0.0
    cagr = float((1 + adj_returns).prod() ** (252 / n) - 1) if n > 0 else 0.0
    max_dd = compute_max_dd(adj_returns)
    win_rate = float((adj_returns > 0).mean()) if n > 0 else 0.0
    avg_win = (
        float(adj_returns[adj_returns > 0].mean()) if (adj_returns > 0).any() else 0.0
    )
    avg_loss = (
        float(adj_returns[adj_returns < 0].mean()) if (adj_returns < 0).any() else 0.0
    )
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    return {
        "sharpe": compute_sharpe(adj_returns, annual_rf_pct),
        "sortino": compute_sortino(adj_returns, annual_rf_pct),
        "calmar": compute_calmar(adj_returns),
        "max_drawdown": max_dd,
        "total_return": total_return,
        "cagr": cagr,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "total_trades": n,
        "assumptions": {
            "annual_rf_pct": annual_rf_pct,
            "slippage_bps": slippage_bps,
            "commission_pct": commission_pct,
            "krx_trading_tax_pct": krx_tax,
        },
    }


# ── P2: DSR + PBO ────────────────────────────────────────────────────


def compute_dsr(
    daily_returns: pd.Series,
    annual_rf_pct: float = 0.0,
    benchmark_sharpe: float = 1.0,
) -> float:
    """
    Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    DSR = Φ[(SR_hat - SR*) * √(T-1) / √(1 - γ₃*SR_hat + γ₄/4 * SR_hat²)]

    SR_hat: 관측된 Sharpe ratio
    SR*   : 벤치마크 Sharpe ratio (과적합 기준선)
    T     : 관측 수
    γ₃    : 왜도, γ₄: 초과 첨도
    Φ     : 표준정규 CDF

    Returns:
        0~1 사이 확률 (1에 가까울수록 과적합 의심 낮음, 즉 실제 성과 가능성 높음)
    """
    from scipy.stats import norm  # type: ignore[import-untyped]

    n = len(daily_returns)
    if n < 30:
        return float("nan")

    sr_hat = compute_sharpe(daily_returns, annual_rf_pct)
    if np.isnan(sr_hat):
        return float("nan")

    skew = float(daily_returns.skew())
    kurt = float(daily_returns.kurt())  # excess kurtosis

    # 분모: 분산 보정
    denominator = 1 - skew * sr_hat + (kurt / 4) * sr_hat**2
    if denominator <= 0:
        denominator = 1e-6

    numerator = (sr_hat - benchmark_sharpe) * np.sqrt(n - 1)
    z = numerator / np.sqrt(denominator)
    return float(norm.cdf(z))


def compute_pbo(
    daily_returns: pd.Series,
    n_splits: int = 16,
    annual_rf_pct: float = 0.0,
    n_trials: int = 1000,
    random_seed: int = 42,
) -> dict:
    """
    Probability of Backtest Overfitting (Bailey et al., 2014) — Monte Carlo 근사.

    전략 수익률을 n_splits개 구간으로 나눠 무작위 조합으로 IS/OOS 비교.

    Args:
        daily_returns: 일별 수익률
        n_splits:      분할 수 (짝수 권장)
        annual_rf_pct: 연율 rf
        n_trials:      무작위 시도 수
        random_seed:   재현성

    Returns:
        {"pbo": float, "n_trials": int, "n_splits": int,
         "mean_oos_sharpe": float, "mean_is_sharpe": float}
    """
    n = len(daily_returns)
    if n < n_splits * 5:
        return {
            "pbo": float("nan"),
            "note": f"데이터 부족 (필요: {n_splits * 5}일, 제공: {n}일)",
        }

    rng = np.random.default_rng(random_seed)
    splits = np.array_split(daily_returns, n_splits)
    half = n_splits // 2

    is_sharpes, oos_sharpes = [], []
    n_oos_underperform = 0

    for _ in range(n_trials):
        idx = rng.permutation(n_splits)
        is_idx = idx[:half]
        oos_idx = idx[half:]

        is_ret = pd.concat([splits[i] for i in is_idx])
        oos_ret = pd.concat([splits[i] for i in oos_idx])

        is_sr = compute_sharpe(is_ret, annual_rf_pct)
        oos_sr = compute_sharpe(oos_ret, annual_rf_pct)

        if np.isnan(is_sr) or np.isnan(oos_sr):
            continue

        is_sharpes.append(is_sr)
        oos_sharpes.append(oos_sr)
        if oos_sr < 0:
            n_oos_underperform += 1

    valid_trials = len(is_sharpes)
    pbo = n_oos_underperform / valid_trials if valid_trials > 0 else float("nan")

    return {
        "pbo": round(pbo, 4),
        "pbo_pct": round(pbo * 100, 2),
        "n_trials": valid_trials,
        "n_splits": n_splits,
        "mean_is_sharpe": round(float(np.mean(is_sharpes)), 3)
        if is_sharpes
        else float("nan"),
        "mean_oos_sharpe": round(float(np.mean(oos_sharpes)), 3)
        if oos_sharpes
        else float("nan"),
        "interpretation": (
            "과적합 의심 높음 (PBO>0.5)"
            if pbo > 0.5
            else "과적합 의심 낮음 (PBO≤0.5)"
            if not np.isnan(pbo)
            else "계산 불가"
        ),
    }
