"""Multi-agent decision-maker contract tests."""

from concurrent.futures import Future
from datetime import datetime
import os
import sys

import pytest

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

import multi_agent as multi_agent_module  # noqa: E402
from multi_agent import (  # noqa: E402
    AgentResult,
    BaseAgent,
    DecisionMaker,
    MultiAgentOrchestrator,
    _build_decision_maker,
)


class _FakeAgent:
    def __init__(self, name: str, llm_provider: str = "test"):
        self.name = name
        self.llm_provider = llm_provider


def test_legacy_decision_maker_fallback_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MULTI_AGENT_ALLOW_LEGACY_DECISION_MAKER", raising=False)
    monkeypatch.setitem(sys.modules, "enhanced_decision_maker", None)

    with pytest.raises(RuntimeError, match="legacy DecisionMaker fallback is disabled"):
        _build_decision_maker("test")


def test_legacy_decision_maker_fallback_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_ALLOW_LEGACY_DECISION_MAKER", "true")
    monkeypatch.setitem(sys.modules, "enhanced_decision_maker", None)

    dm = _build_decision_maker("test")

    assert isinstance(dm, DecisionMaker)
    assert dm.decision_maker_mode == "legacy_llm"
    assert dm.legacy_fallback_reason


def test_collect_agent_futures_converts_unfinished_future_to_agent_error():
    orchestrator = object.__new__(MultiAgentOrchestrator)
    finished_agent = _FakeAgent("Finished Agent")
    slow_agent = _FakeAgent("Slow Agent")

    finished_future = Future()
    finished_future.set_result(
        AgentResult(
            agent_name=finished_agent.name,
            signal="buy",
            confidence=7.0,
            reasoning="completed",
            evidence=[],
            llm_provider=finished_agent.llm_provider,
            execution_time=0.1,
        )
    )
    slow_future = Future()
    futures = {
        finished_future: finished_agent,
        slow_future: slow_agent,
    }
    warnings = []

    results = orchestrator._collect_agent_futures(
        futures=futures,
        done={finished_future},
        not_done={slow_future},
        timeout_seconds=1,
        warnings=warnings,
        started_at=datetime.now(),
    )

    assert len(results) == 2
    assert warnings == ["에이전트 실행 전체 타임아웃(1s) 초과: 1/2개 미완료"]
    assert slow_future.cancelled()
    assert results[0].agent_name == "Finished Agent"
    assert results[0].error is None
    assert results[1].agent_name == "Slow Agent"
    assert results[1].signal == "neutral"
    assert results[1].confidence == 0.0
    assert results[1].error == (
        "Agent timed out after 1s and was excluded from final aggregation"
    )


def test_analyze_converts_unfinished_futures_timeout_to_system_failure(monkeypatch):
    import ticker_verifier

    orchestrator = object.__new__(MultiAgentOrchestrator)
    orchestrator.agents = []
    orchestrator.ollama_healthy = True
    orchestrator.max_workers = 1
    orchestrator.decision_maker = None

    monkeypatch.setattr(
        MultiAgentOrchestrator,
        "_get_stock_name",
        lambda self, ticker: None,
    )
    monkeypatch.setattr(
        ticker_verifier,
        "verify_and_validate",
        lambda ticker: {
            "exists": True,
            "can_analyze": True,
            "company_name": ticker,
            "data_quality": {"quality_score": 80},
            "warnings": [],
        },
    )

    def _raise_unfinished_timeout(ticker):
        raise TimeoutError("7 (of 7) futures unfinished")

    monkeypatch.setattr(multi_agent_module, "fetch_ohlcv", _raise_unfinished_timeout)

    result = orchestrator.analyze("SPY")

    assert "error" not in result
    assert result["runtime"]["timeout_fallback"] is True
    assert result["final_decision"]["final_signal"] == "neutral"
    assert result["final_decision"]["system_failure"] is True
    assert "future timeout" in result["final_decision"]["consensus"]


def test_base_agent_parse_failure_never_infers_buy_from_text():
    agent = BaseAgent("Test Agent", [], "test")

    signal, confidence, reasoning = agent._parse_response("do not buy this stock")

    assert signal == "neutral"
    assert confidence == 0.0
    assert "neutral fallback" in reasoning


def test_decision_parse_failure_returns_zero_confidence_neutral():
    dm = DecisionMaker("test")

    decision = dm._parse_decision("strong buy, but not json")

    assert decision["final_signal"] == "neutral"
    assert decision["final_confidence"] == 0.0
    assert "Decision parsing failed" in decision["key_risks"]
