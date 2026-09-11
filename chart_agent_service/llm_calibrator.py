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

# 홀드아웃 — 학습 표본으로 평가한 ECE 는 isotonic 특성상 거의 0이 나온다.
# 개선폭을 그대로 믿으면 '보정이 잘 되고 있다'는 착시가 된다 (2026-09 진단:
# ece_before 0.1989 → ece_after 0.0000). 시계열이므로 **과거로 학습해 미래로
# 평가**한다(out-of-time). 랜덤 분할은 미래 정보를 학습에 흘린다.
HOLDOUT_FRACTION = 0.3
MIN_HOLDOUT_SAMPLES = 20


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
        self._ece_after_in_sample: Optional[float] = None
        self._holdout: dict = {"status": "not_evaluated"}
        self._fitted_at: Optional[str] = None

    # ── 데이터 로드 ───────────────────────────────────────────────────

    def load_outcomes(self) -> pd.DataFrame:
        """signal_outcomes에서 (conviction, hit_7d) 페어를 로드한다."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self._days_back)
        ).isoformat()
        conn = sqlite3.connect(self._db_path)
        try:
            # (종목, 소스, 발행일)당 1행 — 30분 스캔의 하루 48회 반복을 접는다.
            # 접지 않으면 isotonic 이 반복 기록된 종목·날짜에 과적합되고 ECE 가
            # 실제보다 좋게 나온다 (2026-09-10 표본 독립성 진단).
            df = pd.read_sql_query(
                """WITH ranked AS (
                       SELECT conviction, return_7d, signal_type, issued_at,
                              ROW_NUMBER() OVER (
                                  PARTITION BY ticker, signal_source,
                                               substr(issued_at, 1, 10)
                                  ORDER BY issued_at DESC
                              ) AS rn
                       FROM signal_outcomes
                       WHERE evaluated_at IS NOT NULL
                         AND return_7d IS NOT NULL
                         AND conviction IS NOT NULL
                         AND issued_at >= ?
                   )
                   SELECT conviction, return_7d, signal_type, issued_at
                   FROM ranked WHERE rn = 1
                   ORDER BY issued_at ASC""",
                conn,
                params=(cutoff,),
            )
        except Exception as exc:
            logger.warning("load_outcomes 실패: %s", exc)
            df = pd.DataFrame()
        finally:
            conn.close()
        if not df.empty:
            # hit 을 `return_7d > 0` 으로 두면 **매도 신호는 맞을 때마다 오답**으로
            # 라벨링된다. 표본의 약 44%가 매도라 isotonic 이 반대 방향으로 학습됐다
            # (2026-09-10 방향 보정 감사). 방향 보정 수익률로 판정한다.
            from signal_tracker import signed_return

            signed = df.apply(
                lambda r: signed_return(r.get("signal_type"), r["return_7d"]), axis=1
            )
            # 방향이 없는 neutral 은 학습 대상이 아니다 (부호를 붙일 수 없다).
            df = df.assign(signed_return=signed).dropna(subset=["signed_return"])
            df["hit"] = (df["signed_return"] > 0).astype(float)
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
                "ece_after_in_sample": None,
                "holdout": {"status": "not_evaluated"},
            }

        X = df["conviction"].to_numpy(dtype=float)
        y = df["hit"].to_numpy(dtype=float)

        # 보정 전 ECE — 학습이 개입하지 않으므로 전체 표본으로 재도 정직하다.
        self._ece_before = self._compute_ece(X, y)

        # ── 홀드아웃 평가 (out-of-time) ─────────────────────────────
        # 개선폭은 **학습에 쓰지 않은 구간**에서만 의미가 있다.
        self._holdout = self._evaluate_holdout(X, y)

        # ── 운영용 보정기는 전체 표본으로 학습한다 ──────────────────
        # (최신 정보까지 반영해야 하므로. 성능 보고는 위 홀드아웃 값을 쓴다.)
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(X / 10.0, y)
        self._calibrator = iso
        self._is_fitted = True
        self._n_samples = len(df)
        self._fitted_at = datetime.now(timezone.utc).isoformat()

        # 학습 표본으로 잰 ECE — isotonic 특성상 거의 0이다. 이름에 그 사실을 박아
        # 성능 지표로 오독되지 않게 한다.
        y_pred = iso.predict(X / 10.0)
        self._ece_after_in_sample = self._compute_ece(y_pred * 10.0, y)

        logger.info(
            "LLMCalibrator fitted: n=%d, ECE before=%.4f, in-sample after=%.4f, "
            "holdout=%s",
            self._n_samples,
            self._ece_before or 0,
            self._ece_after_in_sample or 0,
            self._holdout.get("status"),
        )

        return {
            "status": "fitted",
            "n_samples": self._n_samples,
            "ece_before": round(self._ece_before or 0, 4),
            # 옛 `ece_after` 키는 없앴다 — 학습 표본으로 잰 값이라 항상 0에 가까웠고,
            # 이름만 봐서는 그 사실을 알 수 없었다 (avg_return_pct 와 같은 이유).
            "ece_after_in_sample": round(self._ece_after_in_sample or 0, 4),
            "holdout": self._holdout,
            "fitted_at": self._fitted_at,
        }

    def _evaluate_holdout(self, X, y) -> dict:
        """과거로 학습해 미래로 평가한다(out-of-time). 표본이 모자라면 그렇다고 적는다."""
        from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]

        n = len(X)
        split = int(n * (1 - HOLDOUT_FRACTION))
        train_n, test_n = split, n - split
        if train_n < MIN_SAMPLES or test_n < MIN_HOLDOUT_SAMPLES:
            return {
                "status": "insufficient",
                "train_samples": train_n,
                "holdout_samples": test_n,
                "min_train": MIN_SAMPLES,
                "min_holdout": MIN_HOLDOUT_SAMPLES,
                "detail": "홀드아웃 표본 부족 — 개선폭을 말할 수 없다",
            }

        X_train, y_train = X[:split], y[:split]
        X_test, y_test = X[split:], y[split:]

        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(X_train / 10.0, y_train)
        before = self._compute_ece(X_test, y_test)
        after = self._compute_ece(iso.predict(X_test / 10.0) * 10.0, y_test)
        return {
            "status": "evaluated",
            "train_samples": train_n,
            "holdout_samples": test_n,
            "ece_before": round(before, 4),
            "ece_after": round(after, 4),
            "improvement": round(before - after, 4),
            "detail": "시간순 분할 — 과거 학습, 미래 평가",
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
            "ece_after_in_sample": self._ece_after_in_sample,
            "holdout": self._holdout,
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
