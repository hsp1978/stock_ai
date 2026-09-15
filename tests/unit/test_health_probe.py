"""`/health` 는 스레드 슬롯을 쓰지 않는다.

`docs/SYSTEM_OVERVIEW.md` §15: "FastAPI 전 핸들러 sync + blocking I/O". 핸들러
86개가 전부 `def` 라 anyio 스레드풀(기본 **40**)에서 돈다.

2026-09-15 측정. `/health` **자체** 비용은 18ms 다:

    _ollama_runtime_status   3.27 ms   (httpx)
    gpu_pause_status         3.67 ms   (내부에서 또 httpx)
    get_market_session x2   10.63 ms   (CPU)
    나머지(메모리)            ~0 ms

그런데 느린 요청 45개(한도 40 초과)를 동시에 던지면 **30ms → 7.33초**가 된다.
자기 일이 느린 게 아니라 **스레드 슬롯을 못 받아 기다린 시간**이다. 컨테이너
헬스체크 timeout 은 2초다 (compose.yaml) — 지속 부하에서 unhealthy 로 떨어진다.

**86개를 async 로 바꾸는 것은 해법이 아니다.** 내부의 blocking 호출이 그대로면
이벤트 루프를 막아 더 나빠진다. 그래서 가용성이 걸린 `/health` 하나만 `async` 로
바꾸고, 네트워크·CPU 프로브는 백그라운드 태스크가 갱신한 스냅샷에서 읽는다.

여기서 고정하는 것:
  1. `/health` 는 `async def` 다 — sync 로 되돌리면 같이 굶는다
  2. 핸들러는 메모리만 읽는다 (build_data_health 인라인 호출 금지)
  3. 프로브 갱신은 `httpx.AsyncClient` 로 — blocking httpx 면 이벤트 루프가 멎는다
  4. 스냅샷 **나이**를 내보낸다. 한 번도 못 받았으면 stale 이다 (§13-4)
  5. 스레드풀 한도는 설정값으로 올린다
"""

import asyncio
import inspect
import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import service  # noqa: E402


def _source(name: str) -> str:
    """주석·docstring 을 제거한 코드. 설명 문구를 코드로 오인하지 않기 위해서다.

    이 세션에서 세 번 같은 실수를 했다 — `"...를 부르지 않는다"` 라고 적은 주석이
    원문 검색에서 위반으로 걸렸다. `ast.unparse` 는 주석을 버린다.
    """
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(service, name))))
    func = tree.body[0]
    body = func.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        func.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


# ── 핸들러 형태 ───────────────────────────────────────────────────


def test_health_handler_is_async():
    """sync 로 되돌리면 스레드풀 포화 때 같이 굶는다."""
    assert asyncio.iscoroutinefunction(service.health), (
        "/health 가 sync 로 돌아갔다 — 느린 요청 45개에서 7.33초가 된다"
    )


def test_health_reads_only_memory():
    """핸들러가 네트워크·무거운 계산을 직접 하면 async 로 만든 의미가 없다."""
    src = _source("health")

    for forbidden in ("httpx.get", "build_data_health()", "get_market_session",
                      "_ollama_runtime_status()"):
        assert forbidden not in src, f"/health 가 {forbidden} 을 직접 호출한다"
    assert "_health_probe_snapshot()" in src


def test_deep_health_endpoint_stays_sync():
    """실시간 진단용 경로는 스레드에서 돌아야 한다 (blocking 호출 포함)."""
    assert not asyncio.iscoroutinefunction(service.health_deep)
    src = _source("health_deep")
    assert "build_data_health()" in src


def test_probe_refresh_uses_async_client():
    """blocking httpx 를 쓰면 Ollama 가 멈출 때 이벤트 루프가 3초씩 멎는다."""
    src = _source("_refresh_health_probe")

    assert "httpx.AsyncClient" in src
    assert "httpx.get(" not in src
    # CPU 프로브는 워커 스레드로 보낸다
    assert "to_thread.run_sync" in src


def test_startup_raises_the_thread_limit():
    src = _source("_startup_restore_state")

    assert "total_tokens = API_THREAD_LIMIT" in src
    from config import Settings

    assert Settings.model_fields["API_THREAD_LIMIT"].default > 40


