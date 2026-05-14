"""
GlobalKillSwitch 단위 테스트 (EXECUTION_PLAN Step 1)

테스트 시나리오:
- daily_pnl_pct=-3.5 → action=halt
- daily_pnl_pct=-2.2 → action=alert
- vix=32 → action=halt
- 정상 상태 → events=[]
- cool_down_until > now → is_blocked()=True
- middleware 423 응답 검증
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# conftest.py가 sys.path를 세팅하지만, 직접 실행 시에도 동작하도록 보장
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from safety.models import DecisionContext  # noqa: E402
from safety.kill_switch import GlobalKillSwitch  # noqa: E402


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_settings():
    """kill_switch.py 내부 settings 를 기본 임계값으로 교체."""
    s = MagicMock()
    s.DAILY_LOSS_LIMIT_ALERT_PCT = 2.0
    s.DAILY_LOSS_LIMIT_HARD_PCT = 3.0
    s.WEEKLY_DRAWDOWN_LIMIT_PCT = 5.0
    s.TRAILING_PEAK_DD_PCT = 10.0
    s.CONSECUTIVE_LOSS_COUNT = 5
    s.VIX_CAP = 30.0
    s.VIX_SPIKE_PCT = 20.0
    s.DATA_STALENESS_HALT_HOURS = 6.0
    s.COOL_DOWN_HOURS = 24
    return s


@pytest.fixture
def ks(tmp_path, mock_settings):
    """임시 DB를 사용하는 GlobalKillSwitch 인스턴스."""
    db = str(tmp_path / "ks_test.db")
    with patch("safety.kill_switch.settings", mock_settings):
        # __init__ 내부 _ensure_table 호출 시 settings 미사용 → OK
        instance = GlobalKillSwitch(db_path=db)
    return instance, db, mock_settings


# ── 평가 시나리오 ──────────────────────────────────────────────────────


def test_daily_loss_halt(ks):
    """일일 손실 3.5% → halt 이벤트."""
    instance, db, mock_settings = ks
    ctx = DecisionContext(portfolio_pnl_pct=-3.5)
    with patch("safety.kill_switch.settings", mock_settings):
        events = instance.evaluate(ctx)
    assert len(events) == 1
    assert events[0].action == "halt"
    assert events[0].trigger_type == "daily_loss_halt"
    assert events[0].cool_down_until is not None


def test_daily_loss_alert(ks):
    """일일 손실 2.2% → alert 이벤트 (halt 아님)."""
    instance, db, mock_settings = ks
    ctx = DecisionContext(portfolio_pnl_pct=-2.2)
    with patch("safety.kill_switch.settings", mock_settings):
        events = instance.evaluate(ctx)
    assert len(events) == 1
    assert events[0].action == "alert"
    assert events[0].trigger_type == "daily_loss_alert"
    assert events[0].cool_down_until is None


def test_vix_halt(ks):
    """VIX 32 → halt 이벤트."""
    instance, db, mock_settings = ks
    ctx = DecisionContext(vix=32.0)
    with patch("safety.kill_switch.settings", mock_settings):
        events = instance.evaluate(ctx)
    halt_events = [e for e in events if e.trigger_type == "vix_halt"]
    assert len(halt_events) == 1
    assert halt_events[0].action == "halt"


def test_normal_state_no_events(ks):
    """정상 상태 → 이벤트 없음."""
    instance, db, mock_settings = ks
    ctx = DecisionContext(
        portfolio_pnl_pct=-0.5,
        vix=18.0,
        data_freshness_hours=1.0,
        consecutive_losses=1,
        weekly_drawdown_pct=-1.0,
        trailing_peak_dd_pct=-2.0,
    )
    with patch("safety.kill_switch.settings", mock_settings):
        events = instance.evaluate(ctx)
    assert events == []


def test_is_blocked_after_halt(ks):
    """halt 이벤트 기록 후 is_blocked() = True."""
    instance, db, mock_settings = ks
    ctx = DecisionContext(portfolio_pnl_pct=-3.5)
    with patch("safety.kill_switch.settings", mock_settings):
        instance.evaluate(ctx)
        blocked, reason = instance.is_blocked()
    assert blocked is True
    assert reason is not None


def test_is_not_blocked_initially(ks):
    """이벤트 없으면 is_blocked() = False."""
    instance, db, mock_settings = ks
    blocked, reason = instance.is_blocked()
    assert blocked is False
    assert reason is None


def test_consecutive_loss_halt(ks):
    """연속 손실 5회 → halt."""
    instance, db, mock_settings = ks
    ctx = DecisionContext(consecutive_losses=5)
    with patch("safety.kill_switch.settings", mock_settings):
        events = instance.evaluate(ctx)
    halt = [e for e in events if e.trigger_type == "consecutive_loss_halt"]
    assert len(halt) == 1
    assert halt[0].action == "halt"


def test_data_stale_halt(ks):
    """데이터 신선도 7시간 → halt."""
    instance, db, mock_settings = ks
    ctx = DecisionContext(data_freshness_hours=7.0)
    with patch("safety.kill_switch.settings", mock_settings):
        events = instance.evaluate(ctx)
    halt = [e for e in events if e.trigger_type == "data_stale_halt"]
    assert len(halt) == 1


def test_vix_spike_halt(ks):
    """VIX 스파이크 25% → halt."""
    instance, db, mock_settings = ks
    ctx = DecisionContext(vix=25.0, vix_prev=20.0)  # spike = 25%
    with patch("safety.kill_switch.settings", mock_settings):
        events = instance.evaluate(ctx)
    spike = [e for e in events if e.trigger_type == "vix_spike_halt"]
    assert len(spike) == 1


def test_force_halt_and_blocked(ks):
    """force_halt() 후 is_blocked() = True."""
    instance, db, mock_settings = ks
    with patch("safety.kill_switch.settings", mock_settings):
        instance.force_halt(reason="test", hours=1)
        blocked, reason = instance.is_blocked()
    assert blocked is True


# ── 미들웨어 423 응답 검증 ────────────────────────────────────────────


def test_middleware_blocks_scan_when_halted(tmp_path, mock_settings):
    """kill_switch 활성 시 /scan 호출 → 423."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.middleware.base import BaseHTTPMiddleware
    from fastapi.responses import JSONResponse

    db = str(tmp_path / "mw_test.db")

    with patch("safety.kill_switch.settings", mock_settings):
        ks_instance = GlobalKillSwitch(db_path=db)
        ks_instance.force_halt(reason="test", hours=1)

    test_app = FastAPI()

    class _TestKSMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            from safety.kill_switch import _is_kill_switch_protected

            if _is_kill_switch_protected(request.url.path):
                blocked, reason = ks_instance.is_blocked()
                if blocked:
                    return JSONResponse(
                        status_code=423,
                        content={"detail": "kill_switch_active", "reason": reason},
                    )
            return await call_next(request)

    test_app.add_middleware(_TestKSMiddleware)

    @test_app.post("/scan")
    def _scan():
        return {"ok": True}

    @test_app.get("/health")
    def _health():
        return {"ok": True}

    client = TestClient(test_app, raise_server_exceptions=False)

    # /scan → 423
    resp = client.post("/scan")
    assert resp.status_code == 423
    assert resp.json()["detail"] == "kill_switch_active"

    # /health → 200 (보호 대상 아님)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_middleware_scan_log_not_blocked(tmp_path, mock_settings):
    """/scan-log 는 kill_switch 보호 대상이 아니어야 한다."""
    from safety.kill_switch import _is_kill_switch_protected

    assert _is_kill_switch_protected("/scan") is True
    assert _is_kill_switch_protected("/scan/AAPL") is True
    assert _is_kill_switch_protected("/scan-log") is False
    assert _is_kill_switch_protected("/paper/order") is True
    assert _is_kill_switch_protected("/paper/reset") is False
