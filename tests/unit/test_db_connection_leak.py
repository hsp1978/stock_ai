"""Worker threads must not leak SQLite connections.

Regression for 2026-08-18: every scan/screener run created a fresh
ThreadPoolExecutor, and each dead worker's connection stayed reachable through a
module-level list. After ~7 days the process held 400 connections (800 fds with
WAL) and hit the 1024 nofile limit, so accept() failed for every request and the
whole agent-api became unreachable.
"""

import gc
import os
import sys
import threading

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import db as db_mod

    test_db = tmp_path / "leak_test.db"
    monkeypatch.setattr(db_mod, "DB_PATH", str(test_db))
    db_mod.init_db()
    db_mod.close_thread_connection()
    return db_mod


def _live_connections(db_mod) -> int:
    gc.collect()
    with db_mod._DB_CONNECTIONS_LOCK:
        return len(db_mod._DB_CONNECTIONS)


def _run_and_forget(target) -> None:
    """Run target in a thread and drop every reference to that thread.

    The registry is keyed by the Thread object, so a lingering local variable
    would pin the entry and make the assertion lie.
    """
    worker = threading.Thread(target=target)
    worker.start()
    worker.join()
    del worker


def test_dead_worker_threads_do_not_accumulate_connections(db):
    """Connections opened by short-lived threads are reclaimed once they exit."""
    baseline = _live_connections(db)

    for _ in range(10):
        _run_and_forget(lambda: db.get_app_state("missing"))

    assert _live_connections(db) == baseline


def test_worker_connection_scope_closes_on_success(db):
    baseline = _live_connections(db)

    def task():
        with db.worker_connection_scope():
            db.set_app_state("scope.ok", {"v": 1})

    _run_and_forget(task)

    assert _live_connections(db) == baseline
    assert db.get_app_state("scope.ok") == {"v": 1}


def test_worker_connection_scope_closes_on_exception(db):
    """A failing task must still hand its fd back."""
    baseline = _live_connections(db)
    raised = []

    def task():
        try:
            with db.worker_connection_scope():
                db.get_app_state("missing")
                raise RuntimeError("boom")
        except RuntimeError as exc:
            raised.append(exc)

    _run_and_forget(task)

    assert len(raised) == 1
    assert _live_connections(db) == baseline


def test_connection_is_reused_within_a_thread(db):
    """The scope must not reintroduce per-call connect/close churn."""
    db.get_app_state("missing")
    first = db._get_conn()._conn
    db.get_app_state("missing")
    second = db._get_conn()._conn

    assert first is second
    db.close_thread_connection()
