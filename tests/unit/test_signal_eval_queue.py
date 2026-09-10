"""신호 사후 평가 큐 — 아사(starvation) 회귀 방지.

2026-09-10 진단: `evaluate_past_signals`가 `ORDER BY issued_at DESC LIMIT 500`으로
후보를 뽑았고 도래 여부를 보지 않았다. 하루 100건 이상 적립되는 규모에서는 매 런이
최신 500건(전부 7일 미도래)만 집어 `processed 0 / skipped_not_due 500`을 반복했고,
4,201건이 영구 대기하면서 08-06 로직 개편 이후 표본이 한 건도 평가되지 않았다.
그 상태가 40일간 status=completed 로 보고됐다.

여기서 고정하는 것:
  1. 후보는 **도래한 horizon이 있는 행만** — 미도래 행이 슬롯을 먹지 않는다
  2. 정렬은 **오래된 것부터** — 신규 유입이 백로그를 밀어내지 못한다
  3. 시세는 **티커별 1회**만 조회 — 백로그 규모에서 왕복이 폭발하지 않는다
  4. 잔량이 결과에 실린다 — 아무것도 못 한 런이 '완료'로 보이지 않는다
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

_SCHEMA = """
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
    agreement_level  TEXT,
    eval_state       TEXT
);
"""

NOW = datetime.now(timezone.utc)


@pytest.fixture
def signal_db(tmp_path):
    db_path = tmp_path / "signals.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return str(db_path)


def _conn_for(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert(db_path, signal_id, days_ago, ticker="AAPL", price=100.0, **cols):
    issued_at = (NOW - timedelta(days=days_ago)).isoformat()
    keys = ", ".join(cols)
    placeholders = ", ".join("?" for _ in cols)
    sql = (
        "INSERT INTO signal_outcomes "
        f"(signal_id, ticker, signal_type, signal_source, issued_at, conviction, price_at_signal"
        f"{', ' + keys if cols else ''}) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?{', ' + placeholders if cols else ''})"
    )
    conn = sqlite3.connect(db_path)
    conn.execute(sql, ("%s" % signal_id, ticker, "buy", "scan_agent", issued_at, 8.0, price,
                       *cols.values()))
    conn.commit()
    conn.close()


def _frame(days_span=60, start_price=100.0):
    """일봉 프레임 — 종가는 100.0 고정이라 수익률 계산이 결정적이다."""
    end = NOW + timedelta(days=1)
    index = pd.date_range(end=end.date(), periods=days_span, freq="D")
    return pd.DataFrame({"Close": [start_price] * len(index)}, index=index)


def _run(db_path, **kwargs):
    """실제 조회 경로(_fetch_history)만 가짜로 바꿔 평가를 돌린다."""
    calls = []

    def fake_fetch(ticker, start, end):
        calls.append((ticker, start, end))
        return _frame()

    with (
        patch("signal_tracker._get_conn", lambda: _conn_for(db_path)),
        patch("signal_tracker._fetch_history", side_effect=fake_fetch),
    ):
        import signal_tracker

        signal_tracker.clear_price_history_cache()
        stats = signal_tracker.evaluate_past_signals(**kwargs)
    return stats, calls


def test_not_due_rows_do_not_consume_the_batch_slots(signal_db):
    """미도래 신규 행이 limit을 먹어 백로그를 굶기던 조건 — 이게 원 결함이다."""
    # 신규 유입 (7일 미도래) 5건 + 도래한 백로그 1건
    for i in range(5):
        _insert(signal_db, f"fresh-{i}", days_ago=1)
    _insert(signal_db, "backlog-1", days_ago=20)

    stats, _ = _run(signal_db, days_back=90, limit=3)

    # 종전 구현: 최신 3건(전부 미도래) → processed 0. 지금은 백로그가 잡힌다.
    assert stats["candidates"] == 1
    assert stats["updated"] == 1
    assert stats["skipped_not_due"] == 0

    conn = sqlite3.connect(signal_db)
    evaluated = conn.execute(
        "SELECT signal_id FROM signal_outcomes WHERE return_7d IS NOT NULL"
    ).fetchall()
    conn.close()
    assert [r[0] for r in evaluated] == ["backlog-1"]


def test_queue_drains_oldest_first(signal_db):
    _insert(signal_db, "old", days_ago=40)
    _insert(signal_db, "mid", days_ago=25)
    _insert(signal_db, "new", days_ago=10)

    stats, _ = _run(signal_db, days_back=90, limit=2)

    assert stats["updated"] == 2
    conn = sqlite3.connect(signal_db)
    done = {
        r[0]
        for r in conn.execute(
            "SELECT signal_id FROM signal_outcomes WHERE evaluated_at IS NOT NULL"
        )
    }
    conn.close()
    assert done == {"old", "mid"}


def test_30d_horizon_gets_filled_after_partial_evaluation(signal_db):
    """7일만 채워진 행이 30일 도래 후 다시 후보가 된다 (return_30d 0건 원인 확인)."""
    _insert(
        signal_db,
        "partial",
        days_ago=35,
        price_7d=101.0,
        return_7d=0.01,
        price_14d=102.0,
        return_14d=0.02,
        evaluated_at=(NOW - timedelta(days=20)).isoformat(),
    )

    stats, _ = _run(signal_db, days_back=90, limit=10)

    assert stats["completed_by_horizon"][30] == 1
    assert stats["already_complete_by_horizon"][7] == 1
    conn = sqlite3.connect(signal_db)
    row = conn.execute(
        "SELECT return_7d, return_14d, return_30d FROM signal_outcomes "
        "WHERE signal_id='partial'"
    ).fetchone()
    conn.close()
    assert row[0] == 0.01 and row[1] == 0.02   # 기존 값 보존
    assert row[2] == 0.0                        # 종가 100.0 / 진입 100.0


def test_price_history_is_fetched_once_per_ticker(signal_db):
    """행 x horizon 개별 조회 제거 — 백로그에서 왕복이 폭발하던 부분."""
    for i in range(6):
        _insert(signal_db, f"aapl-{i}", days_ago=31 + i, ticker="AAPL")
    for i in range(4):
        _insert(signal_db, f"msft-{i}", days_ago=31 + i, ticker="MSFT")

    stats, calls = _run(signal_db, days_back=90, limit=100)

    assert stats["updated"] == 10
    # 종전이라면 10행 x 3 horizon = 30회. 지금은 티커당 1회.
    assert sorted(t for t, _, _ in calls) == ["AAPL", "MSFT"]
    assert stats["prefetch"]["tickers_cached"] == 2


def test_result_reports_remaining_backlog_and_window_expiry(signal_db):
    _insert(signal_db, "due-1", days_ago=20)
    _insert(signal_db, "due-2", days_ago=15)
    _insert(signal_db, "expired", days_ago=200)   # 창 밖 — 다시 후보가 되지 않는다
    _insert(signal_db, "not-due", days_ago=2)

    stats, _ = _run(signal_db, days_back=90, limit=1)

    assert stats["pending_due_before"] == 2
    assert stats["pending_due"] == 1              # 남은 잔량이 결과에 실린다
    assert stats["expired_unevaluated"] == 1
    assert stats["oldest_pending_days"] is not None
    assert stats["days_back"] == 90 and stats["limit"] == 1


def test_missing_price_is_not_reported_as_nothing_to_do(signal_db):
    """시세 미수신과 '평가할 게 없음'을 같은 카운터에 담지 않는다."""
    _insert(signal_db, "delisted", days_ago=20, ticker="DEAD")

    with (
        patch("signal_tracker._get_conn", lambda: _conn_for(signal_db)),
        patch("signal_tracker._fetch_history", lambda *a, **k: pd.DataFrame()),
    ):
        import signal_tracker

        signal_tracker.clear_price_history_cache()
        stats = signal_tracker.evaluate_past_signals(days_back=90, limit=10)

    assert stats["updated"] == 0
    assert stats["skipped_no_price"] == 1
    assert stats["skipped_not_due"] == 0
    assert stats["prefetch"]["tickers_failed"] == ["DEAD"]
    assert stats["pending_due"] == 1


def test_backlog_status_marks_validation_degraded():
    """잔량이 있으면 검증 잡이 completed 로 보고되지 않는다."""
    import service

    clear = service._signal_eval_backlog_status(
        {"pending_due": 0, "expired_unevaluated": 0, "oldest_pending_days": 3, "days_back": 90}
    )
    assert clear["degraded"] is False

    starved = service._signal_eval_backlog_status(
        {
            "pending_due": 4201,
            "expired_unevaluated": 23,
            "oldest_pending_days": 66,
            "days_back": 90,
        }
    )
    assert starved["degraded"] is True
    assert "4201" in starved["detail"]


def test_symbol_without_prices_is_closed_out_instead_of_retried_forever(signal_db):
    """존재하지 않는 심볼(057050.KS 사례)이 큐와 경고를 영구히 붙잡지 않는다."""
    # 30일 horizon + grace(14일)를 넘긴 행 / 아직 안 넘긴 행
    _insert(signal_db, "stuck-old", days_ago=60, ticker="GHOST")
    _insert(signal_db, "stuck-young", days_ago=20, ticker="GHOST")

    def _run_empty():
        with (
            patch("signal_tracker._get_conn", lambda: _conn_for(signal_db)),
            patch("signal_tracker._fetch_history", lambda *a, **k: pd.DataFrame()),
        ):
            import signal_tracker

            signal_tracker.clear_price_history_cache()
            return signal_tracker.evaluate_past_signals(days_back=90, limit=10)

    first = _run_empty()
    assert first["marked_unresolved"] == 1
    assert first["unresolved_tickers"] == ["GHOST"]
    assert first["unresolved_total"] == 1
    # grace 안쪽 행은 계속 대기 — 조급하게 종결하지 않는다
    assert first["pending_due"] == 1

    # 종결된 행은 다음 런에서 후보가 아니다 (영구 재시도 제거)
    second = _run_empty()
    assert second["candidates"] == 1
    assert second["marked_unresolved"] == 0
    assert second["pending_due"] == 1


def test_persistent_missing_symbol_does_not_keep_alerting():
    """한 심볼의 시세 미수신이 매일 degraded 를 만들면 그 경고는 읽히지 않게 된다."""
    import service

    # 종결이 일어난 런: 한 번은 알린다
    marking_run = service._signal_eval_backlog_status(
        {
            "pending_due": 12,
            "expired_unevaluated": 0,
            "oldest_pending_days": 5,
            "days_back": 90,
            "marked_unresolved": 53,
            "unresolved_tickers": ["057050.KS"],
            "prefetch": {"tickers_requested": 19, "tickers_failed": ["057050.KS"]},
        }
    )
    assert marking_run["degraded"] is True
    assert "057050.KS" in marking_run["detail"]

    # 이후 런: 같은 심볼이 계속 실패하지만 종결은 끝났고 잔량도 정상
    steady_run = service._signal_eval_backlog_status(
        {
            "pending_due": 12,
            "expired_unevaluated": 0,
            "oldest_pending_days": 5,
            "days_back": 90,
            "marked_unresolved": 0,
            "unresolved_total": 53,
            "skipped_no_price": 0,
            "prefetch": {"tickers_requested": 19, "tickers_failed": ["057050.KS"]},
        }
    )
    assert steady_run["degraded"] is False
    assert steady_run["unresolved_total"] == 53      # 카운트로는 계속 보인다
    assert steady_run["prefetch_failed"] == ["057050.KS"]


def test_total_price_source_outage_still_degrades():
    """전 종목 시세 실패는 즉시 degraded — 종결 경로로 조용히 넘기지 않는다."""
    import service

    status = service._signal_eval_backlog_status(
        {
            "pending_due": 40,
            "expired_unevaluated": 0,
            "oldest_pending_days": 8,
            "days_back": 90,
            "marked_unresolved": 0,
            "prefetch": {"tickers_requested": 7, "tickers_failed": ["A", "B", "C", "D", "E", "F", "G"]},
        }
    )
    assert status["degraded"] is True
    assert "전면 실패" in status["detail"]
