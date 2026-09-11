"""보정 성능은 학습에 쓰지 않은 구간에서만 말할 수 있다.

`docs/SYSTEM_OVERVIEW.md` §15-2: `ece_after` 가 **학습 표본 그대로** 계산돼 늘 0에
가깝게 나왔다. 실측(2026-09-10 재학습): `ece_before 0.1989 → ece_after 0.0000`.
isotonic regression 은 학습 데이터를 계단 함수로 거의 완전히 맞출 수 있으므로 당연한
결과이고, 그 0을 개선폭으로 읽으면 '보정이 잘 되고 있다'는 착시가 된다.

여기서 고정하는 것:
  1. 개선폭은 **out-of-time 홀드아웃**에서 잰다 (과거 학습 → 미래 평가)
  2. 랜덤 분할이 아니다 — 시계열에서 랜덤 분할은 미래 정보를 학습에 흘린다
  3. 홀드아웃 표본이 모자라면 숫자를 만들지 않고 `insufficient` 라고 적는다
  4. 학습 표본으로 잰 값은 이름에 그 사실을 박는다 (`ece_after_in_sample`)
  5. 운영 보정기는 여전히 전체 표본으로 학습한다 (최신 정보 반영)
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from llm_calibrator import (  # noqa: E402
    HOLDOUT_FRACTION,
    MIN_HOLDOUT_SAMPLES,
    MIN_SAMPLES,
    LLMCalibrator,
)

NOW = datetime.now(timezone.utc)


def _make_db(tmp_path, n, *, informative=True, seed=7):
    """conviction 이 높을수록 적중률이 높은 표본 (informative=False 면 무관)."""
    from db import _CREATE_OUTCOMES_TABLE

    path = tmp_path / "calib.db"
    conn = sqlite3.connect(path)
    conn.executescript(_CREATE_OUTCOMES_TABLE)
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        conviction = float(rng.uniform(1, 9))
        p_hit = conviction / 10.0 if informative else 0.5
        ret = (
            float(rng.uniform(0.01, 0.05))
            if rng.random() < p_hit
            else float(rng.uniform(-0.05, -0.01))
        )
        rows.append((
            f"sig-{i}", f"T{i % 7}", "buy", "multi_agent_final",
            (NOW - timedelta(days=n - i)).isoformat(), conviction, 100.0,
            ret, NOW.isoformat(),
        ))
    conn.executemany(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source, issued_at, conviction,
            price_at_signal, return_7d, evaluated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()
    return str(path)


# ── 홀드아웃 분할 ─────────────────────────────────────────────────


def test_holdout_is_evaluated_out_of_time(tmp_path):
    db = _make_db(tmp_path, 200)
    result = LLMCalibrator(db_path=db, days_back=400).fit()

    holdout = result["holdout"]
    assert holdout["status"] == "evaluated"
    assert holdout["holdout_samples"] == pytest.approx(200 * HOLDOUT_FRACTION, abs=2)
    assert holdout["train_samples"] + holdout["holdout_samples"] == 200
    assert "시간순 분할" in holdout["detail"]
    # 홀드아웃 ECE 는 학습 표본 값과 다른 숫자다 (0으로 수렴하지 않는다)
    assert holdout["ece_after"] != result["ece_after_in_sample"]


def test_in_sample_ece_is_named_so_and_old_key_is_gone(tmp_path):
    """옛 `ece_after` 는 이름만 봐서는 학습 표본 값인 줄 알 수 없었다."""
    db = _make_db(tmp_path, 200)
    result = LLMCalibrator(db_path=db, days_back=400).fit()

    assert "ece_after" not in result
    assert "ece_improvement" not in result
    assert result["ece_after_in_sample"] < 0.05      # isotonic 특성상 거의 0
    assert result["ece_before"] > result["ece_after_in_sample"]


def test_insufficient_holdout_reports_instead_of_fabricating(tmp_path):
    """표본이 모자라면 개선폭을 만들어내지 않는다."""
    db = _make_db(tmp_path, MIN_SAMPLES + 5)
    result = LLMCalibrator(db_path=db, days_back=400).fit()

    holdout = result["holdout"]
    assert holdout["status"] == "insufficient"
    assert holdout["min_holdout"] == MIN_HOLDOUT_SAMPLES
    assert "말할 수 없다" in holdout["detail"]
    assert "ece_after" not in holdout               # 없는 숫자를 만들지 않는다
    # 그래도 운영 보정기는 학습된다 (전체 표본)
    assert result["status"] == "fitted"


def test_production_calibrator_uses_all_samples(tmp_path):
    db = _make_db(tmp_path, 200)
    calib = LLMCalibrator(db_path=db, days_back=400)
    result = calib.fit()

    assert result["n_samples"] == 200               # 홀드아웃만큼 줄지 않는다
    assert calib.calibrate(8.0) != 8.0 or calib.calibrate(2.0) != 2.0


def test_uninformative_data_shows_no_holdout_gain(tmp_path):
    """conviction 이 적중과 무관하면 홀드아웃 개선폭이 크지 않아야 한다.

    학습 표본으로 재면 이 경우에도 0에 가깝게 나온다 — 그게 문제였다.
    """
    db = _make_db(tmp_path, 300, informative=False)
    result = LLMCalibrator(db_path=db, days_back=400).fit()

    holdout = result["holdout"]
    assert holdout["status"] == "evaluated"
    assert result["ece_after_in_sample"] < 0.05          # 학습 표본: 거의 0
    assert holdout["ece_after"] > result["ece_after_in_sample"]  # 홀드아웃: 그렇지 않다


def test_status_exposes_holdout(tmp_path):
    db = _make_db(tmp_path, 200)
    calib = LLMCalibrator(db_path=db, days_back=400)
    calib.fit()
    status = calib.status()

    assert status["is_active"] is True
    assert status["holdout"]["status"] == "evaluated"
    assert status["ece_after_in_sample"] is not None
    assert "ece_after" not in status


def test_unfitted_status_says_not_evaluated(tmp_path):
    calib = LLMCalibrator(db_path=str(tmp_path / "missing.db"))
    status = calib.status()

    assert status["is_active"] is False
    assert status["holdout"]["status"] == "not_evaluated"