# ── 스냅샷 보고 ───────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_probe():
    saved = dict(service._HEALTH_PROBE)
    yield
    with service._HEALTH_PROBE_LOCK:
        service._HEALTH_PROBE.clear()
        service._HEALTH_PROBE.update(saved)


def _set_probe(**kw):
    with service._HEALTH_PROBE_LOCK:
        service._HEALTH_PROBE.clear()
        service._HEALTH_PROBE.update({
            "probed_at": None, "probed_wall": None, "ollama_ok": False,
            "ollama_runtime": {"status": "unknown", "models": []},
            "market_session": {"KRX": "unknown", "NYSE": "unknown"},
            "error": None, **kw,
        })


def test_never_probed_is_stale_not_healthy_looking():
    """한 번도 못 받은 값을 '최신'처럼 내보내면 안 된다."""
    _set_probe(probed_at=None)

    snap = service._health_probe_snapshot()

    assert snap["probe_age_sec"] is None
    assert snap["probe_stale"] is True


def test_fresh_probe_is_not_stale():
    import time as _time

    _set_probe(probed_at=_time.monotonic(), ollama_ok=True)

    snap = service._health_probe_snapshot()

    assert snap["probe_age_sec"] is not None and snap["probe_age_sec"] < 1
    assert snap["probe_stale"] is False


def test_old_probe_is_marked_stale():
    """백그라운드 루프가 죽으면 값이 늙는다 — 그 사실이 드러나야 한다."""
    import time as _time
    from config import HEALTH_PROBE_INTERVAL_SECONDS

    _set_probe(probed_at=_time.monotonic() - HEALTH_PROBE_INTERVAL_SECONDS * 5)

    assert service._health_probe_snapshot()["probe_stale"] is True


def test_health_payload_carries_probe_metadata():
    import time as _time

    _set_probe(probed_at=_time.monotonic(), probed_wall="2026-09-15T04:00:00",
               ollama_ok=True,
               ollama_runtime={"status": "gpu", "models": []},
               market_session={"KRX": "closed", "NYSE": "open"})

    payload = asyncio.run(service.health())

    assert payload["ollama"] == "connected"
    assert payload["ollama_runtime"]["status"] == "gpu"
    assert payload["market_session"] == {"KRX": "closed", "NYSE": "open"}
    assert payload["probe"]["stale"] is False
    assert payload["probe"]["probed_at"] == "2026-09-15T04:00:00"


def test_health_reports_not_computed_data_health(monkeypatch):
    """스냅샷이 없으면 인라인 계산 대신 그렇게 적는다."""
    import time as _time

    _set_probe(probed_at=_time.monotonic())
    monkeypatch.setattr(service, "_LAST_DATA_HEALTH", {})
    monkeypatch.setattr(service, "build_data_health",
                        lambda *a, **k: pytest.fail("/health 가 build_data_health 를 불렀다"))

    payload = asyncio.run(service.health())

    assert payload["data_health"] == {"status": "not_computed"}


# ── 분류 로직 공유 ────────────────────────────────────────────────


@pytest.mark.parametrize("models,expected", [
    ([], "idle"),
    ([{"name": "m", "size": 100, "size_vram": 100}], "gpu"),
    ([{"name": "m", "size": 100, "size_vram": 0}], "cpu_fallback"),
])
def test_ollama_classification_is_shared(models, expected):
    """동기·비동기 경로가 같은 판정을 써야 한다 (한쪽만 고쳐지는 것 방지)."""
    assert service._classify_ollama_models(models)["status"] == expected


def test_gpu_pause_snapshot_does_not_requery():
    """이미 받아 둔 runtime 을 쓴다 — /health 의 httpx 3회가 여기서 왔다."""
    src = _source("_gpu_pause_snapshot")

    assert "_ollama_runtime_status" not in src
    snap = service._gpu_pause_snapshot(
        {"status": "gpu", "models": [{"name": "m", "on_gpu": True, "size_vram_bytes": 10}]}
    )
    assert snap["ollama_runtime"] == "gpu"
    assert snap["vram_bytes"] == 10
    assert snap["models_on_gpu"] == ["m"]
