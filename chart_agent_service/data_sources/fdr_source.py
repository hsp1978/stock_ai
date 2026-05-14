"""
FinanceDataReader 기반 데이터 소스.
한국(KRX) 및 미국 주식 OHLCV 지원.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

import pandas as pd

from data_collector_models import PERIOD_DAYS
from data_sources.base import Quote


class FdrSource:
    """FinanceDataReader 래퍼 — yfinance 폴백 소스."""

    name = "fdr"

    def get_ohlcv(
        self, ticker: str, period: str = "2y", interval: str = "1d"
    ) -> pd.DataFrame:
        import FinanceDataReader as fdr  # type: ignore[import-untyped]

        # "005930.KS" → "005930", "AAPL" → "AAPL"
        fdr_ticker = ticker.upper().split(".")[0]

        end = date.today()
        days = PERIOD_DAYS.get(period, 740)
        start = end - timedelta(days=days)

        df = fdr.DataReader(fdr_ticker, start=start.isoformat(), end=end.isoformat())

        if df is None or df.empty:
            return pd.DataFrame()

        df.index = pd.to_datetime(df.index)
        df = df.rename(columns={"Adj Close": "Close"})

        # 필수 컬럼만 추출 (없으면 그냥 통과)
        desired = ["Open", "High", "Low", "Close", "Volume"]
        available = [c for c in desired if c in df.columns]
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
        price = self.get_latest_price("AAPL")
        latency_ms = int((datetime.now() - start).total_seconds() * 1000)
        return {
            "ok": price is not None,
            "latency_ms": latency_ms,
            "message": f"fdr (AAPL={price})" if price else "fdr 응답 없음",
        }
