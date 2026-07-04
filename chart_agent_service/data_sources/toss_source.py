"""
토스증권 Open API 시세 데이터 소스 어댑터.

`DataSource` 프로토콜 준수. 국내(KRX)·미국 캔들/가격/호가를 제공한다.
- 캔들 `/api/v1/candles`는 1회 최대 200봉 → `nextBefore` 페이지네이션(최대 5페이지).
- 반환 DataFrame은 yfinance 호환 컬럼(Open/High/Low/Close/Volume) + DatetimeIndex(오름차순).
  캐시 메타(fetched_at/latest_bar_date/source)는 `df.attrs`에 기록(CLAUDE.md 5.5).

인증은 브로커와 동일한 `TossTokenManager`를 공유한다.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import pandas as pd

from data_sources.base import Quote
from brokers.toss_auth import TossTokenManager
from brokers.toss_broker import to_toss_symbol


# 1회 호출 최대 봉 수 (명세)
_PAGE_SIZE = 200
# 무한루프 방지 페이지 한도
_MAX_PAGES = 5

# period → 목표 봉 수 (영업일 근사)
_PERIOD_BARS = {
    "1d": 1, "5d": 5, "1mo": 23, "3mo": 66, "6mo": 130,
    "1y": 260, "2y": 520, "5y": 1000, "max": 1000,
}

# 내부 interval → 토스 캔들 interval.
# 토스 /api/v1/candles는 "1m", "1d"만 지원 → 그 외는 1d로 근사(일봉 EOD 기준).
_INTERVAL_MAP = {
    "1m": "1m", "5m": "1m", "15m": "1m", "30m": "1m", "1h": "1m",
    "1d": "1d", "1wk": "1d", "1mo": "1d",
}


class TossDataSource:
    """토스증권 Open API 시세 REST 어댑터."""

    name = "toss"

    def __init__(self,
                 app_key: Optional[str] = None,
                 app_secret: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: float = 10.0):
        self.app_key = app_key if app_key is not None else os.getenv("TOSS_APP_KEY", "")
        self.app_secret = (
            app_secret if app_secret is not None else os.getenv("TOSS_APP_SECRET", "")
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

    # ─── 내부 ──────────────────────────────────────
    def _credentials_present(self) -> bool:
        return bool(self.app_key and self.app_secret)

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        return self._client

    def _get(self, path: str, params: Dict[str, Any]) -> Optional[httpx.Response]:
        """인증 GET. 401이면 토큰 무효화 후 1회 재시도. 실패 시 None."""
        try:
            client = self._get_client()
            resp = client.get(path, params=params, headers=self._auth.auth_header())
            if resp.status_code == 401:
                self._auth.invalidate()
                resp = client.get(path, params=params, headers=self._auth.auth_header())
            return resp
        except Exception:
            return None

    # ─── OHLCV ──────────────────────────────────────
    def get_ohlcv(self, ticker: str, period: str = "1y",
                  interval: str = "1d") -> pd.DataFrame:
        """
        과거 OHLCV DataFrame 반환 (Open/High/Low/Close/Volume, DatetimeIndex 오름차순).
        자격증명 없으면 빈 DataFrame. nextBefore 페이지네이션(최대 5페이지).
        """
        if not self._credentials_present():
            return pd.DataFrame()

        symbol = to_toss_symbol(ticker)
        toss_interval = _INTERVAL_MAP.get(interval, "day")
        target_bars = _PERIOD_BARS.get(period, 260)

        rows: List[Dict[str, Any]] = []
        next_before: Optional[str] = None
        for _ in range(_MAX_PAGES):
            params: Dict[str, Any] = {
                "symbol": symbol,
                "interval": toss_interval,
                "count": _PAGE_SIZE,
            }
            # 페이지네이션: 이전 페이지의 nextBefore를 `before`로 전달 (해당 시점 이전 캔들).
            if next_before:
                params["before"] = next_before
            resp = self._get("/api/v1/candles", params)
            if resp is None or resp.status_code != 200:
                break
            result = resp.json().get("result", {})
            candles = result.get("candles", []) if isinstance(result, dict) else result
            if not candles:
                break
            rows.extend(candles)
            next_before = result.get("nextBefore") if isinstance(result, dict) else None
            if not next_before or len(rows) >= target_bars:
                break

        if not rows:
            return pd.DataFrame()

        df = self._candles_to_df(rows)
        if df.empty:
            return df
        # 목표 봉 수로 절단 (최근 N개)
        df = df.iloc[-target_bars:]
        # 캐시 메타 (CLAUDE.md 5.5)
        df.attrs["source"] = self.name
        df.attrs["fetched_at"] = datetime.now(timezone.utc).isoformat()
        df.attrs["latest_bar_date"] = df.index[-1].isoformat()
        return df

    @staticmethod
    def _candles_to_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
        df = pd.DataFrame(rows)
        # 타임스탬프/컬럼명 정규화. 토스 캔들 필드: openPrice/highPrice/lowPrice/closePrice/volume.
        ts_col = next((c for c in ("timestamp", "dt", "date", "time") if c in df.columns), None)
        if ts_col is None:
            return pd.DataFrame()
        rename = {ts_col: "timestamp",
                  "openPrice": "Open", "highPrice": "High",
                  "lowPrice": "Low", "closePrice": "Close", "volume": "Volume",
                  # 구버전/대체 키 방어
                  "open": "Open", "high": "High", "low": "Low", "close": "Close"}
        df = df.rename(columns=rename)
        needed = ["Open", "High", "Low", "Close", "Volume"]
        if not all(c in df.columns for c in needed):
            return pd.DataFrame()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        for c in needed:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["Volume"] = df["Volume"].fillna(0)
        return df[needed]

    # ─── 실시간 ─────────────────────────────────────
    def get_latest_price(self, ticker: str) -> Optional[float]:
        """최신 가격 (GET /api/v1/prices?symbols=...). 응답: result[0].lastPrice."""
        if not self._credentials_present():
            return None
        resp = self._get("/api/v1/prices", {"symbols": to_toss_symbol(ticker)})
        if resp is None or resp.status_code != 200:
            return None
        result = resp.json().get("result", [])
        if isinstance(result, list) and result:
            item = result[0]
        elif isinstance(result, dict):
            item = result
        else:
            return None
        price = item.get("lastPrice", item.get("price", item.get("close")))
        return float(price) if price is not None else None

    def get_quote(self, ticker: str) -> Optional[Quote]:
        """최신 호가 (GET /api/v1/orderbook)."""
        if not self._credentials_present():
            return None
        symbol = to_toss_symbol(ticker)
        resp = self._get("/api/v1/orderbook", {"symbol": symbol})
        if resp is None or resp.status_code != 200:
            return None
        data = resp.json().get("result", {})
        # 최우선 매수/매도 호가. 토스 호가 필드: price/volume.
        bids = data.get("bids") or []
        asks = data.get("asks") or []
        if bids and asks:
            bid, ask = bids[0], asks[0]
            return Quote(
                ticker=ticker.upper(),
                bid=float(bid.get("price", 0) or 0),
                ask=float(ask.get("price", 0) or 0),
                bid_size=int(float(bid.get("volume", bid.get("quantity", 0)) or 0)),
                ask_size=int(float(ask.get("volume", ask.get("quantity", 0)) or 0)),
                timestamp=data.get("timestamp", datetime.now().isoformat()),
                last_price=self.get_latest_price(ticker),
            )
        # 평탄 구조 폴백
        if "bidPrice" in data and "askPrice" in data:
            return Quote(
                ticker=ticker.upper(),
                bid=float(data.get("bidPrice", 0) or 0),
                ask=float(data.get("askPrice", 0) or 0),
                bid_size=int(data.get("bidSize", 0) or 0),
                ask_size=int(data.get("askSize", 0) or 0),
                timestamp=data.get("timestamp", datetime.now().isoformat()),
                last_price=self.get_latest_price(ticker),
            )
        return None

    def health_check(self) -> Dict[str, Any]:
        if not self._credentials_present():
            return {"ok": False, "latency_ms": 0, "message": "토스 자격증명 미설정"}
        start = datetime.now()
        price = self.get_latest_price("005930.KS")
        latency_ms = int((datetime.now() - start).total_seconds() * 1000)
        if price:
            return {"ok": True, "latency_ms": latency_ms,
                    "message": f"토스 시세 정상 (005930={price:.0f})"}
        return {"ok": False, "latency_ms": latency_ms, "message": "토스 시세 응답 없음"}

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
