"""리서치 도구 1단계 — 브리핑·보유·실적·텔레그램 형식.

브리핑은 사실과 거리만 담는다. 매수·매도 신호, 종합 점수, 신뢰도는 없다 (2026-10-08
전환 제안서). 각 조각의 실패는 숨기지 않고 errors 에 사유와 함께 남는다 (CLAUDE.md §13).
"""

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from research import briefing as B  # noqa: E402
from research import earnings as E  # noqa: E402
from research import holdings as H  # noqa: E402
from research.models import BriefingItem, Holding  # noqa: E402
from research.telegram_format import format_briefing  # noqa: E402


def _df(closes, volumes=None):
    n = len(closes)
    idx = pd.date_range("2026-09-01", periods=n, freq="B", tz="Asia/Seoul")
    return pd.DataFrame({"Close": closes, "Volume": volumes or [1000] * n}, index=idx)


def _fetchers(df, state="complete", verify="ok", earnings=None, disclosures=None,
              earnings_exc=None, disclosure_exc=None):
    def _earn(t):
        if earnings_exc:
            raise earnings_exc
        return earnings

    def _disc(t):
        if disclosure_exc:
            raise disclosure_exc
        return disclosures or []

    return B.Fetchers(
        ohlcv=lambda t: df,
        bar_status=lambda t, d: {"state": state},
        verify=lambda t: SimpleNamespace(status=verify, detail="d"),
        earnings=_earn,
        disclosures=_disc,
    )


# ── 가격 ────────────────────────────────────────────────────────────


def test_complete_bar_change_and_volume_ratio():
    df = _df([100.0] * 21 + [110.0], [1000] * 21 + [3000])
    item = B.build_item("005930.KS", None, _fetchers(df))
    assert item.close == 110.0 and item.change_pct == 10.0
    assert item.volume_ratio == 3.0
    assert any("거래량 3.0배" in f for f in item.flags)
    assert any("하루 +10.0%" in f for f in item.flags)


def test_intraday_bar_is_excluded_and_flagged():
    """장중 마지막 봉은 미완성이다 — 2026-10-02 GLW 거래량 0.11x 의 원인."""
    df = _df([100.0] * 21 + [105.0, 50.0], [1000] * 22 + [10])
    item = B.build_item("GLW", None, _fetchers(df, state="in_progress"))
    assert item.close == 105.0          # 미완성 봉(50) 이 아니라 직전 완결 봉
    assert item.volume_ratio == 1.0     # 10주가 아니라 완결 봉 거래량
    assert "장중" in item.bar_note
    assert not any("장중" in f for f in item.flags)  # 상태 안내는 '볼 것'이 아니다


def test_price_failure_is_reported_not_hidden():
    def boom(t):
        raise ConnectionError("down")

    f = _fetchers(_df([1.0, 2.0]))
    f.ohlcv = boom
    item = B.build_item("PLTR", None, f)
    assert item.close is None
    assert any("시세 조회 실패" in e for e in item.errors)


def test_unverified_price_is_flagged():
    item = B.build_item("PLTR", None, _fetchers(_df([1.0, 2.0]), verify="single_source"))
    assert item.price_check == "single_source"
    assert any("가격 검증 single_source" in f for f in item.flags)


# ── 보유 ────────────────────────────────────────────────────────────


def test_holding_distances_and_stop_near():
    h = Holding(ticker="pltr", qty=10, avg_price=100, stop_price=97, target_price=150)
    item = B.build_item("PLTR", h, _fetchers(_df([100.0, 99.0])))
    assert item.is_holding and item.pnl_pct == -1.0
    assert item.to_stop_pct == pytest.approx(-2.02, abs=0.01)
    assert any("손절가까지 2.0%" in f for f in item.flags)


def test_stop_reached_flag():
    h = Holding(ticker="PLTR", qty=1, avg_price=100, stop_price=100)
    item = B.build_item("PLTR", h, _fetchers(_df([101.0, 95.0])))
    assert "손절가 도달" in item.flags


