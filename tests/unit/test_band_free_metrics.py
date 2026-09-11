"""±2% 밴드를 대표 지표에서 내린다.

`docs/SYSTEM_OVERVIEW.md` §15-2의 마지막 항목. win 정의가 "신호 방향으로 ±2% 이상
움직였는가"였는데, **±2% 라는 값에 근거가 없다.** 더 나쁜 건 horizon 이 길수록 넘기
쉬워진다는 점이다 — 14일 구간의 ±2% 는 7일 구간의 ±2% 보다 느슨하므로, horizon 을
바꾸면 '승률'이 지표 개선 없이도 올라간다 (실측: 7일 33.6% → 14일 39.1%).

대안은 임의 임계를 다른 임의 임계로 바꾸는 게 아니라, **이미 갖춘 것들로 보고**하는
것이다:
  - 방향 적중률 (부호만)
  - 시장 대비 초과수익 (#43)
  - 수익률 분포 (p25/median/p75)

밴드 집계는 버리지 않고 `band_outcome` 에 **임계값과 함께** 남긴다 — 큰 움직임만
세고 싶을 때 쓰되, 그 숫자가 임계에 의존한다는 사실이 같이 보이게 한다.
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from db import _CREATE_OUTCOMES_TABLE  # noqa: E402
from signal_tracker import OUTCOME_THRESHOLD_PCT, get_accuracy_stats  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "signals.db"
    conn = sqlite3.connect(path)
    conn.executescript(_CREATE_OUTCOMES_TABLE)
    conn.commit()
    conn.close()
    return str(path)


def _conn_for(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert(path, sid, *, ret, bench=None, signal_type="buy", ticker="PLTR",
            days_ago=20, source="scan_agent"):
    conn = sqlite3.connect(path)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source, issued_at, conviction,
            price_at_signal, return_14d, benchmark_return_14d, evaluated_at)
           VALUES (?, ?, ?, ?, ?, 8.0, 100.0, ?, ?, ?)""",
        (sid, ticker, signal_type, source,
         (NOW - timedelta(days=days_ago)).isoformat(), ret, bench, NOW.isoformat()),
    )
    conn.commit()
    conn.close()


def _stats(path, **kw):
    with patch("signal_tracker._get_conn", lambda: _conn_for(path)):
        return get_accuracy_stats(horizon=14, days_back=90, **kw)


# ── 대표 지표는 밴드에 의존하지 않는다 ────────────────────────────


def test_small_correct_moves_count_as_direction_hits(db):
    """±2% 안쪽이라도 방향은 맞았다 — 밴드는 그걸 'neutral' 로 버렸다."""
    for i, ret in enumerate([0.005, 0.008, 0.012, 0.015]):   # 전부 +0.5~1.5%
        _insert(db, f"s{i}", ret=ret, ticker=f"T{i}")

    stats = _stats(db)

    assert stats["direction_hit_rate_pct"] == 100.0     # 4건 전부 방향 적중
    assert stats["direction_sample"] == 4
    band = stats["band_outcome"]
    assert band["win"] == 0 and band["neutral"] == 4    # 밴드로는 전부 '중립'
    assert band["win_rate_pct"] == 0.0                  # 승률 0% 로 보였다


def test_band_outcome_carries_its_threshold(db):
    _insert(db, "a", ret=0.05)
    band = _stats(db)["band_outcome"]

    assert band["threshold_pct"] == OUTCOME_THRESHOLD_PCT
    assert "임의값" in band["note"]


def test_old_top_level_band_keys_are_gone(db):
    """이름만 봐서는 임계 의존을 알 수 없던 키는 없앴다."""
    _insert(db, "a", ret=0.05)
    stats = _stats(db)

    for legacy in ("win_rate_pct", "win_count", "loss_count", "neutral_count",
                   "win_rate_ci95"):
        assert legacy not in stats


def test_confidence_interval_is_computed_on_direction_hits(db):
    for i in range(6):
        _insert(db, f"h{i}", ret=0.01, ticker=f"T{i}", days_ago=20 + i * 15)

    stats = _stats(db)
    lo, hi = stats["direction_hit_ci95"]

    assert stats["direction_hit_rate_pct"] == 100.0
    assert lo > 0 and hi <= 100
    # 밴드 승률(0%)이 아니라 방향 적중률(100%)을 중심으로 잡힌다
    assert hi > 50


# ── 분포 보고 ─────────────────────────────────────────────────────


def test_distribution_is_reported_not_just_the_mean(db):
    """평균 하나로는 꼬리가 보이지 않는다."""
    for i, ret in enumerate([-0.10, 0.01, 0.02, 0.03, 0.20]):
        _insert(db, f"d{i}", ret=ret, ticker=f"T{i}")

    dist = _stats(db)["signed_return_dist"]

    assert dist["median"] == pytest.approx(2.0)        # 중앙값 +2%
    assert dist["p25"] < dist["median"] < dist["p75"]
    # 평균은 꼬리(+20%)에 끌려간다 — 중앙값과 다르다
    assert _stats(db)["avg_signed_return_pct"] != dist["median"]


def test_excess_distribution_is_reported_when_benchmark_exists(db):
    for i, (ret, bench) in enumerate([(0.05, 0.01), (0.02, 0.03), (0.10, 0.02)]):
        _insert(db, f"e{i}", ret=ret, bench=bench, ticker=f"T{i}")

    stats = _stats(db)

    assert stats["benchmark_sample"] == 3
    assert stats["excess_return_dist"]["median"] == pytest.approx(4.0)  # 5-1=4


def test_empty_sample_reports_zero_not_crash(db):
    stats = _stats(db)

    assert stats["direction_hit_rate_pct"] == 0.0
    assert stats["direction_sample"] == 0
    assert stats["signed_return_dist"] == {"p25": 0.0, "median": 0.0, "p75": 0.0}


# ── 하위 집계 ─────────────────────────────────────────────────────


def test_by_signal_and_bands_expose_both_views(db):
    _insert(db, "b1", ret=0.01, signal_type="buy", ticker="A")
    _insert(db, "s1", ret=-0.05, signal_type="sell", ticker="B")

    stats = _stats(db)

    assert stats["by_signal"]["buy"]["direction_hit_rate_pct"] == 100.0
    assert stats["by_signal"]["buy"]["band_outcome"]["win_rate_pct"] == 0.0
    assert stats["by_signal"]["sell"]["direction_hit_rate_pct"] == 100.0
    band_row = [b for b in stats["by_confidence_band"] if b["total"]][0]
    assert "direction_hit_rate_pct" in band_row and "band_win_rate_pct" in band_row


def test_calibrator_targets_direction_hits(db):
    """보정 대상은 '방향이 맞을 확률' — 임의 밴드가 보정값을 좌우하면 안 된다."""
    import signal_tracker as st

    for i in range(12):
        _insert(db, f"c{i}", ret=0.01, ticker=f"T{i}", days_ago=20 + i)

    with patch("signal_tracker._get_conn", lambda: _conn_for(db)):
        calib = st.ConfidenceCalibrator(horizon=14)
        calib.refit(days_back=90)

    # 밴드 기준이면 전부 '중립'이라 보정 근거가 없다. 방향 기준이면 100% 적중이다.
    assert calib.status()["total_samples"] == 12
