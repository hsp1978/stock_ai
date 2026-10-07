"""통계 조회 범위 — 현재 로직 구간과 무효 창을 섞지 않는다.

2026-10-07: Signal Accuracy 화면 기본값(최근 180일)이 현재 로직 시작일(08-06) 이전의
무효 창 909건(−3.56%)을 섞어, 현재 로직 −0.58% 를 −2.21% 로 보이게 했다 (14일,
ticker_day). 발행일 범위(since/until)로 끊을 수 있어야 한다.
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

import signal_tracker  # noqa: E402
from db import _CREATE_OUTCOMES_TABLE as _SCHEMA  # noqa: E402


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "signals.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return str(path)


def _conn_for(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert(path, sid, issued: datetime, ret: float, signal_type="buy"):
    conn = sqlite3.connect(path)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source, issued_at, conviction,
            price_at_signal, return_7d, return_14d, return_30d, evaluated_at)
           VALUES (?, 'PLTR', ?, 'multi_agent_final', ?, 7.0, 100.0, ?, ?, ?, ?)""",
        (sid, signal_type, issued.isoformat(), ret, ret, ret, issued.isoformat()),
    )
    conn.commit()
    conn.close()


def _stats(path, **kw):
    with patch("signal_tracker._get_conn", lambda: _conn_for(path)):
        return signal_tracker.get_accuracy_stats(horizon=14, **kw)


def _seed(db):
    """구 로직 3일(−5%), 현재 로직 2일(+1%)."""
    start = datetime.fromisoformat(signal_tracker.CURRENT_LOGIC_START).replace(tzinfo=timezone.utc)
    for i in range(3):
        _insert(db, f"old{i}", start - timedelta(days=i + 1, hours=-12), -0.05)
    for i in range(2):
        _insert(db, f"new{i}", start + timedelta(days=i, hours=12), 0.01)
    return start


def test_since_limits_to_current_logic(db):
    start = _seed(db)
    s = _stats(db, since=start.date().isoformat(), days_back=3650)
    assert s["total_evaluated"] == 2
    assert s["avg_signed_return_pct"] == pytest.approx(1.0)
    assert s["window_includes_pre_logic"] is False
    assert s["window"]["days_back"] is None


def test_until_isolates_legacy_window(db):
    start = _seed(db)
    s = _stats(db, until=start.date().isoformat(), days_back=3650)
    assert s["total_evaluated"] == 3
    assert s["avg_signed_return_pct"] == pytest.approx(-5.0)


def test_wide_days_back_mixes_and_says_so(db):
    """종전 화면 기본값의 재현 — 섞인 평균이 나오고, 섞였다고 보고한다."""
    _seed(db)
    s = _stats(db, days_back=3650)
    assert s["total_evaluated"] == 5
    assert s["avg_signed_return_pct"] == pytest.approx(-2.6)
    assert s["window_includes_pre_logic"] is True


def test_invalid_since_is_rejected(db):
    with pytest.raises(ValueError):
        _stats(db, since="not-a-date")


def test_endpoint_maps_bad_date_to_400():
    import service
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        service.api_signal_accuracy(since="2026-13-40")
    assert exc.value.status_code == 400


def test_horizon_endpoint_exposes_logic_start():
    import service

    assert service.api_signal_horizon()["current_logic_start"] == signal_tracker.CURRENT_LOGIC_START
