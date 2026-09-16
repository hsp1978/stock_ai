"""에이전트 ↔ 노드 배정 — 한 노드에 몰리지 않게 한다.

`docs/SYSTEM_OVERVIEW.md` §13.9o. 17:30 배치가 7종목에 1,117초를 쓰는 이유를
측정했다. 한 종목(PLTR) 에이전트별 실측:

    ML Specialist      146.7초  (Mac)   │  Geopolitical Analyst  12.3초 (Gemini)
    Technical Analyst  132.3초  (Mac)   │  Event Analyst          8.7초 (Gemini)
    Risk Manager        91.0초  (Mac)   │  Value Investor         6.5초 (Gemini)
    Quant Analyst       46.8초  (Mac)   │
    ─────────────────────────────────── │
    Ollama 4개 합 417초                 │  Gemini 3개 합 27.5초

Mac Studio 단독 호출은 7.5초(9.7 tok/s)다. 4개를 한 노드에 몰아 큐가 쌓인 결과다.

2026-09-16: 2:2 로 나눴다. 위 '분산이 더 느리다'는 측정은 교착된 RTX 에서 잰
것이라 무효였고, 정상 노드 재측정은 94.2초 → 40.3초(2.33배 개선)다.
`test_current_node_assignment_is_the_measured_one` 의 docstring 참조.

원인이 둘이었다:
  1. `AGENT_LLM_MAPPING` 의 `node` 필드가 **라우터 경로에서 무시됐다** —
     `_call_llm` 이 provider 만 넘겨서 Ollama 에이전트 전부가
     `agent-llm-secondary`(Mac Studio)를 먼저 쳤다
  2. 매핑 자체가 Ollama 4개를 모두 mac_studio 로 배정했다
     ("Ollama 추론 작업 전부를 Mac Studio 로 집중")

여기서 고정하는 것:
  1. 노드 배정이 균형을 유지한다 (한 노드에 3개 이상 금지)
  2. `preferred_node` 가 라우터 후보 순서를 실제로 바꾼다
  3. 폴백 순서는 유지된다 — 지정 노드가 죽으면 다른 노드로 넘어간다
  4. Gemini 에이전트는 노드 지정이 없고 라우터가 무시한다
  5. tier↔노드 대응이 `_node_for_model()` 과 어긋나지 않는다
"""

import collections
import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
for _p in (_AGENT_DIR, _ANALYZER_DIR):
    if _p not in sys.path:  # noqa: E402
        sys.path.append(_p)

import dual_node_config as dn  # noqa: E402
from llm import router as rt  # noqa: E402


# ── 배정 균형 ─────────────────────────────────────────────────────


def _ollama_nodes() -> collections.Counter:
    return collections.Counter(
        cfg["node"]
        for cfg in dn.AGENT_LLM_MAPPING.values()
        if cfg.get("provider") == "ollama" and cfg.get("node")
    )


def test_current_node_assignment_is_the_measured_one():
    """지금 배정은 **측정으로 고른 것**이다 — 바꾸려면 다시 재고 바꿔라.

    2026-09-15 에 2:2 분산을 시도했다가 "2.2배 악화"로 되돌렸고, 이 테스트는
    `{"mac_studio": 4}` 를 고정하고 있었다. **그 측정이 무효였다.**

    당시 RTX 는 이미 교착 중이었다 (§13.9p — VRAM 100% 적재인데 1토큰도 생성
    못 하는 상태). Quant 320.1초·Risk 279.1초는 실효 ~2 tok/s 로, 정상 노드의
    값이 아니다. 나는 같은 문서에 "측정 직후 RTX 는 8토큰 요청조차 90초 내에
    끝내지 못했다"고 적어두고도, 그 관측이 **직전 측정을 소급 무효화한다**는
    함의를 읽지 않았다.

    `ollama serve` 재시작 후 정상 노드에서 다시 쟀다 (Gemini 미사용, 실제
    에이전트와 같은 호출 조건: think=False, temperature=0.0, num_thread=4,
    프롬프트 ~900 tok):

        A 현재(Mac 4)   벽시계 94.2초   34.2 / 54.2 / 74.2 / 94.2초
                                        ← 20초 간격 = 완전 직렬 큐잉
        B 2:2 분산      벽시계 40.3초   Mac 20.4·40.3 / RTX 5.9·8.4 (63 tok/s)
        ────────────────────────────────────────
        한 종목 Ollama 구간  2.33배 **개선**

    이득의 출처는 처리량이 아니라 **큐 길이**다. 두 노드 모두
    OLLAMA_NUM_PARALLEL=1 로 직렬 처리하므로, 4개를 한 노드에 몰면 마지막
    에이전트가 앞의 3개를 전부 기다린다.

    이 테스트는 여전히 '분산이 옳다'를 주장하지 않는다 — **현재 배정이 우연이
    아니라는 것**을 고정한다. 되돌리려면 그때의 실측을 근거로 함께 고칠 것.
    """
    counts = _ollama_nodes()

    assert dict(counts) == {"rtx_5070": 2, "mac_studio": 2}, (
        f"Ollama 노드 배정이 바뀌었다: {dict(counts)} — "
        "2:2 분산은 2026-09-16 정상 노드 실측(94.2초 → 40.3초)으로 고른 것이다. "
        "되돌리려면 그때의 측정을 근거로 제시할 것"
    )


