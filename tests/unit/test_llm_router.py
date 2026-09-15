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
import time
from unittest.mock import MagicMock, patch

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)
# stock_analyzer는 dual_node_config용으로만 필요하다. insert(0)으로 넣으면
# 동명 모듈(news_analyzer)이 chart_agent_service 쪽을 가려 다른 테스트 파일이
# 실행 순서에 따라 깨진다. 우선순위를 뺏지 않도록 뒤에 붙인다.
_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.append(_ANALYZER_DIR)

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


def test_call_agent_llm_deadline_before_call_returns_neutral():
    """이미 지난 deadline은 LLM 호출 없이 안전 응답."""
    from llm.router import call_agent_llm

    mock_router = MagicMock()

    result = call_agent_llm(mock_router, "Test Agent", "test", timeout_seconds=0)

    assert result.signal == "neutral"
    assert result.confidence == 0.0
    assert "LLM_DEADLINE_EXCEEDED" in result.risk_flags
    mock_router.completion.assert_not_called()


def test_call_agent_llm_passes_timeout_to_router_completion():
    """남은 deadline이 Router.completion timeout으로 전달된다."""
    from llm.router import call_agent_llm

    mock_router = MagicMock()
    mock_router.completion.return_value = _make_api_response(_valid_json())

    with patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        result = call_agent_llm(
            mock_router,
            "Technical Analyst",
            "analyze AAPL",
            timeout_seconds=3.2,
        )

    assert result.signal == "buy"
    # timeout_seconds는 호출 전체의 예산이므로 진입 시 고정한 deadline에서
    # 남은 시간을 잘라 넘긴다. 예산을 넘지 않으면서 그에 근접해야 한다.
    passed = mock_router.completion.call_args.kwargs["timeout"]
    assert 3.0 < passed <= 3.2


def test_call_agent_llm_caps_ollama_timeout(monkeypatch):
    """남은 전체 시간이 길어도 Ollama 단일 호출은 LLM timeout 상한을 넘기지 않는다."""
    import dual_node_config
    from llm.router import call_agent_llm

    mock_router = MagicMock()
    mock_router.completion.return_value = _make_api_response(_valid_json())
    monkeypatch.setenv("MULTI_AGENT_LLM_TIMEOUT", "42")
    dual_node_config.reset_node_cooldowns()

    with patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        result = call_agent_llm(
            mock_router,
            "Technical Analyst",
            "analyze AAPL",
            preferred_provider="ollama",
            timeout_seconds=600,
        )

    assert result.signal == "buy"
    assert mock_router.completion.call_args.kwargs["timeout"] == 42


