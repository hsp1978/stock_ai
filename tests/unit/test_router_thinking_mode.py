"""Ollama tier 가 thinking 모드를 끄는지 고정한다.

2026-09-16 배치 실측. ML Specialist 가 7종목 × 2회 = **14회 전부** 스키마 검증에
실패했다. 오류는 `3 validation errors ... input_value={}` — 모델이 빈 객체를
반환했다.

원인은 두 설정의 충돌이다:

  - 이 경로는 `response_format={"type": "json_object"}` 로 응답을 받는다.
    Ollama 에서 그건 `format: json` 문법 제약이 된다
  - qwen3 는 thinking 이 **기본 ON** 이다. `<think>` 로 시작하려 하는데 문법이
    JSON 만 허용하므로 **즉시 `{}` 를 내고 끝낸다**

실측 (qwen3:14b-q4_K_M, format:json, 3회 반복):

    think 미지정   ->  '{}'                 eval 2 tok     (3/3 동일)
    think: false   ->  '{"signal": ...}'    eval 135 tok

`multi_agent.py` 의 직접 호출 경로에는 **이미 `think=False` 가 있었다.** 라우터
경로에만 없었다 — 한 경로에서 배운 것을 다른 경로에 옮기지 않은 형태다
(§13.9h 의 GPU 게이트와 같다).

증상이 고약한 이유: 실패가 조용하다. `{}` 는 HTTP 200 이고, 재시도 2회를 쓴 뒤
다른 노드로 폴백해 **결과는 나온다.** 느려질 뿐이라 로그를 안 보면 모른다.
CLAUDE.md §13-3 — "응답 코드 200을 성공으로 읽지 말 것."
"""

import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.append(_AGENT_DIR)

from llm import router as rt  # noqa: E402


def _ollama_entries(model_list):
    return [
        m for m in model_list
        if str(m["litellm_params"].get("model", "")).startswith("ollama/")
    ]


@pytest.fixture
def model_list(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    built = {}

    class _FakeRouter:
        def __init__(self, model_list, **kw):
            built["model_list"] = model_list

    monkeypatch.setattr(rt, "Router", _FakeRouter)
    rt.build_router()
    return built["model_list"]


def test_every_ollama_tier_disables_thinking(model_list):
    entries = _ollama_entries(model_list)

    assert entries, "Ollama tier 가 하나도 없다"
    for entry in entries:
        assert entry["litellm_params"].get("think") is False, (
            f"{entry['model_name']} 에 think=False 가 없다 — "
            "format:json 과 충돌해 모델이 '{}' 만 반환한다"
        )


def test_both_nodes_are_covered(model_list):
    """한 노드에만 넣으면 폴백했을 때 같은 증상이 난다."""
    names = {e["model_name"] for e in _ollama_entries(model_list)}

    assert {"agent-llm-secondary", "agent-llm-tertiary"} <= names


def test_gemini_tiers_do_not_get_the_ollama_flag(model_list, monkeypatch):
    """think 는 Ollama 전용이다 — Gemini 로 새면 요청이 깨질 수 있다."""
    for entry in model_list:
        if not str(entry["litellm_params"].get("model", "")).startswith("ollama/"):
            assert "think" not in entry["litellm_params"], (
                f"{entry['model_name']} 는 Ollama 가 아닌데 think 가 붙었다"
            )


def test_json_response_format_is_still_requested():
    """think=False 는 스키마 강제를 대체하지 않는다 — 둘 다 있어야 한다."""
    import inspect

    src = inspect.getsource(rt.call_agent_llm)

    assert '"response_format"' in src
    assert '"json_object"' in src
