"""Gemini 모델 설정 — 죽은 기본값과 쿼터 구조.

2026-09-15 확인. 두 가지가 겹쳐 있었다:

1. **기본 모델이 폐기됐다.** `config.GEMINI_MODEL` 과 `router.build_router()` 의
   폴백 기본값이 `gemini-2.0-flash` 였는데 API 가 404 를 준다:
   "This model models/gemini-2.0-flash is no longer available.
    Please update your code to use models/gemini-3.6-flash"
   `.env` 가 덮어쓰고 있어 운영은 돌았지만, `.env` 없는 환경에서는 Gemini tier 가
   통째로 실패한다. 문서(CLAUDE.md·SYSTEM_OVERVIEW)도 죽은 모델을 적고 있었다.

2. **무료 등급 쿼터는 모델당 하루 20회다.** 429 본문:
   `GenerateRequestsPerDayPerProjectPerModel-FreeTier = 20`
   Gemini 에이전트 4개 × 워치리스트 7종목 = **배치 1회에 28회** → 한 모델로는 매일
   20회에서 끊기고 나머지가 Ollama 로 폴백된다. 기다려서 풀리는 문제가 아니라
   워크로드가 한도를 넘는 구조다.

쿼터가 **모델당** 계산되므로 다른 모델을 한 단계 더 두면 예산이 따로 잡힌다
(20 + 20 = 40 > 28). Router 의 내부 재시도/폴백은 좀비 스레드 방지로 꺼져 있어
(`num_retries=0`, `fallbacks=[]`) LiteLLM 에 맡기지 않고 `_model_candidates()` 의
외부 루프에 별도 tier 로 넣었다 — deadline 예산(#14)·노드 가용성 검사가 그대로 적용된다.
"""

import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from llm import router as rt  # noqa: E402

#: 폐기 확인된 모델 (2026-09-15). 기본값·문서에 남으면 안 된다.
_RETIRED = ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash-lite")


def test_default_model_is_not_a_retired_one():
    from config import Settings

    default = Settings.model_fields["GEMINI_MODEL"].default
    assert default not in _RETIRED, f"{default} 은 폐기된 모델이다"
    assert default == rt.DEFAULT_GEMINI_MODEL


def test_router_fallback_default_matches_config():
    """`.env` 가 없는 환경에서도 살아 있는 모델로 떨어져야 한다."""
    src = open(os.path.join(_AGENT_DIR, "llm", "router.py"), encoding="utf-8").read()

    for retired in _RETIRED:
        assert f'"{retired}"' not in src, f"router 에 폐기 모델 {retired} 잔존"
    assert rt.DEFAULT_GEMINI_MODEL not in _RETIRED


def test_fallback_model_differs_from_primary():
    """같은 모델이면 쿼터가 같이 소진돼 폴백 의미가 없다."""
    assert rt.DEFAULT_GEMINI_FALLBACK_MODEL != rt.DEFAULT_GEMINI_MODEL
    assert rt.DEFAULT_GEMINI_FALLBACK_MODEL not in _RETIRED


#: 폐기 사실을 **설명**하는 줄은 허용한다. 금지 대상은 현재 구성으로 적는 것이다.
_RETIREMENT_MARKERS = ("폐기", "404", "no longer available", "NOT_FOUND", "더 이상")


def test_docs_do_not_cite_retired_models():
    """문서가 죽은 모델을 현재 구성으로 적고 있으면 안 된다.

    이 테스트가 실제로 잡았다 — 모델을 교체하고도 SYSTEM_OVERVIEW 의 에이전트 표와
    요약 표가 `gemini-2.0-flash` 를 그대로 두고 있었다. 설정과 문서가 갈리면 다음
    사람이 죽은 모델로 되돌린다.
    """
    root = os.path.dirname(_AGENT_DIR)
    offenders = []
    for name in ("CLAUDE.md", os.path.join("docs", "SYSTEM_OVERVIEW.md")):
        for line in open(os.path.join(root, name), encoding="utf-8").read().splitlines():
            if not any(retired in line for retired in _RETIRED):
                continue
            if any(marker in line for marker in _RETIREMENT_MARKERS):
                continue
            offenders.append(f"{name}: {line.strip()[:90]}")

    assert not offenders, "폐기 모델을 현재 구성으로 적고 있다:\n  " + "\n  ".join(offenders)


