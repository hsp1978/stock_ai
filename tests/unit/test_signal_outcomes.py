"""
signal_outcomes 배치 활성화 단위 테스트 (EXECUTION_PLAN Step 4)

테스트 시나리오:
- 시그널 insert → signal_outcomes row 생성
- 30일 경과 시뮬레이션 → evaluate 호출 → return_7/14/30d 산출
- ECE 계산 정확성 (sample fixture)
- signal_performance_summary view 조회
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd
import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from jobs.calibration_metrics import compute_ece  # noqa: E402


# ── DB 픽스처 ──────────────────────────────────────────────────────────


def _init_test_db(path: str) -> None:
    """테스트용 signal_outcomes 테이블만 생성."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signal_outcomes (
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
        CREATE VIEW IF NOT EXISTS signal_performance_summary AS
        SELECT signal_source, signal_type, regime,
               COUNT(*) AS n,
               AVG(CASE WHEN return_7d > 0 THEN 1.0 ELSE 0.0 END) AS hit_rate_7d,
               AVG(return_7d)  AS expectancy_7d,
               AVG(return_30d) AS expectancy_30d,
               AVG(max_drawdown_30d) AS avg_max_dd
        FROM signal_outcomes
        WHERE evaluated_at IS NOT NULL
          AND issued_at >= datetime('now', '-90 days')
        GROUP BY signal_source, signal_type, regime;
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def test_db(tmp_path):
    db = str(tmp_path / "test_so.db")
    _init_test_db(db)
    return db


# ── 시그널 insert 테스트 ───────────────────────────────────────────────


def test_insert_signal_outcome_creates_row(test_db):
    """insert_signal_outcome → DB에 row가 생성됨."""
    with patch("signal_tracker._get_conn", lambda: _patched_conn(test_db)):
        from signal_tracker import insert_signal_outcome

        sid = insert_signal_outcome(
            ticker="AAPL",
            signal_type="buy",
            signal_source="scan_agent",
            conviction=7.5,
            price_at_signal=180.0,
        )

    conn = sqlite3.connect(test_db)
    row = conn.execute(
        "SELECT * FROM signal_outcomes WHERE signal_id = ?", (sid,)
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[1] == "AAPL"  # ticker
    assert row[2] == "buy"  # signal_type
    assert row[6] == 180.0  # price_at_signal


def _patched_conn(path: str):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# ── 30일 경과 → 평가 테스트 ───────────────────────────────────────────


def test_evaluate_pending_updates_returns(test_db):
    """issued_at 35일 전 row → evaluate 후 return_7d 계산됨."""
    old_issued = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
    sig_id = "test-signal-001"

    conn = sqlite3.connect(test_db)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source,
            issued_at, conviction, price_at_signal)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (sig_id, "AAPL", "buy", "scan_agent", old_issued, 7.0, 100.0),
    )
    conn.commit()
    conn.close()

    # _fetch_price_at / _compute_max_dd mock: 실제 네트워크 호출 없이 고정값 반환
    _call_prices = iter([108.0, 112.0, 120.0])

    def _mock_fetch(ticker, target_date):
        try:
            return next(_call_prices)
        except StopIteration:
            return 110.0

    def _mock_max_dd(ticker, start, days=30):
        return -0.05

    from jobs.evaluate_signal_outcomes import evaluate_pending_outcomes

    with (
        patch("jobs.evaluate_signal_outcomes._fetch_price_at", side_effect=_mock_fetch),
        patch(
            "jobs.evaluate_signal_outcomes._compute_max_dd", side_effect=_mock_max_dd
        ),
    ):
        stats = evaluate_pending_outcomes(db_path=test_db)

    assert stats["processed"] >= 1

    conn = sqlite3.connect(test_db)
    row = conn.execute(
        "SELECT return_7d, max_drawdown_30d, evaluated_at FROM signal_outcomes WHERE signal_id=?",
        (sig_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] is not None  # return_7d 계산됨
    assert row[1] is not None  # max_drawdown_30d 계산됨
    assert row[2] is not None  # evaluated_at 설정됨


# ── ECE 계산 정확성 ────────────────────────────────────────────────────


def test_compute_ece_perfect_calibration():
    """conviction == actual win_rate 이면 ECE ≈ 0."""
    n = 200
    # conviction 0.5 (=5/10) → 50% 가 승
    df = pd.DataFrame(
        {
            "conviction": [5.0] * n,
            "return_7d": [0.01] * (n // 2) + [-0.01] * (n // 2),
        }
    )
    ece = compute_ece(df)
    # 완벽한 보정 → ECE ~0
    assert ece < 0.05, f"ECE should be near 0, got {ece}"


def test_compute_ece_worst_calibration():
    """conviction=10 이지만 항상 손실 → ECE ≈ 1."""
    n = 100
    df = pd.DataFrame(
        {
            "conviction": [10.0] * n,
            "return_7d": [-0.01] * n,  # 항상 손실
        }
    )
    ece = compute_ece(df)
    assert ece > 0.5, f"ECE should be high, got {ece}"


def test_compute_ece_empty_df():
    """빈 DataFrame → nan 반환."""
    import math

    ece = compute_ece(pd.DataFrame())
    assert math.isnan(ece)


# ── signal_performance_summary view 조회 ─────────────────────────────


def test_signal_performance_summary_view(test_db):
    """evaluated_at 있는 row → summary view에 집계됨."""
    now = datetime.now(timezone.utc)
    issued = (now - timedelta(days=40)).isoformat()
    evaluated = now.isoformat()

    conn = sqlite3.connect(test_db)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source,
            issued_at, conviction, price_at_signal,
            return_7d, return_30d, evaluated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "v-001",
            "TSLA",
            "buy",
            "scan_agent",
            issued,
            8.0,
            200.0,
            0.05,
            0.12,
            evaluated,
        ),
    )
    conn.commit()

    rows = conn.execute("SELECT * FROM signal_performance_summary").fetchall()
    conn.close()

    assert len(rows) >= 1
    row = rows[0]
    assert row[0] == "scan_agent"  # signal_source
    assert row[1] == "buy"  # signal_type
