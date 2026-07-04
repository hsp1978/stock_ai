"""
토스증권 브로커 어댑터 + OAuth 토큰 매니저 단위 테스트.

respx로 토스 Open API를 mock하여 실제 네트워크 호출 없이 검증한다 (CLAUDE.md 5.6).
커버: 토큰 발급/캐시/401 재발급, accountSeq 식별·헤더, 주문 매핑, 티커 변환, 안전 폴백.
"""
import httpx
import pytest
import respx

from brokers.toss_auth import TossTokenManager, TossAuthError, mask_secret
from brokers.toss_broker import (
    TossBroker, to_toss_symbol, from_toss_symbol, is_kr_ticker,
)
from brokers.base import OrderRequest, OrderSide, OrderType, OrderStatus

BASE = "https://openapi.tossinvest.com"
TOKEN_URL = f"{BASE}/oauth2/token"


def _token_route(respx_mock, token="tok-1", expires_in=1800):
    return respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": token, "expires_in": expires_in})
    )


def _make_broker(account_no="11012345678"):
    return TossBroker(app_key="ak-test", app_secret="sk-secret-1234",
                      account_no=account_no, base_url=BASE)


# ─── 티커 변환 ──────────────────────────────────────
def test_ticker_conversion():
    assert to_toss_symbol("005930.KS") == "005930"
    assert to_toss_symbol("035720.KQ") == "035720"
    assert to_toss_symbol("AAPL") == "AAPL"
    assert from_toss_symbol("005930", "KOSPI") == "005930.KS"
    assert from_toss_symbol("035720", "KOSDAQ") == "035720.KQ"
    assert from_toss_symbol("AAPL") == "AAPL"
    assert is_kr_ticker("005930.KS") and not is_kr_ticker("AAPL")


# ─── 토큰 매니저 ────────────────────────────────────
@respx.mock
def test_token_issue_and_cache(respx_mock):
    route = _token_route(respx_mock)
    mgr = TossTokenManager(app_key="ak", app_secret="sk", base_url=BASE)
    assert mgr.get_token() == "tok-1"
    # 두 번째 호출은 캐시 → 추가 발급 없음
    assert mgr.get_token() == "tok-1"
    assert route.call_count == 1


@respx.mock
def test_token_invalidate_reissues(respx_mock):
    route = _token_route(respx_mock)
    mgr = TossTokenManager(app_key="ak", app_secret="sk", base_url=BASE)
    mgr.get_token()
    mgr.invalidate()
    mgr.get_token()
    assert route.call_count == 2


def test_token_missing_credentials():
    mgr = TossTokenManager(app_key="", app_secret="", base_url=BASE)
    assert not mgr.credentials_present()
    with pytest.raises(TossAuthError):
        mgr.get_token()


def test_mask_secret():
    assert mask_secret("abcdefgh").startswith("abcd")
    assert "efgh" not in mask_secret("abcdefgh")
    assert mask_secret("") == "<unset>"


# ─── accountSeq 식별 ────────────────────────────────
@respx.mock
def test_account_seq_match_by_account_no(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/v1/accounts").mock(return_value=httpx.Response(
        200, json={"result": [
            {"accountSeq": 7, "accountNo": "11012345678"},
            {"accountSeq": 8, "accountNo": "99999999999"},
        ]}))
    broker = _make_broker(account_no="110-123-45678")  # 하이픈 포함도 매칭
    assert broker._resolve_account_seq() == 7


@respx.mock
def test_account_seq_single_account_fallback(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/v1/accounts").mock(return_value=httpx.Response(
        200, json=[{"accountSeq": 3, "accountNo": "55500011122"}]))
    broker = _make_broker(account_no="")  # 미지정 + 단일계좌 → 사용
    assert broker._resolve_account_seq() == 3


@respx.mock
def test_account_seq_mismatch_returns_none(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/v1/accounts").mock(return_value=httpx.Response(
        200, json={"result": [{"accountSeq": 1, "accountNo": "00000000000"}]}))
    broker = _make_broker(account_no="11112345678")
    assert broker._resolve_account_seq() is None


# ─── 주문 ───────────────────────────────────────────
@respx.mock
def test_place_order_success_sets_account_header(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/v1/accounts").mock(return_value=httpx.Response(
        200, json={"result": [{"accountSeq": 7, "accountNo": "11012345678"}]}))
    order_route = respx_mock.post(f"{BASE}/api/v1/orders").mock(return_value=httpx.Response(
        201, json={"orderId": "OID-99", "status": "ACCEPTED",
                   "clientOrderId": "cid-1", "filledQuantity": 0}))
    broker = _make_broker()
    req = OrderRequest(ticker="005930.KS", qty=10, side=OrderSide.BUY,
                       order_type=OrderType.LIMIT, limit_price=70000,
                       client_order_id="cid-1")
    res = broker.place_order(req)
    assert res.success and res.broker_order_id == "OID-99"
    assert res.status == OrderStatus.ACCEPTED
    # X-Tossinvest-Account 헤더에 accountSeq(7) 탑재 확인
    sent = order_route.calls.last.request
    assert sent.headers["X-Tossinvest-Account"] == "7"
    assert "Bearer tok-1" in sent.headers["Authorization"]


