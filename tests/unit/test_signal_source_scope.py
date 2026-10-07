"""통계 소스 범위 — 대표 지표는 판정 소스만 본다.

2026-10-07: 루닛(328130.KQ) 2026-09 매도 1건이 group_fundamental·group_risk·
group_technical·multi_agent_final·scan_agent 5곳에서 각각 집계됐다. group_* 은
멀티에이전트 구성요소라 최종 판정과 같은 사건을 중복으로 센다.
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

NOW = datetime.now(timezone.utc)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "signals.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    for i, (src, ret) in enumerate([
        ("multi_agent_final", 0.02), ("scan_agent", 0.04), ("screener", 0.00),
        ("group_fundamental", -0.10), ("group_risk", -0.10), ("groupish", 0.0),
    ]):
        issued = (NOW - timedelta(days=20)).isoformat()
        conn.execute(
            """INSERT INTO signal_outcomes (signal_id, ticker, signal_type, signal_source,
               issued_at, conviction, price_at_signal, return_7d, return_14d, return_30d,
               evaluated_at) VALUES (?, 'PLTR', 'buy', ?, ?, 7.0, 100.0, ?, ?, ?, ?)""",
            (f"s{i}", src, issued, ret, ret, ret, issued),
        )
    conn.commit()
    conn.close()
    return str(path)


def _stats(path, **kw):
    def _conn():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    with patch("signal_tracker._get_conn", _conn):
        return signal_tracker.get_accuracy_stats(horizon=14, days_back=60, **kw)


def test_decisions_scope_excludes_components(db):
    s = _stats(db, sources="decisions")
    assert set(s["by_source"]) == {"multi_agent_final", "scan_agent", "screener"}
    assert s["avg_signed_return_pct"] == pytest.approx(2.0)
    assert s["sampling"]["rows_raw"] == 3


def test_components_scope_is_group_prefix_only(db):
    """'groupish' 처럼 접두어만 비슷한 소스는 구성요소가 아니다 (LIKE 이스케이프)."""
    s = _stats(db, sources="components")
    assert set(s["by_source"]) == {"group_fundamental", "group_risk"}


def test_function_default_stays_all_for_calibrator(db):
    """칼리브레이터 등 내부 호출자의 종전 동작을 바꾸지 않는다."""
    s = _stats(db)
    assert s["source_scope"] == "all"
    assert s["total_evaluated"] == 6


def test_by_source_carries_role(db):
    s = _stats(db, sources="all")
    assert s["by_source"]["multi_agent_final"]["role"] == "decision"
    assert s["by_source"]["group_risk"]["role"] == "component"
    assert s["by_source"]["groupish"]["role"] == "other"


def test_invalid_scope_rejected(db):
    with pytest.raises(ValueError):
        _stats(db, sources="bogus")


def test_endpoint_defaults_to_decisions_and_maps_errors():
    import inspect

    import service
    from fastapi import HTTPException

    assert inspect.signature(service.api_signal_accuracy).parameters["sources"].default == "decisions"
    with pytest.raises(HTTPException) as exc:
        service.api_signal_accuracy(sources="bogus")
    assert exc.value.status_code == 400
