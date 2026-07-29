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
import time
from contextlib import nullcontext
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

# 스키마 미준수(파싱) 실패 시 동일 모델 최대 시도 횟수. 1 = 재시도 없음.
_PARSE_MAX_ATTEMPTS = 2


def _setting(name: str, default: str = "") -> str:
    """환경변수 우선, 없으면 chart_agent_service/config.py 설정값 사용."""
    if name in os.environ:
        return os.environ.get(name, "")

    try:
        from config import settings

        configured = getattr(settings, name, default)
        return str(configured) if configured is not None else default
    except Exception:
        return default


def _int_setting(name: str, default: int) -> int:
    try:
        return int(_setting(name, str(default)))
    except (TypeError, ValueError):
        return default


def _gemini_api_key() -> str:
    return _setting("GEMINI_API_KEY") or _setting("GOOGLE_API_KEY")


# ── Router 생성 ──────────────────────────────────────────────────────


def build_router() -> Router:
    """환경변수를 읽어 3-tier LiteLLM Router를 생성한다."""
    gemini_key = _gemini_api_key()
    mac_url = _setting("MAC_STUDIO_URL", "http://hsptest-macstudio:8080")
    rtx_url = _setting("OLLAMA_BASE_URL", "http://localhost:11434")
    gemini_model = _setting("GEMINI_MODEL", "gemini-2.0-flash")
    mac_model = _setting("OLLAMA_MAC_MODEL", "qwen2.5:32b-instruct-q4_K_M")
    rtx_model = _setting("OLLAMA_MODEL", "qwen3:14b-q4_K_M")
    ollama_timeout = _int_setting("MULTI_AGENT_LLM_TIMEOUT", 240)

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
                    "timeout": max(60, ollama_timeout),
                },
            },
            {
                "model_name": "agent-llm-tertiary",
                "litellm_params": {
                    "model": f"ollama/{rtx_model}",
                    "api_base": rtx_url,
                    "timeout": max(90, ollama_timeout),
                },
            },
        ]
    )

    return Router(
        model_list=model_list,
        fallbacks=[],          # [수정] 내부 폴백 비활성화. 외부 루프에서 node_slot 제어와 함께 폴백 처리.
        num_retries=0,         # [수정] 내부 재시도 비활성화. 좀비 스레드 방지.
        retry_after=1,
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
    preferred_provider: str | None = None,
    timeout_seconds: float | None = None,
) -> T:
    """
    LiteLLM Router + circuit breaker를 통해 LLM을 호출하고
    Pydantic 모델로 검증된 응답을 반환한다.

    파싱 실패 시 neutral 안전 응답을 반환하므로 호출자에서 예외 처리 불필요.

    timeout_seconds는 이 호출 **전체**의 예산이다. 후보 모델 폴백(3) × 파싱
    재시도(2)가 각각 timeout_seconds를 다시 쓰면 최악 6배까지 늘어나므로,
    진입 시 deadline을 고정하고 매 시도마다 남은 시간으로 잘라 쓴다.
    """
    if timeout_seconds is not None and timeout_seconds <= 0:
        return _safe_response(
            response_model, "deadline_exceeded_before_call", ["LLM_DEADLINE_EXCEEDED"]
        )

    deadline = (
        time.monotonic() + float(timeout_seconds) if timeout_seconds is not None else None
    )

    schema = response_model.model_json_schema()
    required_keys = schema.get("required") or list(
        (schema.get("properties") or {}).keys()
    )
    messages = [
        {
            "role": "system",
            "content": (
                f"You are {agent_role}. "
                "Respond with ONLY a single JSON object INSTANCE that fills in the "
                "values for the required keys. Output the answer values only — never "
                'echo the schema itself, and never include "properties", "description", '
                '"enum", "type", or "$defs" keys in your output.\n'
                f"Required keys: {', '.join(required_keys)}.\n"
                f"Schema (for reference only, do not repeat it): {json.dumps(schema)}"
            ),
        },
        {"role": "user", "content": prompt},
    ]

    model_candidates = _model_candidates(preferred_provider)
    last_exc: Exception | None = None

    for model_name in model_candidates:
        if deadline is not None and deadline - time.monotonic() <= 0:
            last_exc = last_exc or TimeoutError("deadline_exceeded")
            break

        if not _node_available_for_model(model_name):
            last_exc = RuntimeError(f"node_unavailable:{_node_for_model(model_name)}")
            logger.warning(
                "LLM node unavailable for %s via %s", agent_role, model_name
            )
            continue

        with _node_slot_for_model(model_name) as acquired:
            if not acquired:
                last_exc = RuntimeError(f"node_overloaded:{_node_for_model(model_name)}")
                logger.warning(
                    "LLM node overloaded for %s via %s", agent_role, model_name
                )
                continue

            # 파싱(스키마 미준수) 실패는 모델 환각인 경우가 많아 같은 모델로 1회
            # 재시도하고, 그래도 실패하면 다음 후보 모델로 폴백한다.
            for attempt in range(_PARSE_MAX_ATTEMPTS):
                try:
                    completion_kwargs = {
                        "response_format": {"type": "json_object"},
                    }
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            last_exc = TimeoutError("deadline_exceeded")
                            break
                        completion_kwargs["timeout"] = max(
                            1,
                            min(
                                remaining,
                                _model_timeout_cap(model_name),
                                300.0,
                            ),
                        )
                    api_response = call_with_breaker(
                        _do_router_completion,
                        router,
                        model_name,
                        messages,
                        breaker_name=f"agent_llm:{agent_role}:{model_name}",
                        **completion_kwargs,
                    )
                    _record_node_success_for_model(model_name)
                    raw = (api_response.choices[0].message.content or "").strip()
                    json_str = _extract_json(raw)
                    return response_model.model_validate_json(json_str)

                except ValidationError as exc:
                    last_exc = exc
                    logger.warning(
                        "LLM response parse fail for %s via %s (attempt %d/%d): %s",
                        agent_role,
                        model_name,
                        attempt + 1,
                        _PARSE_MAX_ATTEMPTS,
                        exc,
                    )
                    # 같은 모델 재시도 소진 시 루프 탈출 → 다음 후보 모델 폴백
                    continue

                except Exception as exc:
                    last_exc = exc
                    _record_node_failure_for_model(model_name, exc)
                    logger.warning(
                        "LLM call fail for %s via %s: %s", agent_role, model_name, exc
                    )
                    # 호출 자체 실패는 같은 모델 재시도 무의미 → 다음 후보로
                    break

    if isinstance(last_exc, ValidationError):
        return _safe_response(
            response_model, f"parse_error: {last_exc}", ["LLM_PARSE_ERROR"]
        )
    if isinstance(last_exc, TimeoutError):
        return _safe_response(
            response_model, "deadline_exceeded", ["LLM_DEADLINE_EXCEEDED"]
        )
    return _safe_response(
        response_model, f"call_error: {last_exc}", ["LLM_CALL_ERROR"]
    )


