"""30분 스캔 경로 — LLM 이 **실제로 답했는지** 결과에 남긴다.

배치 경로(#89)에 이은 스캔 경로. 스캔(`ChartAnalysisAgent._run_ollama_agent`)은 RTX 를
한 번 직접 부르고 다른 노드로 넘어가지 않는다. 그래서 폴백이 아니라 **무응답**을 본다.

종전에 무응답이 가려진 방식:
  1. 생성 호출이 실패해도 `agent_mode` 는 `ollama` 였다. 실패는 `llm_conclusion` 본문의
     `[LLM 오류]` 문구로만 남았다
  2. 200 인데 본문이 비어도 성공처럼 지나갔다
  3. `/api/tags` 가 죽으면 규칙 점수만 냈는데, 결과에 그 사실을 알리는 필드가 없었다
  4. 알림은 `[오류]` 접두사만 걸러서, `[LLM 오류] ...` 가 'LLM 판단' 제목 아래 나갔다
  5. 스캔 잡은 무응답과 무관하게 `completed` 만 보고했다

여기서 고정하는 것:
  - 결과마다 `llm_route` (배치와 같은 형태: planned/served_by/unserved/attempts + slot_acquired)
  - 스캔 잡 요약에 `llm_routing` + `degraded` (status 는 그대로 — 신호는 규칙 점수다)
  - 기록 없는 종목은 `unrecorded` 로 센다 — 답했다고 읽지 않는다
"""

import os
import sys
from contextlib import contextmanager, nullcontext
from unittest.mock import MagicMock

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.append(_ANALYZER_DIR)

import analysis_tools as at  # noqa: E402


def _agent() -> "at.ChartAnalysisAgent":
    """ChartAnalysisAgent without data — only the LLM step is under test."""
    agent = object.__new__(at.ChartAnalysisAgent)
    agent.ticker = "AAPL"
    agent.tool_results = []
    agent.run_all_tools = lambda: None
    agent.compute_composite_score = lambda: {
        "final_signal": "neutral",
        "composite_score": 0.5,
        "signal_distribution": {"buy": 1, "sell": 1, "neutral": 1},
    }
    agent._format_tool_results_for_llm = lambda: "tools"
    agent._build_agent_system_prompt = lambda: "system"
    return agent


def _tags_ok(*a, **kw):
    return MagicMock(status_code=200)


def _generate(body=None, exc=None):
    def post(*a, **kw):
        if exc:
            raise exc
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: body
        return resp

    return post


@pytest.fixture
def slot(monkeypatch):
    """Control whether `_local_node_slot` reports the slot as acquired."""
    state = {"acquired": True}

    @contextmanager
    def fake_slot():
        yield state["acquired"]

    monkeypatch.setattr(at, "_local_node_slot", fake_slot)
    return state


# ── 스캔 에이전트 ─────────────────────────────────────────────────────


def test_answered_call_is_served(monkeypatch, slot):
    monkeypatch.setattr(at.httpx, "get", _tags_ok)
    monkeypatch.setattr(at.httpx, "post", _generate({"response": "## 종합 판단\n관망"}))
    out = _agent()._run_ollama_agent()

    route = out["llm_route"]
    assert route["served_by"] == "rtx_5070" and route["unserved"] is False
    assert route["slot_acquired"] is True
    assert route["attempts"][0]["outcome"] == "ok"
    assert out["agent_mode"] == "ollama"


def test_failed_call_is_unserved_with_reason(monkeypatch, slot):
    monkeypatch.setattr(at.httpx, "get", _tags_ok)
    monkeypatch.setattr(at.httpx, "post", _generate(exc=TimeoutError("read timeout 180s")))
    out = _agent()._run_ollama_agent()

    route = out["llm_route"]
    assert route["unserved"] is True and route["served_by"] is None
    assert route["attempts"][0]["outcome"] == "call_error"
    assert "read timeout" in route["attempts"][0]["detail"]
    assert out["llm_conclusion"].startswith("[LLM 오류]")


@pytest.mark.parametrize("body", [{"response": ""}, {"response": "   "}, {}])
def test_empty_200_is_not_success(monkeypatch, slot, body):
    monkeypatch.setattr(at.httpx, "get", _tags_ok)
    monkeypatch.setattr(at.httpx, "post", _generate(body))
    out = _agent()._run_ollama_agent()

    assert out["llm_route"]["unserved"] is True
    assert out["llm_route"]["attempts"][0]["outcome"] == "empty"
    assert out["llm_conclusion"] == "[응답 없음]"


def test_unreachable_ollama_is_labelled_rule_only(monkeypatch, slot):
    def down(*a, **kw):
        raise ConnectionError("refused")

    monkeypatch.setattr(at.httpx, "get", down)
    out = _agent()._run_ollama_agent()

    assert out["agent_mode"] == "rule_only"
    assert out["llm_route"]["unserved"] is True
    assert out["llm_route"]["attempts"][0]["outcome"] == "unavailable"


def test_missing_slot_is_recorded_but_call_proceeds(monkeypatch, slot):
    slot["acquired"] = False
    monkeypatch.setattr(at.httpx, "get", _tags_ok)
    monkeypatch.setattr(at.httpx, "post", _generate({"response": "ok"}))
    out = _agent()._run_ollama_agent()

    assert out["llm_route"]["slot_acquired"] is False
    assert out["llm_route"]["unserved"] is False


def test_route_has_the_batch_shape():
    """배치 집계(`summarize_llm_routing`)와 같은 키를 쓴다."""
    route = at._scan_llm_route("ok", 0.0, True)
    for key in ("planned", "served_by", "fallback", "rotated", "unserved", "attempts"):
        assert key in route


