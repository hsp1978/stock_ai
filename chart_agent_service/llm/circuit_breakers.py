"""
LLM 호출용 Circuit Breaker (Step 9).

failure_threshold=3, recovery_timeout=300s (5분).
"""

from __future__ import annotations

import logging
import threading

import litellm
from circuitbreaker import CircuitBreaker, CircuitBreakerError  # noqa: F401

logger = logging.getLogger(__name__)
_DEFAULT_BREAKER_NAME = "agent_llm"
_breaker_lock = threading.Lock()


def _new_breaker(name: str) -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=3,
        recovery_timeout=300,
        expected_exception=(
            litellm.exceptions.Timeout,
            litellm.exceptions.RateLimitError,
            ConnectionError,
            TimeoutError,
        ),
        name=name,
        fallback_function=None,
    )


# 기존 테스트/호출부 호환용 기본 브레이커.
_BREAKER = _new_breaker(_DEFAULT_BREAKER_NAME)
_BREAKERS: dict[str, CircuitBreaker] = {_DEFAULT_BREAKER_NAME: _BREAKER}


def _get_breaker(name: str) -> CircuitBreaker:
    with _breaker_lock:
        breaker = _BREAKERS.get(name)
        if breaker is None:
            breaker = _new_breaker(name)
            _BREAKERS[name] = breaker
        return breaker


def call_with_breaker(func, *args, breaker_name: str = _DEFAULT_BREAKER_NAME, **kwargs):
    """브레이커를 통해 func(*args, **kwargs)를 호출한다."""
    return _get_breaker(breaker_name).call(func, *args, **kwargs)


def reset_breaker(name: str | None = None) -> None:
    """브레이커를 닫힌 상태로 강제 리셋 (테스트·수동 복구용)."""
    targets = list(_BREAKERS.values()) if name is None else [_get_breaker(name)]
    for breaker in targets:
        breaker.reset()
    logger.info("LLM circuit breaker reset to closed state")


def breaker_state(name: str = _DEFAULT_BREAKER_NAME) -> str:
    return str(_get_breaker(name).state)
