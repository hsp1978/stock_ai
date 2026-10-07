"""
토스증권 시세 데이터 소스 단위 테스트.

respx로 캔들/가격/호가 API를 mock (실 호출 0). 페이지네이션·DataFrame 정합성·파싱 검증.
"""
import httpx
import pandas as pd
import respx

from data_sources.toss_source import TossDataSource
from data_sources.base import Quote

BASE = "https://openapi.tossinvest.com"
TOKEN_URL = f"{BASE}/oauth2/token"


def _token_route(respx_mock):
    return respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 1800}))


def _make_source():
    return TossDataSource(app_key="ak", app_secret="sk", base_url=BASE)


def _candles(start_day, n):
    # 토스 캔들 실제 필드: openPrice/highPrice/lowPrice/closePrice/volume
    return [
        {"timestamp": f"2026-01-{start_day + i:02d}T00:00:00Z",
         "openPrice": 100 + i, "highPrice": 105 + i, "lowPrice": 95 + i,
         "closePrice": 102 + i, "volume": 1000 + i}
        for i in range(n)
    ]


@respx.mock
def test_ohlcv_pagination_loop(respx_mock):
    _token_route(respx_mock)
    # 1페이지: nextBefore 제공 → 2페이지: nextBefore 없음 → 종료 (응답은 result 래퍼)
    page1 = {"result": {"candles": _candles(10, 5), "nextBefore": "cursor-1"}}
    page2 = {"result": {"candles": _candles(1, 5), "nextBefore": None}}
    route = respx_mock.get(f"{BASE}/api/v1/candles").mock(side_effect=[
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
    ])
    src = _make_source()
    df = src.get_ohlcv("005930.KS", period="1y", interval="1d")
    assert route.call_count == 2
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 10
    # 오름차순 정렬
    assert df.index.is_monotonic_increasing
    # 2페이지 호출에 before=nextBefore 전달됐는지
    assert "before=cursor-1" in str(route.calls[1].request.url)
    # 캐시 메타
    assert df.attrs["source"] == "toss"
    assert "fetched_at" in df.attrs and "latest_bar_date" in df.attrs


@respx.mock
def test_ohlcv_respects_max_pages(respx_mock):
    _token_route(respx_mock)
    # 항상 nextBefore 제공 → 최대 5페이지에서 중단
    route = respx_mock.get(f"{BASE}/api/v1/candles").mock(
        return_value=httpx.Response(200, json={"result": {"candles": _candles(1, 5),
                                                          "nextBefore": "always"}}))
    src = _make_source()
    src.get_ohlcv("005930.KS", period="max", interval="1d")
    assert route.call_count == 5


@respx.mock
def test_ohlcv_no_credentials_returns_empty():
    src = TossDataSource(app_key="", app_secret="", base_url=BASE)
    df = src.get_ohlcv("005930.KS")
    assert df.empty


@respx.mock
def test_latest_price(respx_mock):
    _token_route(respx_mock)
    # 실제 응답: result 리스트, lastPrice 필드
    respx_mock.get(f"{BASE}/api/v1/prices").mock(
        return_value=httpx.Response(200, json={"result": [{"symbol": "005930",
                                                           "lastPrice": "72500"}]}))
    src = _make_source()
    assert src.get_latest_price("005930.KS") == 72500.0


@respx.mock
def test_quote_nested_orderbook(respx_mock):
    _token_route(respx_mock)
    # 실제 호가: result.{asks,bids}, 필드 price/volume
    respx_mock.get(f"{BASE}/api/v1/orderbook").mock(return_value=httpx.Response(
        200, json={"result": {"bids": [{"price": "72400", "volume": "100"}],
                              "asks": [{"price": "72500", "volume": "80"}],
                              "timestamp": "2026-06-23T01:00:00Z"}}))
    respx_mock.get(f"{BASE}/api/v1/prices").mock(
        return_value=httpx.Response(200, json={"result": [{"lastPrice": "72450"}]}))
    src = _make_source()
    q = src.get_quote("005930.KS")
    assert isinstance(q, Quote)
    assert q.bid == 72400 and q.ask == 72500
    assert q.bid_size == 100 and q.ask_size == 80
    assert q.last_price == 72450


