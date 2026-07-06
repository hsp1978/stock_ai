"""일일 멀티에이전트(V2) 배치 잡 테스트.

signal_outcomes 표본 자동 축적: 스케줄된 배치가 워치리스트 전 종목을
V2 분석하고 결과를 기록해야 한다. 종목별 실패는 배치를 죽이지 않는다.
"""

import os
import sys
from unittest.mock import patch

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import service  # noqa: E402


class _FakeOrchestrator:
    fail_tickers: set = set()

    def analyze(self, ticker):
        if ticker in self.fail_tickers:
            raise RuntimeError(f"LLM timeout for {ticker}")
        return {
            "ticker": ticker,
            "final_decision": {
                "final_signal": "buy",
                "final_confidence": 5.5,
                "group_results": {"technical": {"signal": "buy", "confidence": 6.0}},
            },
        }


def _run_batch(monkeypatch, tickers, fail=()):
    recorded = []
    _FakeOrchestrator.fail_tickers = set(fail)
    monkeypatch.setattr(service, "MultiAgentOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(service, "_load_watchlist_files", lambda: tickers)
    monkeypatch.setattr(
        service, "_try_insert_group_outcomes",
        lambda ticker, result: recorded.append(ticker),
    )
    result = service._run_multi_agent_batch_impl()
    return result, recorded


def test_batch_processes_all_watchlist_and_records_outcomes(monkeypatch):
    result, recorded = _run_batch(monkeypatch, ["AAPL", "005930.KS", "950170.KQ"])

    assert result["status"] == "completed"
    assert result["processed"] == 3
    assert result["succeeded"] == 3
    assert recorded == ["AAPL", "005930.KS", "950170.KQ"]
    assert result["signals"]["AAPL"]["signal"] == "buy"


def test_batch_continues_after_single_ticker_failure(monkeypatch):
    result, recorded = _run_batch(
        monkeypatch, ["AAPL", "BROKEN.KQ", "005930.KS"], fail={"BROKEN.KQ"}
    )

    assert result["status"] == "completed"  # 부분 실패는 전체 실패 아님
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert "BROKEN.KQ" in result["errors"]
    assert recorded == ["AAPL", "005930.KS"]


def test_batch_all_failed_marks_error(monkeypatch):
    result, recorded = _run_batch(monkeypatch, ["A", "B"], fail={"A", "B"})

    assert result["status"] == "error"
    assert result["succeeded"] == 0
    assert recorded == []


def test_batch_skips_when_module_unavailable(monkeypatch):
    monkeypatch.setattr(service, "MultiAgentOrchestrator", None)
    result = service._run_multi_agent_batch_impl()

    assert result["status"] == "skipped"


def test_ops_run_job_routes_multi_agent_batch(monkeypatch):
    called = {}

    def _fake_batch(tickers=None):
        called["ran"] = True
        return {"status": "completed"}

    monkeypatch.setattr(service, "run_multi_agent_batch", _fake_batch)
    result = service.ops_run_job("multi_agent_batch")

    assert called.get("ran") is True
    assert result["status"] == "completed"


def test_known_ops_jobs_includes_batch():
    assert "multi_agent_batch" in service._KNOWN_OPS_JOBS


def test_batch_wrapper_records_job_status(monkeypatch):
    events = []
    monkeypatch.setattr(service, "_record_job_start", lambda job_id, label: events.append(("start", job_id)) or "t0")
    monkeypatch.setattr(service, "_record_job_success", lambda job_id, started, result: events.append(("success", job_id)))
    monkeypatch.setattr(service, "_record_job_error", lambda job_id, started, exc: events.append(("error", job_id)))
    monkeypatch.setattr(service, "_run_multi_agent_batch_impl", lambda tickers=None: {"status": "completed"})

    service.run_multi_agent_batch()

    assert ("start", "multi_agent_batch") in events
    assert ("success", "multi_agent_batch") in events
