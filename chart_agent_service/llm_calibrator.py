"""
LLM Confidence Calibration — ECE + Isotonic Regression (P2).

signal_outcomes 테이블에서 과거 데이터를 읽어
LLM이 출력하는 conviction(0-10)을 실제 적중률에 맞게 보정한다.

workflow:
1. load_outcomes()       → (conviction, hit) pairs
2. compute_ece()         → 보정 전 ECE
3. fit()                 → isotonic regression 학습
4. calibrate(conviction) → 보정된 confidence 반환 (0-10 스케일)
5. compute_ece_after()   → 보정 후 ECE 비교

최소 MIN_SAMPLES 이상 accumulated 된 후에만 active.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_SAMPLES = 30  # 학습 최소 샘플 수


class LLMCalibrator:
    """
    Isotonic Regression 기반 LLM conviction 보정기.

    사용:
        calib = LLMCalibrator()
        calib.fit()
        adjusted = calib.calibrate(raw_conviction=7.5)
    """

    def __init__(self, db_path: Optional[str] = None, days_back: int = 90) -> None:
        if db_path is None:
            from config import OUTPUT_DIR

            db_path = os.path.join(OUTPUT_DIR, "scan_log.db")
        self._db_path = db_path
        self._days_back = days_back
        self._calibrator = None  # sklearn IsotonicRegression
        self._is_fitted = False
        self._n_samples = 0
        self._ece_before: Optional[float] = None
        self._ece_after: Optional[float] = None
        self._fitted_at: Optional[str] = None

    # ── 데이터 로드 ───────────────────────────────────────────────────

    def load_outcomes(self) -> pd.DataFrame:
        """signal_outcomes에서 (conviction, hit_7d) 페어를 로드한다."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self._days_back)
        ).isoformat()
        conn = sqlite3.connect(self._db_path)
        try:
            df = pd.read_sql_query(
                """SELECT conviction, return_7d
                   FROM signal_outcomes
                   WHERE evaluated_at IS NOT NULL
                     AND return_7d IS NOT NULL
                     AND conviction IS NOT NULL
                     AND issued_at >= ?""",
                conn,
                params=(cutoff,),
            )
        except Exception as exc:
            logger.warning("load_outcomes 실패: %s", exc)
            df = pd.DataFrame()
        finally:
            conn.close()
        if not df.empty:
            df["hit"] = (df["return_7d"] > 0).astype(float)
        return df

    # ── ECE 계산 ──────────────────────────────────────────────────────

    @staticmethod
    def _compute_ece(
        convictions: np.ndarray, hits: np.ndarray, n_bins: int = 10
    ) -> float:
        """ECE 계산 (conviction은 0-10 스케일 → 0-1 정규화)."""
        if len(convictions) == 0:
            return float("nan")
        conf_norm = convictions / 10.0
        bins = np.linspace(0, 1, n_bins + 1)
        ece = 0.0
        n_total = len(convictions)
        for i in range(n_bins):
            mask = (conf_norm >= bins[i]) & (conf_norm < bins[i + 1])
            if i == n_bins - 1:
                mask = (conf_norm >= bins[i]) & (conf_norm <= bins[i + 1])
            if mask.sum() == 0:
                continue
            avg_conf = float(conf_norm[mask].mean())
            acc = float(hits[mask].mean())
            ece += mask.sum() / n_total * abs(avg_conf - acc)
        return float(ece)

    # ── 학습 ─────────────────────────────────────────────────────────

    def fit(self) -> dict:
        """
        isotonic regression을 학습한다.

        Returns:
            {"status": str, "n_samples": int, "ece_before": float, "ece_after": float}
        """
        from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]

        df = self.load_outcomes()
        if df.empty or len(df) < MIN_SAMPLES:
            self._is_fitted = False
            return {
                "status": "insufficient_data",
                "n_samples": len(df),
                "required": MIN_SAMPLES,
                "ece_before": None,
                "ece_after": None,
            }

        X = df["conviction"].to_numpy(dtype=float)
        y = df["hit"].to_numpy(dtype=float)

        # ECE before
        self._ece_before = self._compute_ece(X, y)

        # Isotonic regression (conviction 0-10 → calibrated 0-1)
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(X / 10.0, y)  # 입력을 0-1로 정규화
        self._calibrator = iso
        self._is_fitted = True
        self._n_samples = len(df)
        self._fitted_at = datetime.now(timezone.utc).isoformat()

        # ECE after
        y_pred = iso.predict(X / 10.0)
        self._ece_after = self._compute_ece(y_pred * 10.0, y)  # 다시 0-10 스케일로

        logger.info(
            "LLMCalibrator fitted: n=%d, ECE before=%.4f, after=%.4f",
            self._n_samples,
            self._ece_before or 0,
            self._ece_after or 0,
        )

        return {
            "status": "fitted",
            "n_samples": self._n_samples,
            "ece_before": round(self._ece_before or 0, 4),
            "ece_after": round(self._ece_after or 0, 4),
            "ece_improvement": round(
                (self._ece_before or 0) - (self._ece_after or 0), 4
            ),
            "fitted_at": self._fitted_at,
        }

    # ── 보정 ─────────────────────────────────────────────────────────

    def calibrate(self, raw_conviction: float) -> float:
        """
        raw_conviction(0-10)을 isotonic regression으로 보정해 반환한다.

        학습되지 않은 상태이면 raw_conviction 그대로 반환.
        """
        if not self._is_fitted or self._calibrator is None:
            return raw_conviction

        clamped = max(0.0, min(10.0, raw_conviction))
        # calibrator는 0-1 스케일 입력을 기대
        calibrated_prob = float(self._calibrator.predict([[clamped / 10.0]])[0])
        # 0-1 확률 → 0-10 스케일 변환 (선형)
        return round(calibrated_prob * 10.0, 3)

    def status(self) -> dict:
        return {
            "is_active": self._is_fitted,
            "n_samples": self._n_samples,
            "min_required": MIN_SAMPLES,
            "ece_before": self._ece_before,
            "ece_after": self._ece_after,
            "fitted_at": self._fitted_at,
        }


# ── 모듈 수준 싱글톤 ─────────────────────────────────────────────────

_global_calibrator: LLMCalibrator | None = None


def get_calibrator(db_path: Optional[str] = None) -> LLMCalibrator:
    global _global_calibrator
    if _global_calibrator is None:
        _global_calibrator = LLMCalibrator(db_path=db_path)
    return _global_calibrator


def reset_calibrator() -> None:
    global _global_calibrator
    _global_calibrator = None
