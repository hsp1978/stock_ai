"""
거래비용 모델 (슬리피지 + 수수료 + 세금).

백테스트와 페이퍼트레이딩에서 실제 순수익에 가깝게 체결가를 조정.
환경변수로 조정 가능:
  TRADING_COMMISSION_PCT_KR, TRADING_COMMISSION_PCT_US
  TRADING_SLIPPAGE_PCT, TRADING_SELL_TAX_PCT_KR
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class TradingCosts:
    """
    모든 값은 백분율(%) 단위.
    한쪽 거래당 적용 — 왕복은 진입(apply_entry) + 청산(apply_exit) 누적.
    """
    commission_pct: float = 0.0    # 수수료 (한쪽 기준)
    slippage_pct: float = 0.05     # 슬리피지 (한쪽)
    tax_on_sell_pct: float = 0.0   # 매도 시 세금

    @classmethod
    def for_market(cls, market: str) -> "TradingCosts":
        """
        시장별 기본 비용 프로파일.
        - 한국: 수수료 0.015%(양방향) + 거래세 0.18%(매도시)
        - 미국: 수수료 거의 0 + 슬리피지만
        """
        m = (market or "").upper()
        if m == "KR":
            return cls(
                commission_pct=_env_float("TRADING_COMMISSION_PCT_KR", 0.015),
                slippage_pct=_env_float("TRADING_SLIPPAGE_PCT", 0.05),
                tax_on_sell_pct=_env_float("TRADING_SELL_TAX_PCT_KR", 0.18),
            )
        # 미국 기본
        return cls(
            commission_pct=_env_float("TRADING_COMMISSION_PCT_US", 0.0),
            slippage_pct=_env_float("TRADING_SLIPPAGE_PCT", 0.05),
            tax_on_sell_pct=_env_float("TRADING_SELL_TAX_PCT_US", 0.0),
        )

    @classmethod
    def for_ticker(cls, ticker: str) -> "TradingCosts":
        """티커에서 시장을 추론하여 기본 비용 프로파일 반환."""
        t = (ticker or "").upper()
        if t.endswith(".KS") or t.endswith(".KQ"):
            return cls.for_market("KR")
        return cls.for_market("US")

    def apply_entry(self, price: float) -> float:
        """매수 체결가: 호가 상단 + 수수료."""
        if price <= 0:
            return price
        return price * (1 + (self.slippage_pct + self.commission_pct) / 100)

    def apply_exit(self, price: float) -> float:
        """매도 체결가: 호가 하단 - 수수료 - 세금."""
        if price <= 0:
            return price
        return price * (1 - (self.slippage_pct + self.commission_pct + self.tax_on_sell_pct) / 100)

    def roundtrip_pct(self) -> float:
        """왕복 거래 비용 총합 (%)."""
        return 2 * self.slippage_pct + 2 * self.commission_pct + self.tax_on_sell_pct

    def to_dict(self) -> dict:
        return {
            "commission_pct": self.commission_pct,
            "slippage_pct": self.slippage_pct,
            "tax_on_sell_pct": self.tax_on_sell_pct,
            "roundtrip_pct": round(self.roundtrip_pct(), 4),
        }


# 비용 없음 (기존 동작 보존용)
ZERO_COSTS = TradingCosts(commission_pct=0.0, slippage_pct=0.0, tax_on_sell_pct=0.0)
