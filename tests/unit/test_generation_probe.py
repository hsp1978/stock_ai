"""노드가 **실제로 생성할 수 있는지** 확인한다 — 적재 위치만으로는 못 잡는다.

`docs/SYSTEM_OVERVIEW.md` §13.9p. 2026-09-16 실측, RTX 5070:

    /api/tags     200, 0.36ms
    /api/ps       qwen3:14b-q4_K_M  size_vram 10.8GB  gpu_fraction 1.0
    nvidia-smi    util 0%, 8.8W, 10,134/12,227 MiB
    /api/generate **모델 무관하게 60초 넘게 아무것도 생성하지 못함** (runner 교착)

그동안 `/health` 는 `ollama: connected, runtime: gpu` 를 보고했다.

§13.9h 에서 Mac Studio 에 넣은 게이트는 `size_vram > 0` 으로 **CPU 폴백**을 잡는다.
지금 RTX 는 CPU 폴백이 아니다 — GPU 에 100% 올라가 있는데도 쓸 수 없다. 적재 위치가
아니라 **생성 경로**를 봐야 잡히는 상태다. CLAUDE.md §13-3 이 경고한 형태다
("응답 코드 200을 성공으로 읽지 말 것 — Ollama 언로드도 200과 실패가 공존한다").

여기서 고정하는 것:
  1. 적재된 모델로 **1토큰만** 생성해 본다 (`num_predict: 1`)
  2. **모델이 적재돼 있을 때만** 시도한다 — 유휴 노드에 보내면 모델 로드를 유발해
     검사가 스스로 부하를 만든다
  3. 타임아웃은 `stalled` — '적재는 됐으나 생성 불가'를 별도 상태로 구분한다
  4. 적재 모델 없음(`idle`)은 `skipped` 이고 **'정상'이 아니다**
  5. 생성 실패 시 `runtime` 을 `unusable` 로 내려 라우팅에서 제외한다 (Mac)
"""

import asyncio
import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
for _p in (_AGENT_DIR, _ANALYZER_DIR):
    if _p not in sys.path:  # noqa: E402
        sys.path.append(_p)

import dual_node_config as dn  # noqa: E402
import service  # noqa: E402

_LOADED = {"models": [{"name": "qwen3:14b-q4_K_M", "on_gpu": True,
                       "size_bytes": 1000, "size_vram_bytes": 1000,
                       "gpu_fraction": 1.0}]}


# ── agent-api 쪽 (async 프로브) ───────────────────────────────────


class _FakeAsyncClient:
    def __init__(self, behavior):
        self._behavior = behavior

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        return self._behavior(url, json)


def _patch_async(monkeypatch, behavior):
    monkeypatch.setattr(
        service.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(behavior)
    )


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {"response": "ok"}

    def json(self):
        return self._payload

    def raise_for_status(self):
        # `_refresh_health_probe` 가 /api/ps 응답에 이걸 호출한다. 없으면
        # AttributeError 가 예외 처리로 흘러가 runtime 이 조용히 unknown 이 된다.
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_generation_ok_when_a_token_comes_back(monkeypatch):
    seen = {}

    def behavior(url, json):
        seen.update({"url": url, "json": json})
        return _Resp(200)

    _patch_async(monkeypatch, behavior)

    result = asyncio.run(service._probe_generation("http://rtx:11434", dict(_LOADED)))

    assert result["status"] == "ok"
    assert result["model"] == "qwen3:14b-q4_K_M"
    assert result["latency_ms"] is not None
    assert seen["url"].endswith("/api/generate")
    # 1토큰이면 충분하다 — 검사가 부하를 만들지 않아야 한다
    assert seen["json"]["options"]["num_predict"] == 1
    assert seen["json"]["stream"] is False


def test_timeout_is_stalled_not_error(monkeypatch):
    """이게 잡으려는 상태다 — 적재는 됐는데 생성이 안 된다."""
    def behavior(url, json):
        raise service.httpx.TimeoutException("read timeout")

    _patch_async(monkeypatch, behavior)

    result = asyncio.run(service._probe_generation("http://rtx:11434", dict(_LOADED)))

    assert result["status"] == "stalled"
    assert "생성하지 못했다" in result["detail"]


def test_non_200_is_error(monkeypatch):
    _patch_async(monkeypatch, lambda url, json: _Resp(500))

    result = asyncio.run(service._probe_generation("http://rtx:11434", dict(_LOADED)))

    assert result["status"] == "error"
    assert "HTTP 500" in result["detail"]


