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
    # 스키마는 db.py 의 실제 DDL 을 쓴다 — 복제하면 컬럼 추가 때마다 어긋난다.
    from db import _CREATE_OUTCOMES_TABLE

    conn.executescript(_CREATE_OUTCOMES_TABLE)
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

    def _mock_price(ticker, target_date):
        # 벤치마크 지수(^KS11/^GSPC 등)는 발행일 기준점도 조회되므로 horizon 0 이 온다.
        if str(ticker).startswith("^"):
            return 1000.0          # 지수 변화 없음 → 초과수익 = 종목 수익
        horizon = round((target_date - issued_at).total_seconds() / 86400)
        return {7: 104.0, 14: 99.0, 30: 110.0}[horizon]

    with (
        patch("signal_tracker._get_conn", lambda: _conn_for(signal_db)),
        patch("signal_tracker._latest_close_for", side_effect=_mock_price),
        # 배치 프리페치가 실제 yfinance를 타지 않게 한다 (테스트는 외부 호출 금지).
        patch("signal_tracker._fetch_history", lambda *a, **k: None),
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
    band = stats["band_outcome"]
    assert band["win"] == 2 and band["loss"] == 1
    assert band["win_rate_pct"] == 66.7
    assert band["threshold_pct"] == 2.0          # 임계를 값과 함께 싣는다
    assert stats["by_signal"]["buy"]["total"] == 1
    assert stats["by_signal"]["buy"]["band_outcome"]["win_rate_pct"] == 100.0
    assert stats["by_signal"]["sell"]["total"] == 2
    assert stats["by_signal"]["sell"]["band_outcome"]["win_rate_pct"] == 50.0
    assert stats["by_source"]["scan_agent"]["total"] == 3
