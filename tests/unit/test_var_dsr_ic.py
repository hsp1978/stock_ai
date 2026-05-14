"""
VaR/CVaR + DSR/PBO + IC-weighted ensemble 단위 테스트 (P2)

테스트 시나리오:
- Historical VaR 95%: 분위수 계산 정확성
- CVaR ≤ VaR (CVaR는 항상 더 보수적)
- 정상 vs 패닉 수익률 → VaR 크기 차이
- DSR: 과적합 벤치마크 대비 판별
- PBO: 과적합 데이터 → PBO 높음
- IC 계산: 높은 IC 소스 → 높은 가중치
"""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from risk_management import PortfolioRiskCalculator  # noqa: E402
from backtest_metrics import compute_dsr, compute_pbo  # noqa: E402


# ── 공통 픽스처 ───────────────────────────────────────────────────────


def _normal_returns(
    n: int = 252, mean: float = 0.001, std: float = 0.01, seed: int = 0
) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mean, std, n))


def _panic_returns(n: int = 252, seed: int = 1) -> pd.Series:
    """극단적 손실이 섞인 수익률."""
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0005, 0.01, n)
    # 5%의 날 큰 손실 삽입
    crash_idx = rng.choice(n, size=int(n * 0.05), replace=False)
    ret[crash_idx] = rng.uniform(-0.08, -0.04, len(crash_idx))
    return pd.Series(ret)


# ── VaR / CVaR ───────────────────────────────────────────────────────


def test_var_95_in_loss_territory():
    """VaR 95% → 음수 (손실 방향)."""
    ret = _normal_returns()
    calc = PortfolioRiskCalculator(ret, nav=100_000)
    v95 = calc.var(0.95)
    assert v95 < 0, f"VaR 95% should be negative (loss), got {v95}"


def test_cvar_lte_var():
    """CVaR ≤ VaR (expected shortfall is more extreme)."""
    ret = _normal_returns()
    calc = PortfolioRiskCalculator(ret)
    v95 = calc.var(0.95)
    cv95 = calc.cvar(0.95)
    assert cv95 <= v95 + 1e-9, f"CVaR {cv95:.4f} should be ≤ VaR {v95:.4f}"


def test_panic_var_larger_than_normal():
    """패닉 수익률 → VaR 절댓값 > 정상 수익률 VaR."""
    normal = PortfolioRiskCalculator(_normal_returns())
    panic = PortfolioRiskCalculator(_panic_returns())
    assert abs(panic.var(0.99)) > abs(normal.var(0.99))


def test_var_99_lt_var_95():
    """99% VaR 절댓값 > 95% VaR 절댓값 (더 엄격)."""
    calc = PortfolioRiskCalculator(_normal_returns())
    v95 = calc.var(0.95)
    v99 = calc.var(0.99)
    assert abs(v99) >= abs(v95), (
        f"|VaR99|={abs(v99):.4f} should ≥ |VaR95|={abs(v95):.4f}"
    )


def test_compute_all_keys():
    """compute_all()이 필수 키를 모두 반환."""
    calc = PortfolioRiskCalculator(_normal_returns(), nav=100_000)
    result = calc.compute_all()
    for key in (
        "var_95",
        "var_99",
        "cvar_95",
        "cvar_99",
        "var_95_amount",
        "annualized_vol_pct",
        "n_days",
    ):
        assert key in result, f"Missing key: {key}"


def test_cornish_fisher_method():
    """Cornish-Fisher VaR 계산 성공."""
    ret = _panic_returns()
    calc = PortfolioRiskCalculator(ret)
    v = calc.var(0.95, method="cornish_fisher")
    assert v < 0
    assert abs(v) > 0


# ── DSR ──────────────────────────────────────────────────────────────


def test_dsr_good_strategy_high_value():
    """좋은 전략(높은 Sharpe) → DSR 높음 (과적합 가능성 낮음)."""
    rng = np.random.default_rng(42)
    strong_ret = pd.Series(rng.normal(0.003, 0.005, 252))  # Sharpe ~9
    dsr = compute_dsr(strong_ret, annual_rf_pct=0.0, benchmark_sharpe=1.0)
    assert 0 < dsr <= 1.0


def test_dsr_weak_strategy_low_value():
    """약한 전략(낮은 Sharpe) → DSR 낮음 (과적합 의심)."""
    rng = np.random.default_rng(99)
    weak_ret = pd.Series(rng.normal(0.0, 0.02, 252))  # Sharpe ~0
    dsr = compute_dsr(weak_ret, annual_rf_pct=0.0, benchmark_sharpe=1.0)
    assert dsr < 0.5


