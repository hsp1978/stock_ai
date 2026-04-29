"""
호가단위(tick size) 유틸리티.

실제 매매가 가능한 단위로 가격을 반올림하여 시스템 출력을 현실화.
- 한국: 2023년 1월 개편 기준 가격대별 호가단위
- 미국: $1 미만은 $0.0001, 그 외 $0.01
"""
from __future__ import annotations


def korean_tick_size(price: float) -> int:
    """한국 주식 호가단위 (2023-01 개편 기준)."""
    if price < 2_000:
        return 1
    if price < 5_000:
        return 5
    if price < 20_000:
        return 10
    if price < 50_000:
        return 50
    if price < 200_000:
        return 100
    if price < 500_000:
        return 500
    return 1_000


def us_tick_size(price: float) -> float:
    """미국 주식 호가단위 ($1 미만은 0.0001달러, 그 외 0.01달러)."""
    return 0.0001 if price < 1.0 else 0.01


def _market_from_ticker(ticker: str) -> str:
    """티커에서 시장 추론 (KR | US)."""
    if not ticker:
        return "US"
    t = ticker.upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        return "KR"
    return "US"


def round_to_tick(price: float, ticker: str, side: str = "nearest") -> float:
    """
    가격을 호가단위로 반올림.

    Args:
        price: 원 가격
        ticker: 종목 티커 (시장 판별용)
        side: "nearest"(기본), "up"(매수용 상향), "down"(매도용 하향)
    """
    if price <= 0:
        return price
    market = _market_from_ticker(ticker)
    tick = korean_tick_size(price) if market == "KR" else us_tick_size(price)
    if tick <= 0:
        return price

    ratio = price / tick
    if side == "up":
        import math
        return math.ceil(ratio) * tick
    if side == "down":
        import math
        return math.floor(ratio) * tick
    # nearest
    rounded = round(ratio) * tick
    # 부동소수점 오차 정리: 미국 주식은 소수점 2-4자리, 한국은 정수
    if market == "KR":
        return int(round(rounded))
    return round(rounded, 4 if price < 1.0 else 2)


def tick_size_for(ticker: str, price: float):
    """현재 가격에서의 호가단위 반환 (디버깅/표시용)."""
    market = _market_from_ticker(ticker)
    return korean_tick_size(price) if market == "KR" else us_tick_size(price)
