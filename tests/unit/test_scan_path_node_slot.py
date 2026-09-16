"""스캔 경로의 Ollama 호출이 **집계에 보이는지** 고정한다.

2026-09-16, §13.9q 의 근인. 30분 스캔(`ChartAnalysisAgent._run_ollama_mode`)은
`analysis_tools.py` 에서 Ollama 를 **직접** 쳤다 — `node_slot` 을 거치지 않아
`node_load_snapshot()` 에 한 번도 잡히지 않았다.

두 가지가 깨져 있었다:

  1. 노드 동시 요청 제한이 이 경로에만 적용되지 않았다
  2. 헬스 프로브가 "노드가 바쁘다"를 알 수 없었다. 그래서 스캔 중 1토큰 프로브가
     큐 뒤에서 20초 타임아웃하고, **GPU 가 98%·250W 로 일하는 정상 노드를
     `unusable` 로 보고했다.** Mac 이었다면 그 시점에 라우팅에서 빠졌다

여기서 고정하는 것:
  1. 호출이 슬롯 안에서 일어난다 — 호출 시점에 in-flight 가 올라가 있다
  2. 끝나면 내려온다 (누수 없음)
  3. 슬롯을 못 잡아도 **분석은 진행된다** — 드러내는 변경이지 막는 변경이 아니다
  4. dual_node_config 를 못 불러와도 죽지 않는다
"""

import os
import sys

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
for _p in (_AGENT_DIR, _ANALYZER_DIR):
    if _p not in sys.path:  # noqa: E402
        sys.path.append(_p)

import analysis_tools as at  # noqa: E402
import dual_node_config as dn  # noqa: E402


def _clear_load():
    with dn._node_lock:
        dn._node_inflight.clear()


def test_slot_is_held_during_the_call():
    _clear_load()

    with at._local_node_slot() as acquired:
        assert acquired is True
        assert dn.node_load_snapshot().get("rtx_5070") == 1
        assert dn.node_is_busy("rtx_5070") is True

    assert dn.node_load_snapshot().get("rtx_5070", 0) == 0
    _clear_load()


def test_slot_is_released_even_on_failure():
    """호출이 터져도 in-flight 가 남으면 프로브가 영원히 건너뛴다."""
    _clear_load()

    try:
        with at._local_node_slot():
            raise RuntimeError("ollama 500")
    except RuntimeError:
        pass

    assert dn.node_load_snapshot().get("rtx_5070", 0) == 0
    _clear_load()


def test_analysis_proceeds_when_the_slot_is_unavailable(monkeypatch):
    """막는 변경이 아니다 — 이 경로는 원래 제한이 없었다."""
    _clear_load()
    monkeypatch.setenv("RTX_5070_MAX_INFLIGHT", "1")
    with dn._node_lock:
        dn._node_semaphores.clear()

    with dn.node_slot("rtx_5070", block=False) as first:
        assert first is True
        with at._local_node_slot() as acquired:
            assert acquired is False      # 슬롯은 못 잡았지만
            # 컨텍스트 안으로 들어왔다 = 호출이 진행된다

    with dn._node_lock:
        dn._node_semaphores.clear()
    _clear_load()


def test_missing_dual_node_config_does_not_break_the_scan(monkeypatch):
    """webui 없이 agent-api 만 도는 환경에서도 분석은 돌아야 한다."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "dual_node_config":
            raise ImportError("not available")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with at._local_node_slot() as acquired:
        assert acquired is False


def test_the_ollama_call_site_is_inside_the_slot():
    """구현이 슬롯 밖으로 되돌아가면 집계가 다시 비어 버린다."""
    import inspect
    import re

    src = inspect.getsource(at.ChartAnalysisAgent._run_ollama_agent)
    body = "\n".join(ln for ln in src.split("\n") if not ln.strip().startswith("#"))

    slot = re.search(r"^(\s*)with _local_node_slot\(\):", body, re.M)
    assert slot, "_run_ollama_agent 가 _local_node_slot 을 쓰지 않는다"

    call = re.search(r"^(\s*)resp = httpx\.post\(", body, re.M)
    assert call, "Ollama 호출부를 찾지 못했다"
    assert len(call.group(1)) > len(slot.group(1)), (
        "httpx.post 가 슬롯 컨텍스트 밖에 있다 — 부하가 집계되지 않는다"
    )
