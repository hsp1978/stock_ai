"""
LLM 호출용 Circuit Breaker (Step 9).

failure_threshold=3, recovery_timeout=300s (5분).
"""

from __future__ import annotations

import logging

import litellm
from circuitbreaker import CircuitBreaker, CircuitBreakerError  # noqa: F401

logger = logging.getLogger(__name__)

# 모든 LLM 호출이 공유하는 단일 브레이커
_BREAKER = CircuitBreaker(
    failure_threshold=3,
    recovery_timeout=300,
    expected_exception=(
        litellm.exceptions.Timeout,
        litellm.exceptions.RateLimitError,
        ConnectionError,
        TimeoutError,
    ),
    name="agent_llm",
    fallback_function=None,
)


def call_with_breaker(func, *args, **kwargs):
    """브레이커를 통해 func(*args, **kwargs)를 호출한다."""
    return _BREAKER.call(func, *args, **kwargs)


def reset_breaker() -> None:
    """브레이커를 닫힌 상태로 강제 리셋 (테스트·수동 복구용)."""
    _BREAKER.reset()
    logger.info("LLM circuit breaker reset to closed state")


def breaker_state() -> str:
    return str(_BREAKER.state)
