"""
Alpaca Market Data API (REST) 어댑터 (Phase 2.2).

Endpoint: https://data.alpaca.markets/v2/stocks/...
- /bars       : 과거 OHLCV
- /quotes/latest : 최신 호가
- /trades/latest : 최신 체결가

Free 플랜 = IEX feed, 유료 = SIP feed (모든 거래소)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import httpx
import pandas as pd

from data_sources.base import Quote


# period 문자열 → (timeframe, days) 매핑
_PERIOD_MAP = {
    "1d": ("1Day", 1),
    "5d": ("1Day", 7),
    "1mo": ("1Day", 31),
    "3mo": ("1Day", 93),
    "6mo": ("1Day", 186),
    "1y": ("1Day", 366),
    "2y": ("1Day", 732),
    "5y": ("1Day", 1826),
    "max": ("1Day", 3650),
}

# interval → Alpaca timeframe
_INTERVAL_MAP = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "1d": "1Day",
    "1wk": "1Week",
    "1mo": "1Month",
}


class AlpacaDataSource:
    """Alpaca Market Data REST 어댑터."""

    name = "alpaca"

    def __init__(self,
                 api_key: Optional[str] = None,
                 secret_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 feed: Optional[str] = None,
                 timeout: float = 10.0):
        self.api_key = api_key or os.getenv("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY", "")
        self.base_url = (base_url or os.getenv(
            "ALPACA_DATA_URL", "https://data.alpaca.markets"
        )).rstrip("/")
        self.feed = feed or os.getenv("ALPACA_DATA_FEED", "iex")
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None

    def _headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=self._headers(),
                timeout=self.timeout,
            )
        return self._client

    def _credentials_present(self) -> bool:
        return bool(self.api_key and self.secret_key)

    # ─── OHLCV ──────────────────────────────────────
    def get_ohlcv(self, ticker: str, period: str = "1y",
                  interval: str = "1d") -> pd.DataFrame:
        """
        과거 OHLCV DataFrame 반환.
        반환 컬럼: Open, High, Low, Close, Volume (yfinance 호환).
        자격증명 없으면 빈 DataFrame.
        """
        if not self._credentials_present():
            return pd.DataFrame()

        # period/interval 매핑
        timeframe = _INTERVAL_MAP.get(interval, "1Day")
        _, days_back = _PERIOD_MAP.get(period, ("1Day", 366))
        # 유료 계좌 아닐 시 어제까지만 조회 가능 (15분 지연 free tier)
        # 여유있게 end를 현재로 두고 start를 days_back 이전으로
        end = datetime.now()
        start = end - timedelta(days=days_back)

        params = {
            "timeframe": timeframe,
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 10000,
            "feed": self.feed,
            "adjustment": "raw",
        }

        try:
            client = self._get_client()
            resp = client.get(f"/v2/stocks/{ticker.upper()}/bars", params=params)
        except Exception:
            return pd.DataFrame()

        if resp.status_code != 200:
            return pd.DataFrame()

        data = resp.json()
        bars = data.get("bars", [])
        if not bars:
            return pd.DataFrame()

        # DataFrame 변환 (yfinance 호환 컬럼명)
        df = pd.DataFrame(bars)
        df = df.rename(columns={
            "t": "timestamp",
            "o": "Open",
            "h": "High",
            "l": "Low",
            "c": "Close",
            "v": "Volume",
        })
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
        return df[["Open", "High", "Low", "Close", "Volume"]]

    # ─── 실시간 (무료 티어는 15분 지연) ────────────
    def get_latest_price(self, ticker: str) -> Optional[float]:
        """최신 체결가 (GET /v2/stocks/{symbol}/trades/latest)."""
        if not self._credentials_present():
            return None
        try:
            client = self._get_client()
            resp = client.get(
                f"/v2/stocks/{ticker.upper()}/trades/latest",
                params={"feed": self.feed},
            )
            if resp.status_code == 200:
                data = resp.json()
                trade = data.get("trade", {})
                if "p" in trade:
                    return float(trade["p"])
        except Exception:
            return None
        return None

    def get_quote(self, ticker: str) -> Optional[Quote]:
        """최신 호가 (GET /v2/stocks/{symbol}/quotes/latest)."""
        if not self._credentials_present():
            return None
        try:
            client = self._get_client()
            resp = client.get(
                f"/v2/stocks/{ticker.upper()}/quotes/latest",
                params={"feed": self.feed},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            q = data.get("quote", {})
            if not q:
                return None
            last_price = self.get_latest_price(ticker)
            return Quote(
                ticker=ticker.upper(),
                bid=float(q.get("bp", 0)),
                ask=float(q.get("ap", 0)),
                bid_size=int(q.get("bs", 0)),
                ask_size=int(q.get("as", 0)),
                timestamp=q.get("t", datetime.now().isoformat()),
                last_price=last_price,
            )
        except Exception:
            return None

    def health_check(self) -> Dict[str, Any]:
        if not self._credentials_present():
            return {"ok": False, "latency_ms": 0, "message": "Alpaca 자격증명 미설정"}
        start = datetime.now()
        price = self.get_latest_price("SPY")
        latency_ms = int((datetime.now() - start).total_seconds() * 1000)
        if price:
            return {
                "ok": True,
                "latency_ms": latency_ms,
                "message": f"Alpaca {self.feed} feed 정상 (SPY=${price:.2f})",
            }
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "message": "Alpaca 응답 없음 (키/구독 확인)",
        }

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
