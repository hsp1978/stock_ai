"""Ollama 가속기 상태 감지 테스트.

/api/tags 200 응답은 데몬 생존만 증명한다. GPU 폴트로 모델이 CPU에 적재되면
추론이 ~10배 느려져 시간제한이 걸린 모든 LLM 호출이 타임아웃으로 죽는데,
기존 헬스체크는 이를 "connected"로 보고해 일주일간 은폐됐다.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def runtime_status():
    from service import _ollama_runtime_status

    return _ollama_runtime_status


def _resp(payload: dict) -> MagicMock:
    m = MagicMock()
    m.json.return_value = payload
    m.raise_for_status.return_value = None
    return m


def test_reports_gpu_when_model_resident_in_vram(runtime_status):
    payload = {
        "models": [
            {"name": "qwen3:14b", "size": 10_000_000_000, "size_vram": 9_500_000_000}
        ]
    }
    with patch("service.httpx.get", return_value=_resp(payload)):
        st = runtime_status()

    assert st["status"] == "gpu"
    assert st["models"][0]["on_gpu"] is True
    assert st["models"][0]["gpu_fraction"] == pytest.approx(0.95, abs=0.01)


def test_detects_cpu_fallback_when_size_vram_zero(runtime_status):
    """GPU 폴트 시 Ollama가 조용히 CPU로 적재하는 실제 장애 형태."""
    payload = {
        "models": [{"name": "qwen3:14b", "size": 10_000_000_000, "size_vram": 0}]
    }
    with patch("service.httpx.get", return_value=_resp(payload)):
        st = runtime_status()

    assert st["status"] == "cpu_fallback"
    assert st["cpu_only_models"] == ["qwen3:14b"]
    assert st["models"][0]["on_gpu"] is False


def test_partial_offload_still_counts_as_gpu(runtime_status):
    """일부 레이어만 GPU에 올라간 경우는 폴백이 아니다."""
    payload = {
        "models": [
            {"name": "qwen3:14b", "size": 10_000_000_000, "size_vram": 4_000_000_000}
        ]
    }
    with patch("service.httpx.get", return_value=_resp(payload)):
        st = runtime_status()

    assert st["status"] == "gpu"
    assert st["models"][0]["gpu_fraction"] == pytest.approx(0.4, abs=0.01)


def test_idle_when_no_model_loaded(runtime_status):
    with patch("service.httpx.get", return_value=_resp({"models": []})):
        st = runtime_status()

    assert st["status"] == "idle"
    assert st["models"] == []


def test_unreachable_daemon_reports_unknown_not_crash(runtime_status):
    with patch("service.httpx.get", side_effect=OSError("connection refused")):
        st = runtime_status()

    assert st["status"] == "unknown"
    assert "connection refused" in st["error"]