# ── 실적 ────────────────────────────────────────────────────────────


def test_earnings_soon_flag_and_failure_kept_apart():
    soon = B.build_item("PLTR", None, _fetchers(_df([1.0, 2.0]), earnings=2.4))
    assert soon.earnings_status == "ok" and any("실적 발표 D-2" in f for f in soon.flags)
    none = B.build_item("PLTR", None, _fetchers(_df([1.0, 2.0]), earnings=None))
    assert none.earnings_status == "ok" and none.days_to_earnings is None
    failed = B.build_item("PLTR", None, _fetchers(_df([1.0, 2.0]), earnings_exc=RuntimeError("x")))
    assert failed.earnings_status == "unavailable"
    assert any("실적 일정 조회 실패" in e for e in failed.errors)


def test_days_to_next_earnings_ignores_past_timestamp():
    """earningsTimestamp 는 직전 실적일이다 — 다음 실적은 Start/End 에 있다."""
    now = datetime(2026, 10, 8, 0, 0, tzinfo=timezone.utc)
    past = datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp()
    nxt = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    info = {"earningsTimestamp": past, "earningsTimestampStart": nxt}
    assert E.days_to_next_earnings(info, "PLTR", now) == pytest.approx(4.0, abs=0.01)
    assert E.days_to_next_earnings({"earningsTimestamp": past}, "PLTR", now) is None


def test_earnings_cache_counts_down(monkeypatch):
    E.clear_cache()
    clock = [1_000_000.0]
    monkeypatch.setattr(E.time, "time", lambda: clock[0])
    calls = []
    monkeypatch.setattr(E, "days_to_next_earnings", lambda info, t, now=None: 3.0)
    assert E.fetch_days_to_earnings("PLTR", lambda t: calls.append(t) or {"earningsTimestampStart": 1}) == 3.0
    clock[0] += 86400 / 4  # 6시간 — 캐시 유효기간(12시간) 안
    assert E.fetch_days_to_earnings("PLTR", lambda t: calls.append(t) or {"earningsTimestampStart": 1}) == pytest.approx(2.75)
    assert calls == ["PLTR"]
    E.clear_cache()


# ── 공시 ────────────────────────────────────────────────────────────


def test_kr_disclosures_listed_with_links():
    rows = [{"rcept_dt": "20261007", "report_nm": "주요사항보고서", "classified": "major", "rcept_no": "2026100700001"}]
    item = B.build_item("005930.KS", None, _fetchers(_df([1.0, 2.0]), disclosures=rows))
    assert item.disclosure_status == "ok"
    assert item.disclosures[0].url.endswith("rcpNo=2026100700001")
    assert any("공시 1건" in f for f in item.flags)


def test_dart_failure_is_not_no_disclosures():
    """'최근 30일 공시 없음'이 사실은 라이브러리 미설치였다 (§13 #17)."""
    item = B.build_item("005930.KS", None,
                        _fetchers(_df([1.0, 2.0]), disclosure_exc=RuntimeError("DART_API_KEY 미설정")))
    assert item.disclosure_status == "unavailable"
    assert any("공시 조회 실패" in e for e in item.errors)


def test_us_ticker_has_no_dart():
    item = B.build_item("PLTR", None, _fetchers(_df([1.0, 2.0])))
    assert item.disclosure_status == "not_applicable"


# ── 묶음·보유 저장 ──────────────────────────────────────────────────


def test_briefing_orders_holdings_first_and_dedupes():
    f = _fetchers(_df([1.0, 2.0]))
    h = [Holding(ticker="IBM", qty=1, avg_price=1)]
    b = B.build_briefing(["pltr", "IBM", "PLTR"], h, f)
    assert [i.ticker for i in b.items] == ["IBM", "PLTR"]
    assert b.items[0].is_holding and not b.items[1].is_holding


