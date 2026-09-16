"""AGENT_LLM_MAPPING 이 **적힌 대로 동작하는지** 고정한다.

2026-09-16, 2:2 분산을 적용하다 두 번 당했다. 둘 다 조용히 어긋나는 형태다.

  1. 중복 키 — 새 `"ML Specialist"`(rtx_5070)를 위에 넣었는데 구 항목이 아래
     남아 있었다. 파이썬 dict 리터럴은 **뒤엣것이 이긴다.** 매핑에는 rtx 라고
     적혀 있는데 실제로는 mac 으로 갔다. 문법 오류도 경고도 없다.

  2. 모델 별칭 오타 — RTX 의 qwen3 별칭은 `qwen3_14b` 인데 `qwen_14b`
     (qwen2.5:14b 폴백용)로 적었다. `get_llm_config()` 는

         node_config["models"].get(model_key, node_config["default_model"])

     로 **없는 키를 조용히 기본 모델로 대체**한다. 그래서 벤치마크한 모델이
     아닌 다른 모델이 돌아도 아무도 모른다.

둘 다 CLAUDE.md §13 의 형태다 — 설정이 거짓말을 하는데 실행은 성공한다.
여기서는 "매핑에 적힌 것"과 "실제로 쓰이는 것"이 같은지만 본다.
"""

import ast
import os
import sys
from collections import Counter

import pytest

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _ANALYZER_DIR)

import dual_node_config as dn  # noqa: E402

_SOURCE = os.path.join(_ANALYZER_DIR, "dual_node_config.py")


def _mapping_keys_in_source() -> list[str]:
    """소스에 **쓰여 있는** 키를 순서대로 준다 (dict 가 삼키기 전의 것)."""
    tree = ast.parse(open(_SOURCE, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "AGENT_LLM_MAPPING" for t in node.targets
        ):
            assert isinstance(node.value, ast.Dict)
            return [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
    pytest.fail("AGENT_LLM_MAPPING 대입문을 찾지 못했다")


def test_mapping_has_no_duplicate_agent_keys():
    """중복 키는 뒤엣것이 이긴다 — 적힌 것과 도는 것이 갈린다."""
    dupes = [k for k, n in Counter(_mapping_keys_in_source()).items() if n > 1]

    assert not dupes, f"AGENT_LLM_MAPPING 에 중복 키: {dupes}"


def test_every_source_key_survives_into_the_dict():
    """중복이 없다면 소스의 키 수와 dict 크기가 같아야 한다."""
    assert len(_mapping_keys_in_source()) == len(dn.AGENT_LLM_MAPPING)


@pytest.mark.parametrize("agent", sorted(dn.AGENT_LLM_MAPPING))
def test_ollama_entries_name_a_real_model_alias(agent):
    """별칭 오타는 `default_model` 로 조용히 대체된다 — 그걸 막는다."""
    entry = dn.AGENT_LLM_MAPPING[agent]
    if entry.get("provider") != "ollama":
        return

    node = entry["node"]
    assert node in dn.LLM_NODES, f"{agent}: 알 수 없는 노드 {node!r}"

    alias = entry["model"]
    models = dn.LLM_NODES[node]["models"]
    assert alias in models, (
        f"{agent}: {node} 에 모델 별칭 {alias!r} 가 없다 — "
        f"get_llm_config() 가 기본 모델로 조용히 대체한다. 있는 별칭: {sorted(models)}"
    )


@pytest.mark.parametrize("agent", sorted(dn.AGENT_LLM_MAPPING))
def test_resolved_config_matches_what_the_mapping_says(agent):
    """`get_llm_config()` 결과가 매핑 선언과 일치하는지 — 폴백에 가려지지 않게."""
    entry = dn.AGENT_LLM_MAPPING[agent]
    cfg = dn.get_llm_config(agent)

    assert cfg["provider"] == entry.get("provider", "ollama")
    if cfg["provider"] != "ollama":
        return

    assert cfg["node"] == entry["node"]
    assert cfg["model"] == dn.LLM_NODES[entry["node"]]["models"][entry["model"]]


def test_ollama_agents_are_split_across_both_nodes():
    """2026-09-16 분산의 의도를 고정한다.

    두 노드 모두 OLLAMA_NUM_PARALLEL=1 로 직렬 처리한다. 한 노드에 몰면 마지막
    에이전트가 앞의 것들을 전부 기다린다 — 실측 94.2초 대 40.3초(2.33배).
    다시 한쪽으로 모으려면 **그때의 실측을 근거로** 이 테스트를 고칠 것.
    """
    nodes = Counter(
        e["node"] for e in dn.AGENT_LLM_MAPPING.values() if e.get("provider") == "ollama"
    )

    assert len(nodes) >= 2, f"Ollama 에이전트가 한 노드에 몰려 있다: {dict(nodes)}"
    assert max(nodes.values()) - min(nodes.values()) <= 1, (
        f"노드 간 배분이 2 이상 어긋난다: {dict(nodes)}"
    )
