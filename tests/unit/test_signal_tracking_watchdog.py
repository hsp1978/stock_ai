"""signal_outcomes 추적 파이프라인 워치독 테스트.

2026-07 무기록 버그(83일 0행, 무음)의 재발 감지:
방향성 스캔 신호(BUY/SELL)가 발생했는데 최근 outcomes가 0건이면
data_health가 'silent'로 경고해야 한다.
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from signal_tracker import get_tracking_health  # noqa: E402


def _init_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE signal_outcomes (
            signal_id TEXT PRIMARY KEY,
            ticker TEXT, signal_type TEXT, signal_source TEXT,
            issued_at TIMESTAMP, conviction REAL, price_at_signal REAL
        );
        CREATE TABLE scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT, signal TEXT, scanned_at TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def _conn(path: str):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso(days_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_silent_when_directional_scans_but_no_outcomes(tmp_path):
    db = str(tmp_path / "t.db")
    _init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO scan_log (ticker, signal, scanned_at) VALUES (?, ?, ?)",
        ("AAPL", "BUY", _now_iso(1)),
    )
    conn.commit()
    conn.close()

    with patch("signal_tracker._get_conn", lambda: _conn(db)):
        health = get_tracking_health()

    assert health["status"] == "silent"
    assert health["outcomes_recent"] == 0
    assert health["directional_scans_recent"] == 1


def test_ok_when_outcomes_recorded(tmp_path):
    db = str(tmp_path / "t.db")
    _init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO signal_outcomes (signal_id, ticker, signal_type, signal_source, issued_at, conviction, price_at_signal) "
        "VALUES ('x', 'AAPL', 'buy', 'multi_agent_final', ?, 5.0, 100.0)",
        (_now_iso(1),),
    )
    conn.execute(
        "INSERT INTO scan_log (ticker, signal, scanned_at) VALUES (?, ?, ?)",
        ("AAPL", "BUY", _now_iso(1)),
    )
    conn.commit()
    conn.close()

    with patch("signal_tracker._get_conn", lambda: _conn(db)):
        health = get_tracking_health()

    assert health["status"] == "ok"
    assert health["outcomes_recent"] == 1


def test_no_signals_when_only_holds(tmp_path):
    """방향성 신호가 없으면 기록 0이어도 정상 (silent 오탐 방지)."""
    db = str(tmp_path / "t.db")
    _init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO scan_log (ticker, signal, scanned_at) VALUES (?, ?, ?)",
        ("AAPL", "HOLD", _now_iso(1)),
    )
    conn.commit()
    conn.close()

    with patch("signal_tracker._get_conn", lambda: _conn(db)):
        health = get_tracking_health()

    assert health["status"] == "no_signals"


def test_old_signals_outside_window_ignored(tmp_path):
    db = str(tmp_path / "t.db")
    _init_db(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO scan_log (ticker, signal, scanned_at) VALUES (?, ?, ?)",
        ("AAPL", "BUY", _now_iso(30)),  # 윈도우(7일) 밖
    )
    conn.commit()
    conn.close()

    with patch("signal_tracker._get_conn", lambda: _conn(db)):
        health = get_tracking_health(days_back=7)

    assert health["status"] == "no_signals"


def test_data_health_degrades_on_silent_tracking():
    """build_data_health가 silent 판정 시 전체 status를 강등해야 한다."""
    import service

    with (
        patch.object(service, "_collect_data_health_tickers", lambda tickers=None: ["AAPL"]),
        patch.object(service, "get_data_cache_status", lambda tickers, period=None: {
            "tickers": {"AAPL": {
                "ohlcv": {"present": True, "fresh": True, "age_sec": 60},
                "fundamentals": {"present": True, "fresh": True, "data_quality": "full"},
            }}
        }),
        patch.object(service, "get_news_cache_status", lambda tickers: {
            "tickers": {"AAPL": {"present": True, "fresh": True}}
        }),
        patch("signal_tracker.get_tracking_health", lambda days_back=7: {
            "status": "silent", "outcomes_recent": 0,
            "directional_scans_recent": 3, "days_back": 7,
        }),
        patch.object(service, "_persist_data_health", lambda: None),
    ):
        payload = service.build_data_health(["AAPL"])

    assert payload["signal_tracking"]["status"] == "silent"
    assert payload["status"] == "degraded"
