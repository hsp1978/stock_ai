"""게이트 2 판정 — 병행 2주간 알림 누락 0.

잡 상태는 마지막 실행 1건만 남겨서 '모든 거래일에 전달됐는가'를 판정할 수 없었다.
실행 이력을 쌓고, 판정할 근거가 없으면 PASS 가 아니라 INCOMPLETE 로 적는다 (§13-4).
"""

import os
import sys
from datetime import date, datetime, timezone

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from research import gate_report as G  # noqa: E402
from research import history as H  # noqa: E402
from research import jobs as J  # noqa: E402

D1, D2 = date(2026, 10, 8), date(2026, 10, 9)


def _run(job, day, hour, **kw):
    return {"job_id": job, "started_at": f"{day}T{hour:02d}:10:00+00:00", **kw}


def _ok_briefings():
    return [_run("research_briefing_kr", d, 7, delivered=True, status="completed") for d in (D1, D2)] + \
           [_run("research_briefing_us", d, 21, delivered=True, status="completed") for d in (D1, D2)]


TRADING = {"KRX": [D1, D2], "NYSE": [D1, D2]}


def test_all_delivered_is_pass():
    hist = _ok_briefings() + [_run("research_disclosure_watch", D1, 2, status="initialized",
                                   initialized=["A"], delivered=False)]
    r = G.build_report(D1, D2, hist, TRADING, [{"rcept_no": "A", "rcept_dt": "20261008", "ticker": "X"}])
    assert r["verdict"] == "PASS" and r["briefings"]["ok"] == 4


def test_missing_briefing_day_fails():
    hist = _ok_briefings()[1:]   # KRX 10-08 없음
    r = G.build_report(D1, D2, hist, TRADING, [])
    assert r["verdict"] == "FAIL" and r["briefings"]["missing"] == ["KRX 2026-10-08"]


def test_undelivered_briefing_fails():
    hist = _ok_briefings()
    hist[2] = {**hist[2], "delivered": False, "status": "delivery_failed"}
    r = G.build_report(D1, D2, hist, TRADING, [])
    assert r["verdict"] == "FAIL" and "delivery_failed" in r["briefings"]["failed"][0]


def test_disclosure_failure_recovered_by_later_run_passes():
    hist = _ok_briefings() + [
        _run("research_disclosure_watch", D1, 3, status="delivery_failed", delivered=False),
        _run("research_disclosure_watch", D1, 4, status="completed", delivered=True, alerted=["B"]),
    ]
    r = G.build_report(D1, D2, hist, TRADING, [{"rcept_no": "B", "rcept_dt": "20261008", "ticker": "X"}])
    assert r["verdict"] == "PASS" and r["disclosure_delivery"]["delivery_failed"] == 1


def test_unrecovered_disclosure_failure_fails():
    hist = _ok_briefings() + [_run("research_disclosure_watch", D2, 5, status="delivery_failed")]
    r = G.build_report(D1, D2, hist, TRADING, [])
    assert r["verdict"] == "FAIL" and len(r["disclosure_delivery"]["unrecovered"]) == 1


def test_filing_never_alerted_is_missed():
    r = G.build_report(D1, D2, _ok_briefings(), TRADING,
                       [{"rcept_no": "C", "rcept_dt": "20261009", "ticker": "005930.KS", "report_nm": "유상증자결정 "}])
    assert r["verdict"] == "FAIL"
    assert r["disclosure_coverage"]["missed"] == ["005930.KS 20261009 유상증자결정"]


def test_seen_list_covers_init_before_history():
    """이력 기록 전에 일어난 첫 실행분은 '본 것' 목록이 증명한다."""
    r = G.build_report(D1, D2, _ok_briefings(), TRADING,
                       [{"rcept_no": "S", "rcept_dt": "20261008", "ticker": "X"}], seen=["S"])
    assert r["verdict"] == "PASS"


def test_filing_before_window_is_ignored():
    r = G.build_report(D1, D2, _ok_briefings(), TRADING,
                       [{"rcept_no": "Z", "rcept_dt": "20261001", "ticker": "X"}])
    assert r["disclosure_coverage"]["filings"] == 0


def test_history_starting_late_is_incomplete_not_pass():
    """근거 없는 구간을 통과로 덮지 않는다."""
    hist = [_run("research_briefing_kr", D2, 7, delivered=True)]
    r = G.build_report(D1, D2, hist, {"KRX": [D2], "NYSE": []}, [])
    assert r["verdict"] == "INCOMPLETE" and "이력 시작" in r["gaps"][0]


def test_dart_unavailable_is_incomplete():
    r = G.build_report(D1, D2, _ok_briefings(), TRADING, [], filings_error="005930.KS: DART down")
    assert r["verdict"] == "INCOMPLETE"


def test_markdown_states_verdict_and_misses():
    hist = _ok_briefings()[1:]
    md = G.to_markdown(G.build_report(D1, D2, hist, TRADING, []))
    assert md.startswith("# 게이트 2 판정 — FAIL") and "누락: KRX 2026-10-08" in md


