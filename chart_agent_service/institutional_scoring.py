#!/usr/bin/env python3
"""
기관 투자자 관점의 기술적 스코어링 모델
- 추세 추종(Trend Following) 전략 기반
- 가점/감점 체계 통합
- 상대강도(RS), 이격도, 볼린저 밴드 등 핵심 지표 포함
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
import yfinance as yf
from datetime import datetime, timedelta


class InstitutionalTechnicalScoring:
    """기관급 기술적 스코어링 시스템"""

    def __init__(self, df: pd.DataFrame, ticker: str = None):
        """
        초기화
        Args:
            df: OHLCV + 기술적 지표가 포함된 DataFrame
            ticker: 종목 티커 (상대강도 계산용)
        """
        self.df = df
        self.ticker = ticker
        self.latest = df.iloc[-1] if not df.empty else {}
        self.benchmark_ticker = self._get_benchmark_ticker()

    def _get_benchmark_ticker(self) -> str:
        """벤치마크 지수 결정"""
        if not self.ticker:
            return "^GSPC"  # 기본값 S&P 500

        if self.ticker.endswith('.KS'):
            return "^KS11"  # KOSPI
        elif self.ticker.endswith('.KQ'):
            return "^KQ11"  # KOSDAQ
        else:
            return "^GSPC"  # S&P 500

    def calculate_comprehensive_score(self) -> Dict:
        """
        종합 기술적 점수 계산
        Returns:
            점수 상세 및 최종 신호
        """
        scores = {}
        details = []

        # 1. 가점 항목 계산
        positive_scores = self._calculate_positive_scores()
        scores.update(positive_scores)

        # 2. 감점 항목 계산
        negative_scores = self._calculate_negative_scores()
        scores.update(negative_scores)

        # 3. 보완 지표 계산
        supplementary_scores = self._calculate_supplementary_scores()
        scores.update(supplementary_scores)

        # 4. 총점 계산
        total_score = sum(scores.values())

        # 5. 신호 결정
        signal = self._determine_signal(total_score, scores)

        # 6. 신호 강도 계산
        signal_strength = self._calculate_signal_strength(total_score)

        return {
            "total_score": round(total_score, 1),
            "signal": signal,
            "signal_strength": signal_strength,
            "scores_detail": scores,
            "positive_total": sum(v for v in scores.values() if v > 0),
            "negative_total": sum(v for v in scores.values() if v < 0),
            "recommendation": self._get_recommendation(signal, signal_strength, scores),
            "timestamp": datetime.now().isoformat()
        }

    def _calculate_positive_scores(self) -> Dict[str, float]:
        """가점 항목 계산"""
        scores = {}

        # 1. MACD 모멘텀 크로스 (30점)
        macd_score = self._check_macd_momentum()
        scores['macd_momentum'] = macd_score

        # 2. 이동평균 정배열 (20점)
        ma_score = self._check_ma_alignment()
        scores['ma_alignment'] = ma_score

        # 3. 동적 RSI (20점)
        rsi_score = self._check_dynamic_rsi()
        scores['dynamic_rsi'] = rsi_score

        # 4. 수급 동반 양봉 (20점)
        volume_price_score = self._check_volume_price_action()
        scores['volume_price'] = volume_price_score

        # 5. 생명선 지지 (10점)
        ma20_support_score = self._check_ma20_support()
        scores['ma20_support'] = ma20_support_score

        return scores

    def _calculate_negative_scores(self) -> Dict[str, float]:
        """감점 항목 계산"""
        scores = {}

        # 1. MACD 데드크로스 (-20점)
        if self._check_macd_dead_cross():
            scores['macd_dead_cross'] = -20

        # 2. 극단적 과매수 (-15점)
        if 'RSI' in self.df.columns:
            rsi = float(self.latest.get('RSI', 50))
            if rsi > 78:
                scores['extreme_overbought'] = -15

        # 3. 수급 소멸 (-10점)
        if self._check_volume_decline():
            scores['volume_decline'] = -10

        # 4. 장기 추세 역행 (-10점)
        if self._check_long_term_trend_violation():
            scores['long_term_violation'] = -10

        return scores

    def _calculate_supplementary_scores(self) -> Dict[str, float]:
        """보완 지표 계산"""
        scores = {}

        # 1. 상대강도 (RS)
        rs_score = self._calculate_relative_strength()
        if rs_score is not None:
            scores['relative_strength'] = rs_score

        # 2. 이격도
        disparity_score = self._calculate_disparity()
        scores['disparity'] = disparity_score

        # 3. 볼린저 밴드 돌파
        bb_score = self._check_bollinger_breakout()
        scores['bollinger_breakout'] = bb_score

        return scores

    def _check_macd_momentum(self) -> float:
        """MACD 모멘텀 크로스 체크 (최근 10일 이내)"""
        score = 0.0

        # MACD 컬럼 확인
        macd_cols = [col for col in self.df.columns if 'MACD' in col]
        if not macd_cols:
            return score

        # MACD와 Signal 찾기
        macd_col = None
        signal_col = None
        for col in macd_cols:
            if 'MACDs' in col:
                signal_col = col
            elif 'MACDh' not in col:
                macd_col = col

        if not macd_col or not signal_col:
            return score

        # 최근 10거래일 내 골든크로스 확인
        lookback = min(10, len(self.df))
        recent_df = self.df.tail(lookback)

        for i in range(1, len(recent_df)):
            prev_macd = float(recent_df.iloc[i-1][macd_col])
            prev_signal = float(recent_df.iloc[i-1][signal_col])
            curr_macd = float(recent_df.iloc[i][macd_col])
            curr_signal = float(recent_df.iloc[i][signal_col])

            # 골든크로스 발생
            if prev_macd <= prev_signal and curr_macd > curr_signal:
                # 최근일수록 높은 점수
                days_ago = lookback - i
                score = 30 * (1 - days_ago * 0.05)  # 최대 30점, 날짜별 감소
                break

        return max(0, score)

    def _check_ma_alignment(self) -> float:
        """이동평균 정배열 체크 (MA5 > MA20 > MA60)"""
        score = 0.0

        # 이동평균 계산 또는 가져오기
        ma5 = self._get_or_calculate_ma(5)
        ma20 = self._get_or_calculate_ma(20)
        ma60 = self._get_or_calculate_ma(60)

        if ma5 is None or ma20 is None or ma60 is None:
            return score

        price = float(self.latest.get('Close', 0))

        # 정배열 체크
        if price > ma5 > ma20 > ma60:
            score = 20.0

            # 최근 전환 보너스 (5일 이내)
            if len(self.df) >= 5:
                recent_5d = self.df.tail(5)
                for i in range(len(recent_5d)-1):
                    prev_ma5 = self._get_ma_at_index(5, -5+i)
                    prev_ma20 = self._get_ma_at_index(20, -5+i)
                    if prev_ma5 <= prev_ma20:
                        # 최근 정배열 전환
                        score += 5.0
                        break

        return score

    def _check_dynamic_rsi(self) -> float:
        """동적 RSI 체크 (RSI > 50 + 3일 연속 상승)"""
        score = 0.0

        if 'RSI' not in self.df.columns:
            return score

        current_rsi = float(self.latest.get('RSI', 50))

        # RSI > 50 기본 조건
        if current_rsi > 50:
            score = 10.0

            # 3일 연속 상승 체크
            if len(self.df) >= 4:
                rsi_values = self.df['RSI'].tail(4).values
                if all(rsi_values[i] < rsi_values[i+1] for i in range(3)):
                    score = 20.0  # 전체 조건 충족

        return score

    def _check_volume_price_action(self) -> float:
        """수급 동반 양봉 체크 (최근 3일 중 2일)"""
        score = 0.0

        if 'Volume' not in self.df.columns:
            return score

        # 최근 3거래일 체크
        lookback = min(3, len(self.df))
        if lookback < 2:
            return score

        positive_days = 0
        for i in range(1, lookback + 1):
            curr = self.df.iloc[-i]
            prev = self.df.iloc[-i-1] if len(self.df) > i else None

            if prev is not None:
                # 거래량 증가
                volume_increased = curr['Volume'] > prev['Volume']
                # 양봉 (종가 > 시가)
                is_bullish = curr['Close'] > curr['Open']

                if volume_increased and is_bullish:
                    positive_days += 1

        # 3일 중 2일 이상 조건 충족
        if positive_days >= 2:
            score = 20.0

        return score

    def _check_ma20_support(self) -> float:
        """MA20 지지 확인"""
        score = 0.0

        ma20 = self._get_or_calculate_ma(20)
        if ma20 is None:
            return score

        price = float(self.latest.get('Close', 0))
        low = float(self.latest.get('Low', 0))

        # MA20 근처 지지 (2% 이내)
        distance_pct = abs(price - ma20) / ma20 * 100
        if distance_pct <= 2 and low >= ma20 * 0.98:
            score = 10.0

        # 최근 3일 내 MA20 터치 후 반등
        elif len(self.df) >= 3:
            for i in range(1, 4):
                prev_low = float(self.df.iloc[-i]['Low'])
                if prev_low <= ma20 * 1.01:
                    # MA20 터치 후 현재 상승
                    if price > ma20:
                        score = 10.0
                        break

        return score

    def _check_macd_dead_cross(self) -> bool:
        """MACD 데드크로스 체크"""
        macd_cols = [col for col in self.df.columns if 'MACD' in col]
        if not macd_cols:
            return False

        macd_col = None
        signal_col = None
        for col in macd_cols:
            if 'MACDs' in col:
                signal_col = col
            elif 'MACDh' not in col:
                macd_col = col

        if not macd_col or not signal_col:
            return False

        # 현재 MACD < Signal
        curr_macd = float(self.latest.get(macd_col, 0))
        curr_signal = float(self.latest.get(signal_col, 0))

        if curr_macd < curr_signal:
            # 최근 3일 내 데드크로스 발생 확인
            if len(self.df) >= 4:
                for i in range(1, 4):
                    prev_macd = float(self.df.iloc[-i-1][macd_col])
                    prev_signal = float(self.df.iloc[-i-1][signal_col])
                    curr_macd_i = float(self.df.iloc[-i][macd_col])
                    curr_signal_i = float(self.df.iloc[-i][signal_col])

                    if prev_macd >= prev_signal and curr_macd_i < curr_signal_i:
                        return True

        return False

    def _check_volume_decline(self) -> bool:
        """5일 연속 거래량 감소 체크"""
        if 'Volume' not in self.df.columns or len(self.df) < 6:
            return False

        volumes = self.df['Volume'].tail(6).values

        # 5일 연속 감소 체크
        consecutive_decline = all(volumes[i] > volumes[i+1] for i in range(5))

        return consecutive_decline

    def _check_long_term_trend_violation(self) -> bool:
        """장기 추세선(MA120) 하향 이탈"""
        ma120 = self._get_or_calculate_ma(120)
        if ma120 is None:
            return False

        price = float(self.latest.get('Close', 0))
        return price < ma120

    def _calculate_relative_strength(self) -> Optional[float]:
        """상대강도(RS) 계산"""
        if not self.ticker:
            return None

        try:
            # 최근 20일 수익률 계산
            if len(self.df) < 20:
                return None

            stock_return = (self.df['Close'].iloc[-1] / self.df['Close'].iloc[-20] - 1) * 100

            # 벤치마크 데이터 가져오기
            end_date = pd.Timestamp.now()
            start_date = end_date - timedelta(days=30)

            benchmark_data = yf.download(
                self.benchmark_ticker,
                start=start_date,
                end=end_date,
                progress=False
            )

            if len(benchmark_data) < 20:
                return None

            benchmark_return = (benchmark_data['Close'].iloc[-1] / benchmark_data['Close'].iloc[-20] - 1) * 100

            # 상대강도 = 종목 수익률 - 벤치마크 수익률
            rs = stock_return - benchmark_return

            # 점수 변환 (RS > 5% = 10점, RS > 0% = 5점, RS < -5% = -5점)
            if rs > 5:
                return 10.0
            elif rs > 0:
                return 5.0
            elif rs < -5:
                return -5.0
            else:
                return 0.0

        except Exception:
            return None

    def _calculate_disparity(self) -> float:
        """이격도 계산 및 점수화"""
        score = 0.0

        ma20 = self._get_or_calculate_ma(20)
        if ma20 is None or ma20 == 0:
            return score

        price = float(self.latest.get('Close', 0))
        disparity = (price / ma20) * 100

        # 이격도 기준 점수
        if 102 <= disparity <= 108:
            score = 5.0  # 최적 매수 구간
        elif disparity > 115:
            score = -10.0  # 과열 구간
        elif disparity < 98:
            score = -5.0  # 추세 이탈

        return score

    def _check_bollinger_breakout(self) -> float:
        """볼린저 밴드 돌파 체크"""
        score = 0.0

        # 볼린저 밴드 컬럼 찾기
        bb_upper = None
        bb_lower = None
        bb_middle = None

        for col in self.df.columns:
            if 'BBU' in col:
                bb_upper = col
            elif 'BBL' in col:
                bb_lower = col
            elif 'BBM' in col:
                bb_middle = col

        if not bb_upper or not bb_lower:
            return score

        upper = float(self.latest.get(bb_upper, 0))
        lower = float(self.latest.get(bb_lower, 0))
        price = float(self.latest.get('Close', 0))

        # 밴드 폭 계산
        if bb_middle:
            middle = float(self.latest.get(bb_middle, price))
            bandwidth = (upper - lower) / middle * 100 if middle > 0 else 0

            # 스퀴즈 감지 (밴드폭 < 평균의 60%)
            if len(self.df) >= 20:
                avg_bandwidth = self._calculate_avg_bandwidth(20)
                if avg_bandwidth > 0 and bandwidth < avg_bandwidth * 0.6:
                    # 스퀴즈 상태에서 상단 돌파
                    if price > upper:
                        score = 15.0  # 강력한 돌파 신호

        # 일반 밴드 돌파
        if price > upper:
            score = max(score, 5.0)  # 상단 돌파
        elif price < lower:
            score = min(score, -5.0)  # 하단 이탈

        return score

    def _get_or_calculate_ma(self, period: int) -> Optional[float]:
        """이동평균 가져오기 또는 계산"""
        # 기존 컬럼에서 찾기
        ma_col = f'MA{period}'
        sma_col = f'SMA_{period}'
        ema_col = f'EMA_{period}'

        for col in [ma_col, sma_col, ema_col]:
            if col in self.df.columns:
                return float(self.latest.get(col, 0))

        # 없으면 계산
        if len(self.df) >= period:
            return float(self.df['Close'].tail(period).mean())

        return None

    def _get_ma_at_index(self, period: int, index: int) -> Optional[float]:
        """특정 인덱스의 이동평균 계산"""
        if abs(index) > len(self.df):
            return None

        if index < 0:
            end_idx = len(self.df) + index + 1
        else:
            end_idx = index + 1

        start_idx = max(0, end_idx - period)

        if end_idx - start_idx < period:
            return None

        return float(self.df['Close'].iloc[start_idx:end_idx].mean())

    def _calculate_avg_bandwidth(self, period: int) -> float:
        """평균 볼린저 밴드 폭 계산"""
        bb_upper = None
        bb_lower = None
        bb_middle = None

        for col in self.df.columns:
            if 'BBU' in col:
                bb_upper = col
            elif 'BBL' in col:
                bb_lower = col
            elif 'BBM' in col:
                bb_middle = col

        if not bb_upper or not bb_lower or not bb_middle:
            return 0.0

        lookback = min(period, len(self.df))
        bandwidths = []

        for i in range(lookback):
            idx = -lookback + i
            upper = float(self.df.iloc[idx][bb_upper])
            lower = float(self.df.iloc[idx][bb_lower])
            middle = float(self.df.iloc[idx][bb_middle])

            if middle > 0:
                bandwidth = (upper - lower) / middle * 100
                bandwidths.append(bandwidth)

        return np.mean(bandwidths) if bandwidths else 0.0

    def _determine_signal(self, total_score: float, scores: Dict) -> str:
        """최종 신호 결정"""
        # 강한 감점 항목이 있는 경우
        if scores.get('macd_dead_cross', 0) < 0 or scores.get('extreme_overbought', 0) < 0:
            if total_score < 10:
                return "sell"

        # 점수 기반 신호
        if total_score >= 30:
            return "strong_buy"
        elif total_score >= 15:
            return "buy"
        elif total_score <= -30:
            return "strong_sell"
        elif total_score <= -15:
            return "sell"
        else:
            return "neutral"

    def _calculate_signal_strength(self, total_score: float) -> str:
        """신호 강도 계산"""
        abs_score = abs(total_score)

        if abs_score >= 40:
            return "very_strong"
        elif abs_score >= 25:
            return "strong"
        elif abs_score >= 15:
            return "moderate"
        elif abs_score >= 5:
            return "weak"
        else:
            return "very_weak"

    def _get_recommendation(self, signal: str, strength: str, scores: Dict) -> str:
        """투자 권고사항 생성"""
        recommendations = []

        # 신호별 기본 권고
        if signal == "strong_buy":
            recommendations.append("강력 매수 신호. 적극적 진입 고려")
        elif signal == "buy":
            recommendations.append("매수 신호. 분할 매수 권장")
        elif signal == "strong_sell":
            recommendations.append("강력 매도 신호. 즉시 청산 고려")
        elif signal == "sell":
            recommendations.append("매도 신호. 포지션 축소 권장")
        else:
            recommendations.append("중립 구간. 관망 권장")

        # 특별 조건 체크
        if scores.get('macd_momentum', 0) >= 25:
            recommendations.append("MACD 골든크로스 직후 - 단기 모멘텀 강함")

        if scores.get('extreme_overbought', 0) < 0:
            recommendations.append("RSI 극도 과매수 - 단기 조정 가능성 높음")

        if scores.get('volume_decline', 0) < 0:
            recommendations.append("거래량 지속 감소 - 추세 약화 신호")

        if scores.get('disparity', 0) <= -10:
            recommendations.append("이격도 과열 - 진입 시점 조정 필요")

        return " / ".join(recommendations)