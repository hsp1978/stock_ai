import os
import sys

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _ANALYZER_DIR)

import dual_node_config  # noqa: E402
from multi_agent import BaseAgent  # noqa: E402


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"response": '{"signal":"buy"}'}

    def json(self):
        return self._payload


class _Session:
    def __init__(self):
        self.get_calls = []
        self.post_calls = []
        self.get_responses = []
        self.post_responses = []

    def get(self, url, timeout):
        self.get_calls.append((url, timeout))
        result = self.get_responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url, json, timeout):
        self.post_calls.append((url, json, timeout))
        result = self.post_responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _reset_node_slots():
    with dual_node_config._node_lock:
        dual_node_config._node_semaphores.clear()
        dual_node_config._node_inflight.clear()
        dual_node_config._node_overloads.clear()
    dual_node_config.reset_node_cooldowns()


def test_mac_studio_health_uses_longer_timeout_and_ttl_cache(monkeypatch):
    """TTL 캐시로 두 번째 호출은 네트워크를 타지 않는다.

    2026-09-14: 도달성 확인 뒤 `/api/ps` 로 가속기 상태까지 본다
    (test_mac_studio_gpu_gate.py). 그래서 한 번의 health 검사가 GET 2회다 —
    tags 그리고 ps. TTL 안의 재호출은 여전히 0회여야 한다.
    """
    session = _Session()
    session.get_responses.extend([
        _Response(200),                                     # /api/tags
        _Response(200, {"models": [                          # /api/ps
            {"name": "qwen2.5:32b", "size": 1000, "size_vram": 990}]}),
    ])
    # 2026-09-16: 적재 위치만으로는 '생성이 죽은 노드'를 못 잡아, 1토큰 생성 검사를
    # 더했다 (test_generation_probe.py). 그래서 health 검사가 GET 2회 + POST 1회다.
    session.post_responses.append(_Response(200, {"response": "ok"}))
    monkeypatch.setattr(dual_node_config, "get_http_session", lambda: session)
    monkeypatch.setenv("MAC_STUDIO_HEALTH_TIMEOUT", "6.5")
    monkeypatch.setenv("MAC_STUDIO_HEALTH_TTL_SECONDS", "60")

    dual_node_config.reset_mac_studio_health_cache()

    assert dual_node_config.is_mac_studio_available(force_refresh=True) is True
    assert dual_node_config.is_mac_studio_available() is True     # 캐시 적중
    assert [url.rsplit("/", 1)[-1] for url, _ in session.get_calls] == ["tags", "ps"]
    assert all(timeout == 6.5 for _, timeout in session.get_calls)
    # 생성 검사는 한 번만 — TTL 안의 재호출은 네트워크를 타지 않는다
    assert len(session.post_calls) == 1
    assert session.post_calls[0][0].endswith("/api/generate")


def test_mac_studio_health_requires_consecutive_failures(monkeypatch):
    session = _Session()
    session.get_responses.extend([
        _Response(200),                                      # /api/tags
        _Response(200, {"models": [                           # /api/ps
            {"name": "qwen2.5:32b", "size": 1000, "size_vram": 990}]}),
        TimeoutError("busy"),
        TimeoutError("still busy"),
    ])
    session.post_responses.append(_Response(200, {"response": "ok"}))  # 1토큰 생성 검사
    monkeypatch.setattr(dual_node_config, "get_http_session", lambda: session)
    monkeypatch.setenv("MAC_STUDIO_HEALTH_FAILURE_THRESHOLD", "2")

    dual_node_config.reset_mac_studio_health_cache()

    assert dual_node_config.is_mac_studio_available(force_refresh=True) is True
    assert dual_node_config.is_mac_studio_available(force_refresh=True) is True
    snapshot = dual_node_config.mac_studio_health_snapshot()
    assert snapshot["available"] is True
    assert snapshot["failures"] == 1

    assert dual_node_config.is_mac_studio_available(force_refresh=True) is False
    snapshot = dual_node_config.mac_studio_health_snapshot()
    assert snapshot["available"] is False
    assert snapshot["failures"] == 2


def test_node_slot_rejects_when_limit_is_full(monkeypatch):
    monkeypatch.setenv("MAC_STUDIO_MAX_INFLIGHT", "1")
    _reset_node_slots()

    with dual_node_config.node_slot("mac_studio", block=False) as acquired:
        assert acquired is True
        assert dual_node_config.node_load_snapshot()["mac_studio"] == 1
        with dual_node_config.node_slot("mac_studio", block=False) as nested_acquired:
            assert nested_acquired is False

    assert dual_node_config.node_load_snapshot()["mac_studio"] == 0


def test_node_failure_opens_cooldown_and_success_resets(monkeypatch):
    monkeypatch.setenv("LLM_NODE_FAILURE_THRESHOLD", "2")
    monkeypatch.setenv("LLM_NODE_COOLDOWN_SECONDS", "60")
    dual_node_config.reset_node_cooldowns("rtx_5070")

    dual_node_config.record_node_failure("rtx_5070", TimeoutError("first"))
    assert dual_node_config.is_node_in_cooldown("rtx_5070") is False

    dual_node_config.record_node_failure("rtx_5070", TimeoutError("second"))
    assert dual_node_config.is_node_in_cooldown("rtx_5070") is True

    snapshot = dual_node_config.node_capacity_snapshot()["rtx_5070"]
    assert snapshot["failure_count"] == 2
    assert snapshot["cooldown_remaining_sec"] > 0
    assert snapshot["last_error"] == "second"

    dual_node_config.record_node_success("rtx_5070")
    assert dual_node_config.is_node_in_cooldown("rtx_5070") is False
    snapshot = dual_node_config.node_capacity_snapshot()["rtx_5070"]
    assert snapshot["failure_count"] == 0


def test_ollama_falls_back_when_mac_node_is_overloaded(monkeypatch):
    """Mac 이 꽉 차면 RTX 로 넘어간다.

    2026-09-16: 에이전트를 Technical → Quant 로 바꿨다. 2:2 분산으로 Technical 의
    **기본 노드가 이미 RTX** 라 더 이상 'Mac 포화 → 폴백'을 검증하지 못한다
    (test_agent_node_balance.py). Quant 는 Mac 에 남아 있고, `_call_ollama` 의
    폴백 분기 대상 목록에도 들어 있다.
    """
    session = _Session()
    session.post_responses.append(_Response(200, {"response": '{"signal":"neutral"}'}))
    monkeypatch.setattr(dual_node_config, "get_http_session", lambda: session)
    monkeypatch.setenv("MAC_STUDIO_MAX_INFLIGHT", "1")
    monkeypatch.setenv("RTX_5070_MAX_INFLIGHT", "1")
    _reset_node_slots()

    agent = BaseAgent("Quant Analyst", [], "ollama")

    with dual_node_config.node_slot("mac_studio", block=False) as acquired:
        assert acquired is True
        response = agent._call_ollama("prompt")

    assert response == '{"signal":"neutral"}'
    assert len(session.post_calls) == 1
    assert "localhost" in session.post_calls[0][0]
    assert session.post_calls[0][1]["model"] == "qwen2.5:14b-instruct-q4_K_M"
