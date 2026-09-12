"""스크리너 결과를 표본으로 적립한다 — 종목 확대의 실질.

`docs/SYSTEM_OVERVIEW.md` §15-1: 측정 체계를 다 고쳤지만(#35~#47) **표본이 모자라
어떤 규칙도 세울 수 없다.** 신 로직 기준 독립 블록이 79~124개다. 7종목 워치리스트로는
기간을 기다려도 블록이 느리게 는다 — 같은 종목의 연속 신호는 서로 겹치기 때문이다.

스크리너는 이미 KOSPI+KOSDAQ 280여 종목을 매번 훑고 있었고, 그 판단을 **버리고**
있었다. 적립하면 LLM 비용 없이 종목 다양성이 큰 표본이 생긴다 — 종목이 다르면
`ticker_day`/블록 기준으로 서로 독립이다.

여기서 고정하는 것:
  1. 방향 있는 신호(buy/sell)만 적립한다 — neutral 은 부호를 못 매긴다
  2. 건너뛴 수를 반환한다 ('기록 없음'과 '적립할 게 없었음'을 구분)
  3. 개별 실패가 스크리너 전체를 죽이지 않는다
  4. 적립 상한(RECORD_TOP_N)을 넘지 않는다 — 평가 큐 폭증 방지
"""

import os
import sys
from unittest.mock import patch

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import screener  # noqa: E402


def _item(ticker, signal="buy", price=10000.0, score=78.0, conf=6.5, rank=1):
    return {
        "ticker": ticker,
        "screener_signal": signal,
        "screener_confidence": conf,
        "current_price": price,
        "score": score,
        "grade": "A",
        "rank": rank,
    }


def test_directional_results_are_recorded_as_samples():
    calls = []

    with patch("signal_tracker.insert_signal_outcome",
               side_effect=lambda **kw: calls.append(kw) or "id"):
        stats = screener.record_screener_outcomes(
            [_item("005930.KS"), _item("035720.KS", signal="sell", price=52000.0)]
        )

    assert stats["recorded"] == 2 and stats["errors"] == 0
    assert {c["ticker"] for c in calls} == {"005930.KS", "035720.KS"}
    assert {c["signal_source"] for c in calls} == {"screener"}
    assert calls[0]["price_at_signal"] == 10000.0
    assert calls[0]["conviction"] == 6.5
    # 점수·등급·순위를 맥락으로 남겨 사후에 되짚을 수 있게 한다
    assert calls[0]["market_context"]["grade"] == "A"
    assert calls[0]["market_context"]["rank"] == 1


def test_neutral_results_are_skipped_and_counted():
    """neutral 은 부호를 못 매겨 방향 적중률·초과수익 계산에 못 들어간다."""
    calls = []

    with patch("signal_tracker.insert_signal_outcome",
               side_effect=lambda **kw: calls.append(kw)):
        stats = screener.record_screener_outcomes(
            [_item("A.KS", signal="neutral"), _item("B.KS", signal="buy")]
        )

    assert stats["recorded"] == 1
    assert stats["skipped_non_directional"] == 1     # 조용히 사라지지 않는다
    assert [c["ticker"] for c in calls] == ["B.KS"]


def test_missing_price_is_an_error_not_a_silent_skip():
    with patch("signal_tracker.insert_signal_outcome", side_effect=lambda **kw: None):
        stats = screener.record_screener_outcomes([_item("A.KS", price=0)])

    assert stats["recorded"] == 0 and stats["errors"] == 1


def test_one_failure_does_not_abort_the_rest():
    seen = []

    def flaky(**kw):
        if kw["ticker"] == "BAD.KS":
            raise RuntimeError("db locked")
        seen.append(kw["ticker"])

    with patch("signal_tracker.insert_signal_outcome", side_effect=flaky):
        stats = screener.record_screener_outcomes(
            [_item("BAD.KS"), _item("GOOD.KS"), _item("ALSO.KS")]
        )

    assert stats["recorded"] == 2 and stats["errors"] == 1
    assert seen == ["GOOD.KS", "ALSO.KS"]


def test_record_limit_bounds_queue_growth():
    """적립 상한이 없으면 평가 큐가 매일 상위 N 만큼 불어난다."""
    calls = []

    with patch("signal_tracker.insert_signal_outcome",
               side_effect=lambda **kw: calls.append(kw)):
        stats = screener.record_screener_outcomes(
            [_item(f"T{i}.KS") for i in range(20)], limit=5
        )

    assert stats["recorded"] == 5 and len(calls) == 5


def test_recording_is_config_gated():
    assert isinstance(screener.RECORD_OUTCOMES, bool)
    assert screener.RECORD_TOP_N >= 1


# ── 스케줄 잡 ─────────────────────────────────────────────────────


def _isolated_job_status(monkeypatch):
    """잡 상태 기록을 가로챈다.

    `_record_job_*` 는 `set_app_state()` 로 **운영 DB(scan_log.db)** 에 쓴다. 테스트
    컨테이너가 리포지토리를 그대로 마운트하므로 패치하지 않으면 운영 잡 상태가
    오염된다 (2026-09-12 실제 발생: 테스트의 "pykrx down" 이 /ops/jobs 에 떴다).
    """
    import service

    monkeypatch.setattr(service, "_record_job_start", lambda *a, **k: "t0")
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: None)
    monkeypatch.setattr(service, "_record_job_error", lambda *a, **k: None)
    return service


def test_screener_batch_job_reports_sample_recording(monkeypatch):
    service = _isolated_job_status(monkeypatch)

    fake = {
        "run_id": "run-1",
        "universe_size": 281,
        "results": [{"ticker": "005930.KS"}],
        "outcome_recording": {"recorded": 7, "skipped_non_directional": 3, "errors": 0},
    }

    with patch("screener.run_screener", return_value=fake):
        summary = service.run_screener_batch()

    assert summary["status"] == "completed"
    assert summary["universe_size"] == 281
    # 몇 건이 표본으로 쌓였는지가 잡 결과에 남아야 한다 — 안 그러면 '돌았다'만 남는다
    assert summary["outcome_recording"]["recorded"] == 7


def test_screener_batch_job_records_failure(monkeypatch):
    service = _isolated_job_status(monkeypatch)

    with patch("screener.run_screener", side_effect=RuntimeError("pykrx down")):
        summary = service.run_screener_batch()

    assert summary["status"] == "error"
    assert "pykrx down" in summary["error"]


def test_screener_batch_is_registered_in_known_jobs():
    import service

    assert "screener_batch" in service._KNOWN_OPS_JOBS