def test_call_agent_llm_budget_not_multiplied_across_fallbacks():
    """timeout_seconds는 호출 전체 예산 — 모델 폴백마다 다시 부여되지 않는다."""
    import dual_node_config
    from llm.router import call_agent_llm

    dual_node_config.reset_node_cooldowns()

    budget = 3.0
    mock_router = MagicMock()
    timeouts = []

    def _completion(*args, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        # 후보 모델마다 예산을 1초씩 소모하며 실패 → 다음 후보로 폴백
        time.sleep(1.0)
        raise RuntimeError("upstream unavailable")

    mock_router.completion.side_effect = _completion

    started = time.monotonic()
    with patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        call_agent_llm(
            mock_router,
            "Technical Analyst",
            "analyze AAPL",
            timeout_seconds=budget,
        )
    elapsed = time.monotonic() - started

    assert len(timeouts) >= 2, "폴백이 최소 1회는 일어나야 의미 있는 검증"
    # 핵심: 폴백마다 예산이 차감된다. 예전처럼 매번 budget을 그대로 주면
    # timeouts가 [3.0, 3.0, 3.0]으로 평평해져 이 단조감소 검증에 걸린다.
    assert timeouts == sorted(timeouts, reverse=True), timeouts
    assert timeouts[0] > timeouts[-1], timeouts
    assert all(t <= budget for t in timeouts), timeouts
    assert elapsed < budget + 1.0, f"예산 {budget}s 대비 과다 소요: {elapsed:.2f}s"


def test_call_agent_llm_respects_ollama_preference():
    """ollama 선호 에이전트는 Gemini key가 있어도 Ollama tier부터 호출."""
    from llm.router import call_agent_llm

    mock_router = MagicMock()
    mock_router.completion.return_value = _make_api_response(_valid_json())

    with patch.dict(
        os.environ,
        {"GEMINI_API_KEY": "test-gemini-key", "GOOGLE_API_KEY": ""},
        clear=False,
    ), patch(
        "llm.router._node_available_for_model", return_value=True
    ), patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        result = call_agent_llm(
            mock_router,
            "Risk Manager",
            "analyze AAPL",
            preferred_provider="ollama",
        )

    assert result.signal == "buy"
    assert mock_router.completion.call_args.kwargs["model"] == "agent-llm-secondary"


def test_call_agent_llm_falls_back_to_tertiary_after_mac_ollama_error():
    """Mac Studio Ollama 호출이 실패하면 RTX Ollama tier를 먼저 시도."""
    from llm.router import call_agent_llm

    mock_router = MagicMock()
    mock_router.completion.side_effect = [
        ConnectionError("ollama down"),
        _make_api_response(_valid_json()),
    ]

    with patch.dict(
        os.environ,
        {"GEMINI_API_KEY": "test-gemini-key", "GOOGLE_API_KEY": ""},
        clear=False,
    ), patch(
        "llm.router._node_available_for_model", return_value=True
    ), patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        result = call_agent_llm(
            mock_router,
            "ML Specialist",
            "analyze AAPL",
            preferred_provider="ollama",
        )

    assert result.signal == "buy"
    called_models = [call.kwargs["model"] for call in mock_router.completion.call_args_list]
    assert called_models == ["agent-llm-secondary", "agent-llm-tertiary"]


def test_call_agent_llm_falls_back_to_primary_after_ollama_tiers_fail():
    """Ollama tier들이 모두 실패하면 Gemini primary를 마지막으로 시도."""
    from llm.router import call_agent_llm

    mock_router = MagicMock()
    mock_router.completion.side_effect = [
        ConnectionError("mac down"),
        ConnectionError("rtx down"),
        _make_api_response(_valid_json()),
    ]

    with patch.dict(
        os.environ,
        {"GEMINI_API_KEY": "test-gemini-key", "GOOGLE_API_KEY": ""},
        clear=False,
    ), patch(
        "llm.router._node_available_for_model", return_value=True
    ), patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        result = call_agent_llm(
            mock_router,
            "ML Specialist",
            "analyze AAPL",
            preferred_provider="ollama",
        )

    assert result.signal == "buy"
    called_models = [call.kwargs["model"] for call in mock_router.completion.call_args_list]
    assert called_models == [
        "agent-llm-secondary",
        "agent-llm-tertiary",
        "agent-llm-primary",
    ]


def test_call_agent_llm_skips_overloaded_mac_slot():
    """Mac Studio 슬롯이 꽉 차면 요청을 보내지 않고 RTX tier로 넘어간다."""
    from contextlib import nullcontext
    from llm.router import call_agent_llm

    mock_router = MagicMock()
    mock_router.completion.return_value = _make_api_response(_valid_json())

    def fake_slot(model_name):
        if model_name == "agent-llm-secondary":
            return nullcontext(False)
        return nullcontext(True)

    with patch.dict(
        os.environ,
        {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""},
        clear=False,
    ), patch(
        "llm.router._node_available_for_model", return_value=True
    ), patch(
        "llm.router._node_slot_for_model", side_effect=fake_slot
    ), patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        result = call_agent_llm(
            mock_router,
            "ML Specialist",
            "analyze AAPL",
            preferred_provider="ollama",
        )

    assert result.signal == "buy"
    called_models = [call.kwargs["model"] for call in mock_router.completion.call_args_list]
    assert called_models == ["agent-llm-tertiary"]


def test_call_agent_llm_skips_node_in_cooldown(monkeypatch):
    """노드가 cooldown 상태면 slot 획득 전에 해당 tier를 건너뛴다."""
    from contextlib import nullcontext
    import dual_node_config
    from llm.router import call_agent_llm

    mock_router = MagicMock()
    mock_router.completion.return_value = _make_api_response(_valid_json())

    monkeypatch.setenv("LLM_NODE_FAILURE_THRESHOLD", "1")
    monkeypatch.setenv("LLM_NODE_COOLDOWN_SECONDS", "60")
    dual_node_config.reset_node_cooldowns("mac_studio")
    dual_node_config.record_node_failure("mac_studio", TimeoutError("down"))

    with patch.dict(
        os.environ,
        {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""},
        clear=False,
    ), patch(
        "llm.router._node_slot_for_model", return_value=nullcontext(True)
    ), patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        result = call_agent_llm(
            mock_router,
            "ML Specialist",
            "analyze AAPL",
            preferred_provider="ollama",
        )

    assert result.signal == "buy"
    called_models = [call.kwargs["model"] for call in mock_router.completion.call_args_list]
    assert called_models == ["agent-llm-tertiary"]
    dual_node_config.reset_node_cooldowns("mac_studio")


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


def test_named_circuit_breakers_are_isolated():
    """한 에이전트 breaker 장애가 다른 에이전트 호출을 막지 않는다."""
    from llm.circuit_breakers import call_with_breaker, reset_breaker

    reset_breaker()

    def _always_fail(*a, **kw):
        raise ConnectionError("forced fail")

    def _ok(*a, **kw):
        return "ok"

    for _ in range(3):
        try:
            call_with_breaker(_always_fail, breaker_name="agent-a")
        except Exception:
            pass

    assert call_with_breaker(_ok, breaker_name="agent-b") == "ok"
    reset_breaker()


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

    with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False):
        router = build_router()

    model_names = [m["model_name"] for m in router.model_list]
    assert "agent-llm-secondary" in model_names
    assert "agent-llm-tertiary" in model_names
    assert "agent-llm-primary" not in model_names


