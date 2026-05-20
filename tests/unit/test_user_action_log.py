"""user_action_log DB 함수 단위 테스트."""

import importlib
import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """임시 DB 경로로 db 모듈을 reload 한 후 init_db 실행."""
    import db as db_mod

    test_db = tmp_path / "ual_test.db"
    monkeypatch.setattr(db_mod, "DB_PATH", str(test_db))
    db_mod.init_db()
    return db_mod


def test_insert_returns_row_id(db):
    new_id = db.insert_user_action(
        action_type="page_view",
        page="dashboard",
    )
    assert new_id > 0


def test_insert_normalizes_ticker_to_upper(db):
    db.insert_user_action(action_type="ticker_search", ticker="aapl")
    rows = db.get_user_actions(limit=1)["actions"]
    assert rows[0]["ticker"] == "AAPL"


def test_insert_metadata_is_stored_as_json(db):
    db.insert_user_action(
        action_type="watchlist_edit",
        ticker="MSFT",
        metadata={"op": "add", "source": "sidebar"},
    )
    rows = db.get_user_actions(limit=1)["actions"]
    assert rows[0]["metadata"] is not None
    assert "add" in rows[0]["metadata"]
    assert "MSFT" == rows[0]["ticker"]


def test_filter_by_action_type(db):
    db.insert_user_action(action_type="page_view", page="home")
    db.insert_user_action(action_type="manual_scan", ticker="NVDA")
    db.insert_user_action(action_type="page_view", page="detail")

    page_views = db.get_user_actions(action_type="page_view")
    assert page_views["total"] == 2
    assert all(a["action_type"] == "page_view" for a in page_views["actions"])


def test_filter_by_ticker(db):
    db.insert_user_action(action_type="manual_scan", ticker="AAPL")
    db.insert_user_action(action_type="manual_scan", ticker="MSFT")
    db.insert_user_action(action_type="manual_scan", ticker="AAPL")

    aapl_rows = db.get_user_actions(ticker="aapl")
    assert aapl_rows["total"] == 2
    assert all(a["ticker"] == "AAPL" for a in aapl_rows["actions"])


def test_stats_aggregation(db):
    db.insert_user_action(action_type="page_view", page="home")
    db.insert_user_action(action_type="page_view", page="detail")
    db.insert_user_action(action_type="manual_scan", ticker="NVDA")
    db.insert_user_action(action_type="manual_scan", ticker="NVDA")

    stats = db.get_user_action_stats(days_back=1)
    by_type = {row["action_type"]: row["count"] for row in stats["by_action_type"]}
    assert by_type["page_view"] == 2
    assert by_type["manual_scan"] == 2
    top = {row["ticker"]: row["count"] for row in stats["top_tickers"]}
    assert top["NVDA"] == 2


def test_insert_failure_returns_zero(db, monkeypatch):
    """insert_user_action 은 호출자에 예외를 전파하지 않는다."""
    def _broken_conn():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(db, "_get_conn", _broken_conn)
    new_id = db.insert_user_action(action_type="page_view", page="home")
    assert new_id == 0
