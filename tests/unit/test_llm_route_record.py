"""LLM 호출이 **실제로 어디서** 처리됐는지 결과에 남긴다.

2026-09-29 17:30 배치(docs/SYSTEM_OVERVIEW.md §13.9w): RTX 에 배정된 에이전트
호출이 전부 Mac Studio 로 넘어갔다. Mac 호출은 29건에서 61건으로 늘었고 배치는
2,039초가 걸렸다(직전 662초). 폴백은 설계대로 동작했지만 잡 결과는 `completed` 뿐이라,
ollama 로그를 뒤지기 전에는 알 수 없었다.

라우터의 반환 타입은 호출자의 스키마라 "누가 답했나"를 실을 곳이 없었다.

여기서 고정하는 것:
  1. 라우터가 후보별 시도 결과를 route_log 에 남긴다 (ok/overloaded/unavailable/...)
  2. 요약은 fallback(다른 대상이 답함)과 unserved(아무도 못 답함)를 구분한다
     — 빈 이력은 unserved 다. 기록이 없는 호출을 정상으로 읽지 않는다
  3. 에이전트가 호출마다 요약을 쌓고, 오케스트레이터가 실행 전에 비운다
  4. 배치 요약에 `llm_routing` 과 `degraded` 가 실린다. status 는 그대로 둔다
     (폴백은 실패가 아니다). 텔레그램 요약에도 한 줄 나온다
"""

import inspect
import os
import sys
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.append(_ANALYZER_DIR)

from llm import router as rt  # noqa: E402

_OK = '{"signal": "buy", "confidence": 6.0, "reasoning": "ok"}'


def _api_response(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _call(slot_ok=lambda model: True, completion=None, **kwargs):
    """Run call_agent_llm as an ollama agent preferring RTX; return route_log."""
    router = MagicMock()
    router.completion.side_effect = completion or (lambda *a, **kw: _api_response(_OK))
    log: list[dict] = []
    with (
        patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}),
        patch("llm.router._node_available_for_model", return_value=True),
        patch(
            "llm.router._node_slot_for_model",
            side_effect=lambda model: nullcontext(slot_ok(model)),
        ),
        patch("llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)),
    ):
        response = rt.call_agent_llm(
            router,
            "Technical Analyst",
            "analyze AAPL",
            preferred_provider="ollama",
            preferred_node="rtx_5070",
            route_log=log,
            **kwargs,
        )
    return response, log


# ── 라우터 ────────────────────────────────────────────────────────────


def test_assigned_node_serving_is_not_a_fallback():
    response, log = _call()
    s = rt.summarize_route(log)

    assert response.signal == "buy"
    assert s["planned"] == "rtx_5070" and s["served_by"] == "rtx_5070"
    assert s["fallback"] is False and s["unserved"] is False


def test_overloaded_rtx_falling_back_to_mac_is_recorded():
    """09-29 의 형태: RTX 슬롯을 못 잡아 Mac 이 답했다."""
    _, log = _call(slot_ok=lambda model: model != "agent-llm-tertiary")
    s = rt.summarize_route(log)

    assert [e["outcome"] for e in log] == ["overloaded", "ok"]
    assert s["planned"] == "rtx_5070"
    assert s["served_by"] == "mac_studio"
    assert s["fallback"] is True and s["unserved"] is False


def test_call_error_carries_its_reason():
    calls = {"n": 0}

    def completion(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("503 maximum pending requests exceeded")
        return _api_response(_OK)

    _, log = _call(completion=completion)

    assert log[0]["outcome"] == "call_error"
    assert "maximum pending" in log[0]["detail"]
    assert rt.summarize_route(log)["served_by"] == "mac_studio"


def test_nobody_answering_is_unserved_not_fallback():
    def completion(*a, **kw):
        raise ConnectionError("down")

    response, log = _call(completion=completion)
    s = rt.summarize_route(log)

    assert response.signal == "neutral"  # 안전 응답
    assert s["served_by"] is None
    assert s["unserved"] is True and s["fallback"] is False


def test_parse_failure_on_every_candidate_is_unserved():
    _, log = _call(completion=lambda *a, **kw: _api_response("not json"))
    assert {e["outcome"] for e in log} == {"parse_error"}
    assert rt.summarize_route(log)["unserved"] is True


def test_deadline_before_any_attempt_is_recorded():
    _, log = _call(timeout_seconds=0)
    assert log and log[0]["outcome"] == "deadline"
    assert rt.summarize_route(log)["unserved"] is True


def test_empty_history_is_not_read_as_success():
    s = rt.summarize_route([])
    assert s["unserved"] is True


def test_route_log_is_optional():
    """기존 호출자(news_analyzer 등)는 인자 없이 그대로 동작한다."""
    router = MagicMock()
    router.completion.return_value = _api_response(_OK)
    with (
        patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}),
        patch("llm.router._node_available_for_model", return_value=True),
        patch("llm.router._node_slot_for_model", return_value=nullcontext(True)),
        patch("llm.router.call_with_breaker", side_effect=lambda fn, *a, **kw: fn(*a, **kw)),
    ):
        assert rt.call_agent_llm(router, "X", "p", preferred_provider="ollama").signal == "buy"


# ── 집계 ──────────────────────────────────────────────────────────────


def _entry(planned, served):
    return {
        "planned": planned,
        "served_by": served,
        "fallback": served is not None and served != planned,
        "unserved": served is None,
    }


