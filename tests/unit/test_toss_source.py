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
