"""Mac Studio 가용 판정 — 도달성이 아니라 **쓸 수 있는지**를 본다.

2026-09-14 진단. `/api/tags` 200 만 보던 `is_mac_studio_available()` 이 5일 내내
True 를 돌려주는 동안, 그 노드는 32B 모델을 **CPU 로** 돌리고 있었다:

    2026-09-09 13:50  다른 프로세스가 CPU 점유 (launchd KeepAlive)
    2026-09-09 13:51  Ollama: "failure during GPU discovery
                      — failed to finish discovery before timeout"
                      → load_tensors: offloaded 0/65 layers to GPU

Metal 은 정상 인식됐다(`Apple M1 Max, 25557 MiB free`). 레이어를 하나도 올리지
않았을 뿐이다. 실측 **0.5 tok/s**(복구 후 9.4) — 1/19 속도다. 그동안 8개 중 4개
에이전트(Technical/Quant/Risk/ML)가 그 노드로 갔고, LLM 타임아웃은 240초다.

같은 검사가 agent-api 쪽에는 이미 있었다 (`service._ollama_runtime_status`, #15).
**한 노드에서 배운 것을 다른 노드에 옮기지 않은 것**이 이 결함의 정체다.

여기서 고정하는 것:
  1. `/api/ps` 의 `size_vram` 으로 CPU 폴백을 잡는다
  2. CPU 폴백이면 가용에서 뺀다 — 라우팅이 RTX 단독으로 돌아간다
  3. 그건 '연결 실패'가 아니다 — 연속 실패 카운터로 덮지 않는다
  4. 적재 모델이 없으면 `idle` = **판정 불가**이지 '정상'이 아니다
  5. 게이트는 끌 수 있다 (`MAC_STUDIO_REQUIRE_GPU=false`)
"""

import os
import sys

import pytest

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _ANALYZER_DIR)

import dual_node_config as dn  # noqa: E402


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _model(name="qwen2.5:32b", size=20_000_000_000, vram=0):
    return {"name": name, "size": size, "size_vram": vram}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    dn.reset_mac_studio_health_cache()
    for key in ("MAC_STUDIO_REQUIRE_GPU", "MAC_STUDIO_MIN_GPU_FRACTION",
                "MAC_STUDIO_HEALTH_TTL_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MAC_STUDIO_HEALTH_TTL_SECONDS", "0")   # 캐시 무효화
    yield
    dn.reset_mac_studio_health_cache()


def _session(monkeypatch, tags=_Resp(), ps=None, generate=None):
    """/api/tags, /api/ps, /api/generate 응답을 따로 준다.

    2026-09-16: 적재 위치(`size_vram>0`)만으로는 '생성이 죽은 노드'를 못 잡아
    1토큰 생성 검사를 더했다 (test_generation_probe.py). 그래서 이 픽스처도
    `/api/generate` 를 받아야 한다 — 없으면 전부 `unusable` 로 떨어진다.
    """
    class S:
        def get(self, url, timeout=None):
            if url.endswith("/api/ps"):
                if isinstance(ps, Exception):
                    raise ps
                return ps if ps is not None else _Resp(200, {"models": []})
            if isinstance(tags, Exception):
                raise tags
            return tags

        def post(self, url, json=None, timeout=None):
            if isinstance(generate, Exception):
                raise generate
            return generate if generate is not None else _Resp(200, {"response": "ok"})

    monkeypatch.setattr(dn, "get_http_session", lambda: S())


# ── 런타임 판정 ───────────────────────────────────────────────────


def test_cpu_loaded_model_is_reported_as_cpu_fallback(monkeypatch):
    _session(monkeypatch, ps=_Resp(200, {"models": [_model(vram=0)]}))

    status = dn.mac_studio_runtime_status()

    assert status["status"] == "cpu_fallback"
    assert status["cpu_only_models"] == ["qwen2.5:32b"]
    assert status["models"][0]["gpu_fraction"] == 0.0


def test_gpu_loaded_model_is_reported_as_gpu(monkeypatch):
    _session(monkeypatch, ps=_Resp(200, {"models": [
        _model(size=26_474_817_536, vram=25_836_128_256)]}))

    status = dn.mac_studio_runtime_status()

    assert status["status"] == "gpu"
    assert status["models"][0]["gpu_fraction"] == pytest.approx(0.976, abs=0.002)


