"""
토스증권 Open API 브로커 어댑터.

`https://openapi.tossinvest.com` REST API를 통해 국내(KRX)·미국 주식 주문/계좌/보유주식을
다룬다. `BrokerInterface`를 완전히 준수하여 factory에서 투명하게 사용된다.

인증: OAuth2 Bearer (`TossTokenManager`).
계좌/자산/주문 API는 `X-Tossinvest-Account: {accountSeq}` 헤더 필수.
  accountSeq는 계좌번호가 아니라 GET /api/v1/accounts가 반환하는 정수 식별값 →
  사용자 입력 TOSS_ACCOUNT_NO를 매칭해 자동 식별·캐싱한다.

엔드포인트 경로/필드명은 OpenAPI JSON 명세를 SSOT로 한다 (변경 시 이 어댑터 조정).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from brokers.base import (
    OrderRequest, OrderResult,
    OrderStatus, OrderSide, OrderType, TimeInForce,
)
from brokers.toss_auth import TossTokenManager, TossAuthError


# KR 착오주문 방지: 이 금액(원) 이상이면 confirmHighValueOrder 플래그 부착
_HIGH_VALUE_KRW = 100_000_000


# ─── 티커 변환 (브로커·데이터소스 공유) ────────────────────────
def is_kr_ticker(ticker: str) -> bool:
    """내부 표기에서 한국 종목 여부 (.KS=KOSPI, .KQ=KOSDAQ)."""
    return ticker.upper().endswith((".KS", ".KQ"))


def to_toss_symbol(ticker: str) -> str:
    """내부 티커 → 토스 심볼. 한국은 6자리 숫자, 미국은 대문자 심볼."""
    t = ticker.upper()
    if t.endswith((".KS", ".KQ")):
        return t[:-3]
    return t


def from_toss_symbol(code: str, market: Optional[str] = None) -> str:
    """
    토스 심볼 → 내부 티커.
    market(KOSPI/KOSDAQ)이 주어지면 .KS/.KQ 접미사 복원, 아니면 그대로(미국).
    """
    if market:
        m = market.upper()
        if m in ("KOSPI", "KSC", "KS"):
            return f"{code}.KS"
        if m in ("KOSDAQ", "KOE", "KQ"):
            return f"{code}.KQ"
    return code.upper()


class TossBroker:
    """토스증권 Open API REST 어댑터."""

    name = "toss"

    # 토스 주문 상태 → 내부 OrderStatus 매핑 (명세 status 값 기준)
    _STATUS_MAP = {
        "PENDING": OrderStatus.SUBMITTED,
        "RECEIVED": OrderStatus.SUBMITTED,
        "ACCEPTED": OrderStatus.ACCEPTED,
        "PARTIALLY_FILLED": OrderStatus.PARTIAL,
        "PARTIAL": OrderStatus.PARTIAL,
        "FILLED": OrderStatus.FILLED,
        "COMPLETED": OrderStatus.FILLED,
        "EXECUTED": OrderStatus.FILLED,
        "CANCELLED": OrderStatus.CANCELLED,
        "CANCELED": OrderStatus.CANCELLED,
        "EXPIRED": OrderStatus.CANCELLED,
        "REJECTED": OrderStatus.REJECTED,
    }

    # 내부 OrderType → 토스 orderType
    _TYPE_MAP = {
        OrderType.MARKET: "MARKET",
        OrderType.LIMIT: "LIMIT",
    }

    def __init__(self,
                 app_key: Optional[str] = None,
                 app_secret: Optional[str] = None,
                 account_no: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: float = 10.0):
        self.app_key = app_key if app_key is not None else os.getenv("TOSS_APP_KEY", "")
        self.app_secret = (
            app_secret if app_secret is not None else os.getenv("TOSS_APP_SECRET", "")
        )
        self.account_no = (
            account_no if account_no is not None else os.getenv("TOSS_ACCOUNT_NO", "")
        )
        self.base_url = (base_url or os.getenv(
            "TOSS_BASE_URL", "https://openapi.tossinvest.com"
        )).rstrip("/")
        self.timeout = timeout

        self._auth = TossTokenManager(
            app_key=self.app_key, app_secret=self.app_secret, base_url=self.base_url,
            timeout=timeout,
        )
        self._client: Optional[httpx.Client] = None
        self._account_seq: Optional[int] = None  # 캐시

    # ─── 내부 유틸 ──────────────────────────────────
    def _credentials_present(self) -> bool:
        return bool(self.app_key and self.app_secret)

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        return self._client

    def _map_status(self, raw: str) -> str:
        return self._STATUS_MAP.get((raw or "").upper(), OrderStatus.ACCEPTED)

    def _resolve_account_seq(self) -> Optional[int]:
        """
        GET /api/v1/accounts에서 TOSS_ACCOUNT_NO와 매칭되는 accountSeq를 찾아 캐싱.

        - account_no가 비어있고 계좌가 1개뿐이면 그 계좌 사용.
        - 매칭 실패 시 None (호출부에서 명시적 에러 처리).
        """
        if self._account_seq is not None:
            return self._account_seq
        resp = self._raw_request("GET", "/api/v1/accounts", with_account=False)
        if resp.status_code != 200:
            return None
        accounts = resp.json()
        if isinstance(accounts, dict):
            accounts = accounts.get("result", accounts.get("accounts", accounts.get("data", [])))
        if not isinstance(accounts, list) or not accounts:
            return None

        def _seq(a: Dict[str, Any]) -> Optional[int]:
            v = a.get("accountSeq", a.get("account_seq"))
            return int(v) if v is not None else None

        # account_no 매칭
        if self.account_no:
            target = self.account_no.replace("-", "")
            for a in accounts:
                no = str(a.get("accountNo", a.get("account_no", ""))).replace("-", "")
                if no and no == target:
                    self._account_seq = _seq(a)
                    return self._account_seq
        # 미지정 + 단일 계좌
        if not self.account_no and len(accounts) == 1:
            self._account_seq = _seq(accounts[0])
            return self._account_seq
        return None

    def _raw_request(self, method: str, path: str, *,
                     with_account: bool, **kwargs) -> httpx.Response:
        """
        인증 헤더 부착 후 호출. 401이면 토큰 무효화 후 1회 재시도.
        with_account=True면 X-Tossinvest-Account(accountSeq) 헤더 부착.
        """
        client = self._get_client()
        headers = dict(kwargs.pop("headers", {}))
        headers.update(self._auth.auth_header())
        if with_account:
            seq = self._resolve_account_seq()
            if seq is None:
                raise TossAuthError(
                    f"accountSeq 식별 실패 (TOSS_ACCOUNT_NO={self.account_no or '<unset>'})"
                )
            headers["X-Tossinvest-Account"] = str(seq)

        resp = client.request(method, path, headers=headers, **kwargs)
        if resp.status_code == 401:
            self._auth.invalidate()
            headers.update(self._auth.auth_header())
            resp = client.request(method, path, headers=headers, **kwargs)
        return resp

    def _error_result(self, req_or_id: Any, msg: str,
                      status: str = OrderStatus.ERROR) -> OrderResult:
        coid = getattr(req_or_id, "client_order_id", "") or ""
        return OrderResult(
            success=False, status=status, client_order_id=coid,
            broker=self.name, error_message=msg,
        )

    # ─── BrokerInterface 구현 ───────────────────────
    def place_order(self, req: OrderRequest) -> OrderResult:
        """주문 제출 (POST /api/v1/orders). LIMIT/MARKET 지원."""
        if not self._credentials_present():
            return self._error_result(req, "토스 자격증명 미설정")
        if req.order_type not in (OrderType.MARKET, OrderType.LIMIT):
            return self._error_result(
                req, f"토스 미지원 주문유형: {req.order_type}", OrderStatus.REJECTED)

        symbol = to_toss_symbol(req.ticker)
        body: Dict[str, Any] = {
            "symbol": symbol,
            "side": "BUY" if req.side == OrderSide.BUY else "SELL",
            "orderType": self._TYPE_MAP[req.order_type],
            "quantity": req.qty,
            "clientOrderId": req.client_order_id,
        }
        if req.order_type == OrderType.LIMIT:
            body["price"] = req.limit_price
        # KR 고액 착오주문 방지 플래그
        est = req.estimated_cost()
        if is_kr_ticker(req.ticker) and est is not None and est >= _HIGH_VALUE_KRW:
            body["confirmHighValueOrder"] = True

        try:
            resp = self._raw_request("POST", "/api/v1/orders", with_account=True, json=body)
        except TossAuthError as e:
            return self._error_result(req, str(e))
        except Exception as e:
            return self._error_result(req, f"네트워크 오류: {type(e).__name__}")

        if resp.status_code in (200, 201):
            data = resp.json()
            return OrderResult(
                success=True,
                status=self._map_status(data.get("status", "ACCEPTED")),
                client_order_id=data.get("clientOrderId", req.client_order_id),
                broker_order_id=str(data.get("orderId") or data.get("id") or ""),
                broker=self.name,
                filled_qty=int(data.get("filledQuantity", 0) or 0),
                avg_fill_price=(
                    float(data["avgPrice"]) if data.get("avgPrice") else None
                ),
                raw_response=data,
            )
        return self._reject_or_error(req.client_order_id, resp)

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        """주문 취소 (POST /api/v1/orders/{orderId}/cancel)."""
        try:
            resp = self._raw_request(
                "POST", f"/api/v1/orders/{broker_order_id}/cancel", with_account=True)
        except TossAuthError as e:
            return OrderResult(success=False, status=OrderStatus.ERROR, client_order_id="",
                               broker_order_id=broker_order_id, broker=self.name,
                               error_message=str(e))
        except Exception as e:
            return OrderResult(success=False, status=OrderStatus.ERROR, client_order_id="",
                               broker_order_id=broker_order_id, broker=self.name,
                               error_message=f"취소 네트워크 오류: {type(e).__name__}")
        if resp.status_code in (200, 204):
            return OrderResult(success=True, status=OrderStatus.CANCELLED, client_order_id="",
                               broker_order_id=broker_order_id, broker=self.name)
        return OrderResult(success=False, status=OrderStatus.ERROR, client_order_id="",
                           broker_order_id=broker_order_id, broker=self.name,
                           error_message=f"취소 실패 [{resp.status_code}]")

    def get_order_status(self, broker_order_id: str) -> OrderResult:
        """주문 상세 조회 (GET /api/v1/orders/{orderId})."""
        try:
            resp = self._raw_request(
                "GET", f"/api/v1/orders/{broker_order_id}", with_account=True)
        except TossAuthError as e:
            return OrderResult(success=False, status=OrderStatus.ERROR, client_order_id="",
                               broker_order_id=broker_order_id, broker=self.name,
                               error_message=str(e))
        except Exception as e:
            return OrderResult(success=False, status=OrderStatus.ERROR, client_order_id="",
                               broker_order_id=broker_order_id, broker=self.name,
                               error_message=f"조회 오류: {type(e).__name__}")
        if resp.status_code == 200:
            data = resp.json()
            return OrderResult(
                success=True,
                status=self._map_status(data.get("status", "")),
                client_order_id=data.get("clientOrderId", ""),
                broker_order_id=str(data.get("orderId") or broker_order_id),
                broker=self.name,
                filled_qty=int(data.get("filledQuantity", 0) or 0),
                avg_fill_price=float(data["avgPrice"]) if data.get("avgPrice") else None,
                raw_response=data,
            )
        return OrderResult(success=False, status=OrderStatus.ERROR, client_order_id="",
                           broker_order_id=broker_order_id, broker=self.name,
                           error_message=f"조회 실패 [{resp.status_code}]")

    def get_positions(self) -> List[Dict[str, Any]]:
        """
        보유 포지션 (GET /api/v1/holdings → result.items).

        토스 보유종목 필드: symbol, marketCountry(US/KR), currency, quantity(소수가능),
        lastPrice, averagePurchasePrice, marketValue.amount, profitLoss.amount/rate.
        KR 종목은 /api/v1/stocks로 KOSPI/KOSDAQ을 조회해 .KS/.KQ 접미사 복원.
        """
        try:
            resp = self._raw_request("GET", "/api/v1/holdings", with_account=True)
        except Exception:
            return []
        if resp.status_code != 200:
            return []
        result = resp.json().get("result", {})
        items = result.get("items", []) if isinstance(result, dict) else result
        if not isinstance(items, list):
            return []

        market_map = self._lookup_kr_markets(items)
        out = []
        for p in items:
            code = str(p.get("symbol", p.get("code", "")))
            ticker = from_toss_symbol(code, market_map.get(code))
            mv = p.get("marketValue", {}) if isinstance(p.get("marketValue"), dict) else {}
            pl = p.get("profitLoss", {}) if isinstance(p.get("profitLoss"), dict) else {}
            out.append({
                "ticker": ticker,
                "qty": float(p.get("quantity", 0) or 0),
                "avg_entry_price": float(p.get("averagePurchasePrice", 0) or 0),
                "current_price": float(p.get("lastPrice", 0) or 0),
                "unrealized_pnl": float(pl.get("amount", 0) or 0),
                "unrealized_pnl_pct": float(pl.get("rate", 0) or 0),
                "market_value": float(mv.get("amount", 0) or 0),
                "side": "long",
                "currency": p.get("currency", "KRW" if is_kr_ticker(ticker) else "USD"),
            })
        return out

    def _lookup_kr_markets(self, holdings: List[Dict[str, Any]]) -> Dict[str, str]:
        """KR 종목 코드 → 시장(KOSPI/KOSDAQ) 매핑 (GET /api/v1/stocks?symbols= 다건)."""
        kr_codes = [
            str(p.get("symbol", p.get("code", "")))
            for p in holdings
            if str(p.get("marketCountry", "")).upper() == "KR"
            or str(p.get("symbol", p.get("code", ""))).isdigit()
        ]
        if not kr_codes:
            return {}
        try:
            resp = self._raw_request(
                "GET", "/api/v1/stocks", with_account=False,
                params={"symbols": ",".join(kr_codes)})
        except Exception:
            return {}
        if resp.status_code != 200:
            return {}
        data = resp.json()
        stocks = data.get("result", data.get("stocks", data)) if isinstance(data, dict) else data
        out: Dict[str, str] = {}
        if isinstance(stocks, list):
            for s in stocks:
                code = str(s.get("symbol", s.get("code", "")))
                mkt = s.get("market", s.get("marketType", ""))
                if code and mkt:
                    out[code] = mkt
        return out

    def get_account(self) -> Dict[str, Any]:
        """
        계좌 요약 — 평가금액(GET /api/v1/holdings) + 매수가능금액(GET /api/v1/buying-power).

        토스에는 통합 잔고 엔드포인트가 없어 두 API를 합성한다.
        - holdings.result.marketValue.amount.{krw,usd}: 보유 평가금액
        - buying-power?currency=KRW|USD → result.cashBuyingPower: 현금 매수가능금액
        """
        if not self._credentials_present():
            return {"broker": self.name, "error": "토스 자격증명 미설정"}
        try:
            resp = self._raw_request("GET", "/api/v1/holdings", with_account=True)
        except TossAuthError as e:
            return {"broker": self.name, "error": str(e)}
        except Exception as e:
            return {"broker": self.name, "error": f"조회 오류: {type(e).__name__}"}
        if resp.status_code != 200:
            return {"broker": self.name, "error": f"[{resp.status_code}] 계좌 조회 실패"}
        result = resp.json().get("result", {})
        mv = result.get("marketValue", {}).get("amount", {}) if isinstance(result, dict) else {}
        mv_krw = float(mv.get("krw", 0) or 0)
        mv_usd = float(mv.get("usd", 0) or 0)

        bp_krw = self._buying_power("KRW")
        bp_usd = self._buying_power("USD")
        return {
            "broker": self.name,
            "account_seq": self._account_seq,
            "paper_trading": False,
            "market_value_krw": mv_krw,
            "market_value_usd": mv_usd,
            "cash_krw": bp_krw,
            "cash_usd": bp_usd,
            "buying_power_krw": bp_krw,
            "buying_power_usd": bp_usd,
            "raw": result,
        }

    def _buying_power(self, currency: str) -> float:
        """통화별 현금 매수가능금액 (GET /api/v1/buying-power?currency=...)."""
        try:
            resp = self._raw_request(
                "GET", "/api/v1/buying-power", with_account=True,
                params={"currency": currency})
        except Exception:
            return 0.0
        if resp.status_code != 200:
            return 0.0
        result = resp.json().get("result", {})
        return float(result.get("cashBuyingPower", 0) or 0)

    def is_market_open(self, market: str = "KR") -> bool:
        """개장 여부 (GET /api/v1/market-calendar/{market})."""
        try:
            resp = self._raw_request(
                "GET", f"/api/v1/market-calendar/{market.upper()}", with_account=False)
        except Exception:
            return False
        if resp.status_code != 200:
            return False
        data = resp.json()
        return bool(data.get("isOpen", data.get("open", False)))

    def health_check(self) -> Dict[str, Any]:
        """연결 확인 — 토큰 발급 + 계좌 조회."""
        if not self._credentials_present():
            return {"ok": False, "latency_ms": 0, "message": "토스 자격증명 미설정"}
        start = datetime.now()
        try:
            seq = self._resolve_account_seq()
        except Exception as e:
            return {"ok": False, "latency_ms": 0, "message": f"연결 실패: {type(e).__name__}"}
        latency_ms = int((datetime.now() - start).total_seconds() * 1000)
        if seq is not None:
            return {"ok": True, "latency_ms": latency_ms,
                    "message": f"토스 계좌 정상 (accountSeq={seq})"}
        return {"ok": False, "latency_ms": latency_ms,
                "message": "accountSeq 식별 실패 — TOSS_ACCOUNT_NO 확인"}

    def _reject_or_error(self, client_order_id: str, resp: httpx.Response) -> OrderResult:
        try:
            err = resp.json()
            msg = err.get("message", err.get("error", resp.text))
        except Exception:
            err = {"text": resp.text}
            msg = resp.text
        return OrderResult(
            success=False,
            status=OrderStatus.REJECTED if resp.status_code in (400, 422) else OrderStatus.ERROR,
            client_order_id=client_order_id, broker=self.name,
            error_message=f"[{resp.status_code}] {str(msg)[:200]}", raw_response=err,
        )

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
