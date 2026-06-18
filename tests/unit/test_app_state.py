"""app_state DB key-value storage tests."""

import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)


@pytest.fixture
def db(tmp_path, monkeypatch):
    import db as db_mod

    test_db = tmp_path / "app_state_test.db"
    monkeypatch.setattr(db_mod, "DB_PATH", str(test_db))
    db_mod.init_db()
    return db_mod


def test_app_state_roundtrip(db):
    value = {
        "AAPL": {
            "signal": "SELL",
            "triggered_at": "2026-06-18T09:00:00",
        }
    }

    db.set_app_state("service.cooling_off_state", value)

    assert db.get_app_state("service.cooling_off_state") == value


def test_app_state_default_for_missing_key(db):
    assert db.get_app_state("missing", default={"ok": True}) == {"ok": True}


def test_app_state_delete(db):
    db.set_app_state("service.scan_history", [{"timestamp": "now"}])
    db.delete_app_state("service.scan_history")

    assert db.get_app_state("service.scan_history", default=[]) == []