# ── 스캔 잡 집계 ──────────────────────────────────────────────────────


def _route(outcome, slot_acquired=True):
    return at._scan_llm_route(outcome, 0.0, slot_acquired)


def test_scan_route_summary_counts():
    import service

    out = service._summarize_scan_routes(
        {
            "AAPL": _route("ok"),
            "MSFT": _route("call_error"),
            "IBM": _route("empty", slot_acquired=False),
            "FCX": None,  # 분석 예외 — 기록 없음
        }
    )
    assert out["calls"] == 3
    assert out["unserved"] == 2
    assert sorted(out["unserved_tickers"]) == ["IBM", "MSFT"]
    assert out["unrecorded_tickers"] == ["FCX"]
    assert out["outcomes"] == {"ok": 1, "call_error": 1, "empty": 1}
    assert out["slot_missed"] == 1


def _run_scan(monkeypatch, routes: dict):
    import data_collector
    import service

    def analyze(ticker, ai_mode="ollama"):
        if routes[ticker] == "raise":
            raise RuntimeError("data fetch failed")
        return {
            "final_signal": "neutral",
            "composite_score": 0.5,
            "confidence": 5.0,
            "llm_route": routes[ticker],
        }

    monkeypatch.setattr(service, "_gpu_pause_until", lambda: None)
    monkeypatch.setattr(service, "_load_watchlist_files", lambda: list(routes))
    monkeypatch.setattr(data_collector, "prefetch_ohlcv_batch", lambda t: None)
    monkeypatch.setattr(data_collector, "clear_ohlcv_cache", lambda: None)
    monkeypatch.setattr(service, "analyze_ticker", analyze)
    monkeypatch.setattr(service, "worker_connection_scope", nullcontext)
    monkeypatch.setattr(service, "insert_scan", lambda *a, **kw: 1)
    monkeypatch.setattr(service, "check_alert_condition", lambda *a: None)
    monkeypatch.setattr(service, "_try_insert_signal_outcome", lambda *a: None)
    monkeypatch.setattr(service, "build_data_health", lambda: None)
    monkeypatch.setattr(service, "_stage_latest_result_summary", lambda t: None)
    monkeypatch.setattr(service, "_flush_latest_result_summaries", lambda: None)
    monkeypatch.setattr(service, "_persist_scan_history", lambda: None)
    monkeypatch.setattr(service, "latest_results", {})
    monkeypatch.setattr(service, "scan_history", [])
    return service, service._run_scheduled_scan_impl()


def test_scan_job_reports_unserved_as_degraded_not_failed(monkeypatch):
    service, result = _run_scan(monkeypatch, {"AAPL": _route("ok"), "MSFT": _route("call_error")})

    assert result["status"] == "completed"
    assert result["degraded"] is True
    assert result["llm_routing"]["unserved_tickers"] == ["MSFT"]
    entry = service.scan_history[-1]["results"]
    assert entry["AAPL"]["llm_served"] is True
    assert entry["MSFT"]["llm_served"] is False


def test_clean_scan_is_not_degraded(monkeypatch):
    _, result = _run_scan(monkeypatch, {"AAPL": _route("ok"), "MSFT": _route("ok")})
    assert result["degraded"] is False
    assert result["llm_routing"]["calls"] == 2


def test_failed_ticker_is_unrecorded_and_degrades(monkeypatch):
    _, result = _run_scan(monkeypatch, {"AAPL": _route("ok"), "MSFT": "raise"})
    assert result["llm_routing"]["unrecorded_tickers"] == ["MSFT"]
    assert result["degraded"] is True


# ── 알림 ──────────────────────────────────────────────────────────────


def _alert_result(conclusion, route):
    return {
        "final_signal": "buy",
        "composite_score": 1.5,
        "confidence": 7.0,
        "tool_summaries": [],
        "llm_conclusion": conclusion,
        "llm_route": route,
    }


@pytest.mark.parametrize(
    "conclusion,route",
    [
        ("[LLM 오류] read timeout\n\n시스템 자동 판단: buy", _route("call_error")),
        ("[응답 없음]", _route("empty")),
        ("멀쩡해 보이는 본문", _route("call_error")),
    ],
)
def test_alert_does_not_present_a_failed_llm_as_its_judgement(conclusion, route):
    import service

    msg = service.format_alert_message("AAPL", _alert_result(conclusion, route))
    assert "LLM 판단" not in msg


def test_alert_includes_a_real_llm_judgement():
    import service

    msg = service.format_alert_message("AAPL", _alert_result("## 종합 판단\n매수", _route("ok")))
    assert "LLM 판단" in msg


def test_unknown_slot_state_is_not_counted_as_missed():
    """dual_node_config 가 없어 집계를 못 한 것은 과부하가 아니다."""
    import service

    out = service._summarize_scan_routes({"AAPL": _route("ok", slot_acquired=None)})
    assert out["slot_missed"] == 0


def test_scan_routing_survives_into_the_job_status(monkeypatch):
    """반환값만 보면 놓친다 — 잡 기록(/ops/jobs)에 실리는지 래퍼로 확인한다."""
    service, _ = _run_scan(monkeypatch, {"AAPL": _route("ok"), "MSFT": _route("call_error")})
    monkeypatch.setattr(service, "_persist_job_status", lambda: None)

    service.run_scheduled_scan()
    recorded = service._JOB_STATUS["watchlist_scan"]["last_result_summary"]

    assert recorded["degraded"] is True
    assert recorded["llm_routing"]["unserved_tickers"] == ["MSFT"]
    assert "elapsed_sec" in recorded