@respx.mock
def test_place_order_high_value_kr_flag(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/v1/accounts").mock(return_value=httpx.Response(
        200, json=[{"accountSeq": 1, "accountNo": "11012345678"}]))
    order_route = respx_mock.post(f"{BASE}/api/v1/orders").mock(return_value=httpx.Response(
        201, json={"orderId": "X", "status": "ACCEPTED"}))
    broker = _make_broker()
    # 1억 이상: 70000 * 2000 = 1.4억
    req = OrderRequest(ticker="005930.KS", qty=2000, side=OrderSide.BUY,
                       order_type=OrderType.LIMIT, limit_price=70000)
    broker.place_order(req)
    import json
    body = json.loads(order_route.calls.last.request.content)
    assert body.get("confirmHighValueOrder") is True


@respx.mock
def test_place_order_401_then_reissue(respx_mock):
    # 토큰 1회차 tok-1, 2회차 tok-2
    respx_mock.post(TOKEN_URL).mock(side_effect=[
        httpx.Response(200, json={"access_token": "tok-1", "expires_in": 1800}),
        httpx.Response(200, json={"access_token": "tok-2", "expires_in": 1800}),
    ])
    respx_mock.get(f"{BASE}/api/v1/accounts").mock(return_value=httpx.Response(
        200, json=[{"accountSeq": 1, "accountNo": "11012345678"}]))
    # 첫 주문 호출 401 → 재발급 후 201
    respx_mock.post(f"{BASE}/api/v1/orders").mock(side_effect=[
        httpx.Response(401, json={"message": "expired"}),
        httpx.Response(201, json={"orderId": "OID-2", "status": "FILLED",
                                  "filledQuantity": 5, "avgPrice": 71000}),
    ])
    broker = _make_broker()
    req = OrderRequest(ticker="005930.KS", qty=5, side=OrderSide.BUY,
                       order_type=OrderType.MARKET)
    res = broker.place_order(req)
    assert res.success and res.status == OrderStatus.FILLED
    assert res.filled_qty == 5 and res.avg_fill_price == 71000


@respx.mock
def test_place_order_reject_maps_status(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/v1/accounts").mock(return_value=httpx.Response(
        200, json=[{"accountSeq": 1, "accountNo": "11012345678"}]))
    respx_mock.post(f"{BASE}/api/v1/orders").mock(return_value=httpx.Response(
        400, json={"message": "invalid price"}))
    broker = _make_broker()
    req = OrderRequest(ticker="005930.KS", qty=1, side=OrderSide.BUY,
                       order_type=OrderType.LIMIT, limit_price=1)
    res = broker.place_order(req)
    assert not res.success and res.status == OrderStatus.REJECTED


@respx.mock
def test_cancel_and_status(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/v1/accounts").mock(return_value=httpx.Response(
        200, json=[{"accountSeq": 1, "accountNo": "11012345678"}]))
    respx_mock.post(f"{BASE}/api/v1/orders/OID-9/cancel").mock(
        return_value=httpx.Response(200, json={}))
    respx_mock.get(f"{BASE}/api/v1/orders/OID-9").mock(return_value=httpx.Response(
        200, json={"orderId": "OID-9", "status": "PARTIALLY_FILLED",
                   "filledQuantity": 3, "clientOrderId": "c9"}))
    broker = _make_broker()
    assert broker.cancel_order("OID-9").status == OrderStatus.CANCELLED
    st = broker.get_order_status("OID-9")
    assert st.status == OrderStatus.PARTIAL and st.filled_qty == 3


@respx.mock
def test_positions_restore_kr_suffix(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/v1/accounts").mock(return_value=httpx.Response(
        200, json=[{"accountSeq": 1, "accountNo": "11012345678"}]))
    # 실제 보유종목 응답: result.items, marketCountry/quantity/lastPrice/averagePurchasePrice
    respx_mock.get(f"{BASE}/api/v1/holdings").mock(return_value=httpx.Response(
        200, json={"result": {"items": [
            {"symbol": "005930", "marketCountry": "KR", "currency": "KRW",
             "quantity": "10", "lastPrice": "72000", "averagePurchasePrice": "70000",
             "marketValue": {"amount": "720000"}, "profitLoss": {"amount": "20000",
                                                                 "rate": "0.0286"}},
            {"symbol": "035720", "marketCountry": "KR", "currency": "KRW",
             "quantity": "5", "lastPrice": "49000", "averagePurchasePrice": "50000",
             "marketValue": {"amount": "245000"}, "profitLoss": {"amount": "-5000",
                                                                 "rate": "-0.02"}},
        ]}}))
    respx_mock.get(f"{BASE}/api/v1/stocks").mock(return_value=httpx.Response(
        200, json={"result": [
            {"symbol": "005930", "market": "KOSPI"},
            {"symbol": "035720", "market": "KOSDAQ"},
        ]}))
    broker = _make_broker()
    pos = broker.get_positions()
    tickers = {p["ticker"] for p in pos}
    assert tickers == {"005930.KS", "035720.KQ"}
    by_ticker = {p["ticker"]: p for p in pos}
    assert by_ticker["005930.KS"]["qty"] == 10
    assert by_ticker["005930.KS"]["avg_entry_price"] == 70000
    assert by_ticker["005930.KS"]["market_value"] == 720000


# ─── 안전 폴백 ──────────────────────────────────────
def test_no_credentials_safe_behavior():
    broker = TossBroker(app_key="", app_secret="", account_no="", base_url=BASE)
    assert not broker._credentials_present()
    req = OrderRequest(ticker="005930.KS", qty=1, side=OrderSide.BUY,
                       order_type=OrderType.MARKET)
    res = broker.place_order(req)
    assert not res.success and res.status == OrderStatus.ERROR
    assert broker.health_check()["ok"] is False
