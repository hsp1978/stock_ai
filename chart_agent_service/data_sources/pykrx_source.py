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


def _pick_column(df: pd.DataFrame, candidates: tuple[str, ...], label: str) -> Optional[str]:
    """pykrx 컬럼을 이름으로 고른다. **못 찾으면 None** — 아무거나 고르지 않는다.

    2026-09-22, 여기서 두 건이 동시에 터졌다. 둘 다 컬럼명이 한 글자 달랐다.

        한도소진률  vs  코드가 찾던 "소진율"   (률 ≠ 율)
        비중        vs  코드가 찾던 "비율"

    매칭이 실패했을 때의 **폴백이 진짜 결함**이었다. 소진율 쪽은
    `rate_col = df.columns.tolist()` 로 떨어져 **첫 컬럼(상장주식수)** 을 집었고,
    그 값을 퍼센트로 보고했다 — 리포트에 `외국인소진율=9048000.0%`. 공매도 쪽은
    빈 리스트가 되어 조용히 `0.0` 을 썼다.

    두 경우 모두 하류 규칙이 `neutral, score 0` 으로 떨어져 **32일 내내 이 도구가
    정확히 0점이었다** — 고장이 '중립 판단'으로 보였다 (CLAUDE.md §13).

    그래서 여기서는 못 찾으면 None 을 주고, 호출부가 그걸 '판단 불가'로 다룬다.
    실제 컬럼명은 로그에 남긴다 — pykrx 가 이름을 또 바꾸면 그게 단서가 된다.
    """
    cols = {str(c).strip(): c for c in df.columns}
    for want in candidates:
        if want in cols:
            return cols[want]
    # 부분 일치는 허용하되, **여러 개면 고르지 않는다** (어느 것인지 모르므로).
    hits = [orig for name, orig in cols.items() if any(w in name for w in candidates)]
    if len(hits) == 1:
        return hits[0]

    import logging

    logging.getLogger(__name__).warning(
        "pykrx %s 컬럼을 찾지 못했다 (후보 %s / 실제 %s) — 판단 불가로 처리한다",
        label, candidates, list(cols),
    )
    return None


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
                return {"exhaustion_rate": None, "trend": "unknown", "signal": "neutral",
                        "score": 0, "available": False, "reason": "no_data"}

            # 실제 컬럼은 `한도소진률`(률)이다. 2026-09-22 이전 코드는 "소진율"(율)을
            # 찾다 실패하고 **첫 컬럼(상장주식수)** 으로 폴백했다 — `_pick_column` 주석 참조.
            rate_col = _pick_column(
                df, ("한도소진률", "한도소진율", "소진률", "소진율", "한도비율"), "외국인 한도소진률"
            )
            if rate_col is None:
                return {"exhaustion_rate": None, "trend": "unknown", "signal": "neutral",
                        "score": 0, "available": False, "reason": "rate_column_not_found",
                        "columns": [str(c) for c in df.columns]}

            current_rate = float(df[rate_col].iloc[-1])
            prev_rate = float(df[rate_col].iloc[0]) if len(df) > 1 else current_rate
            delta = current_rate - prev_rate

            # 퍼센트는 0~100 이다. 이 검사 하나만 있었어도 2026-09-22 의 버그를
            # 즉시 잡았다 — `상장주식수`(9,048,000)를 소진율로 32일간 보고했다.
            # 컬럼을 잘못 잡으면 '값이 이상하다'가 아니라 '판단 불가'로 끝낸다.
            if not (0.0 <= current_rate <= 100.0):
                import logging
                logging.getLogger(__name__).warning(
                    "get_foreign_holding_info(%s): 소진률 %s 가 0~100 밖이다 "
                    "(컬럼 %r) — 잘못된 컬럼일 수 있다", ticker, current_rate, str(rate_col),
                )
                return {"exhaustion_rate": None, "trend": "unknown", "signal": "neutral",
                        "score": 0, "available": False, "reason": "rate_out_of_range",
                        "raw_value": current_rate, "column": str(rate_col)}

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
                "available": True,
            }
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("get_foreign_holding_info(%s): %s", ticker, exc)
            return {"exhaustion_rate": None, "trend": "unknown", "signal": "neutral", "score": 0,
                    "available": False, "reason": f"{type(exc).__name__}: {exc}"[:120]}

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
                return {"short_balance": None, "short_ratio": None, "signal": "neutral",
                        "score": 0, "available": False, "reason": "no_data"}

            # 실제 컬럼은 `비중` 이다. 종전 코드는 "비율"을 찾다 실패하면 **조용히
            # 0.0** 을 썼다 — 비율 0% 는 '공매도가 없다'는 강한 주장인데, 실제로는
            # 컬럼을 못 찾았다는 뜻이었다 (`_pick_column` 주석 참조).
            ratio_col = _pick_column(df, ("비중", "공매도비중", "비율", "ratio"), "공매도 비중")
            bal_col = _pick_column(df, ("공매도잔고", "잔고", "balance"), "공매도 잔고")
            if ratio_col is None:
                return {"short_balance": None, "short_ratio": None, "signal": "neutral",
                        "score": 0, "available": False, "reason": "ratio_column_not_found",
                        "columns": [str(c) for c in df.columns]}

            current_ratio = float(df[ratio_col].iloc[-1])
            prev_ratio = float(df[ratio_col].iloc[0]) if len(df) > 1 else current_ratio
            delta = current_ratio - prev_ratio
            balance = int(df[bal_col].iloc[-1]) if bal_col is not None else None

            # 위와 같은 이유 — 공매도 비중도 퍼센트다.
            if not (0.0 <= current_ratio <= 100.0):
                import logging
                logging.getLogger(__name__).warning(
                    "get_short_selling_info(%s): 비중 %s 가 0~100 밖이다 (컬럼 %r)",
                    ticker, current_ratio, str(ratio_col),
                )
                return {"short_balance": balance, "short_ratio": None, "signal": "neutral",
                        "score": 0, "available": False, "reason": "ratio_out_of_range",
                        "raw_value": current_ratio, "column": str(ratio_col)}

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
                "available": True,
            }
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("get_short_selling_info(%s): %s", ticker, exc)
            return {"short_balance": None, "short_ratio": None, "signal": "neutral", "score": 0,
                    "available": False, "reason": f"{type(exc).__name__}: {exc}"[:120]}
