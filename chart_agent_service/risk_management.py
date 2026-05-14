#!/usr/bin/env python3
"""
ATR 기반 리스크 관리 시스템
- 동적 포지션 사이징
- 샹들리에 청산 (Chandelier Exit)
- 트레일링 스톱 관리
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


class ATRRiskManager:
    """ATR 기반 리스크 관리 시스템"""

    def __init__(self, df: pd.DataFrame, account_size: float = 100000000):
        """
        초기화
        Args:
            df: OHLCV + ATR이 포함된 DataFrame
            account_size: 계좌 총 자산 (원)
        """
        self.df = df
        self.account_size = account_size
        self.latest = df.iloc[-1] if not df.empty else {}

    def calculate_position_size(
        self, price: float, risk_per_trade: float = 0.01, atr_multiplier: float = 2.0
    ) -> Dict:
        """
        ATR 기반 동적 포지션 사이징 계산

        Args:
            price: 현재 주가
            risk_per_trade: 거래당 최대 손실 허용 비율 (기본 1%)
            atr_multiplier: ATR 승수 (스톱로스 거리)

        Returns:
            포지션 사이즈 정보
        """
        # ATR 찾기
        atr_col = self._find_atr_column()
        if not atr_col:
            return {"error": "ATR 데이터 없음", "shares": 0, "position_value": 0}

        atr = float(self.latest.get(atr_col, 0))
        if atr == 0:
            return {"error": "ATR 값이 0", "shares": 0, "position_value": 0}

        # 최대 허용 손실액
        risk_amount = self.account_size * risk_per_trade

        # 스톱로스 거리 (ATR 기반)
        stop_distance = atr * atr_multiplier

        # 포지션 크기 계산
        shares = int(risk_amount / stop_distance)

        # 포지션 가치
        position_value = shares * price

        # 계좌 대비 비중
        position_pct = (position_value / self.account_size) * 100

        # 최대 포지션 제한 (계좌의 20%)
        max_position = self.account_size * 0.2
        if position_value > max_position:
            shares = int(max_position / price)
            position_value = shares * price
            position_pct = (position_value / self.account_size) * 100

        return {
            "shares": shares,
            "position_value": round(position_value, 0),
            "position_pct": round(position_pct, 2),
            "risk_amount": round(risk_amount, 0),
            "stop_distance": round(stop_distance, 2),
            "stop_price": round(price - stop_distance, 2),
            "atr": round(atr, 2),
            "volatility_level": self._classify_volatility(atr, price),
            "recommendation": self._get_sizing_recommendation(position_pct, atr, price),
        }

    def calculate_chandelier_exit(
        self,
        lookback: int = 22,
        atr_multiplier: float = 3.0,
        position_type: str = "long",
    ) -> Dict:
        """
        샹들리에 청산가격 계산

        Args:
            lookback: 고점/저점 확인 기간 (기본 22일)
            atr_multiplier: ATR 승수 (기본 3.0)
            position_type: "long" 또는 "short"

        Returns:
            청산 가격 정보
        """
        atr_col = self._find_atr_column()
        if not atr_col:
            return {"error": "ATR 데이터 없음"}

        atr = float(self.latest.get(atr_col, 0))
        if atr == 0:
            return {"error": "ATR 값이 0"}

        # 기간 내 고점/저점
        lookback_period = min(lookback, len(self.df))
        recent_data = self.df.tail(lookback_period)

        if position_type == "long":
            # 롱 포지션: 최고가 - (ATR * 승수)
            highest = float(recent_data["High"].max())
            exit_price = highest - (atr * atr_multiplier)

            current_price = float(self.latest["Close"])
            distance_pct = ((current_price - exit_price) / current_price) * 100

            return {
                "exit_price": round(exit_price, 2),
                "highest_price": round(highest, 2),
                "current_price": round(current_price, 2),
                "distance_pct": round(distance_pct, 2),
                "atr": round(atr, 2),
                "atr_multiplier": atr_multiplier,
                "status": "safe" if current_price > exit_price * 1.05 else "caution",
                "recommendation": self._get_exit_recommendation(distance_pct, "long"),
            }

        else:  # short position
            # 숏 포지션: 최저가 + (ATR * 승수)
            lowest = float(recent_data["Low"].min())
            exit_price = lowest + (atr * atr_multiplier)

            current_price = float(self.latest["Close"])
            distance_pct = ((exit_price - current_price) / current_price) * 100

            return {
                "exit_price": round(exit_price, 2),
                "lowest_price": round(lowest, 2),
                "current_price": round(current_price, 2),
                "distance_pct": round(distance_pct, 2),
                "atr": round(atr, 2),
                "atr_multiplier": atr_multiplier,
                "status": "safe" if current_price < exit_price * 0.95 else "caution",
                "recommendation": self._get_exit_recommendation(distance_pct, "short"),
            }

    def calculate_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        initial_stop_pct: float = 0.05,
        trailing_pct: float = 0.03,
    ) -> Dict:
        """
        트레일링 스톱 계산

        Args:
            entry_price: 진입 가격
            current_price: 현재 가격
            initial_stop_pct: 초기 스톱로스 비율
            trailing_pct: 트레일링 비율

        Returns:
            트레일링 스톱 정보
        """
        # 수익률 계산
        profit_pct = ((current_price - entry_price) / entry_price) * 100

        # ATR 기반 동적 트레일링
        atr_col = self._find_atr_column()
        if atr_col:
            atr = float(self.latest.get(atr_col, 0))
            atr_pct = (atr / current_price) * 100
            # ATR이 클수록 트레일링 거리도 증가
            dynamic_trailing = max(trailing_pct, atr_pct * 0.5)
        else:
            dynamic_trailing = trailing_pct

        # 초기 스톱로스
        initial_stop = entry_price * (1 - initial_stop_pct)

        # 최고가 기준 트레일링 스톱
        if len(self.df) > 0:
            # 진입 이후 최고가 (실제로는 진입 시점 이후 데이터로 계산해야 함)
            highest_since_entry = max(current_price, entry_price * 1.1)  # 예시
            trailing_stop = highest_since_entry * (1 - dynamic_trailing)
        else:
            trailing_stop = current_price * (1 - dynamic_trailing)

        # 더 높은 스톱 선택
        stop_price = max(initial_stop, trailing_stop)

        # 현재가 대비 거리
        stop_distance_pct = ((current_price - stop_price) / current_price) * 100

        return {
            "stop_price": round(stop_price, 2),
            "entry_price": round(entry_price, 2),
            "current_price": round(current_price, 2),
            "profit_pct": round(profit_pct, 2),
            "stop_distance_pct": round(stop_distance_pct, 2),
            "trailing_pct": round(dynamic_trailing * 100, 2),
            "stop_type": "trailing" if stop_price > initial_stop else "initial",
            "status": self._get_stop_status(profit_pct, stop_distance_pct),
            "recommendation": self._get_stop_recommendation(
                profit_pct, stop_distance_pct
            ),
        }

    def calculate_volatility_adjusted_targets(self) -> Dict:
        """
        변동성 조정 목표가 계산

        Returns:
            변동성 기반 목표가 정보
        """
        atr_col = self._find_atr_column()
        if not atr_col:
            return {"error": "ATR 데이터 없음"}

        atr = float(self.latest.get(atr_col, 0))
        current_price = float(self.latest["Close"])

        # ATR 기반 목표가 레벨
        targets = {
            "target_1": current_price + (atr * 1.0),  # 1 ATR
            "target_2": current_price + (atr * 2.0),  # 2 ATR
            "target_3": current_price + (atr * 3.0),  # 3 ATR
            "target_4": current_price + (atr * 5.0),  # 5 ATR
        }

        # 수익률로 변환
        target_returns = {
            f"{k}_return": round(((v - current_price) / current_price * 100), 2)
            for k, v in targets.items()
        }

        # R:R 비율 (Risk:Reward)
        stop_loss = current_price - (atr * 2.0)
        risk = current_price - stop_loss

        rr_ratios = {
            f"{k}_rr": round((v - current_price) / risk, 2) for k, v in targets.items()
        }

        return {
            "current_price": round(current_price, 2),
            "atr": round(atr, 2),
            "targets": {k: round(v, 2) for k, v in targets.items()},
            "returns": target_returns,
            "rr_ratios": rr_ratios,
            "stop_loss": round(stop_loss, 2),
            "recommendation": self._get_target_recommendation(rr_ratios),
        }

    def analyze_position_risk(
        self, entry_price: float, shares: int, current_price: Optional[float] = None
    ) -> Dict:
        """
        포지션 리스크 종합 분석

        Args:
            entry_price: 진입 가격
            shares: 보유 수량
            current_price: 현재 가격 (없으면 최신 종가 사용)

        Returns:
            종합 리스크 분석
        """
        if current_price is None:
            current_price = float(self.latest["Close"])

        # 기본 정보
        position_value = shares * current_price
        entry_value = shares * entry_price
        profit_loss = position_value - entry_value
        profit_loss_pct = (profit_loss / entry_value) * 100

        # ATR 정보
        atr_col = self._find_atr_column()
        atr = float(self.latest.get(atr_col, 0)) if atr_col else 0

        # 변동성 리스크
        if atr > 0:
            daily_risk = atr * shares  # 일일 예상 변동폭
            daily_risk_pct = (daily_risk / position_value) * 100
            volatility_risk = (
                "high"
                if daily_risk_pct > 5
                else "medium"
                if daily_risk_pct > 2
                else "low"
            )
        else:
            daily_risk = 0
            daily_risk_pct = 0
            volatility_risk = "unknown"

        # 계좌 대비 비중
        position_pct = (position_value / self.account_size) * 100

        # 최대 손실 시나리오 (3 ATR)
        if atr > 0:
            max_loss_price = current_price - (atr * 3)
            max_loss_amount = (current_price - max_loss_price) * shares
            max_loss_pct = (max_loss_amount / self.account_size) * 100
        else:
            max_loss_amount = 0
            max_loss_pct = 0

        # 리스크 점수 (0-100)
        risk_score = self._calculate_risk_score(
            position_pct, volatility_risk, profit_loss_pct, daily_risk_pct
        )

        return {
            "position": {
                "shares": shares,
                "entry_price": round(entry_price, 2),
                "current_price": round(current_price, 2),
                "position_value": round(position_value, 0),
                "profit_loss": round(profit_loss, 0),
                "profit_loss_pct": round(profit_loss_pct, 2),
            },
            "risk_metrics": {
                "daily_risk": round(daily_risk, 0),
                "daily_risk_pct": round(daily_risk_pct, 2),
                "max_loss_amount": round(max_loss_amount, 0),
                "max_loss_pct": round(max_loss_pct, 2),
                "position_pct": round(position_pct, 2),
                "volatility_risk": volatility_risk,
                "risk_score": risk_score,
            },
            "recommendations": self._get_risk_recommendations(
                risk_score, position_pct, profit_loss_pct, volatility_risk
            ),
        }

    def _find_atr_column(self) -> Optional[str]:
        """ATR 컬럼 찾기"""
        for col in self.df.columns:
            if "ATR" in col.upper():
                return col
        return None

    def _classify_volatility(self, atr: float, price: float) -> str:
        """변동성 분류"""
        atr_pct = (atr / price) * 100

        if atr_pct < 1:
            return "very_low"
        elif atr_pct < 2:
            return "low"
        elif atr_pct < 3:
            return "medium"
        elif atr_pct < 5:
            return "high"
        else:
            return "extreme"

    def _get_sizing_recommendation(
        self, position_pct: float, atr: float, price: float
    ) -> str:
        """포지션 사이징 권고"""
        volatility = self._classify_volatility(atr, price)

        recs = []

        if position_pct > 15:
            recs.append("포지션 과대 - 축소 권장")
        elif position_pct < 5:
            recs.append("포지션 과소 - 확대 가능")

        if volatility in ["high", "extreme"]:
            recs.append("고변동성 - 포지션 축소 권장")
        elif volatility == "very_low":
            recs.append("저변동성 - 포지션 확대 가능")

        return " / ".join(recs) if recs else "적정 포지션 크기"

    def _get_exit_recommendation(self, distance_pct: float, position_type: str) -> str:
        """청산 권고"""
        if position_type == "long":
            if distance_pct < 2:
                return "청산선 임박 - 주의 필요"
            elif distance_pct < 5:
                return "청산선 접근 중 - 모니터링 강화"
            else:
                return "안전 구간 - 추세 지속 가능"
        else:  # short
            if distance_pct < 2:
                return "청산선 임박 - 주의 필요"
            elif distance_pct < 5:
                return "청산선 접근 중 - 모니터링 강화"
            else:
                return "안전 구간 - 추세 지속 가능"

    def _get_stop_status(self, profit_pct: float, stop_distance_pct: float) -> str:
        """스톱 상태"""
        if profit_pct > 10:
            return "profit_secured"  # 수익 확보
        elif profit_pct > 5:
            return "in_profit"  # 수익 중
        elif stop_distance_pct < 2:
            return "near_stop"  # 스톱 임박
        else:
            return "normal"  # 정상

    def _get_stop_recommendation(
        self, profit_pct: float, stop_distance_pct: float
    ) -> str:
        """스톱 권고"""
        if profit_pct > 20:
            return "높은 수익 - 일부 익절 고려"
        elif profit_pct > 10:
            return "수익 확보 - 트레일링 스톱 상향 조정"
        elif stop_distance_pct < 1:
            return "스톱 임박 - 시장 상황 재평가 필요"
        elif stop_distance_pct < 3:
            return "스톱 접근 - 주의 관찰"
        else:
            return "정상 범위 - 현 스톱 유지"

    def _get_target_recommendation(self, rr_ratios: Dict) -> str:
        """목표가 권고"""
        # 첫 번째 목표의 R:R 확인
        first_rr = list(rr_ratios.values())[0] if rr_ratios else 0

        if first_rr < 1:
            return "리스크 대비 보상 부족 - 진입 재고려"
        elif first_rr < 2:
            return "최소 R:R 충족 - 신중한 진입"
        else:
            return "우수한 R:R - 적극 진입 가능"

    def _calculate_risk_score(
        self,
        position_pct: float,
        volatility_risk: str,
        profit_loss_pct: float,
        daily_risk_pct: float,
    ) -> int:
        """리스크 점수 계산 (0-100, 높을수록 위험)"""
        score = 0

        # 포지션 비중 (0-30점)
        if position_pct > 20:
            score += 30
        elif position_pct > 15:
            score += 20
        elif position_pct > 10:
            score += 10
        elif position_pct > 5:
            score += 5

        # 변동성 (0-30점)
        volatility_scores = {
            "extreme": 30,
            "high": 20,
            "medium": 10,
            "low": 5,
            "very_low": 0,
            "unknown": 15,
        }
        score += volatility_scores.get(volatility_risk, 15)

        # 손실 상태 (0-20점)
        if profit_loss_pct < -10:
            score += 20
        elif profit_loss_pct < -5:
            score += 10
        elif profit_loss_pct < 0:
            score += 5

        # 일일 리스크 (0-20점)
        if daily_risk_pct > 5:
            score += 20
        elif daily_risk_pct > 3:
            score += 10
        elif daily_risk_pct > 2:
            score += 5

        return min(100, score)

    def _get_risk_recommendations(
        self,
        risk_score: int,
        position_pct: float,
        profit_loss_pct: float,
        volatility_risk: str,
    ) -> list:
        """리스크 권고사항"""
        recs = []

        # 리스크 점수 기반
        if risk_score > 70:
            recs.append("고위험 - 즉시 포지션 축소 권장")
        elif risk_score > 50:
            recs.append("중고위험 - 리스크 관리 강화 필요")
        elif risk_score > 30:
            recs.append("중위험 - 정상 모니터링")
        else:
            recs.append("저위험 - 안정적 포지션")

        # 개별 요소 권고
        if position_pct > 15:
            recs.append("포지션 과대 - 분산 필요")

        if volatility_risk in ["high", "extreme"]:
            recs.append("고변동성 - 스톱로스 강화")

        if profit_loss_pct < -5:
            recs.append("손실 확대 중 - 손절 검토")
        elif profit_loss_pct > 20:
            recs.append("높은 수익 - 부분 익절 고려")

        return recs


# ── P2: VaR/CVaR 계산 ────────────────────────────────────────────────


class PortfolioRiskCalculator:
    """
    포트폴리오 수준 Value-at-Risk / Conditional VaR 계산 (P2).

    지원 방법:
    - historical : 과거 수익률 분위수 기반 (비모수)
    - parametric : 정규분포 가정 (분산-공분산)
    - cornish_fisher: 왜도·첨도 보정 수정 VaR
    """

    _CONFIDENCE_LEVELS = (0.95, 0.99)

    def __init__(self, returns: pd.Series, nav: float = 100_000.0) -> None:
        """
        Args:
            returns: 일별 수익률 시리즈 (소수, e.g. 0.01 = 1%)
            nav:     포트폴리오 순자산 (원화 or USD)
        """
        self.returns = returns.dropna()
        self.nav = nav

    # ── 내부 헬퍼 ───────────────────────────────────────────────────

    def _historical_quantile(self, confidence: float) -> float:
        """과거 수익률의 (1-confidence) 분위수."""
        return float(np.percentile(self.returns, (1 - confidence) * 100))

    def _parametric_quantile(self, confidence: float) -> float:
        """정규분포 분위수 (z-score × σ + μ)."""
        from scipy.stats import norm  # type: ignore[import-untyped]

        mu = float(self.returns.mean())
        sigma = float(self.returns.std())
        z = norm.ppf(1 - confidence)
        return mu + z * sigma

    def _cornish_fisher_quantile(self, confidence: float) -> float:
        """왜도·첨도 보정 VaR (Cornish-Fisher expansion)."""
        from scipy.stats import norm  # type: ignore[import-untyped]

        mu = float(self.returns.mean())
        sigma = float(self.returns.std())
        skew = float(self.returns.skew())
        kurt = float(self.returns.kurt())  # excess kurtosis
        z = norm.ppf(1 - confidence)
        # Cornish-Fisher 2차 보정
        z_cf = (
            z
            + (z**2 - 1) * skew / 6
            + (z**3 - 3 * z) * kurt / 24
            - (2 * z**3 - 5 * z) * skew**2 / 36
        )
        return mu + z_cf * sigma

    # ── 공개 API ────────────────────────────────────────────────────

    def var(self, confidence: float = 0.95, method: str = "historical") -> float:
        """
        Value-at-Risk (손실 부호: 음수).

        Returns: VaR as a decimal (e.g. -0.025 = -2.5%)
        """
        if method == "parametric":
            return self._parametric_quantile(confidence)
        if method == "cornish_fisher":
            return self._cornish_fisher_quantile(confidence)
        return self._historical_quantile(confidence)

    def cvar(self, confidence: float = 0.95, method: str = "historical") -> float:
        """
        Conditional VaR / Expected Shortfall.

        Returns: CVaR as a decimal (e.g. -0.04 = -4%)
        """
        var_threshold = self.var(confidence, method)
        tail = self.returns[self.returns <= var_threshold]
        return float(tail.mean()) if len(tail) > 0 else var_threshold

    def compute_all(self, method: str = "historical") -> dict:
        """
        VaR / CVaR를 두 신뢰 수준(95%, 99%)에서 계산한다.

        Returns:
            {
              "var_95": float,  # –% decimal
              "var_99": float,
              "cvar_95": float,
              "cvar_99": float,
              "var_95_amount": float,  # NAV × |VaR|
              "var_99_amount": float,
              "cvar_95_amount": float,
              "cvar_99_amount": float,
              "method": str,
              "n_days": int,
              "annualized_vol": float,
            }
        """
        v95 = self.var(0.95, method)
        v99 = self.var(0.99, method)
        cv95 = self.cvar(0.95, method)
        cv99 = self.cvar(0.99, method)
        ann_vol = float(self.returns.std() * np.sqrt(252))

        return {
            "var_95": round(v95, 6),
            "var_99": round(v99, 6),
            "cvar_95": round(cv95, 6),
            "cvar_99": round(cv99, 6),
            "var_95_pct": round(v95 * 100, 3),
            "var_99_pct": round(v99 * 100, 3),
            "cvar_95_pct": round(cv95 * 100, 3),
            "cvar_99_pct": round(cv99 * 100, 3),
            "var_95_amount": round(abs(v95) * self.nav, 2),
            "var_99_amount": round(abs(v99) * self.nav, 2),
            "cvar_95_amount": round(abs(cv95) * self.nav, 2),
            "cvar_99_amount": round(abs(cv99) * self.nav, 2),
            "method": method,
            "n_days": len(self.returns),
            "annualized_vol_pct": round(ann_vol * 100, 3),
        }
