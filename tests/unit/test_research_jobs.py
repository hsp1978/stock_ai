"""리서치 잡 — 시장별 브리핑 발송·공시 감시.

결과는 '조건 충족'이 아니라 '결과'로 기록한다 (CLAUDE.md §13-2). 공시는 전송에 성공해야
'본 것'이 된다 — 실패한 알림은 다음 실행에서 다시 나간다.
"""

import os
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from research import briefing as B  # noqa: E402
from research import jobs as J  # noqa: E402
from research.models import Holding  # noqa: E402


def _fetchers():
    df = pd.DataFrame({"Close": [1.0, 2.0], "Volume": [1, 1]},
                      index=pd.date_range("2026-10-01", periods=2, tz="UTC"))
    return B.Fetchers(
        ohlcv=lambda t: df, bar_status=lambda t, d: {"state": "complete"},
        verify=lambda t: SimpleNamespace(status="ok", detail=""),
        earnings=lambda t: None, disclosures=lambda t: [],
    )


# ── 시장별 브리핑 ────────────────────────────────────────────────────


def test_briefing_sends_only_that_market():
    sent = []
    res = J.run_market_briefing(
        "KRX", ["005930.KS", "PLTR"], [Holding(ticker="IBM", qty=1, avg_price=1)],
        send=lambda t: sent.append(t) or True, is_trading_day=lambda m: True, fetchers=_fetchers(),
    )
    assert res["status"] == "completed" and res["delivered"] is True and res["items"] == 1
    assert "005930.KS" in sent[0] and "PLTR" not in sent[0] and "IBM" not in sent[0]


def test_briefing_skips_holiday_without_sending():
    sent = []
    res = J.run_market_briefing("NYSE", ["PLTR"], [], send=lambda t: sent.append(t) or True,
                                is_trading_day=lambda m: False, fetchers=_fetchers())
    assert res["status"] == "skipped_holiday" and sent == []


def test_briefing_delivery_failure_is_not_completed():
    """텔레그램 400 인데 alert_sent=1 이던 결함(§13 #18)을 되풀이하지 않는다."""
    res = J.run_market_briefing("NYSE", ["PLTR"], [], send=lambda t: False,
                                is_trading_day=lambda m: True, fetchers=_fetchers())
    assert res["status"] == "delivery_failed" and res["delivered"] is False


def test_briefing_with_nothing_to_report_is_skipped():
    res = J.run_market_briefing("KRX", ["PLTR"], [], send=lambda t: True,
                                is_trading_day=lambda m: True, fetchers=_fetchers())
    assert res["status"] == "skipped_empty"


# ── 공시 감시 ────────────────────────────────────────────────────────


class _Store:
    def __init__(self, seen=None):
        self.seen = seen

    def load(self):
        return self.seen

    def save(self, items):
        self.seen = items


def _rows(*nos):
    return [{"rcept_no": n, "report_nm": f"공시 {n}  "} for n in nos]


def test_first_run_initializes_without_sending():
    """배포 직후 지난 공시가 한꺼번에 쏟아지지 않게."""
    store, sent = _Store(None), []
    res = J.run_disclosure_watch(["005930.KS"], lambda t: _rows("1", "2"),
                                 lambda t: sent.append(t) or True, store.load, store.save)
    assert res["status"] == "initialized" and sent == []
    assert store.seen == ["1", "2"]


def test_new_disclosure_is_sent_once():
    store, sent = _Store(["1"]), []
    res = J.run_disclosure_watch(["005930.KS", "PLTR"], lambda t: _rows("1", "2"),
                                 lambda t: sent.append(t) or True, store.load, store.save)
    assert res["status"] == "completed" and res["new_disclosures"] == 1 and len(sent) == 1
    assert "rcpNo=2" in sent[0] and "공시 2" in sent[0]
    again = J.run_disclosure_watch(["005930.KS"], lambda t: _rows("1", "2"),
                                   lambda t: sent.append(t) or True, store.load, store.save)
    assert again["new_disclosures"] == 0 and len(sent) == 1


def test_failed_send_keeps_disclosure_unseen_for_retry():
    store = _Store(["1"])
    res = J.run_disclosure_watch(["005930.KS"], lambda t: _rows("1", "2"),
                                 lambda t: False, store.load, store.save)
    assert res["status"] == "delivery_failed"
    assert store.seen == ["1"]   # 다음 실행에서 다시 보낸다


def test_fetch_failure_is_reported():
    def boom(t):
        raise RuntimeError("DART_API_KEY 미설정")

    store = _Store([])
    res = J.run_disclosure_watch(["005930.KS"], boom, lambda t: True, store.load, store.save)
    assert res["status"] == "partial_failure" and res["error_count"] == 1
    assert "DART_API_KEY" in res["errors"][0]


def test_only_korean_tickers_are_watched():
    called = []
    store = _Store([])
    J.run_disclosure_watch(["PLTR", "049430.KQ"], lambda t: called.append(t) or [],
                           lambda t: True, store.load, store.save)
    assert called == ["049430.KQ"]


def test_alert_text_has_no_trade_calls():
    text = J._format_disclosure_alert([("005930.KS", _rows("9")[0])])
    assert "매수·매도 판단이 아닙니다" in text
    for word in ("BUY", "SELL", "매수 신호", "매도 신호"):
        assert word not in text


# ── service 연결 ────────────────────────────────────────────────────


def test_delivery_failure_is_recorded_as_job_error(monkeypatch):
    import service
    from research import api

    monkeypatch.setattr(api, "run_briefing_job", lambda m: {"status": "delivery_failed", "delivered": False})
    calls = {}
    monkeypatch.setattr(service, "_record_job_start", lambda j, l=None: "t0")
    monkeypatch.setattr(service, "_record_job_error", lambda j, s, e: calls.setdefault("error", (j, str(e))))
    monkeypatch.setattr(service, "_record_job_success", lambda j, s, r=None: calls.setdefault("ok", j))
    service.run_research_briefing("NYSE")
    assert calls.get("error", ("",))[0] == "research_briefing_us" and "ok" not in calls


def test_job_summary_keeps_delivery_fields():
    import service

    s = service._summarize_job_result({"status": "completed", "market": "KRX", "delivered": True,
                                       "items": 3, "flagged": 1, "new_disclosures": 2})
    assert s["delivered"] is True and s["flagged"] == 1 and s["new_disclosures"] == 2


def test_scheduler_times_are_after_market_close():
    """시각은 UTC (§6-9-1). KRX 06:30 UTC 마감 뒤, NYSE 21:00 UTC(EST 마감) 뒤."""
    import config

    assert (config.RESEARCH_BRIEFING_KR_HOUR, config.RESEARCH_BRIEFING_KR_MINUTE) > (6, 30)
    assert (config.RESEARCH_BRIEFING_US_HOUR, config.RESEARCH_BRIEFING_US_MINUTE) > (21, 0)


@pytest.mark.parametrize("market", ["kr", "XNYS"])
def test_manual_send_rejects_unknown_market(market):
    from fastapi import HTTPException

    from research import api

    with pytest.raises(HTTPException):
        api.send_briefing(market)