def test_every_ollama_agent_names_a_known_node():
    for name, cfg in dn.AGENT_LLM_MAPPING.items():
        if cfg.get("provider") != "ollama":
            continue
        node = cfg.get("node")
        assert node in dn.LLM_NODES, f"{name}: 알 수 없는 노드 {node}"


def test_every_ollama_agent_model_exists_on_its_node():
    """노드에 없는 모델을 배정하면 그 에이전트는 항상 폴백으로 돈다."""
    for name, cfg in dn.AGENT_LLM_MAPPING.items():
        if cfg.get("provider") != "ollama":
            continue
        node, model_key = cfg["node"], cfg.get("model")
        available = dn.LLM_NODES[node]["models"]
        assert model_key in available, (
            f"{name}: {node} 에 모델 키 {model_key} 가 없다 (가능: {sorted(available)})"
        )


def test_gemini_agents_have_no_node():
    for name, cfg in dn.AGENT_LLM_MAPPING.items():
        if cfg.get("provider") == "gemini":
            assert cfg.get("node") is None, f"{name}: Gemini 인데 node 가 있다"


# ── 라우터가 노드 지정을 존중한다 ─────────────────────────────────


def _patch_gemini(monkeypatch, enabled=False):
    monkeypatch.setattr(rt, "_has_primary", lambda: enabled)
    monkeypatch.setattr(rt, "_gemini_candidates", lambda: ["agent-llm-primary"] if enabled else [])


def test_preferred_node_puts_that_tier_first(monkeypatch):
    _patch_gemini(monkeypatch)

    mac = rt._model_candidates("ollama", "mac_studio")
    rtx = rt._model_candidates("ollama", "rtx_5070")

    assert mac[0] == "agent-llm-secondary"
    assert rtx[0] == "agent-llm-tertiary"


def test_fallback_order_is_preserved(monkeypatch):
    """지정 노드가 죽으면 다른 노드로 넘어가야 한다 — 후보에서 빠지면 안 된다."""
    _patch_gemini(monkeypatch)

    rtx = rt._model_candidates("ollama", "rtx_5070")

    assert set(rtx) == {"agent-llm-secondary", "agent-llm-tertiary"}
    assert rtx == ["agent-llm-tertiary", "agent-llm-secondary"]


def test_no_preferred_node_keeps_the_default_order(monkeypatch):
    _patch_gemini(monkeypatch)

    assert rt._model_candidates("ollama") == [
        "agent-llm-secondary", "agent-llm-tertiary",
    ]


def test_unknown_node_falls_back_to_default_order(monkeypatch):
    """오타나 폐기된 노드명이 후보를 비워 버리면 안 된다."""
    _patch_gemini(monkeypatch)

    assert rt._model_candidates("ollama", "no_such_node") == [
        "agent-llm-secondary", "agent-llm-tertiary",
    ]
    assert rt._model_candidates("ollama", "") == [
        "agent-llm-secondary", "agent-llm-tertiary",
    ]


def test_gemini_preference_still_leads(monkeypatch):
    """노드 지정은 Ollama tier 안의 순서만 바꾼다."""
    _patch_gemini(monkeypatch, enabled=True)

    candidates = rt._model_candidates("gemini", "rtx_5070")

    assert candidates[0] == "agent-llm-primary"
    assert candidates[1:] == ["agent-llm-tertiary", "agent-llm-secondary"]


def test_tier_node_map_matches_node_for_model():
    """두 곳이 어긋나면 노드 게이트가 엉뚱한 노드를 검사한다."""
    for node, tier in rt.OLLAMA_TIER_BY_NODE.items():
        assert rt._node_for_model(tier) == node


# ── 에이전트가 노드를 전달한다 ────────────────────────────────────


def test_agents_pass_preferred_node_to_the_router():
    """`node` 필드가 라우터에 전달되지 않으면 매핑이 장식이 된다."""
    import inspect

    import multi_agent

    for func in (multi_agent.BaseAgent._call_llm, multi_agent.DecisionMaker._call_llm):
        src = inspect.getsource(func)
        assert "preferred_node=self._preferred_node()" in src, (
            f"{func.__qualname__} 가 preferred_node 를 넘기지 않는다"
        )


@pytest.mark.parametrize("agent,expected", [
    ("Technical Analyst", "rtx_5070"),
    ("ML Specialist", "rtx_5070"),
    ("Risk Manager", "mac_studio"),
    ("Quant Analyst", "mac_studio"),
    ("Value Investor", None),
    ("Decision Maker", None),
])
def test_preferred_node_lookup(agent, expected):
    import multi_agent

    assert multi_agent._preferred_node_for(agent) == expected


def test_unknown_agent_falls_back_to_the_local_node():
    """미등록 에이전트는 `get_llm_config` 가 rtx_5070 을 준다 (로컬 최후 폴백).

    처음엔 None 을 기대했는데 구현이 로컬 노드를 준다 — 의도된 동작이다
    (Mac 이 죽어도 로컬에서는 돌아야 한다). 기대를 구현에 맞췄다.
    """
    import multi_agent

    assert multi_agent._preferred_node_for("Nonexistent Agent") == "rtx_5070"


def test_preferred_node_lookup_never_raises(monkeypatch):
    """조회 실패가 에이전트 호출을 막으면 안 된다 — None 으로 떨어져야 한다."""
    import multi_agent

    import dual_node_config

    def boom(name):
        raise RuntimeError("mapping unavailable")

    monkeypatch.setattr(dual_node_config, "get_llm_config", boom)

    assert multi_agent._preferred_node_for("Technical Analyst") is None
