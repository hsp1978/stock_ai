"""평가 horizon ↔ 의도 보유기간 정합.

`docs/SYSTEM_OVERVIEW.md` §15-2: 평가 horizon(7/14/30)이 임의값이고 **실제 보유기간과
연결돼 있지 않았다.** 스윙 스타일의 의도 보유기간은 10일인데 대표 지표는 7일에
채점됐다 — 10일 보유를 의도한 신호를 7일에 재면 그건 보유 도중의 중간 성과일 뿐이다.

보유기간이 세 곳에 흩어져 있던 것도 원인이다:
  entry_plan._HOLDING_DAYS_BY_STYLE (2/10/60)
  signal_tracker.HORIZONS           (7/14/30, 하드코딩 기본 7)
  decision_context                  (DECISION_HORIZON_DAYS, 기본 7)

여기서 고정하는 것:
  1. 보유기간의 단일 출처는 `config._STYLE_PRESETS[...]["holding_days"]`
  2. 대표 horizon 은 의도 보유기간을 **덮는** 가장 짧은 horizon
  3. 덮지 못하면(longterm 60일) 그 사실을 지표에 싣는다 — 조용히 넘어가지 않는다
  4. `DECISION_HORIZON_DAYS` 환경변수는 여전히 우선한다
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

import signal_tracker as st  # noqa: E402
from db import _CREATE_OUTCOMES_TABLE  # noqa: E402
from signal_tracker import (  # noqa: E402
    HORIZONS,
    expected_holding_days,
    get_accuracy_stats,
    primary_horizon_days,
)

NOW = datetime.now(timezone.utc)


# ── 단일 출처 ─────────────────────────────────────────────────────


def test_entry_plan_and_evaluator_read_the_same_holding_days():
    """보유기간이 두 곳에 복제돼 있으면 정합이 깨진다."""
    from config import _STYLE_PRESETS
    from entry_plan import _HOLDING_DAYS_BY_STYLE

    for style, preset in _STYLE_PRESETS.items():
        assert _HOLDING_DAYS_BY_STYLE[style] == preset["holding_days"]

    from config import EXPECTED_HOLDING_DAYS, TRADING_STYLE

    assert expected_holding_days() == EXPECTED_HOLDING_DAYS
    assert EXPECTED_HOLDING_DAYS == _STYLE_PRESETS[TRADING_STYLE]["holding_days"]


# ── 대표 horizon 선택 ─────────────────────────────────────────────


def test_primary_horizon_covers_the_intended_holding_period():
    assert primary_horizon_days(2) == 7        # scalping → 7일로 덮인다
    assert primary_horizon_days(7) == 7        # 경계값은 그대로
    assert primary_horizon_days(10) == 14      # swing 10일 → 7일이 아니라 14일
    assert primary_horizon_days(14) == 14
    assert primary_horizon_days(20) == 30


def test_horizon_longer_than_any_available_falls_back_to_max():
    """longterm 60일은 어떤 horizon 으로도 덮지 못한다 — 최댓값을 쓰되 숨기지 않는다."""
    assert primary_horizon_days(60) == max(HORIZONS) == 30


# ── 통계 payload ──────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "signals.db"
    conn = sqlite3.connect(path)
    conn.executescript(_CREATE_OUTCOMES_TABLE)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source, issued_at, conviction,
            price_at_signal, return_7d, return_14d, evaluated_at)
           VALUES ('s1', 'PLTR', 'buy', 'scan_agent', ?, 8.0, 100.0, 0.03, 0.05, ?)""",
        ((NOW - timedelta(days=20)).isoformat(), NOW.isoformat()),
    )
    conn.commit()
    conn.close()
    return str(path)


def _conn_for(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_stats_default_horizon_is_derived_not_hardcoded_seven(db):
    with (
        patch("signal_tracker._get_conn", lambda: _conn_for(db)),
        patch("signal_tracker.expected_holding_days", lambda: 10),
    ):
        stats = get_accuracy_stats(days_back=90)

    assert stats["horizon_days"] == 14              # 10일 보유 → 14일 평가
    assert stats["expected_holding_days"] == 10
    assert stats["horizon_covers_holding"] is True
    assert stats["avg_signed_return_pct"] == 5.0    # return_14d 를 썼다


def test_stats_flag_when_horizon_cannot_cover_holding(db):
    with (
        patch("signal_tracker._get_conn", lambda: _conn_for(db)),
        patch("signal_tracker.expected_holding_days", lambda: 60),
    ):
        stats = get_accuracy_stats(days_back=90)

    assert stats["horizon_days"] == 30
    assert stats["expected_holding_days"] == 60
    assert stats["horizon_covers_holding"] is False   # 조용히 넘어가지 않는다


def test_explicit_horizon_still_wins(db):
    with (
        patch("signal_tracker._get_conn", lambda: _conn_for(db)),
        patch("signal_tracker.expected_holding_days", lambda: 10),
    ):
        stats = get_accuracy_stats(horizon=7, days_back=90)

    assert stats["horizon_days"] == 7
    assert stats["primary_horizon_days"] == 14        # 대표값은 따로 보고한다
    assert stats["horizon_covers_holding"] is False


def test_invalid_horizon_falls_back_to_primary(db):
    with (
        patch("signal_tracker._get_conn", lambda: _conn_for(db)),
        patch("signal_tracker.expected_holding_days", lambda: 10),
    ):
        stats = get_accuracy_stats(horizon=9, days_back=90)

    assert stats["horizon_days"] == 14


# ── decision_context ──────────────────────────────────────────────


def test_decision_horizon_derives_from_style():
    from decision_context import default_horizon_days

    with (
        patch.dict(os.environ, {}, clear=False),
        patch("signal_tracker.expected_holding_days", lambda: 10),
    ):
        os.environ.pop("DECISION_HORIZON_DAYS", None)
        assert default_horizon_days() == 14


def test_env_override_still_wins():
    from decision_context import default_horizon_days

    with patch.dict(os.environ, {"DECISION_HORIZON_DAYS": "21"}):
        assert default_horizon_days() == 21

    # 잘못된 값은 무시하고 파생값으로 돌아간다
    with (
        patch.dict(os.environ, {"DECISION_HORIZON_DAYS": "abc"}),
        patch("signal_tracker.expected_holding_days", lambda: 2),
    ):
        assert default_horizon_days() == 7


def test_calibrator_uses_primary_horizon():
    calib = st.ConfidenceCalibrator()
    assert calib.horizon == primary_horizon_days()