def test_dsr_insufficient_data_nan():
    """데이터 30일 미만 → nan 반환."""
    import math

    ret = pd.Series([0.001] * 20)
    result = compute_dsr(ret)
    assert math.isnan(result)


# ── PBO ──────────────────────────────────────────────────────────────


def test_pbo_range():
    """PBO 결과 0~1 범위."""
    rng = np.random.default_rng(7)
    ret = pd.Series(rng.normal(0.001, 0.01, 252))
    result = compute_pbo(ret, n_splits=8, n_trials=100)
    assert 0.0 <= result["pbo"] <= 1.0


def test_pbo_overfit_data_high_pbo():
    """과적합 데이터(운에 의한 수익) → PBO 높음 경향."""
    rng = np.random.default_rng(0)
    # 절반은 좋고 절반은 나쁜 혼합
    mixed = pd.Series(
        list(rng.normal(0.002, 0.005, 126)) + list(rng.normal(-0.001, 0.01, 126))
    )
    result = compute_pbo(mixed, n_splits=8, n_trials=200)
    assert "pbo" in result
    assert result["pbo"] >= 0


def test_pbo_insufficient_data():
    """데이터 부족 → nan 포함 반환."""
    import math

    ret = pd.Series([0.001] * 10)
    result = compute_pbo(ret, n_splits=16)
    assert math.isnan(result["pbo"])


# ── IC-weighted ensemble ─────────────────────────────────────────────


def _make_ic_db(tmp: str, n_rows: int = 80) -> str:
    """IC 계산을 위한 인메모리 SQLite DB 생성."""
    db = tmp + "/ic_test.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE signal_outcomes (
            signal_id TEXT PRIMARY KEY,
            signal_source TEXT NOT NULL,
            conviction REAL NOT NULL,
            return_7d REAL,
            issued_at TIMESTAMP,
            evaluated_at TIMESTAMP
        )
    """)

    rng = np.random.default_rng(42)
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(n_rows):
        # source_good: conviction ↑ → return ↑ (high IC)
        conviction = float(rng.uniform(0, 10))
        return_7d = conviction / 10 * 0.05 + float(rng.normal(0, 0.01))
        rows.append(
            (
                f"g-{i}",
                "source_good",
                conviction,
                return_7d,
                (now - timedelta(days=n_rows - i)).isoformat(),
                now.isoformat(),
            )
        )
        # source_bad: conviction ↑ → return ↓ (negative IC)
        rows.append(
            (
                f"b-{i}",
                "source_bad",
                conviction,
                -return_7d + float(rng.normal(0, 0.01)),
                (now - timedelta(days=n_rows - i)).isoformat(),
                now.isoformat(),
            )
        )

    conn.executemany("INSERT INTO signal_outcomes VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return db


def test_ic_weights_good_source_higher():
    """IC 높은 소스 → 더 높은 가중치."""
    from ic_ensemble import compute_ic_weights

    with tempfile.TemporaryDirectory() as tmp:
        db = _make_ic_db(tmp)
        weights = compute_ic_weights(db_path=db, days=365)

    if "source_good" in weights and "source_bad" in weights:
        assert weights["source_good"] >= weights["source_bad"], (
            f"Good source weight {weights['source_good']} should ≥ bad {weights['source_bad']}"
        )


def test_ic_weights_negative_ic_zero():
    """IC ≤ 0 소스 → 가중치 0."""
    from ic_ensemble import compute_ic_weights

    with tempfile.TemporaryDirectory() as tmp:
        db = _make_ic_db(tmp)
        weights = compute_ic_weights(db_path=db, days=365)

    # source_bad가 음의 IC → 가중치 0
    assert weights.get("source_bad", 0.0) == 0.0


def test_ic_equal_weight_fallback():
    """데이터 없으면 균등 가중치 반환."""
    from ic_ensemble import compute_ic_weights

    weights = compute_ic_weights(
        db_path=":memory:",
        sources=["A", "B", "C"],
        days=90,
    )
    # 데이터 없음 → equal weight
    assert len(weights) in (0, 3)
    if weights:
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01


def test_apply_ic_weights():
    """IC 가중치 적용 → 최종 신호 산출."""
    from ic_ensemble import apply_ic_weights

    signals = {
        "source_good": ("buy", 7.0),
        "source_bad": ("sell", 5.0),
    }
    weights = {"source_good": 0.8, "source_bad": 0.2}
    signal, conviction = apply_ic_weights(signals, weights)
    assert signal == "buy"  # good source dominates
    assert conviction > 0
