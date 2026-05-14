"""
pykrx 기반 한국 주식 데이터 소스 (Step 3 baseline).
KRX 종목 전용 — 미국 종목 불가.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

import pandas as pd

from data_collector_models import PERIOD_DAYS
from data_sources.base import Quote


class PykrxSource:
    """pykrx 래퍼 — 한국 KRX 1차 소스."""

    name = "pykrx"

    def get_ohlcv(
        self, ticker: str, period: str = "2y", interval: str = "1d"
    ) -> pd.DataFrame:
        from pykrx import stock  # type: ignore[import-untyped]

        # "005930.KS" → "005930"
        krx_code = ticker.upper().split(".")[0]

        end = date.today()
        days = PERIOD_DAYS.get(period, 740)
        start = end - timedelta(days=days)

        df = stock.get_market_ohlcv(
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            krx_code,
        )

        if df is None or df.empty:
            return pd.DataFrame()

        # pykrx 컬럼(한글) → yfinance 호환 영어
        col_map = {
            "시가": "Open",
            "고가": "High",
            "저가": "Low",
            "종가": "Close",
            "거래량": "Volume",
        }
        df = df.rename(columns=col_map)
        df.index = pd.to_datetime(df.index)

        available = [
            c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns
        ]
        return df[available].dropna(how="all")

    def get_latest_price(self, ticker: str) -> Optional[float]:
        try:
            df = self.get_ohlcv(ticker, period="5d")
            if df is not None and not df.empty and "Close" in df.columns:
                return float(df["Close"].iloc[-1])
        except Exception:
            return None
        return None

    def get_quote(self, ticker: str) -> Optional[Quote]:
        price = self.get_latest_price(ticker)
        if price is None:
            return None
        return Quote(
            ticker=ticker,
            bid=price,
            ask=price,
            bid_size=0,
            ask_size=0,
            timestamp=datetime.now().isoformat(),
            last_price=price,
        )

    def health_check(self) -> Dict[str, Any]:
        start = datetime.now()
        price = self.get_latest_price("005930.KS")
        latency_ms = int((datetime.now() - start).total_seconds() * 1000)
        return {
            "ok": price is not None,
            "latency_ms": latency_ms,
            "message": f"pykrx (005930={price})" if price else "pykrx 응답 없음",
        }
