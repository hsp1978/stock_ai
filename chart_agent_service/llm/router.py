"""
LiteLLM Router — 3-tier fallback LLM 호출 인터페이스 (Step 9).

Tier 1: Gemini gemini-2.0-flash
Tier 2: Mac Studio Ollama qwen2.5:32b
Tier 3: RTX 5070 Ollama qwen3:14b

call_agent_llm() 는 Router를 통해 호출하고 AgentLLMResponse Pydantic 객체를 반환한다.
응답 파싱 실패 시 neutral 안전 응답을 반환하므로 호출자에서 예외 처리 불필요.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import TYPE_CHECKING, TypeVar

import litellm
from litellm import Router
from pydantic import BaseModel, ValidationError

from llm.circuit_breakers import call_with_breaker
from llm.schemas import AgentLLMResponse

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
litellm.set_verbose = False

T = TypeVar("T", bound=BaseModel)

# ── Router 생성 ──────────────────────────────────────────────────────


def build_router() -> Router:
    """환경변수를 읽어 3-tier LiteLLM Router를 생성한다."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    mac_url = os.environ.get("MAC_STUDIO_URL", "http://hsptest-macstudio:8080")
    rtx_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    mac_model = os.environ.get("OLLAMA_MAC_MODEL", "qwen2.5:32b-instruct-q4_K_M")
    rtx_model = os.environ.get("OLLAMA_MODEL", "qwen3:14b-q4_K_M")

    model_list = []

    if gemini_key:
        model_list.append(
            {
                "model_name": "agent-llm-primary",
                "litellm_params": {
                    "model": f"gemini/{gemini_model}",
                    "api_key": gemini_key,
                    "timeout": 30,
                },
            }
        )

    model_list.extend(
        [
            {
                "model_name": "agent-llm-secondary",
                "litellm_params": {
                    "model": f"ollama/{mac_model}",
                    "api_base": mac_url,
                    "timeout": 60,
                },
            },
            {
                "model_name": "agent-llm-tertiary",
                "litellm_params": {
                    "model": f"ollama/{rtx_model}",
                    "api_base": rtx_url,
                    "timeout": 90,
                },
            },
        ]
    )

    # fallback chain: primary → secondary → tertiary
    if gemini_key:
        fallbacks = [
            {"agent-llm-primary": ["agent-llm-secondary", "agent-llm-tertiary"]}
        ]
    else:
        fallbacks = [{"agent-llm-secondary": ["agent-llm-tertiary"]}]

    return Router(
        model_list=model_list,
        fallbacks=fallbacks,
        num_retries=2,
        retry_after=5,
        routing_strategy="usage-based-routing",
        set_verbose=False,
    )


# ── 모듈 수준 싱글톤 ─────────────────────────────────────────────────

_router: Router | None = None


def get_router() -> Router:
    global _router
    if _router is None:
        _router = build_router()
    return _router


# ── JSON 추출 헬퍼 ───────────────────────────────────────────────────


def _extract_json(text: str) -> str:
    """Markdown code fence 또는 raw JSON 블록을 추출한다."""
    if "```json" in text:
        m = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
    if "```" in text:
        m = re.search(r"```\s*(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return m.group(0)
    return text.strip()


# ── 실제 Router 호출 (circuit breaker 래핑) ──────────────────────────


def _do_router_completion(
    router: Router,
    model_name: str,
    messages: list[dict],
    **kwargs,
):
    """Router.completion 단순 래퍼 — 브레이커에서 call_with_breaker()로 감싼다."""
    return router.completion(model=model_name, messages=messages, **kwargs)


# ── 공개 API ─────────────────────────────────────────────────────────


def call_agent_llm(
    router: Router,
    agent_role: str,
    prompt: str,
    response_model: type[T] = AgentLLMResponse,  # type: ignore[assignment]
) -> T:
    """
    LiteLLM Router + circuit breaker를 통해 LLM을 호출하고
    Pydantic 모델로 검증된 응답을 반환한다.

    파싱 실패 시 neutral 안전 응답을 반환하므로 호출자에서 예외 처리 불필요.
    """
    schema = response_model.model_json_schema()
    messages = [
        {
            "role": "system",
            "content": (
                f"You are {agent_role}. "
                f"Respond ONLY in JSON matching this schema: {json.dumps(schema)}"
            ),
        },
        {"role": "user", "content": prompt},
    ]

    # tier 1 먼저 시도 (gemini or secondary)
    primary = "agent-llm-primary" if _has_primary() else "agent-llm-secondary"

    try:
        api_response = call_with_breaker(
            _do_router_completion,
            router,
            primary,
            messages,
            response_format={"type": "json_object"},
        )
        raw = (api_response.choices[0].message.content or "").strip()
        json_str = _extract_json(raw)
        return response_model.model_validate_json(json_str)

    except ValidationError as exc:
        logger.warning("LLM response parse fail for %s: %s", agent_role, exc)
        return _safe_response(
            response_model, f"parse_error: {exc}", ["LLM_PARSE_ERROR"]
        )

    except Exception as exc:
        logger.warning("LLM call fail for %s: %s", agent_role, exc)
        return _safe_response(response_model, f"call_error: {exc}", ["LLM_CALL_ERROR"])


def _has_primary() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY", ""))


def _safe_response(model_cls: type[T], reason: str, flags: list[str]) -> T:
    """Pydantic 기본값으로 채운 neutral 안전 응답을 반환한다."""
    try:
        return model_cls(  # type: ignore[return-value]
            signal="neutral",
            confidence=0.0,
            reasoning=reason[:500],
            key_evidence=[],
            risk_flags=flags,
        )
    except Exception:
        # schema가 달라 signal 필드가 없으면 빈 객체 반환
        return model_cls()  # type: ignore[return-value]
