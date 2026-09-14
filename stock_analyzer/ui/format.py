"""가격·통화 표기 헬퍼.

`webui.py` 분해 — 페이지들이 공통으로 쓰는 표기 함수라 페이지보다 먼저 내보낸다.
`ui/tickers.py` 의 `_is_korean_ticker` 와 판정 기준이 미묘하게 다르다(이쪽은 6자리
숫자 코드도 한국으로 본다) — 통합은 별건으로 둔다. 지금 합치면 표기가 조용히 바뀐다.
"""

from __future__ import annotations


def _is_korean_stock(ticker: str) -> bool:
    """한국 주식 여부 판단 (.KS/.KQ 또는 6자리 숫자 코드)"""
    if not ticker:
        return False
    ticker_upper = ticker.upper()
    return ticker_upper.endswith(('.KS', '.KQ')) or (ticker_upper.isdigit() and len(ticker_upper) == 6)


def _get_currency_symbol(ticker: str) -> str:
    """티커에 맞는 통화 기호 반환 (₩ 또는 $)"""
    return "₩" if _is_korean_stock(ticker) else "$"


def _fmt_price(price, ticker: str, decimals: int = None) -> str:
    """가격을 통화 기호와 함께 포맷 (한국: ₩, 미국: $)"""
    if price is None:
        return "—"
    if isinstance(price, str):
        return price

    currency = _get_currency_symbol(ticker)
    # 한국 주식은 소수점 없이, 미국 주식은 소수점 2자리
    if decimals is None:
        decimals = 0 if _is_korean_stock(ticker) else 2

    return f"{currency}{price:,.{decimals}f}"


def _fmt_num(v, decimals=2):
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    return f"{v:,.{decimals}f}"