def _node_for_model(model_name: str) -> str | None:
    if model_name == "agent-llm-secondary":
        return "mac_studio"
    if model_name == "agent-llm-tertiary":
        return "rtx_5070"
    return None


def _model_timeout_cap(model_name: str) -> float:
    if model_name == "agent-llm-primary":
        return float(_int_setting("GEMINI_LLM_TIMEOUT", 30))
    return float(_int_setting("MULTI_AGENT_LLM_TIMEOUT", 240))


def _node_available_for_model(model_name: str) -> bool:
    node = _node_for_model(model_name)
    if node is None:
        return True

    # rtx_5070 은 로컬 최후 폴백 노드다. 누적 실패 cooldown 으로 완전히 차단하면
    # Mac/Gemini 동시 장애 시 모든 후보가 unavailable 이 되어 전체 에이전트가
    # 무응답(전원 장애)이 된다. 따라서 cooldown 게이트에서 제외하고 항상 시도
    # 대상으로 둔다. 동시성 제한은 node_slot 이, 실패 집계는 record_node_failure 가
    # 계속 담당한다.
    if node != "rtx_5070":
        try:
            from dual_node_config import is_node_in_cooldown

            if is_node_in_cooldown(node):
                return False
        except Exception:
            pass

    if node != "mac_studio":
        return True

    try:
        from dual_node_config import is_mac_studio_available

        return bool(is_mac_studio_available())
    except Exception:
        return True


def _node_slot_for_model(model_name: str):
    node = _node_for_model(model_name)
    if node is None:
        return nullcontext(True)

    try:
        from dual_node_config import node_slot

        return node_slot(node, block=False)
    except Exception:
        return nullcontext(True)


def _record_node_failure_for_model(model_name: str, exc: Exception) -> None:
    node = _node_for_model(model_name)
    if node is None:
        return
    try:
        from dual_node_config import record_node_failure

        record_node_failure(node, exc)
    except Exception:
        pass


def _record_node_success_for_model(model_name: str) -> None:
    node = _node_for_model(model_name)
    if node is None:
        return
    try:
        from dual_node_config import record_node_success

        record_node_success(node)
    except Exception:
        pass


def _model_candidates(preferred_provider: str | None = None) -> list[str]:
    provider = (preferred_provider or "").lower().strip()
    has_primary = _has_primary()

    if provider == "gemini" and has_primary:
        return ["agent-llm-primary", "agent-llm-secondary", "agent-llm-tertiary"]
    if provider == "ollama":
        return (
            ["agent-llm-secondary", "agent-llm-tertiary", "agent-llm-primary"]
            if has_primary
            else ["agent-llm-secondary", "agent-llm-tertiary"]
        )
    return (
        ["agent-llm-primary", "agent-llm-secondary", "agent-llm-tertiary"]
        if has_primary
        else ["agent-llm-secondary", "agent-llm-tertiary"]
    )


def _has_primary() -> bool:
    return bool(_gemini_api_key())


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
