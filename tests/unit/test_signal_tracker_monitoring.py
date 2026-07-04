"""signal_tracker monitoring pipeline tests."""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)


@pytest.fixture
def signal_db(tmp_path):
    db_path = tmp_path / "signals.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE signal_outcomes (
            signal_id        TEXT PRIMARY KEY,
            ticker           TEXT NOT NULL,
            signal_type      TEXT NOT NULL,
            signal_source    TEXT NOT NULL,
            issued_at        TIMESTAMP NOT NULL,
            conviction       REAL NOT NULL,
            price_at_signal  REAL NOT NULL,
            price_7d         REAL,
            price_14d        REAL,
            price_30d        REAL,
            return_7d        REAL,
            return_14d       REAL,
            return_30d       REAL,
            max_drawdown_30d REAL,
            evaluated_at     TIMESTAMP,
            market_context   TEXT,
            regime           TEXT,
            signal_std       REAL,
            agreement_level  TEXT
        );
        """
    )
    conn.commit()
    conn.close()
    return str(db_path)


def _conn_for(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_evaluate_past_signals_updates_current_signal_outcomes_schema(signal_db):
    issued_at = datetime.now(timezone.utc) - timedelta(days=35)
    conn = sqlite3.connect(signal_db)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source,
            issued_at, conviction, price_at_signal)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("sig-1", "AAPL", "buy", "scan_agent", issued_at.isoformat(), 8.0, 100.0),
    )
    conn.commit()
    conn.close()

    def _mock_price(_ticker, target_date):
        horizon = round((target_date - issued_at).total_seconds() / 86400)
        return {7: 104.0, 14: 99.0, 30: 110.0}[horizon]

    with (
        patch("signal_tracker._get_conn", lambda: _conn_for(signal_db)),
        patch("signal_tracker._latest_close_for", side_effect=_mock_price),
    ):
        from signal_tracker import evaluate_past_signals

        stats = evaluate_past_signals(days_back=45, limit=10)

    assert stats["processed"] == 1
    assert stats["updated"] == 1
    assert stats["errors"] == 0

    conn = sqlite3.connect(signal_db)
    row = conn.execute(
        "SELECT price_7d, return_7d, price_30d, return_30d, evaluated_at "
        "FROM signal_outcomes WHERE signal_id='sig-1'"
    ).fetchone()
    conn.close()

    assert row[0] == 104.0
    assert row[1] == 0.04
    assert row[2] == 110.0
    assert row[3] == 0.1
    assert row[4] is not None


def test_accuracy_stats_uses_signal_direction_and_confidence_filter(signal_db):
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        ("buy-win", "AAPL", "buy", "scan_agent", now, 8.0, 100.0, 0.03),
        ("buy-low-conf", "MSFT", "buy", "scan_agent", now, 4.0, 100.0, -0.05),
        ("sell-win", "TSLA", "sell", "scan_agent", now, 9.0, 100.0, -0.04),
        ("sell-loss", "NVDA", "sell", "scan_agent", now, 8.5, 100.0, 0.05),
    ]
    conn = sqlite3.connect(signal_db)
    conn.executemany(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source,
            issued_at, conviction, price_at_signal, return_7d, evaluated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(sid, t, sig, src, issued, conf, price, ret, now) for sid, t, sig, src, issued, conf, price, ret in rows],
    )
    conn.commit()
    conn.close()

    with patch("signal_tracker._get_conn", lambda: _conn_for(signal_db)):
        from signal_tracker import get_accuracy_stats

        stats = get_accuracy_stats(horizon=7, min_confidence=8.0, days_back=30)

    assert stats["total_evaluated"] == 3
    assert stats["win_count"] == 2
    assert stats["loss_count"] == 1
    assert stats["win_rate_pct"] == 66.7
    assert stats["by_signal"]["buy"]["total"] == 1
    assert stats["by_signal"]["buy"]["win_rate_pct"] == 100.0
    assert stats["by_signal"]["sell"]["total"] == 2
    assert stats["by_signal"]["sell"]["win_rate_pct"] == 50.0
    assert stats["by_source"]["scan_agent"]["total"] == 3