def test_routing_summary_counts_and_transitions():
    import multi_agent

    out = multi_agent.summarize_llm_routing(
        {
            "Technical Analyst": [_entry("rtx_5070", "mac_studio")],
            "ML Specialist": [_entry("rtx_5070", "mac_studio"), _entry("rtx_5070", None)],
            "Risk Manager": [_entry("mac_studio", "mac_studio")],
        }
    )

    assert out["calls"] == 4
    assert out["fallback"] == 2 and out["unserved"] == 1
    assert out["served_by"] == {"mac_studio": 3}
    assert out["transitions"] == {"rtx_5070→mac_studio": 2, "rtx_5070→(none)": 1}
    assert out["affected_agents"] == {"Technical Analyst": 1, "ML Specialist": 2}


# ── 에이전트·오케스트레이터 ───────────────────────────────────────────


def test_agent_records_each_llm_call(monkeypatch):
    import multi_agent

    def fake_call(*args, route_log=None, **kwargs):
        route_log.extend(
            [
                {"model": "agent-llm-tertiary", "target": "rtx_5070", "outcome": "overloaded"},
                {"model": "agent-llm-secondary", "target": "mac_studio", "outcome": "ok"},
            ]
        )
        return MagicMock(
            signal="buy", confidence=6.0, reasoning="r", key_evidence=[], risk_flags=[]
        )

    monkeypatch.setattr("llm.router.call_agent_llm", fake_call)
    monkeypatch.setattr("llm.router.get_router", lambda: None)
    agent = multi_agent.TechnicalAnalyst()
    agent._call_llm("p")
    agent._call_llm("p")

    assert len(agent.llm_calls) == 2
    assert agent.llm_calls[0]["served_by"] == "mac_studio"
    assert agent.llm_calls[0]["fallback"] is True


def test_orchestrator_resets_and_reports_routing():
    """재사용되는 에이전트 인스턴스가 이전 종목의 이력을 끌고 오지 않는다."""
    import multi_agent

    src = inspect.getsource(multi_agent.MultiAgentOrchestrator.analyze)
    assert "agent.llm_calls = []" in src
    assert '"llm_routing": summarize_llm_routing(' in src
    assert '"llm_calls": llm_calls_by_agent.get(r.agent_name' in src


# ── 배치 ──────────────────────────────────────────────────────────────


def _batch(monkeypatch, llm_calls):
    import service

    class _Orch:
        def analyze(self, ticker):
            return {
                "ticker": ticker,
                "final_decision": {"final_signal": "neutral", "final_confidence": 4.0},
                "agent_results": [{"agent": "Technical Analyst", "llm_calls": llm_calls}],
                "llm_routing": service.summarize_llm_routing({"Technical Analyst": llm_calls}),
            }

    monkeypatch.setattr(service, "MultiAgentOrchestrator", _Orch)
    monkeypatch.setattr(service, "_load_watchlist_files", lambda: ["AAPL", "MSFT"])
    monkeypatch.setattr(service, "_try_insert_group_outcomes", lambda *a: None)
    return service, service._run_multi_agent_batch_impl()


def test_batch_with_fallback_is_completed_but_degraded(monkeypatch):
    service, result = _batch(monkeypatch, [_entry("rtx_5070", "mac_studio")])

    assert result["status"] == "completed"
    assert result["degraded"] is True
    assert result["llm_routing"]["fallback"] == 2  # 2종목 × 1호출
    assert result["llm_routing"]["transitions"] == {"rtx_5070→mac_studio": 2}
    assert result["signals"]["AAPL"]["llm_fallback"] == 1
    assert "LLM 경로 이탈 2/2호출" in service._format_batch_summary(result)


def test_clean_batch_is_not_degraded(monkeypatch):
    service, result = _batch(monkeypatch, [_entry("rtx_5070", "rtx_5070")])

    assert result["degraded"] is False
    assert result["llm_routing"]["calls"] == 2
    assert "LLM 경로 이탈" not in service._format_batch_summary(result)


# ── Gemini 쿼터 분산 ─────────────────────────────────────────────────


def test_gemini_quota_rotation_is_not_a_node_fallback():
    """3.6 → 3.5 는 쿼터를 나눠 쓰려는 설계다. 경보 대상이 아니다."""
    log = [
        {"model": "agent-llm-primary", "target": "gemini-3.6-flash", "outcome": "call_error"},
        {"model": "agent-llm-primary-alt", "target": "gemini-3.5-flash", "outcome": "ok"},
    ]
    s = rt.summarize_route(log)
    assert s["rotated"] is True
    assert s["fallback"] is False and s["unserved"] is False


def test_gemini_to_ollama_is_a_real_fallback():
    log = [
        {"model": "agent-llm-primary", "target": "gemini-3.6-flash", "outcome": "call_error"},
        {"model": "agent-llm-primary-alt", "target": "gemini-3.5-flash", "outcome": "call_error"},
        {"model": "agent-llm-secondary", "target": "mac_studio", "outcome": "ok"},
    ]
    s = rt.summarize_route(log)
    assert s["fallback"] is True and s["rotated"] is False


def test_rotation_does_not_degrade_the_batch(monkeypatch):
    rotated = {
        "planned": "gemini-3.6-flash",
        "served_by": "gemini-3.5-flash",
        "fallback": False,
        "rotated": True,
        "unserved": False,
    }
    service, result = _batch(monkeypatch, [rotated])

    assert result["degraded"] is False
    assert result["llm_routing"]["rotated"] == 2
    assert result["llm_routing"]["transitions"] == {}
