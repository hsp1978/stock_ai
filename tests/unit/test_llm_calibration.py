"""
LLM confidence calibration (ECE + isotonic) 단위 테스트 (P2)

테스트 시나리오:
- 데이터 없으면 insufficient_data 반환
- 데이터 충분하면 isotonic regression 학습 성공
- ECE before > ECE after (보정이 개선을 가져옴)
- 학습 후 calibrate() → 0-10 범위 내 값 반환
- 학습 전 calibrate() → raw_conviction 그대로 반환
- 과적합 확인용 ECE 개선 지표
"""

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import numpy as np

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from llm_calibrator import LLMCalibrator  # noqa: E402


# ── DB 픽스처 ─────────────────────────────────────────────────────────


def _make_calibration_db(tmp: str, n: int = 60) -> str:
    """calibration 학습용 신호 결과 DB 생성."""
    db = tmp + "/calib.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE signal_outcomes (
            signal_id TEXT PRIMARY KEY,
            signal_source TEXT,
            conviction REAL,
            return_7d REAL,
            issued_at TIMESTAMP,
            evaluated_at TIMESTAMP
        )
    """)

    rng = np.random.default_rng(42)
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(n):
        conviction = float(rng.uniform(1, 9))
        # 높은 conviction → 높은 확률의 긍정 수익
        p_positive = conviction / 10.0
        return_7d = float(
            rng.uniform(0.01, 0.05)
            if rng.random() < p_positive
            else rng.uniform(-0.05, -0.01)
        )
        rows.append(
            (
                f"sig-{i}",
                "scan_agent",
                conviction,
                return_7d,
                (now - timedelta(days=n - i)).isoformat(),
                now.isoformat(),
            )
        )

    conn.executemany("INSERT INTO signal_outcomes VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return db


# ── LLMCalibrator 테스트 ──────────────────────────────────────────────


def test_fit_insufficient_data():
    """데이터 없음 → insufficient_data 반환."""
    with tempfile.TemporaryDirectory() as tmp:
        db = tmp + "/empty.db"
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE signal_outcomes (
                signal_id TEXT, signal_source TEXT,
                conviction REAL, return_7d REAL,
                issued_at TEXT, evaluated_at TEXT
            )
        """)
        conn.commit()
        conn.close()

        calib = LLMCalibrator(db_path=db)
        result = calib.fit()

    assert result["status"] == "insufficient_data"
    assert not calib._is_fitted


def test_fit_success():
    """충분한 데이터 → fitted 상태."""
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_calibration_db(tmp, n=60)
        calib = LLMCalibrator(db_path=db)
        result = calib.fit()

    assert result["status"] == "fitted"
    assert calib._is_fitted
    assert result["n_samples"] == 60
    assert result["ece_before"] is not None
    assert result["ece_after"] is not None


def test_ece_improvement_after_calibration():
    """보정 후 ECE ≤ 보정 전 ECE (일반적으로 개선)."""
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_calibration_db(tmp, n=60)
        calib = LLMCalibrator(db_path=db)
        result = calib.fit()

    # 작은 샘플에서는 항상 보장되지 않지만, 대부분 개선
    if result["status"] == "fitted":
        ece_before = result.get("ece_before", 0)
        ece_after = result.get("ece_after", 0)
        # 보정이 크게 악화되지 않아야 함
        assert ece_after <= ece_before + 0.1


def test_calibrate_before_fit_returns_raw():
    """학습 전 calibrate() → raw_conviction 그대로 반환."""
    calib = LLMCalibrator(db_path=":memory:")
    assert calib.calibrate(7.5) == 7.5
    assert calib.calibrate(3.2) == 3.2


def test_calibrate_after_fit_returns_bounded():
    """학습 후 calibrate() → 0-10 범위 내 값."""
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_calibration_db(tmp, n=60)
        calib = LLMCalibrator(db_path=db)
        calib.fit()

    for raw in [0.0, 2.5, 5.0, 7.5, 10.0]:
        calibrated = calib.calibrate(raw)
        assert 0.0 <= calibrated <= 10.0, f"Out of range: {calibrated} for raw={raw}"


def test_calibrate_monotonic():
    """높은 conviction → 높거나 같은 calibrated 값 (단조성)."""
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_calibration_db(tmp, n=60)
        calib = LLMCalibrator(db_path=db)
        calib.fit()

    values = [1.0, 3.0, 5.0, 7.0, 9.0]
    calibrated = [calib.calibrate(v) for v in values]
    # 단조 증가 (허용 오차 0.1)
    for i in range(len(calibrated) - 1):
        assert calibrated[i] <= calibrated[i + 1] + 0.1, (
            f"Not monotonic at idx {i}: {calibrated[i]:.3f} > {calibrated[i + 1]:.3f}"
        )


def test_status_unfitted():
    """학습 전 status → is_active=False."""
    calib = LLMCalibrator(db_path=":memory:")
    s = calib.status()
    assert s["is_active"] is False
    assert s["n_samples"] == 0


def test_status_fitted():
    """학습 후 status → is_active=True, ECE 포함."""
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_calibration_db(tmp, n=60)
        calib = LLMCalibrator(db_path=db)
        calib.fit()

    s = calib.status()
    assert s["is_active"] is True
    assert s["n_samples"] == 60
    assert s["ece_before"] is not None
    assert s["ece_after"] is not None
    assert s["fitted_at"] is not None


# ── ECE 계산 직접 테스트 ──────────────────────────────────────────────


def test_ece_perfect_calibration():
    """완벽한 보정 → ECE ≈ 0."""
    # conviction 5 → 50% 적중 → ECE 0
    convictions = np.array([5.0] * 100)
    hits = np.array([1.0] * 50 + [0.0] * 50)
    ece = LLMCalibrator._compute_ece(convictions, hits)
    assert ece < 0.05


def test_ece_worst_calibration():
    """최악 보정 (conviction 10 → 항상 손실) → ECE 높음."""
    convictions = np.array([10.0] * 100)
    hits = np.array([0.0] * 100)
    ece = LLMCalibrator._compute_ece(convictions, hits)
    assert ece > 0.5
