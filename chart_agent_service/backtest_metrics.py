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