@respx.mock
def test_health_check_ok(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/v1/prices").mock(
        return_value=httpx.Response(200, json={"result": [{"lastPrice": "70000"}]}))
    src = _make_source()
    hc = src.health_check()
    assert hc["ok"] is True


# ── 정규장 미개장 봉 제거 (2026-10-07) ─────────────────────────────
# 토스는 미국 종목 야간거래(ET 20:00~) 체결을 다음 거래일 일봉으로 미리 만든다.
# 실측: GLW 10-07 봉 거래량 14,102 (전일 8,876,879), yfinance 에는 없음.

from datetime import datetime, timezone  # noqa: E402

import market_cal  # noqa: E402
from data_sources.toss_source import _drop_unopened_us_bar  # noqa: E402


def _us_frame():
    idx = pd.to_datetime([
        "2026-10-05T13:00:00+09:00", "2026-10-06T13:00:00+09:00", "2026-10-07T13:00:00+09:00",
    ])
    return pd.DataFrame(
        {"Open": [164.68, 161.005, 169.01], "High": [164.84, 170.63, 169.65],
         "Low": [158.44, 160.5, 166.55], "Close": [159.37, 168.97, 166.9],
         "Volume": [6580963, 8876879, 14102]},
        index=idx,
    )


def test_unopened_session_bar_is_dropped():
    """10-07 11:13 KST(= ET 10-06 22:13) — 10-07 정규장은 아직 열리지 않았다."""
    now = datetime(2026, 10, 7, 2, 13, tzinfo=timezone.utc)
    df = _drop_unopened_us_bar(_us_frame(), "GLW", now)
    assert df.index[-1].date().isoformat() == "2026-10-06"
    assert df.attrs["session_check"] == "checked"
    dropped = df.attrs["unopened_session_bar"]
    assert dropped["bar_date"] == "2026-10-07"
    assert dropped["volume"] == 14102


def test_bar_kept_once_regular_session_opens():
    """정규장이 열린 뒤의 당일 봉은 진짜 장중 봉이다 — 떼지 않는다."""
    now = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
    df = _drop_unopened_us_bar(_us_frame(), "GLW", now)
    assert df.index[-1].date().isoformat() == "2026-10-07"
    assert df.attrs["unopened_session_bar"] is None


def test_korean_ticker_is_not_touched():
    """KRX 당일 봉은 실제 장중 봉이다 (야간거래 없음)."""
    df = _drop_unopened_us_bar(_us_frame(), "005930.KS",
                               datetime(2026, 10, 7, 2, 13, tzinfo=timezone.utc))
    assert len(df) == 3
    assert df.attrs["session_check"] == "not_applicable"


def test_calendar_failure_keeps_bar_and_says_so(monkeypatch):
    """판정 불가를 '확인함'으로 덮지 않는다 — 봉은 남기고 error 로 기록."""
    def _boom(*a, **k):
        raise RuntimeError("calendar down")

    monkeypatch.setattr(market_cal, "session_has_opened", _boom)
    df = _drop_unopened_us_bar(_us_frame(), "GLW",
                               datetime(2026, 10, 7, 2, 13, tzinfo=timezone.utc))
    assert len(df) == 3
    assert df.attrs["session_check"].startswith("error")


@respx.mock
def test_get_ohlcv_drops_unopened_us_bar(respx_mock, monkeypatch):
    """어댑터 경로 전체 — 떼어낸 사실이 절단 후에도 attrs 에 남는다."""
    _token_route(respx_mock)
    monkeypatch.setattr(market_cal, "session_has_opened", lambda m, d, now=None: d.day != 7)
    candles = [
        {"timestamp": f"2026-10-0{d}T13:00:00.000+09:00", "openPrice": "1", "highPrice": "1",
         "lowPrice": "1", "closePrice": str(100 + d), "volume": "1000"}
        for d in (5, 6, 7)
    ]
    respx_mock.get(f"{BASE}/api/v1/candles").mock(
        return_value=httpx.Response(200, json={"result": {"candles": candles}}))
    df = _make_source().get_ohlcv("GLW", period="1y", interval="1d")
    assert df.index[-1].date().isoformat() == "2026-10-06"
    assert df.attrs["latest_bar_date"].startswith("2026-10-06")
    assert df.attrs["unopened_session_bar"]["bar_date"] == "2026-10-07"
    assert df.attrs["source"] == "toss"
