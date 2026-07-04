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
    session = _Session()
    session.get_responses.append(_Response(200))
    monkeypatch.setattr(dual_node_config, "get_http_session", lambda: session)
    monkeypatch.setenv("MAC_STUDIO_HEALTH_TIMEOUT", "6.5")
    monkeypatch.setenv("MAC_STUDIO_HEALTH_TTL_SECONDS", "60")

    dual_node_config.reset_mac_studio_health_cache()

    assert dual_node_config.is_mac_studio_available(force_refresh=True) is True
    assert dual_node_config.is_mac_studio_available() is True
    assert len(session.get_calls) == 1
    assert session.get_calls[0][1] == 6.5


def test_mac_studio_health_requires_consecutive_failures(monkeypatch):
    session = _Session()
    session.get_responses.extend([
        _Response(200),
        TimeoutError("busy"),
        TimeoutError("still busy"),
    ])
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
    session = _Session()
    session.post_responses.append(_Response(200, {"response": '{"signal":"neutral"}'}))
    monkeypatch.setattr(dual_node_config, "get_http_session", lambda: session)
    monkeypatch.setenv("MAC_STUDIO_MAX_INFLIGHT", "1")
    monkeypatch.setenv("RTX_5070_MAX_INFLIGHT", "1")
    _reset_node_slots()

    agent = BaseAgent("Technical Analyst", [], "ollama")

    with dual_node_config.node_slot("mac_studio", block=False) as acquired:
        assert acquired is True
        response = agent._call_ollama("prompt")

    assert response == '{"signal":"neutral"}'
    assert len(session.post_calls) == 1
    assert "localhost" in session.post_calls[0][0]
    assert session.post_calls[0][1]["model"] == "qwen2.5:14b-instruct-q4_K_M"