def test_collect_filings_reports_errors_and_skips_us():
    def fetch(t, days):
        if t == "000660.KS":
            raise RuntimeError("down")
        return [{"rcept_no": "1", "rcept_dt": "20261008"}]

    rows, err = G.collect_filings(["005930.KS", "000660.KS", "PLTR"], 10, fetch)
    assert [r["ticker"] for r in rows] == ["005930.KS"] and "000660.KS: down" in err


# ── 이력 기록 ────────────────────────────────────────────────────────


def test_history_records_alerted_and_trims(monkeypatch):
    store = {}
    import db

    monkeypatch.setattr(db, "get_app_state", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(db, "set_app_state", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(H, "_LIMIT", 3)
    for i in range(5):
        H.record_run("research_disclosure_watch", datetime(2026, 10, 8, 2, i),
                     {"status": "completed", "delivered": True, "alerted": [str(i)]})
    rows = H.load_history()
    assert len(rows) == 3 and rows[-1]["alerted"] == ["4"]
    assert rows[-1]["started_at"].startswith("2026-10-08T02:04:00+00:00")


def test_watch_result_lists_alerted_and_initialized():
    class S:
        seen = None

    def load():
        return S.seen

    def save(x):
        S.seen = x

    first = J.run_disclosure_watch(["005930.KS"], lambda t: [{"rcept_no": "1"}], lambda t: True, load, save)
    assert first["initialized"] == ["1"]
    nxt = J.run_disclosure_watch(["005930.KS"], lambda t: [{"rcept_no": "1"}, {"rcept_no": "2"}],
                                 lambda t: True, load, save)
    assert nxt["alerted"] == ["2"]
    failed = J.run_disclosure_watch(["005930.KS"], lambda t: [{"rcept_no": "3"}], lambda t: False, load, save)
    assert failed["alerted"] == []   # 전송 실패는 '알림 나감'이 아니다


# ── service 연결 ────────────────────────────────────────────────────


def test_briefing_job_writes_history(monkeypatch):
    import service
    from research import api

    monkeypatch.setattr(api, "run_briefing_job", lambda m: {"status": "completed", "delivered": True})
    monkeypatch.setattr(service, "_record_job_start", lambda j, l=None: datetime(2026, 10, 8, 7, 10))
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(H, "record_run", lambda *a: calls.append(a))
    service.run_research_briefing("KRX")
    assert calls and calls[0][0] == "research_briefing_kr" and calls[0][2]["delivered"] is True


def test_history_failure_does_not_break_job(monkeypatch):
    import service
    from research import api

    monkeypatch.setattr(api, "run_briefing_job", lambda m: {"status": "completed", "delivered": True})
    monkeypatch.setattr(service, "_record_job_start", lambda j, l=None: datetime(2026, 10, 8, 7, 10))
    ok = []
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: ok.append(1))

    def boom(*a):
        raise RuntimeError("db locked")

    monkeypatch.setattr(H, "record_run", boom)
    assert service.run_research_briefing("KRX")["delivered"] is True and ok


@pytest.mark.parametrize("value,expect_none", [("", True), ("bogus", True),
                                               ("2026-10-22T22:30:00+00:00", False),
                                               ("2026-10-22T22:30:00", False)])
def test_parse_gate2_report_at(value, expect_none):
    import service

    parsed = service._parse_gate2_report_at(value)
    assert (parsed is None) == expect_none
    if parsed:
        assert parsed.tzinfo is not None and parsed.astimezone(timezone.utc).hour == 22


def test_report_time_is_after_last_us_briefing():
    import config

    at = datetime.fromisoformat(config.RESEARCH_GATE2_REPORT_AT)
    assert at.date().isoformat() == config.RESEARCH_GATE2_END
    assert (at.hour, at.minute) > (config.RESEARCH_BRIEFING_US_HOUR, config.RESEARCH_BRIEFING_US_MINUTE)


def test_saved_report_endpoint_404_before_run(monkeypatch):
    import db
    from fastapi import HTTPException

    from research import api

    monkeypatch.setattr(db, "get_app_state", lambda k, default=None: default)
    with pytest.raises(HTTPException) as exc:
        api.get_gate2_report(saved=True)
    assert exc.value.status_code == 404


def test_briefing_not_yet_due_is_not_missing():
    """중간 점검에서 아직 발송 시각이 안 된 오늘 브리핑을 누락으로 세지 않는다."""
    now = datetime(2026, 10, 8, 2, 32, tzinfo=timezone.utc)
    assert G.due_days([D1], 7, 10, now) == []
    assert G.due_days([D1], 7, 10, datetime(2026, 10, 8, 7, 40, tzinfo=timezone.utc)) == [D1]
    assert G.due_days([D1], 7, 10, datetime(2026, 10, 8, 7, 39, tzinfo=timezone.utc)) == []