def test_connection_failure_keeps_the_reason(monkeypatch):
    def behavior(url, json):
        raise ConnectionError("connection refused")

    _patch_async(monkeypatch, behavior)

    result = asyncio.run(service._probe_generation("http://rtx:11434", dict(_LOADED)))

    assert result["status"] == "error"
    assert "refused" in result["detail"]


def test_idle_node_is_skipped_without_a_request(monkeypatch):
    """유휴 노드에 요청하면 모델 로드(수십 초)를 유발한다 — 검사가 부하가 된다."""
    def behavior(url, json):
        pytest.fail("적재 모델이 없는데 생성을 시도했다")

    _patch_async(monkeypatch, behavior)

    result = asyncio.run(service._probe_generation("http://rtx:11434", {"models": []}))

    assert result["status"] == "skipped"
    assert result["reason"] == "no_loaded_model"
    assert result["latency_ms"] is None


def test_skipped_is_not_treated_as_healthy(monkeypatch):
    """'판정 불가'를 ok 로 덮으면 이 게이트가 무의미해진다."""
    _patch_async(monkeypatch, lambda url, json: _Resp(200))

    result = asyncio.run(service._probe_generation("http://x", {"models": [{}]}))

    assert result["status"] == "skipped"
    assert result["reason"] == "model_name_unknown"


# ── runtime 판정 강등 ─────────────────────────────────────────────


def _patch_probe(monkeypatch, generation):
    async def fake(base_url, runtime):
        return generation

    monkeypatch.setattr(service, "_probe_generation", fake)


def _refresh(monkeypatch, *, tags=200, ps_models=None):
    class C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def get(self, url):
            if url.endswith("/api/ps"):
                return _Resp(200, {"models": ps_models if ps_models is not None else [
                    {"name": "qwen3:14b-q4_K_M", "size": 1000, "size_vram": 1000}]})
            return _Resp(tags)

    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kw: C())
    monkeypatch.setattr(service, "_market_sessions", lambda: {"KRX": "closed", "NYSE": "open"})
    return asyncio.run(service._refresh_health_probe())


def test_stalled_generation_downgrades_runtime_to_unusable(monkeypatch):
    _patch_probe(monkeypatch, {"status": "stalled", "detail": "20초 안에 …", "latency_ms": 20001})

    snap = _refresh(monkeypatch)

    assert snap["ollama_runtime"]["status"] == "unusable"
    assert "20초" in snap["ollama_runtime"]["unusable_reason"]
    assert snap["ollama_runtime"]["generation"]["status"] == "stalled"


def test_ok_generation_keeps_gpu_status(monkeypatch):
    _patch_probe(monkeypatch, {"status": "ok", "latency_ms": 120})

    snap = _refresh(monkeypatch)

    assert snap["ollama_runtime"]["status"] == "gpu"
    assert snap["ollama_runtime"]["generation"]["latency_ms"] == 120


def test_skipped_generation_does_not_downgrade(monkeypatch):
    """유휴는 장애가 아니다 — 기동 직후마다 unusable 이 되면 안 된다."""
    _patch_probe(monkeypatch, {"status": "skipped", "reason": "no_loaded_model"})

    snap = _refresh(monkeypatch, ps_models=[])

    assert snap["ollama_runtime"]["status"] == "idle"
    assert "unusable_reason" not in snap["ollama_runtime"]


def test_cpu_fallback_still_wins_over_generation(monkeypatch):
    """CPU 폴백이면 그 사유가 더 구체적이다 — unusable 로 덮지 않는다."""
    _patch_probe(monkeypatch, {"status": "ok", "latency_ms": 9000})

    snap = _refresh(
        monkeypatch,
        ps_models=[{"name": "m", "size": 1000, "size_vram": 0}],
    )

    assert snap["ollama_runtime"]["status"] == "cpu_fallback"


def test_health_exposes_generation(monkeypatch):
    _patch_probe(monkeypatch, {"status": "stalled", "detail": "…", "latency_ms": 20001})
    _refresh(monkeypatch)

    payload = asyncio.run(service.health())

    assert payload["ollama_runtime"]["status"] == "unusable"
    assert payload["ollama_runtime"]["generation"]["status"] == "stalled"


# ── Mac Studio 게이트 ─────────────────────────────────────────────


def _mac_session(monkeypatch, *, ps_models, generation):
    class S:
        def get(self, url, timeout=None):
            if url.endswith("/api/ps"):
                return _Resp(200, {"models": ps_models})
            return _Resp(200)

        def post(self, url, json=None, timeout=None):
            raise AssertionError("probe_node_generation 을 패치했는데 post 가 불렸다")

    monkeypatch.setattr(dn, "get_http_session", lambda: S())
    monkeypatch.setattr(dn, "probe_node_generation",
                        lambda base_url, model, timeout=None: generation)
    monkeypatch.setenv("MAC_STUDIO_HEALTH_TTL_SECONDS", "0")