# ── tier 구성 ─────────────────────────────────────────────────────


def _build(monkeypatch, *, key="k" * 39, model=None, alt=None):
    monkeypatch.setenv("GEMINI_API_KEY", key)
    if model is not None:
        monkeypatch.setenv("GEMINI_MODEL", model)
    if alt is not None:
        monkeypatch.setenv("GEMINI_FALLBACK_MODEL", alt)
    return rt.build_router()


def test_two_gemini_deployments_are_registered(monkeypatch):
    router = _build(monkeypatch, model="gemini-3.6-flash", alt="gemini-3.5-flash")
    deployments = {
        e["model_name"]: e["litellm_params"]["model"] for e in router.model_list
    }

    assert deployments["agent-llm-primary"] == "gemini/gemini-3.6-flash"
    assert deployments["agent-llm-primary-alt"] == "gemini/gemini-3.5-flash"


def test_identical_fallback_is_not_registered(monkeypatch):
    """같은 모델을 두 번 등록하면 쿼터가 같이 죽는다 — 의미가 없다."""
    router = _build(monkeypatch, model="gemini-3.6-flash", alt="gemini-3.6-flash")

    assert "agent-llm-primary-alt" not in {e["model_name"] for e in router.model_list}


def test_empty_fallback_is_allowed(monkeypatch):
    router = _build(monkeypatch, model="gemini-3.6-flash", alt="")

    assert "agent-llm-primary-alt" not in {e["model_name"] for e in router.model_list}
    assert "agent-llm-primary" in {e["model_name"] for e in router.model_list}


def test_no_gemini_key_registers_no_gemini_tier(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    router = rt.build_router()

    names = {e["model_name"] for e in router.model_list}
    assert not (names & set(rt.GEMINI_TIERS))


# ── 후보 순서 ─────────────────────────────────────────────────────


def _patch_candidates(monkeypatch, tiers):
    monkeypatch.setattr(rt, "_has_primary", lambda: bool(tiers))
    monkeypatch.setattr(rt, "_gemini_candidates", lambda: list(tiers))


def test_gemini_alt_comes_right_after_primary(monkeypatch):
    """429 를 받으면 Ollama 로 떨어지기 전에 다른 Gemini 모델을 먼저 쓴다."""
    _patch_candidates(monkeypatch, rt.GEMINI_TIERS)

    assert rt._model_candidates() == [
        "agent-llm-primary", "agent-llm-primary-alt",
        "agent-llm-secondary", "agent-llm-tertiary",
    ]


def test_ollama_preference_puts_gemini_last(monkeypatch):
    _patch_candidates(monkeypatch, rt.GEMINI_TIERS)

    assert rt._model_candidates("ollama") == [
        "agent-llm-secondary", "agent-llm-tertiary",
        "agent-llm-primary", "agent-llm-primary-alt",
    ]


def test_candidates_without_gemini_key(monkeypatch):
    _patch_candidates(monkeypatch, [])

    assert rt._model_candidates() == ["agent-llm-secondary", "agent-llm-tertiary"]


def test_alt_tier_uses_the_gemini_timeout_cap(monkeypatch):
    """Ollama 용 240초를 Gemini 에 쓰면 쿼터 오류를 4분간 기다린다."""
    monkeypatch.setenv("GEMINI_LLM_TIMEOUT", "30")
    monkeypatch.setenv("MULTI_AGENT_LLM_TIMEOUT", "240")

    assert rt._model_timeout_cap("agent-llm-primary") == 30.0
    assert rt._model_timeout_cap("agent-llm-primary-alt") == 30.0
    assert rt._model_timeout_cap("agent-llm-secondary") == 240.0


def test_alt_tier_is_not_bound_to_an_ollama_node():
    """Gemini tier 는 mac_studio/rtx 노드 게이트 대상이 아니다."""
    assert rt._node_for_model("agent-llm-primary-alt") is None
    assert rt._node_available_for_model("agent-llm-primary-alt") is True
