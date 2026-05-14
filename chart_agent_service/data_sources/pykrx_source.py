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

    # ── P2: 외국인 보유율 / 공매도 ──────────────────────────────────

    @staticmethod
    def get_foreign_holding_info(ticker: str, days: int = 5) -> Dict[str, Any]:
        """
        외국인 한도 소진율 조회 (pykrx P2).

        Returns:
            {exhaustion_rate: float, trend: str, signal: str, score: int}
        """
        try:
            from pykrx import stock as _stock  # type: ignore[import-untyped]

            code = ticker.upper().split(".")[0]
            end = date.today()
            start = end - timedelta(days=days + 3)  # 주말 여유

            df = _stock.get_exhaustion_rates_of_foreign_investment_by_date(
                start.strftime("%Y%m%d"),
                end.strftime("%Y%m%d"),
                code,
            )

            if df is None or df.empty:
                return {"exhaustion_rate": None, "trend": "unknown", "signal": "neutral", "score": 0}

            # 한도 소진율 컬럼 (한글 → 영어 래핑)
            rate_col = [c for c in df.columns if "소진율" in str(c) or "한도비율" in str(c)]
            if not rate_col:
                rate_col = df.columns.tolist()

            current_rate = float(df[rate_col[0]].iloc[-1])
            prev_rate = float(df[rate_col[0]].iloc[0]) if len(df) > 1 else current_rate
            delta = current_rate - prev_rate

            # 외국인 소진율 높고 증가 → 강한 매수 신호
            if current_rate > 90 and delta > 1:
                signal, score = "buy", 4
            elif current_rate > 80 and delta > 0:
                signal, score = "buy", 2
            elif current_rate < 30 and delta < -1:
                signal, score = "sell", -3
            else:
                signal, score = "neutral", 0

            return {
                "exhaustion_rate": round(current_rate, 2),
                "rate_change": round(delta, 2),
                "trend": "increasing" if delta > 0 else "decreasing" if delta < 0 else "stable",
                "signal": signal,
                "score": score,
            }
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("get_foreign_holding_info(%s): %s", ticker, exc)
            return {"exhaustion_rate": None, "trend": "unknown", "signal": "neutral", "score": 0}

    @staticmethod
    def get_short_selling_info(ticker: str, days: int = 5) -> Dict[str, Any]:
        """
        공매도 잔고 및 비율 조회 (pykrx P2).

        Returns:
            {short_balance: int, short_ratio: float, trend: str, signal: str, score: int}
        """
        try:
            from pykrx import stock as _stock  # type: ignore[import-untyped]

            code = ticker.upper().split(".")[0]
            end = date.today()
            start = end - timedelta(days=days + 3)

            df = _stock.get_shorting_balance_by_date(
                start.strftime("%Y%m%d"),
                end.strftime("%Y%m%d"),
                code,
            )

            if df is None or df.empty:
                return {"short_balance": None, "short_ratio": None, "signal": "neutral", "score": 0}

            # 공매도 잔고 비율 컬럼
            ratio_col = [c for c in df.columns if "비율" in str(c) or "ratio" in str(c).lower()]
            bal_col = [c for c in df.columns if "잔고" in str(c) or "balance" in str(c).lower()]

            current_ratio = float(df[ratio_col[0]].iloc[-1]) if ratio_col else 0.0
            prev_ratio = float(df[ratio_col[0]].iloc[0]) if (ratio_col and len(df) > 1) else current_ratio
            delta = current_ratio - prev_ratio
            balance = int(df[bal_col[0]].iloc[-1]) if bal_col else 0

            # 공매도 비율 높고 증가 → 약세 신호
            if current_ratio > 5.0 and delta > 0.5:
                signal, score = "sell", -4
            elif current_ratio > 3.0 and delta > 0:
                signal, score = "sell", -2
            elif current_ratio < 1.0 and delta < 0:
                signal, score = "buy", 2
            else:
                signal, score = "neutral", 0

            return {
                "short_balance": balance,
                "short_ratio": round(current_ratio, 3),
                "ratio_change": round(delta, 3),
                "trend": "increasing" if delta > 0 else "decreasing" if delta < 0 else "stable",
                "signal": signal,
                "score": score,
            }
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("get_short_selling_info(%s): %s", ticker, exc)
            return {"short_balance": None, "short_ratio": None, "signal": "neutral", "score": 0}
