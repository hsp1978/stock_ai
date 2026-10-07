"""장중 미완성 봉 표시 테스트.

2026-10-02 GLW: 개장 1시간 뒤(14:26 UTC) 수동 분석이 거래량 0.11x 를 '거래량 부족'
근거로 썼다. 일봉 분석은 EOD 전제인데 리포트 어디에도 장중이라는 표시가 없었다.
판정은 바꾸지 않고 상태(`bar_status`)와 문구만 싣는다.
"""

import os
import sys
from datetime import date, datetime, timezone

import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import data_collector as dc  # noqa: E402
import service  # noqa: E402
from market_cal import session_progress  # noqa: E402


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _frame(last_ts: str):
    idx = pd.to_datetime(["2026-10-01T13:00:00+09:00", last_ts])
    return pd.DataFrame({"Close": [1.0, 2.0], "Volume": [100, 10]}, index=idx)


# ── market_cal.session_progress ────────────────────────────────────


def test_krx_mid_session_is_in_progress():
    """KRX 10:00 KST(01:00 UTC) — 09:00~15:30 중 1/6.5 경과."""
    p = session_progress("KRX", date(2026, 10, 7), _utc(2026, 10, 7, 1, 0))
    assert p["state"] == "in_progress"
    assert 14 < p["elapsed_pct"] < 17


def test_nyse_states_across_the_day():
    d = date(2026, 10, 6)
    assert session_progress("NYSE", d, _utc(2026, 10, 6, 13, 0))["state"] == "not_opened"
    assert session_progress("NYSE", d, _utc(2026, 10, 6, 14, 26))["state"] == "in_progress"
    assert session_progress("NYSE", d, _utc(2026, 10, 6, 20, 0))["state"] == "closed"


def test_weekend_has_no_session():
    assert session_progress("NYSE", date(2026, 10, 10))["state"] == "no_session"


# ── data_collector.latest_bar_status ───────────────────────────────


def test_glw_one_hour_after_open_is_flagged():
    """GLW 재현 — 10-02 봉, 14:26 UTC(ET 10:26)."""
    df = _frame("2026-10-02T13:00:00+09:00")
    s = dc.latest_bar_status("GLW", df, _utc(2026, 10, 2, 14, 26))
    assert s["state"] == "in_progress"
    assert s["market"] == "NYSE"
    assert s["bar_date"] == "2026-10-02"
    assert "장중 분석" in s["detail"]


def test_us_bar_after_close_is_complete():
    """ET 자정(13:00 KST) 라벨을 ET 날짜로 읽어야 한다 — KST 로 읽으면 날짜가 같아도 우연."""
    df = _frame("2026-10-06T13:00:00+09:00")
    s = dc.latest_bar_status("GLW", df, _utc(2026, 10, 7, 2, 0))
    assert s["state"] == "complete"


def test_korean_intraday_bar_is_flagged():
    df = _frame("2026-10-07T00:00:00+09:00")
    s = dc.latest_bar_status("005930.KS", df, _utc(2026, 10, 7, 2, 0))
    assert s["state"] == "in_progress"
    assert s["market"] == "KRX"


def test_korean_bar_after_close_is_complete():
    df = _frame("2026-10-07T00:00:00+09:00")
    assert dc.latest_bar_status("005930.KS", df, _utc(2026, 10, 7, 8, 30))["state"] == "complete"


def test_empty_frame_is_unknown_not_complete():
    """판정 불가를 '완결'로 덮지 않는다 (§13)."""
    assert dc.latest_bar_status("GLW", pd.DataFrame())["state"] == "unknown"


def test_calendar_failure_is_unknown(monkeypatch):
    import market_cal

    def _boom(*a, **k):
        raise RuntimeError("calendar down")

    monkeypatch.setattr(market_cal, "session_progress", _boom)
    s = dc.latest_bar_status("GLW", _frame("2026-10-06T13:00:00+09:00"))
    assert s["state"] == "unknown"
    assert "판정 실패" in s["detail"]


# ── 알림 문구 ──────────────────────────────────────────────────────


def _alert_result(state):
    return {
        "final_signal": "BUY", "composite_score": 1.6, "confidence": 6.0,
        "signal_distribution": {"buy": 7, "sell": 2, "neutral": 15}, "tool_summaries": [],
        "bar_status": {"state": state, "detail": "장중 분석 — 마지막 봉(2026-10-02) 미완성"},
    }


def test_alert_message_carries_intraday_warning():
    assert "장중 분석" in service.format_alert_message("GLW", _alert_result("in_progress"))


def test_alert_message_silent_for_complete_bar():
    assert "장중 분석" not in service.format_alert_message("GLW", _alert_result("complete"))
