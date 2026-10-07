"""webui 호출 경로 테스트 — 기본은 HTTP 단일 경로.

2026-04-29 부터 webui 이미지에 chart_agent_service 가 들어가 `local_engine` import 가
성공했고, 그것만으로 in-process 모드가 켜졌다. webui 는 마운트되지 않은 자기 컨테이너의
빈 상태를 읽었다 — 2026-10-07 실측: /results 0건(agent-api 22), signal_outcomes 0건
(agent-api 8,860), 스캔 로그 0건(agent-api 5).
"""

import importlib
import os
import sys

import pytest

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _ANALYZER_DIR)


def _load(monkeypatch, mode):
    if mode is None:
        monkeypatch.delenv("WEBUI_ENGINE_MODE", raising=False)
    else:
        monkeypatch.setenv("WEBUI_ENGINE_MODE", mode)
    import ui.api_client as api_client

    return importlib.reload(api_client)


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    yield
    monkeypatch.delenv("WEBUI_ENGINE_MODE", raising=False)
    import ui.api_client as api_client

    importlib.reload(api_client)


def test_default_is_http_even_when_local_engine_is_importable(monkeypatch):
    """import 가능 여부로 모드를 정하면 안 된다 — 그게 5개월간의 결함이었다."""
    import types

    fake = types.ModuleType("local_engine")
    fake.engine_dispatch_get = lambda p: {"results": {}}
    fake.engine_dispatch_post = lambda *a, **k: {}
    fake.engine_get_chart_path = lambda t: ""
    monkeypatch.setitem(sys.modules, "local_engine", fake)

    client = _load(monkeypatch, None)
    assert client.WEBUI_ENGINE_MODE == "http"
    assert client.USE_LOCAL_ENGINE is False


def test_api_get_goes_to_agent_api_by_default(monkeypatch):
    client = _load(monkeypatch, None)
    calls = []

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": {"PLTR": {}}}

    def _get(url, timeout):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(client.httpx, "get", _get)
    assert client.api_get("/results") == {"results": {"PLTR": {}}}
    assert calls and calls[0].endswith("/results")


def test_local_mode_is_opt_in(monkeypatch):
    import types

    fake = types.ModuleType("local_engine")
    fake.engine_dispatch_get = lambda p: {"local": True}
    fake.engine_dispatch_post = lambda *a, **k: {}
    fake.engine_get_chart_path = lambda t: ""
    monkeypatch.setitem(sys.modules, "local_engine", fake)

    client = _load(monkeypatch, "local")
    assert client.USE_LOCAL_ENGINE is True
    assert client.api_get("/results") == {"local": True}


def test_unknown_mode_falls_back_to_http(monkeypatch):
    client = _load(monkeypatch, "bogus")
    assert client.USE_LOCAL_ENGINE is False
