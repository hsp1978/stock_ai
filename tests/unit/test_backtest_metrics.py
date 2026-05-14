"""
백테스트 가정 명시 + rf 차감 지표 테스트 (Step 10)

테스트 시나리오:
- daily_returns sample → Sharpe rf 차감 정확성
- 강세장 fixture → Sortino > Sharpe (downside 작아서)
- 큰 drawdown 시나리오 → Calmar 감소
- 백테스트 결과 출력에 ANNUAL_RISK_FREE_RATE 명시
"""

import os
import sys
import math

import numpy as np
import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from backtest_metrics import (  # noqa: E402
    compute_sharpe,
    compute_sortino,
    compute_calmar,
    compute_max_dd,
    compute_all,
)


def _daily(annual_return: float, n: int = 252, seed: int = 42) -> pd.Series:
    """목표 연율 수익률 기반 더미 일별 수익률."""
    rng = np.random.default_rng(seed)
    daily_mean = annual_return / 252
    daily_std = 0.01
    return pd.Series(rng.normal(daily_mean, daily_std, n))


# ── compute_sharpe ───────────────────────────────────────────────────


def test_sharpe_rf_zero_matches_naive():
    """rf=0 → 기존 단순 Sharpe(mean/std*sqrt(252))와 동일."""
    ret = _daily(0.15)
    naive = float(ret.mean() / ret.std() * np.sqrt(252))
    result = compute_sharpe(ret, annual_rf_pct=0.0)
    assert abs(result - naive) < 1e-6


def test_sharpe_rf_reduces_ratio():
    """rf > 0 → rf=0 보다 Sharpe 낮아야 함 (수익 일부를 rf로 차감)."""
    ret = _daily(0.10)
    s0 = compute_sharpe(ret, 0.0)
    s4 = compute_sharpe(ret, 4.5)
    assert s4 < s0


def test_sharpe_zero_std_returns_nan():
    """표준편차=0 (완전 평탄) → nan 반환."""
    ret = pd.Series([0.001] * 100)
    result = compute_sharpe(ret, 0.0)
    assert math.isnan(result)


# ── compute_sortino ──────────────────────────────────────────────────


def test_sortino_gt_sharpe_bullish():
    """강세장 (대부분 양수 수익) → Sortino > Sharpe."""
    rng = np.random.default_rng(1)
    ret = pd.Series(np.abs(rng.normal(0.002, 0.005, 252)))  # 전부 양수
    s = compute_sharpe(ret, 3.5)
    so = compute_sortino(ret, 3.5)
    # 하방 거의 없으므로 Sortino >> Sharpe
    assert so > s


def test_sortino_no_downside_returns_inf():
    """손실 없으면 Sortino = inf."""
    ret = pd.Series([0.01] * 100)  # 항상 양수
    result = compute_sortino(ret, 0.0)
    assert result == float("inf")


# ── compute_max_dd ───────────────────────────────────────────────────


def test_max_dd_single_crash():
    """50% crash fixture → MaxDD ≈ -0.5."""
    ret = pd.Series([0.0] * 100 + [-0.5] + [0.0] * 50)
    dd = compute_max_dd(ret)
    assert dd < -0.3


def test_max_dd_all_positive_near_zero():
    """단조 증가 → MaxDD ≈ 0."""
    ret = pd.Series([0.001] * 252)
    dd = compute_max_dd(ret)
    assert dd >= -0.01


# ── compute_calmar ───────────────────────────────────────────────────


def test_calmar_large_dd_low_ratio():
    """큰 drawdown → Calmar 낮음."""
    rng = np.random.default_rng(99)
    ret_normal = pd.Series(rng.normal(0.0005, 0.01, 252))
    ret_crash = pd.Series(
        rng.normal(0.0005, 0.01, 200).tolist()
        + [-0.4]
        + rng.normal(0.0, 0.01, 51).tolist()
    )
    calmar_normal = compute_calmar(ret_normal)
    calmar_crash = compute_calmar(ret_crash)
    # 충돌 시 Calmar 낮아야 함
    assert calmar_crash < calmar_normal


# ── compute_all ──────────────────────────────────────────────────────


def test_compute_all_includes_assumptions():
    """compute_all 결과에 가정 메타 포함."""
    ret = _daily(0.10)
    result = compute_all(ret, annual_rf_pct=3.5, slippage_bps=5.0, commission_pct=0.015)
    assert "assumptions" in result
    assert result["assumptions"]["annual_rf_pct"] == 3.5
    assert result["assumptions"]["slippage_bps"] == 5.0


def test_compute_all_returns_all_metrics():
    """compute_all이 필수 지표를 모두 포함."""
    ret = _daily(0.10)
    result = compute_all(ret, annual_rf_pct=3.5)
    for key in (
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown",
        "win_rate",
        "total_trades",
    ):
        assert key in result, f"Missing key: {key}"


def test_compute_all_krx_tax_applied():
    """is_korean=True → KRX 거래세가 비용에 포함."""
    ret = _daily(0.15)
    r_kr = compute_all(ret, annual_rf_pct=3.5, is_korean=True)
    r_us = compute_all(ret, annual_rf_pct=4.5, is_korean=False)
    # 거래세 0.2% 추가로 한국 sharpe가 더 낮음
    assert r_kr["sharpe"] < r_us["sharpe"]