@pytest.fixture(autouse=True)
def reset_mac_cache():
    dn.reset_mac_studio_health_cache()
    yield
    dn.reset_mac_studio_health_cache()


def test_mac_runtime_becomes_unusable_when_generation_stalls(monkeypatch):
    _mac_session(
        monkeypatch,
        ps_models=[{"name": "qwen2.5:32b", "size": 1000, "size_vram": 990}],
        generation={"status": "stalled", "detail": "20초 안에 1토큰도"},
    )

    status = dn.mac_studio_runtime_status()

    assert status["status"] == "unusable"
    assert "1토큰" in status["unusable_reason"]


def test_mac_unusable_node_is_not_available(monkeypatch):
    """라우팅에서 빠져야 한다 — 아니면 게이트가 판정만 바꾸고 끝난다."""
    _mac_session(
        monkeypatch,
        ps_models=[{"name": "qwen2.5:32b", "size": 1000, "size_vram": 990}],
        generation={"status": "stalled", "detail": "20초 안에 1토큰도"},
    )

    assert dn.is_mac_studio_available(force_refresh=True) is False

    snap = dn.mac_studio_health_snapshot()
    assert snap["runtime"] == "unusable"
    assert "생성 불가" in snap["last_error"]
    # 연결 실패가 아니므로 실패 카운터를 올리지 않는다
    assert snap["failures"] == 0


def test_mac_usable_node_stays_available(monkeypatch):
    _mac_session(
        monkeypatch,
        ps_models=[{"name": "qwen2.5:32b", "size": 1000, "size_vram": 990}],
        generation={"status": "ok", "latency_ms": 300},
    )

    assert dn.is_mac_studio_available(force_refresh=True) is True
    assert dn.mac_studio_health_snapshot()["runtime"] == "gpu"


def test_mac_idle_node_skips_generation_probe(monkeypatch):
    calls = []

    class S:
        def get(self, url, timeout=None):
            if url.endswith("/api/ps"):
                return _Resp(200, {"models": []})
            return _Resp(200)

    monkeypatch.setattr(dn, "get_http_session", lambda: S())
    monkeypatch.setattr(dn, "probe_node_generation",
                        lambda *a, **k: calls.append(1) or {"status": "ok"})

    status = dn.mac_studio_runtime_status()

    assert status["status"] == "idle"
    assert calls == [], "유휴 노드에 생성 요청을 보냈다"


# ── probe_node_generation 자체 ────────────────────────────────────


def test_node_generation_probe_sends_one_token(monkeypatch):
    seen = {}

    class S:
        def post(self, url, json=None, timeout=None):
            seen.update({"url": url, "json": json, "timeout": timeout})
            return _Resp(200)

    monkeypatch.setattr(dn, "get_http_session", lambda: S())

    result = dn.probe_node_generation("http://mac:8080/", "qwen2.5:32b", timeout=5.0)

    assert result["status"] == "ok"
    assert seen["url"] == "http://mac:8080/api/generate"
    assert seen["json"]["options"]["num_predict"] == 1
    assert seen["timeout"] == 5.0


def test_node_generation_probe_timeout_is_stalled(monkeypatch):
    import requests

    class S:
        def post(self, url, json=None, timeout=None):
            raise requests.exceptions.Timeout("read timeout")

    monkeypatch.setattr(dn, "get_http_session", lambda: S())

    result = dn.probe_node_generation("http://mac:8080", "qwen2.5:32b", timeout=1.0)

    assert result["status"] == "stalled"
    assert result["latency_ms"] is not None


def test_node_generation_probe_without_model_is_skipped():
    assert dn.probe_node_generation("http://x", None)["status"] == "skipped"


# ── RTX 는 게이트 대상이 아니다 (의도) ────────────────────────────


def test_rtx_stays_the_last_resort_node():
    """RTX 를 게이트하면 Mac·Gemini 동시 장애 시 전원 장애가 된다.

    `_node_available_for_model` 의 주석이 그 결정을 적고 있다. 생성 검사 결과는
    `/health` 로 **보이게만** 하고 라우팅에서 빼지 않는다.
    """
    from llm import router as rt

    assert rt._node_available_for_model("agent-llm-tertiary") is True
    src = __import__("inspect").getsource(rt._node_available_for_model)
    assert 'node != "rtx_5070"' in src