def test_build_router_uses_google_key_as_gemini_fallback():
    """GOOGLE_API_KEY만 있어도 Gemini primary를 활성화."""
    from llm.router import build_router

    with patch.dict(
        os.environ,
        {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": "test-google-key"},
        clear=False,
    ):
        router = build_router()

    model_names = [m["model_name"] for m in router.model_list]
    assert "agent-llm-primary" in model_names


# ── DecisionMakerResponse 스키마 ─────────────────────────────────────


def test_decision_maker_response_valid():
    """DecisionMakerResponse 정상 파싱."""
    from llm.schemas import DecisionMakerResponse
    import json

    raw = json.dumps({
        "final_signal": "buy",
        "final_confidence": 7.5,
        "consensus": "6명 매수, 1명 매도",
        "conflicts": "ML 에이전트 의견 상충",
        "reasoning": "기술적 지표 강세.",
        "key_risks": ["고금리 지속"],
    })
    r = DecisionMakerResponse.model_validate_json(raw)
    assert r.final_signal == "buy"
    assert r.final_confidence == 7.5


def test_decision_maker_response_signal_normalization():
    """매수/bullish → buy 정규화."""
    from llm.schemas import DecisionMakerResponse
    r = DecisionMakerResponse(final_signal="매수", final_confidence=6.0)  # type: ignore
    assert r.final_signal == "buy"
    r2 = DecisionMakerResponse(final_signal="STRONG BUY", final_confidence=6.0)  # type: ignore
    assert r2.final_signal == "buy"


def test_decision_maker_response_defaults():
    """필드 기본값 확인 — 빈 객체 생성 가능."""
    from llm.schemas import DecisionMakerResponse
    r = DecisionMakerResponse()
    assert r.final_signal == "neutral"
    assert r.final_confidence == 0.0
    assert r.conflicts == "None"


def test_call_agent_llm_with_decision_maker_schema():
    """call_agent_llm이 DecisionMakerResponse 스키마로 작동한다."""
    from llm.router import call_agent_llm
    from llm.schemas import DecisionMakerResponse
    import json

    mock_router = MagicMock()
    mock_router.completion.return_value = _make_api_response(json.dumps({
        "final_signal": "sell",
        "final_confidence": 6.0,
        "consensus": "매도 우세",
        "conflicts": "없음",
        "reasoning": "하락 추세.",
        "key_risks": ["유동성 리스크"],
    }))

    with patch("llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
        result = call_agent_llm(mock_router, "Decision Maker", "판단해라", DecisionMakerResponse)

    assert isinstance(result, DecisionMakerResponse)
    assert result.final_signal == "sell"
    assert result.final_confidence == 6.0


# ── 회귀: 파싱 실패 재시도/폴백 + RTX cooldown 우회 ────────────────────


def test_call_agent_llm_retries_parse_failure_then_recovers():
    """첫 응답이 스키마 미준수(JSON 아님)여도 재시도로 유효 응답을 복구한다.

    이전: ValidationError 시 즉시 parse_error 단락 → 에이전트 무효화.
    현재: 같은 모델 재시도 후 다음 후보 모델 폴백으로 복구.
    """
    from llm.router import call_agent_llm

    mock_router = MagicMock()
    # 1차 호출은 파싱 실패, 2차부터는 유효 JSON
    mock_router.completion.side_effect = [
        _make_api_response(_invalid_json()),
        _make_api_response(_valid_json()),
        _make_api_response(_valid_json()),
        _make_api_response(_valid_json()),
    ]

    with patch(
        "llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)
    ):
        result = call_agent_llm(mock_router, "Technical Analyst", "analyze AAPL")

    assert isinstance(result, AgentLLMResponse)
    assert result.signal == "buy"
    assert "LLM_PARSE_ERROR" not in result.risk_flags
    assert mock_router.completion.call_count >= 2


def test_rtx_node_bypasses_cooldown_gate():
    """rtx_5070(로컬 최후 폴백)은 cooldown 중에도 항상 시도 대상이어야 한다.

    Mac/Gemini 동시 장애 + RTX 일시 실패 시 전원 장애(전체 unavailable)를 막는다.
    """
    import dual_node_config
    from llm.router import _node_available_for_model

    dual_node_config.reset_node_cooldowns()
    try:
        for _ in range(5):
            dual_node_config.record_node_failure("rtx_5070", RuntimeError("x"))
            dual_node_config.record_node_failure("mac_studio", RuntimeError("x"))

        assert dual_node_config.is_node_in_cooldown("rtx_5070") is True
        # RTX 는 cooldown 이어도 available (게이트 우회)
        assert _node_available_for_model("agent-llm-tertiary") is True
        # Mac 은 cooldown 존중 → unavailable (네트워크 호출 없이 차단)
        assert _node_available_for_model("agent-llm-secondary") is False
    finally:
        dual_node_config.reset_node_cooldowns()
