"""
yfinance 기반 데이터 소스 (기존 동작 보존).

실시간 데이터 아님 (15분 지연).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any

import pandas as pd

from data_sources.base import Quote


class YFinanceSource:
    """yfinance 래퍼 — 기존 data_collector 동작을 DataSource 프로토콜로 제공."""

    name = "yfinance"

    def get_ohlcv(self, ticker: str, period: str = "1y",
                  interval: str = "1d") -> pd.DataFrame:
        import yfinance as yf
        t = yf.Ticker(ticker)
        df = t.history(period=period, interval=interval)
        return df if df is not None else pd.DataFrame()

    def get_latest_price(self, ticker: str) -> Optional[float]:
        try:
            df = self.get_ohlcv(ticker, period="1d")
            if df is not None and not df.empty:
                return float(df["Close"].iloc[-1])
        except Exception:
            return None
        return None

    def get_quote(self, ticker: str) -> Optional[Quote]:
        """yfinance는 실시간 호가 미지원 → 종가만 반환."""
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
        # SPY로 ping (yfinance는 자체 health 없음)
        start = datetime.now()
        price = self.get_latest_price("SPY")
        latency_ms = int((datetime.now() - start).total_seconds() * 1000)
        return {
            "ok": price is not None,
            "latency_ms": latency_ms,
            "message": f"yfinance (SPY={price})" if price else "yfinance 응답 없음",
        }