def test_holdings_store_roundtrip(monkeypatch):
    store = {}
    monkeypatch.setattr(H, "get_app_state", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(H, "set_app_state", lambda k, v: store.__setitem__(k, v))
    H.upsert_holding(Holding(ticker="pltr", qty=1, avg_price=100))
    H.upsert_holding(Holding(ticker="PLTR", qty=2, avg_price=110))
    assert [(h.ticker, h.qty) for h in H.list_holdings()] == [("PLTR", 2)]
    assert H.remove_holding("pltr") is True
    assert H.remove_holding("PLTR") is False   # 없던 것을 '삭제됨'으로 보고하지 않는다


def test_api_delete_missing_is_404(monkeypatch):
    from fastapi import HTTPException

    from research import api

    monkeypatch.setattr(api, "remove_holding", lambda t: False)
    with pytest.raises(HTTPException) as exc:
        api.delete_holding("NOPE")
    assert exc.value.status_code == 404


def test_api_watchlist_reads_single_source(tmp_path):
    from research import api

    p = tmp_path / "watchlist.txt"
    p.write_text("pltr\n# comment\n\nIBM\nPLTR\n", encoding="utf-8")
    assert api._watchlist(str(p)) == ["PLTR", "IBM"]


# ── 범위 고정 ────────────────────────────────────────────────────────


def test_briefing_has_no_signal_fields():
    """신호 생성기로 되돌아가지 않게 모델에서 막는다."""
    banned = {"signal", "final_signal", "score", "composite_score", "confidence"}
    assert not banned & set(BriefingItem.model_fields)


def test_telegram_text_carries_no_trade_calls():
    f = _fetchers(_df([100.0, 99.0]))
    b = B.build_briefing(["PLTR"], [Holding(ticker="IBM", qty=1, avg_price=1)], f)
    text = format_briefing(b, "2026-10-08")
    for word in ("BUY", "SELL", "매수 신호", "매도 신호", "관망"):
        assert word not in text
    assert "매수·매도 판단이 아닙니다" in text


def test_telegram_text_is_truncated_with_notice():
    f = _fetchers(_df([100.0, 99.0]))
    b = B.build_briefing([], [Holding(ticker=f"T{i:03d}.KS", qty=1, avg_price=1, note="x" * 200)
                              for i in range(150)], f)
    text = format_briefing(b, "2026-10-08")
    assert len(text) < 4096 and "잘림" in text


def test_missing_earnings_data_is_not_no_schedule():
    """yfinance 는 한국 종목 실적일을 주지 않는다 — '일정 없음'으로 읽히면 안 된다."""
    E.clear_cache()
    with pytest.raises(E.EarningsDataMissing):
        E.fetch_days_to_earnings("049430.KQ", lambda t: {"shortName": "x"})
    item = B.build_item("049430.KQ", None,
                        _fetchers(_df([1.0, 2.0]), earnings_exc=E.EarningsDataMissing("데이터 없음")))
    assert item.earnings_status == "unavailable" and "데이터 없음" in item.earnings_note
    assert item.errors == ()   # 알려진 한계 — 매일 '수집 실패'로 울리지 않는다
    E.clear_cache()


def test_disclosure_title_is_stripped():
    rows = [{"rcept_dt": "20261007", "report_nm": "주식소각결정              ", "rcept_no": "1"}]
    item = B.build_item("005930.KS", None, _fetchers(_df([1.0, 2.0]), disclosures=rows))
    assert item.disclosures[0].title == "주식소각결정"


def test_disclosures_carry_no_sentiment_label():
    """classify_disclosure(호재/악재/중립)는 판단이다 — 리서치 출력에 싣지 않는다."""
    from research.api import DisclosureRow
    from research.models import Disclosure

    assert "kind" not in Disclosure.model_fields
    assert "kind" not in DisclosureRow.model_fields
    rows = [{"rcept_dt": "20261007", "report_nm": "유상증자결정", "classified": "negative",
             "rcept_no": "1"}]
    item = B.build_item("005930.KS", None, _fetchers(_df([1.0, 2.0]), disclosures=rows))
    assert "negative" not in item.model_dump_json()
