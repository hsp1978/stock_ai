"""GPU 일시 해제 제어 테스트.

다른 서비스가 GPU를 30~60분 쓸 때 LLM 작업을 멈추고 VRAM을 반환한다.
- 상태는 DB(app_state)에 두어 agent-api 재시작/재빌드에도 유지된다.
- 만료 시각을 함께 저장해 복구를 잊어도 자동으로 돌아온다.
- 언로드는 응답이 아니라 /api/ps 실측으로 확인한다.
"""

import os
import sys
from datetime import datetime, timedelta

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import service  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_pause(monkeypatch):
    store = {}
    monkeypatch.setattr(service, "set_app_state", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(service, "get_app_state", lambda k, d=None: store.get(k, d))
    yield store


# ── 만료 처리 ───────────────────────────────────────────────────


def test_not_paused_by_default():
    assert service.is_gpu_paused() is False


def test_paused_while_future(_clear_pause):
    until = datetime.now() + timedelta(minutes=30)
    _clear_pause[service._STATE_GPU_PAUSE] = until.isoformat()
    assert service.is_gpu_paused() is True


def test_expired_auto_resumes(_clear_pause):
    """복구를 잊어도 만료되면 자동으로 돌아온다."""
    past = datetime.now() - timedelta(minutes=1)
    _clear_pause[service._STATE_GPU_PAUSE] = past.isoformat()

    assert service.is_gpu_paused() is False
    assert _clear_pause[service._STATE_GPU_PAUSE] is None, "만료값이 정리되지 않았다"


def test_corrupt_value_is_cleared(_clear_pause):
    _clear_pause[service._STATE_GPU_PAUSE] = "not-a-timestamp"
    assert service.is_gpu_paused() is False


# ── 잡 스킵 ─────────────────────────────────────────────────────


def test_scheduled_scan_skips_while_paused(monkeypatch, _clear_pause):
    """해제 중 스캔이 돌면 모델이 재적재되어 해제 목적이 무너진다."""
    until = datetime.now() + timedelta(minutes=30)
    _clear_pause[service._STATE_GPU_PAUSE] = until.isoformat()

    called = []
    monkeypatch.setattr(service, "_load_watchlist_files", lambda: called.append("x") or [])

    out = service._run_scheduled_scan_impl()

    assert out["status"] == "skipped" and out["reason"] == "gpu_paused"
    assert called == [], "해제 중인데 워치리스트를 읽었다"


def test_analyze_ticker_raises_while_paused(_clear_pause):
    """수동 스캔도 막아야 한다 — 막지 않으면 사용자가 모르고 GPU를 되살린다."""
    until = datetime.now() + timedelta(minutes=30)
    _clear_pause[service._STATE_GPU_PAUSE] = until.isoformat()

    with pytest.raises(service.GpuPausedError, match="자동 복귀"):
        service.analyze_ticker("IONQ")


def test_multi_agent_batch_skips_while_paused(_clear_pause):
    until = datetime.now() + timedelta(minutes=30)
    _clear_pause[service._STATE_GPU_PAUSE] = until.isoformat()

    out = service._run_multi_agent_batch_impl()
    assert out["status"] == "skipped" and out["reason"] == "gpu_paused"


# ── 언로드 실측 검증 ────────────────────────────────────────────


class _Resp:
    def __init__(self, payload=None):
        self._payload = payload or {}
        self.status_code = 200

    def json(self):
        return self._payload


def test_unload_uses_string_keep_alive(monkeypatch):
    """정수 0은 done_reason=unload만 오고 실제로 안 내려간다 (Ollama 0.20 실측)."""
    sent = []
    monkeypatch.setattr(service.httpx, "post",
                        lambda url, json=None, timeout=None: sent.append(json) or _Resp())
    monkeypatch.setattr(service, "_loaded_model_names", lambda: [])

    service._unload_ollama_model(verify_seconds=0.1)

    assert sent, "언로드 요청이 나가지 않았다"
    assert all(p.get("keep_alive") == "0s" for p in sent), f"정수 0 사용: {sent}"


def test_unload_returns_false_when_still_loaded(monkeypatch):
    """응답 200을 성공으로 읽으면 미반환이 '반환'으로 보고된다."""
    monkeypatch.setattr(service.httpx, "post", lambda *a, **k: _Resp())
    monkeypatch.setattr(service, "_loaded_model_names", lambda: ["qwen3:14b-q4_K_M"])

    assert service._unload_ollama_model(verify_seconds=0.2) is False


def test_unload_returns_true_when_freed(monkeypatch):
    monkeypatch.setattr(service.httpx, "post", lambda *a, **k: _Resp())
    calls = {"n": 0}

    def _names():
        calls["n"] += 1
        return ["qwen3:14b-q4_K_M"] if calls["n"] == 1 else []

    monkeypatch.setattr(service, "_loaded_model_names", _names)
    assert service._unload_ollama_model(verify_seconds=2.0) is True


# ── 요청 검증 ───────────────────────────────────────────────────


def test_pause_minutes_upper_bound():
    """무한 해제를 막는다 — 상한 없이 두면 서비스가 조용히 멈춘 채 방치된다."""
    with pytest.raises(Exception):
        service.GpuPauseRequest(minutes=service.GPU_PAUSE_MAX_MINUTES + 1)


def test_pause_minutes_must_be_positive():
    with pytest.raises(Exception):
        service.GpuPauseRequest(minutes=0)


def test_pause_default_is_one_hour():
    assert service.GpuPauseRequest().minutes == 60


def test_state_store_failure_fails_open(monkeypatch):
    """상태를 못 읽는다고 스캔·배치를 막으면 장애가 전파된다 (CI에서 실제 발생).

    app_state 테이블이 없는 환경에서 get_app_state가 OperationalError를 냈고,
    V2 배치 테스트가 통째로 실패했다.
    """
    import sqlite3

    def _boom(*a, **k):
        raise sqlite3.OperationalError("no such table: app_state")

    monkeypatch.setattr(service, "get_app_state", _boom)
    assert service.is_gpu_paused() is False
