"""
Alpaca Broker 어댑터 (Phase 2.2).

Alpaca Markets REST API v2 직접 호출 (alpaca-py SDK 미의존).
- Paper 계좌: https://paper-api.alpaca.markets
- Live 계좌:  https://api.alpaca.markets

인증: APCA-API-KEY-ID / APCA-API-SECRET-KEY 헤더
문서: https://docs.alpaca.markets/reference

BrokerInterface를 완전히 준수하여 factory에서 투명하게 사용 가능.
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


class AlpacaBroker:
    """Alpaca Markets REST API 어댑터."""

    name = "alpaca"

    # Alpaca 주문 상태 → 내부 OrderStatus 매핑
    # https://docs.alpaca.markets/reference/getallorders
    _STATUS_MAP = {
        "new": OrderStatus.SUBMITTED,
        "accepted": OrderStatus.ACCEPTED,
        "pending_new": OrderStatus.SUBMITTED,
        "accepted_for_bidding": OrderStatus.ACCEPTED,
        "partially_filled": OrderStatus.PARTIAL,
        "filled": OrderStatus.FILLED,
        "done_for_day": OrderStatus.CANCELLED,
        "canceled": OrderStatus.CANCELLED,
        "expired": OrderStatus.CANCELLED,
        "replaced": OrderStatus.ACCEPTED,
        "pending_cancel": OrderStatus.ACCEPTED,
        "pending_replace": OrderStatus.ACCEPTED,
        "rejected": OrderStatus.REJECTED,
        "suspended": OrderStatus.REJECTED,
        "calculated": OrderStatus.FILLED,
        "stopped": OrderStatus.CANCELLED,
    }

    # 내부 OrderType → Alpaca type 매핑
    _TYPE_MAP = {
        OrderType.MARKET: "market",
        OrderType.LIMIT: "limit",
        OrderType.STOP: "stop",
        OrderType.STOP_LIMIT: "stop_limit",
    }

    # 내부 TimeInForce → Alpaca tif 매핑
    _TIF_MAP = {
        TimeInForce.DAY: "day",
        TimeInForce.GTC: "gtc",
        TimeInForce.IOC: "ioc",
        TimeInForce.FOK: "fok",
    }

    def __init__(self,
                 api_key: Optional[str] = None,
                 secret_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: float = 10.0):
        self.api_key = api_key or os.getenv("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY", "")
        self.base_url = (base_url or os.getenv(
            "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
        )).rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None

    # ─── 내부 유틸 ──────────────────────────────────
    def _headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json",
        }

    def _get_client(self) -> httpx.Client:
        """연결 풀 재사용 (이미 Sprint 2에서 검증된 패턴)."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=self._headers(),
                timeout=self.timeout,
            )
        return self._client

    def _credentials_present(self) -> bool:
        return bool(self.api_key and self.secret_key)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self._credentials_present():
            raise RuntimeError("Alpaca API 키 미설정 (ALPACA_API_KEY / ALPACA_SECRET_KEY)")
        client = self._get_client()
        return client.request(method, path, **kwargs)

    def _map_status(self, alpaca_status: str) -> str:
        return self._STATUS_MAP.get((alpaca_status or "").lower(), OrderStatus.ACCEPTED)

    def _is_paper(self) -> bool:
        return "paper" in self.base_url

    # ─── BrokerInterface 구현 ───────────────────────
    def place_order(self, req: OrderRequest) -> OrderResult:
        """
        주문 제출.

        Alpaca 주문 스펙 (POST /v2/orders):
          symbol, qty (or notional), side, type, time_in_force,
          limit_price, stop_price, client_order_id,
          extended_hours (optional), order_class (simple/bracket/oco/oto)
        """
        if not self._credentials_present():
            return OrderResult(
                success=False, status=OrderStatus.ERROR,
                client_order_id=req.client_order_id,
                broker=self.name,
                error_message="Alpaca 자격증명 미설정",
            )

        body: Dict[str, Any] = {
            "symbol": req.ticker.upper(),
            "qty": str(req.qty),
            "side": req.side,
            "type": self._TYPE_MAP.get(req.order_type, "market"),
            "time_in_force": self._TIF_MAP.get(req.time_in_force, "day"),
            "client_order_id": req.client_order_id,
        }
        if req.limit_price is not None:
            body["limit_price"] = str(req.limit_price)
        if req.stop_price is not None:
            body["stop_price"] = str(req.stop_price)

        try:
            resp = self._request("POST", "/v2/orders", json=body)
        except Exception as e:
            return OrderResult(
                success=False, status=OrderStatus.ERROR,
                client_order_id=req.client_order_id,
                broker=self.name,
                error_message=f"네트워크 오류: {e}",
            )

        if resp.status_code in (200, 201):
            data = resp.json()
            return OrderResult(
                success=True,
                status=self._map_status(data.get("status", "accepted")),
                client_order_id=data.get("client_order_id", req.client_order_id),
                broker_order_id=data.get("id"),
                broker=self.name,
                filled_qty=int(float(data.get("filled_qty", 0) or 0)),
                avg_fill_price=float(data["filled_avg_price"]) if data.get("filled_avg_price") else None,
                raw_response=data,
            )

        # 오류 처리
        try:
            err_data = resp.json()
            msg = err_data.get("message", resp.text)
        except Exception:
            err_data = {"text": resp.text}
            msg = resp.text
        return OrderResult(
            success=False,
            status=OrderStatus.REJECTED if resp.status_code in (400, 422) else OrderStatus.ERROR,
            client_order_id=req.client_order_id,
            broker=self.name,
            error_message=f"[{resp.status_code}] {msg[:200]}",
            raw_response=err_data,
        )

    def cancel_order(self, broker_order_id: str) -> OrderResult:
        """주문 취소 (DELETE /v2/orders/{id}). 204 = 성공."""
        try:
            resp = self._request("DELETE", f"/v2/orders/{broker_order_id}")
        except Exception as e:
            return OrderResult(
                success=False, status=OrderStatus.ERROR,
                client_order_id="",
                broker_order_id=broker_order_id,
                broker=self.name,
                error_message=f"취소 네트워크 오류: {e}",
            )

        if resp.status_code in (200, 204):
            return OrderResult(
                success=True, status=OrderStatus.CANCELLED,
                client_order_id="",
                broker_order_id=broker_order_id,
                broker=self.name,
            )
        return OrderResult(
            success=False,
            status=OrderStatus.ERROR,
            client_order_id="",
            broker_order_id=broker_order_id,
            broker=self.name,
            error_message=f"취소 실패 [{resp.status_code}]: {resp.text[:200]}",
        )

    def get_order_status(self, broker_order_id: str) -> OrderResult:
        """주문 상세 조회."""
        try:
            resp = self._request("GET", f"/v2/orders/{broker_order_id}")
        except Exception as e:
            return OrderResult(
                success=False, status=OrderStatus.ERROR,
                client_order_id="",
                broker_order_id=broker_order_id,
                broker=self.name,
                error_message=f"조회 오류: {e}",
            )

        if resp.status_code == 200:
            data = resp.json()
            return OrderResult(
                success=True,
                status=self._map_status(data.get("status", "")),
                client_order_id=data.get("client_order_id", ""),
                broker_order_id=data.get("id"),
                broker=self.name,
                filled_qty=int(float(data.get("filled_qty", 0) or 0)),
                avg_fill_price=float(data["filled_avg_price"]) if data.get("filled_avg_price") else None,
                raw_response=data,
            )
        return OrderResult(
            success=False, status=OrderStatus.ERROR,
            client_order_id="",
            broker_order_id=broker_order_id,
            broker=self.name,
            error_message=f"조회 실패 [{resp.status_code}]",
        )

    def get_positions(self) -> List[Dict[str, Any]]:
        """보유 포지션 (GET /v2/positions)."""
        try:
            resp = self._request("GET", "/v2/positions")
        except Exception:
            return []
        if resp.status_code != 200:
            return []
        items = resp.json()
        out = []
        for p in items:
            try:
                qty = int(float(p.get("qty", 0)))
            except (ValueError, TypeError):
                qty = 0
            entry = float(p.get("avg_entry_price") or 0)
            current = float(p.get("current_price") or 0)
            unrealized = float(p.get("unrealized_pl") or 0)
            unrealized_pct = float(p.get("unrealized_plpc") or 0) * 100
            out.append({
                "ticker": p.get("symbol"),
                "qty": qty,
                "avg_entry_price": entry,
                "current_price": current,
                "unrealized_pnl": unrealized,
                "unrealized_pnl_pct": unrealized_pct,
                "market_value": float(p.get("market_value") or 0),
                "side": p.get("side", "long"),
                "asset_class": p.get("asset_class"),
            })
        return out

    def get_account(self) -> Dict[str, Any]:
        """계좌 요약 (GET /v2/account)."""
        try:
            resp = self._request("GET", "/v2/account")
        except Exception as e:
            return {"broker": self.name, "error": f"조회 오류: {e}"}
        if resp.status_code != 200:
            return {"broker": self.name, "error": f"[{resp.status_code}] 계좌 조회 실패"}
        data = resp.json()
        return {
            "broker": self.name,
            "account_number": data.get("account_number"),
            "status": data.get("status"),
            "paper_trading": self._is_paper(),
            "total_equity": float(data.get("equity") or 0),
            "cash": float(data.get("cash") or 0),
            "buying_power": float(data.get("buying_power") or 0),
            "position_value": float(data.get("long_market_value") or 0),
            "pattern_day_trader": data.get("pattern_day_trader", False),
            "trading_blocked": data.get("trading_blocked", False),
            "account_blocked": data.get("account_blocked", False),
            "currency": data.get("currency", "USD"),
        }

    def is_market_open(self) -> bool:
        """장 시간 체크 (GET /v2/clock)."""
        try:
            resp = self._request("GET", "/v2/clock")
        except Exception:
            return False
        if resp.status_code != 200:
            return False
        data = resp.json()
        return bool(data.get("is_open", False))

    def get_market_clock(self) -> Dict[str, Any]:
        """다음 open/close 시각 포함한 상세 clock 정보."""
        try:
            resp = self._request("GET", "/v2/clock")
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def health_check(self) -> Dict[str, Any]:
        """연결 확인 — /v2/account 호출로 credential + network 점검."""
        if not self._credentials_present():
            return {"ok": False, "latency_ms": 0, "message": "Alpaca 자격증명 미설정"}

        start = datetime.now()
        try:
            resp = self._request("GET", "/v2/account")
        except Exception as e:
            return {"ok": False, "latency_ms": 0, "message": f"연결 실패: {e}"}

        latency_ms = int((datetime.now() - start).total_seconds() * 1000)
        if resp.status_code == 200:
            data = resp.json()
            mode = "paper" if self._is_paper() else "live"
            return {
                "ok": True,
                "latency_ms": latency_ms,
                "message": f"Alpaca {mode} 계좌 정상 ({data.get('status')})",
            }
        if resp.status_code == 401:
            return {"ok": False, "latency_ms": latency_ms, "message": "인증 실패 — API 키 확인"}
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "message": f"상태 코드 {resp.status_code}",
        }

    def close(self):
        """명시적 연결 정리."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
