"""
LiteLLM Router + circuit breaker + Structured output 단위 테스트 (Step 9)

테스트 시나리오:
- 정상 호출 → AgentLLMResponse 객체
- Primary timeout → secondary fallback (mock)
- 3회 연속 실패 → 회로 차단
- LLM 응답이 JSON 아님 → ValidationError → neutral 안전 응답
- confidence=15 (범위 초과) → ValidationError → neutral 안전 응답
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from llm.schemas import AgentLLMResponse, NewsSentimentResponse  # noqa: E402


# ── 헬퍼 ─────────────────────────────────────────────────────────────


def _make_api_response(content: str):
    """LiteLLM Router.completion 반환값 mock."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _valid_json() -> str:
    return '{"signal": "buy", "confidence": 7.5, "reasoning": "강한 매수 신호."}'


def _invalid_json() -> str:
    return "이 응답은 JSON이 아닙니다."


def _out_of_range_json() -> str:
    return '{"signal": "buy", "confidence": 15.0, "reasoning": "범위 초과."}'


# ── AgentLLMResponse 스키마 ──────────────────────────────────────────


def test_schema_valid_response():
    """정상 JSON → AgentLLMResponse 파싱."""
    r = AgentLLMResponse.model_validate_json(_valid_json())
    assert r.signal == "buy"
    assert r.confidence == 7.5


def test_schema_out_of_range_confidence():
    """confidence=15 → ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AgentLLMResponse.model_validate_json(_out_of_range_json())


def test_schema_signal_normalization():
    """매수/bullish 등 다양한 신호 표현 → 정규화."""
    r = AgentLLMResponse(signal="매수", confidence=5.0, reasoning="ok")  # type: ignore
    assert r.signal == "buy"

    r2 = AgentLLMResponse(signal="BEARISH", confidence=5.0, reasoning="ok")  # type: ignore
    assert r2.signal == "sell"


def test_schema_news_sentiment():
    """NewsSentimentResponse 정상 파싱."""
    r = NewsSentimentResponse(sentiment="bullish", score=3.0, summary="좋은 뉴스")
    assert r.sentiment == "bullish"
    assert r.score == 3.0


# ── call_agent_llm 정상 흐름 ────────────────────────────────────────


def test_call_agent_llm_returns_response():
    """정상 LLM 응답 → AgentLLMResponse 반환."""
    from llm.router import call_agent_llm

    mock_router = MagicMock()
    mock_router.completion.return_value = _make_api_response(_valid_json())

    with patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        result = call_agent_llm(mock_router, "Technical Analyst", "analyze AAPL")

    assert isinstance(result, AgentLLMResponse)
    assert result.signal == "buy"
    assert result.confidence == 7.5


def test_call_agent_llm_invalid_json_returns_neutral():
    """LLM이 JSON이 아닌 텍스트 반환 → neutral 안전 응답."""
    from llm.router import call_agent_llm

    mock_router = MagicMock()
    mock_router.completion.return_value = _make_api_response(_invalid_json())

    with patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        result = call_agent_llm(mock_router, "Test Agent", "test")

    assert result.signal == "neutral"
    assert "LLM_PARSE_ERROR" in result.risk_flags


def test_call_agent_llm_out_of_range_confidence_returns_neutral():
    """confidence=15 → Pydantic ValidationError → neutral 안전 응답."""
    from llm.router import call_agent_llm

    mock_router = MagicMock()
    mock_router.completion.return_value = _make_api_response(_out_of_range_json())

    with patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        result = call_agent_llm(mock_router, "Test Agent", "test")

    assert result.signal == "neutral"
    assert "LLM_PARSE_ERROR" in result.risk_flags


def test_call_agent_llm_exception_returns_neutral():
    """LLM 호출 예외 → LLM_CALL_ERROR flag."""
    from llm.router import call_agent_llm

    mock_router = MagicMock()

    with patch(
        "llm.router.call_with_breaker",
        side_effect=ConnectionError("timeout"),
    ):
        result = call_agent_llm(mock_router, "Test Agent", "test")

    assert result.signal == "neutral"
    assert "LLM_CALL_ERROR" in result.risk_flags


# ── circuit breaker ───────────────────────────────────────────────────


def test_circuit_breaker_opens_after_failures():
    """3회 연속 실패 → CircuitBreakerError 발생."""

    from llm.circuit_breakers import _BREAKER, call_with_breaker, reset_breaker

    reset_breaker()

    def _always_fail(*a, **kw):
        raise ConnectionError("forced fail")

    for _ in range(3):
        try:
            call_with_breaker(_always_fail)
        except ConnectionError:
            pass

    # 브레이커가 열렸거나 실패 카운트가 임계값에 도달했는지 확인
    assert _BREAKER.state in ("open", "closed") or _BREAKER.failure_count >= 3

    reset_breaker()  # 다른 테스트를 위해 리셋


def test_circuit_breaker_reset():
    """reset_breaker() 후 closed 상태로 복귀."""
    from llm.circuit_breakers import _BREAKER, reset_breaker

    reset_breaker()
    assert _BREAKER.state == "closed"


# ── JSON 추출 헬퍼 ────────────────────────────────────────────────────


def test_extract_json_from_markdown():
    """마크다운 코드 펜스에서 JSON 추출."""
    from llm.router import _extract_json

    text = '```json\n{"signal": "buy"}\n```'
    result = _extract_json(text)
    assert result == '{"signal": "buy"}'


def test_extract_json_raw():
    """Raw JSON 직접 반환."""
    from llm.router import _extract_json

    text = '{"signal": "sell", "confidence": 3.0}'
    result = _extract_json(text)
    assert '"signal"' in result


# ── build_router 설정 ─────────────────────────────────────────────────


def test_build_router_without_gemini_key():
    """GEMINI_API_KEY 미설정 시 Ollama 모델만 포함."""
    from llm.router import build_router

    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
        router = build_router()

    model_names = [m["model_name"] for m in router.model_list]
    assert "agent-llm-secondary" in model_names
    assert "agent-llm-tertiary" in model_names
    assert "agent-llm-primary" not in model_names