def test_partial_offload_below_threshold_is_cpu_fallback(monkeypatch):
    """일부만 올라간 것도 느리다 — 절반 미만이면 쓰지 않는다."""
    _session(monkeypatch, ps=_Resp(200, {"models": [_model(size=1000, vram=300)]}))

    assert dn.mac_studio_runtime_status()["status"] == "cpu_fallback"


def test_threshold_is_configurable(monkeypatch):
    monkeypatch.setenv("MAC_STUDIO_MIN_GPU_FRACTION", "0.2")
    _session(monkeypatch, ps=_Resp(200, {"models": [_model(size=1000, vram=300)]}))

    assert dn.mac_studio_runtime_status()["status"] == "gpu"


def test_no_loaded_model_is_idle_not_healthy(monkeypatch):
    """적재된 모델이 없으면 판정할 수 없다 — '정상'이라고 부르지 않는다."""
    _session(monkeypatch, ps=_Resp(200, {"models": []}))

    assert dn.mac_studio_runtime_status()["status"] == "idle"


def test_unreachable_ps_endpoint_keeps_the_reason(monkeypatch):
    _session(monkeypatch, ps=ConnectionError("connection refused"))

    status = dn.mac_studio_runtime_status()

    assert status["status"] == "unknown"
    assert "refused" in status["error"]


# ── 가용 판정 ─────────────────────────────────────────────────────


def test_cpu_fallback_node_is_not_available(monkeypatch):
    """이게 5일간 못 잡힌 상태다."""
    _session(monkeypatch, ps=_Resp(200, {"models": [_model(vram=0)]}))

    assert dn.is_mac_studio_available(force_refresh=True) is False

    snap = dn.mac_studio_health_snapshot()
    assert snap["runtime"] == "cpu_fallback"
    assert snap["cpu_only_models"] == ["qwen2.5:32b"]
    assert "CPU 폴백" in snap["last_error"]


def test_cpu_fallback_does_not_inflate_the_failure_counter(monkeypatch):
    """연결은 되고 있다 — 연속 실패로 세면 원인이 흐려진다."""
    _session(monkeypatch, ps=_Resp(200, {"models": [_model(vram=0)]}))

    for _ in range(3):
        dn.is_mac_studio_available(force_refresh=True)

    assert dn.mac_studio_health_snapshot()["failures"] == 0


def test_gpu_node_is_available(monkeypatch):
    _session(monkeypatch, ps=_Resp(200, {"models": [_model(size=1000, vram=990)]}))

    assert dn.is_mac_studio_available(force_refresh=True) is True
    assert dn.mac_studio_health_snapshot()["runtime"] == "gpu"


def test_idle_node_stays_available(monkeypatch):
    """판정 불가를 장애로 읽으면 기동 직후마다 노드가 빠진다."""
    _session(monkeypatch, ps=_Resp(200, {"models": []}))

    assert dn.is_mac_studio_available(force_refresh=True) is True
    assert dn.mac_studio_health_snapshot()["runtime"] == "idle"


def test_gate_can_be_disabled(monkeypatch):
    monkeypatch.setenv("MAC_STUDIO_REQUIRE_GPU", "false")
    _session(monkeypatch, ps=_Resp(200, {"models": [_model(vram=0)]}))

    assert dn.is_mac_studio_available(force_refresh=True) is True


def test_unreachable_node_is_still_unavailable(monkeypatch):
    """기존 동작 — 도달 자체가 안 되면 당연히 불가."""
    _session(monkeypatch, tags=ConnectionError("no route"))

    assert dn.is_mac_studio_available(force_refresh=True) is False
    assert dn.mac_studio_health_snapshot()["failures"] >= 1


def test_runtime_check_is_skipped_when_unreachable(monkeypatch):
    """도달도 안 되는데 /api/ps 를 또 때리지 않는다."""
    calls = []

    class S:
        def get(self, url, timeout=None):
            calls.append(url)
            raise ConnectionError("no route")

    monkeypatch.setattr(dn, "get_http_session", lambda: S())
    dn.is_mac_studio_available(force_refresh=True)

    assert not any(u.endswith("/api/ps") for u in calls)
