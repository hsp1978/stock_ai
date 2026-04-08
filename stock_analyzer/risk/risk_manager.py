"""
리스크 관리 모듈 (원본 보고서 완전 누락 → 신규 보완)
- 포지션 사이징
- ATR 기반 손절/익절
- 포트폴리오 드로다운 관리
- Kelly Criterion
"""
import numpy as np
import pandas as pd
from config.settings import (
    MAX_POSITION_PCT, MAX_PORTFOLIO_DRAWDOWN,
    DEFAULT_STOP_LOSS_ATR_MULT, DEFAULT_TAKE_PROFIT_RATIO,
    ACCOUNT_SIZE
)


class RiskManager:
    """리스크 관리 엔진"""

    def __init__(self, account_size: float = ACCOUNT_SIZE):
        self.account_size = account_size

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        risk_per_trade_pct: float = 0.02,  # 1회 매매 최대 리스크 2%
    ) -> dict:
        """
        포지션 사이징 (Fixed Fractional Method)
        Args:
            entry_price: 진입 예정 가격
            stop_loss_price: 손절 가격
            risk_per_trade_pct: 1회 매매 최대 리스크 (계좌 대비 %)
        """
        risk_amount = self.account_size * risk_per_trade_pct
        risk_per_share = abs(entry_price - stop_loss_price)

        if risk_per_share <= 0:
            return {"error": "손절 가격이 진입 가격과 같거나 잘못 설정됨"}

        shares = int(risk_amount / risk_per_share)
        position_value = shares * entry_price
        position_pct = position_value / self.account_size

        # 최대 비중 제한
        if position_pct > MAX_POSITION_PCT:
            shares = int((self.account_size * MAX_POSITION_PCT) / entry_price)
            position_value = shares * entry_price
            position_pct = position_value / self.account_size

        return {
            "shares": shares,
            "position_value": round(position_value, 2),
            "position_pct": round(position_pct * 100, 2),
            "risk_amount": round(shares * risk_per_share, 2),
            "risk_pct": round((shares * risk_per_share) / self.account_size * 100, 2),
            "entry_price": entry_price,
            "stop_loss_price": round(stop_loss_price, 2),
        }

    def calculate_atr_stops(
        self,
        current_price: float,
        atr: float,
        direction: str = "long",
        atr_mult: float = DEFAULT_STOP_LOSS_ATR_MULT,
        rr_ratio: float = DEFAULT_TAKE_PROFIT_RATIO,
    ) -> dict:
        """
        ATR 기반 동적 손절/익절 계산
        Args:
            current_price: 현재가
            atr: ATR 값
            direction: "long" 또는 "short"
            atr_mult: ATR 배수 (손절 거리)
            rr_ratio: Risk:Reward 비율
        """
        stop_distance = atr * atr_mult
        target_distance = stop_distance * rr_ratio

        if direction == "long":
            stop_loss = current_price - stop_distance
            take_profit = current_price + target_distance
        else:
            stop_loss = current_price + stop_distance
            take_profit = current_price - target_distance

        return {
            "direction": direction,
            "entry_price": round(current_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "stop_distance_pct": round(stop_distance / current_price * 100, 2),
            "target_distance_pct": round(target_distance / current_price * 100, 2),
            "risk_reward_ratio": f"1:{rr_ratio}",
            "atr_used": round(atr, 2),
        }

    @staticmethod
    def kelly_criterion(win_rate: float, avg_win: float, avg_loss: float) -> dict:
        """
        Kelly Criterion (최적 베팅 비율)
        실전에서는 Half-Kelly(절반) 사용 권장
        """
        if avg_loss == 0:
            return {"error": "평균 손실이 0이면 계산 불가"}

        win_loss_ratio = avg_win / abs(avg_loss)
        kelly_pct = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio

        return {
            "full_kelly_pct": round(max(kelly_pct, 0) * 100, 2),
            "half_kelly_pct": round(max(kelly_pct / 2, 0) * 100, 2),
            "win_rate": round(win_rate * 100, 2),
            "win_loss_ratio": round(win_loss_ratio, 2),
            "recommendation": "Half-Kelly 사용 권장 (과적합 리스크 감소)"
        }

    @staticmethod
    def calculate_max_drawdown(equity_curve: pd.Series) -> dict:
        """최대 드로다운 계산"""
        cummax = equity_curve.cummax()
        drawdown = (equity_curve - cummax) / cummax
        max_dd = drawdown.min()
        max_dd_date = drawdown.idxmin()

        # 회복 기간 계산
        peak_date = cummax[:max_dd_date].idxmax() if max_dd_date is not None else None

        return {
            "max_drawdown_pct": round(max_dd * 100, 2),
            "max_drawdown_date": str(max_dd_date),
            "peak_date": str(peak_date) if peak_date else None,
            "current_drawdown_pct": round(drawdown.iloc[-1] * 100, 2),
            "threshold_warning": abs(max_dd) > MAX_PORTFOLIO_DRAWDOWN,
        }

    def generate_risk_report(
        self,
        current_price: float,
        atr: float,
        direction: str = "long"
    ) -> dict:
        """종합 리스크 리포트 생성"""
        stops = self.calculate_atr_stops(current_price, atr, direction)
        position = self.calculate_position_size(
            entry_price=current_price,
            stop_loss_price=stops["stop_loss"]
        )

        return {
            "account_size": self.account_size,
            "stops": stops,
            "position": position,
            "warnings": self._generate_warnings(position, stops),
        }

    @staticmethod
    def _generate_warnings(position: dict, stops: dict) -> list:
        """리스크 경고 메시지 생성"""
        warnings = []
        if position.get("position_pct", 0) > MAX_POSITION_PCT * 100:
            warnings.append(f"포지션 비중({position['position_pct']}%)이 최대 허용치({MAX_POSITION_PCT*100}%) 초과")
        if stops.get("stop_distance_pct", 0) > 10:
            warnings.append(f"손절 거리({stops['stop_distance_pct']}%)가 과도하게 넓음. 변동성 높은 종목")
        if position.get("shares", 0) == 0:
            warnings.append("계좌 크기 대비 리스크가 커서 매매 불가")
        return warnings
