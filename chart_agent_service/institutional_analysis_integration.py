#!/usr/bin/env python3
"""
기관급 기술적 분석 통합 모듈
- 기존 analysis_tools.py와 통합
- 새로운 스코어링 시스템 활용
- 리스크 관리 통합
"""

import pandas as pd
from typing import Dict, Optional
from institutional_scoring import InstitutionalTechnicalScoring
from risk_management import ATRRiskManager


class InstitutionalAnalyzer:
    """기관급 종합 분석 시스템"""

    def __init__(self, df: pd.DataFrame, ticker: str = None, account_size: float = 100000000):
        """
        초기화
        Args:
            df: OHLCV + 기술적 지표 DataFrame
            ticker: 종목 티커
            account_size: 계좌 총 자산
        """
        self.df = df
        self.ticker = ticker
        self.account_size = account_size
        self.latest = df.iloc[-1] if not df.empty else {}

        # 컴포넌트 초기화
        self.scoring = InstitutionalTechnicalScoring(df, ticker)
        self.risk_manager = ATRRiskManager(df, account_size)

    def comprehensive_analysis(self) -> Dict:
        """
        종합 분석 실행
        Returns:
            종합 분석 결과
        """
        # 1. 기술적 스코어링
        scoring_result = self.scoring.calculate_comprehensive_score()

        # 2. 리스크 분석
        current_price = float(self.latest.get('Close', 0))
        position_sizing = self.risk_manager.calculate_position_size(current_price)
        chandelier_exit = self.risk_manager.calculate_chandelier_exit()
        volatility_targets = self.risk_manager.calculate_volatility_adjusted_targets()

        # 3. 기존 지표와 통합 분석
        traditional_analysis = self._analyze_traditional_indicators()

        # 4. 종합 판단
        final_decision = self._make_final_decision(
            scoring_result,
            traditional_analysis,
            position_sizing
        )

        return {
            "ticker": self.ticker,
            "analysis_type": "institutional_comprehensive",
            "technical_scoring": scoring_result,
            "risk_analysis": {
                "position_sizing": position_sizing,
                "exit_strategy": chandelier_exit,
                "targets": volatility_targets
            },
            "traditional_indicators": traditional_analysis,
            "final_decision": final_decision,
            "timestamp": pd.Timestamp.now().isoformat()
        }

    def _analyze_traditional_indicators(self) -> Dict:
        """기존 기술적 지표 분석"""
        analysis = {}

        # RSI 분석
        if 'RSI' in self.df.columns:
            rsi = float(self.latest.get('RSI', 50))
            analysis['rsi'] = {
                "value": rsi,
                "status": "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral",
                "signal": "sell" if rsi > 70 else "buy" if rsi < 30 else "neutral"
            }

        # MACD 분석
        macd_cols = [col for col in self.df.columns if 'MACD' in col]
        if macd_cols:
            for col in macd_cols:
                if 'MACDh' in col:
                    hist = float(self.latest.get(col, 0))
                    analysis['macd'] = {
                        "histogram": hist,
                        "trend": "bullish" if hist > 0 else "bearish",
                        "momentum": self._check_macd_momentum()
                    }
                    break

        # 볼륨 분석
        if 'Volume' in self.df.columns and len(self.df) >= 20:
            current_vol = float(self.latest['Volume'])
            avg_vol = float(self.df['Volume'].tail(20).mean())
            analysis['volume'] = {
                "current": current_vol,
                "average": avg_vol,
                "ratio": current_vol / avg_vol if avg_vol > 0 else 0,
                "status": "high" if current_vol > avg_vol * 1.5 else "normal"
            }

        # 이동평균 분석
        ma_analysis = {}
        for period in [5, 20, 60, 120]:
            ma_col = f'MA{period}'
            sma_col = f'SMA_{period}'
            for col in [ma_col, sma_col]:
                if col in self.df.columns:
                    ma_value = float(self.latest.get(col, 0))
                    price = float(self.latest.get('Close', 0))
                    ma_analysis[f'ma{period}'] = {
                        "value": ma_value,
                        "position": "above" if price > ma_value else "below"
                    }
                    break

        if ma_analysis:
            analysis['moving_averages'] = ma_analysis

        return analysis

    def _check_macd_momentum(self) -> str:
        """MACD 모멘텀 체크"""
        hist_col = None
        for col in self.df.columns:
            if 'MACDh' in col:
                hist_col = col
                break

        if not hist_col or len(self.df) < 3:
            return "unknown"

        # 최근 3개 히스토그램
        hist_values = self.df[hist_col].tail(3).values

        # 증가/감소 패턴
        if all(hist_values[i] < hist_values[i+1] for i in range(2)):
            return "accelerating"
        elif all(hist_values[i] > hist_values[i+1] for i in range(2)):
            return "decelerating"
        else:
            return "mixed"

    def _make_final_decision(self, scoring: Dict, traditional: Dict, risk: Dict) -> Dict:
        """최종 투자 결정"""
        score = scoring['total_score']
        signal = scoring['signal']
        strength = scoring['signal_strength']

        # 리스크 조정
        if risk.get('volatility_level') in ['extreme', 'high']:
            risk_adjustment = 0.7  # 고변동성 시 신호 약화
        else:
            risk_adjustment = 1.0

        adjusted_score = score * risk_adjustment

        # 최종 액션 결정
        if signal in ['strong_buy', 'buy'] and adjusted_score >= 15:
            action = "BUY"
            confidence = min(10, adjusted_score / 5)
        elif signal in ['strong_sell', 'sell'] and adjusted_score <= -15:
            action = "SELL"
            confidence = min(10, abs(adjusted_score) / 5)
        else:
            action = "HOLD"
            confidence = 5.0

        # 포지션 크기 권고
        if action == "BUY":
            recommended_shares = risk['shares']
            recommended_value = risk['position_value']
        else:
            recommended_shares = 0
            recommended_value = 0

        return {
            "action": action,
            "confidence": round(confidence, 1),
            "adjusted_score": round(adjusted_score, 1),
            "risk_adjustment": risk_adjustment,
            "position_recommendation": {
                "shares": recommended_shares,
                "value": recommended_value,
                "stop_loss": risk.get('stop_price', 0)
            },
            "reasoning": self._generate_reasoning(action, scoring, traditional, risk)
        }

    def _generate_reasoning(self, action: str, scoring: Dict, traditional: Dict, risk: Dict) -> str:
        """투자 결정 근거 생성"""
        reasons = []

        # 기술적 점수 근거
        reasons.append(f"기술적 종합점수: {scoring['total_score']:.1f}점 ({scoring['signal_strength']})")

        # 주요 긍정 요인
        positive_factors = [k for k, v in scoring['scores_detail'].items() if v > 10]
        if positive_factors:
            reasons.append(f"긍정 요인: {', '.join(positive_factors)}")

        # 주요 부정 요인
        negative_factors = [k for k, v in scoring['scores_detail'].items() if v < -10]
        if negative_factors:
            reasons.append(f"부정 요인: {', '.join(negative_factors)}")

        # 리스크 요인
        if risk.get('volatility_level') in ['high', 'extreme']:
            reasons.append(f"변동성 리스크: {risk['volatility_level']}")

        # RSI 상태
        if 'rsi' in traditional:
            rsi_status = traditional['rsi']['status']
            if rsi_status != 'neutral':
                reasons.append(f"RSI {rsi_status}: {traditional['rsi']['value']:.1f}")

        return " | ".join(reasons)

    def generate_report(self) -> str:
        """분석 보고서 생성"""
        analysis = self.comprehensive_analysis()

        report_lines = [
            "=" * 80,
            f"기관급 종합 기술적 분석 보고서",
            "=" * 80,
            f"종목: {self.ticker or 'Unknown'}",
            f"분석 시각: {analysis['timestamp']}",
            "",
            "[ 기술적 스코어링 ]",
            "-" * 40,
            f"종합 점수: {analysis['technical_scoring']['total_score']:.1f}점",
            f"신호: {analysis['technical_scoring']['signal']}",
            f"신호 강도: {analysis['technical_scoring']['signal_strength']}",
            "",
            "세부 점수:",
        ]

        # 세부 점수 출력
        for key, value in analysis['technical_scoring']['scores_detail'].items():
            if value != 0:
                report_lines.append(f"  - {key}: {value:+.1f}점")

        report_lines.extend([
            "",
            "[ 리스크 분석 ]",
            "-" * 40,
            f"권장 포지션: {analysis['risk_analysis']['position_sizing']['shares']}주",
            f"포지션 가치: {analysis['risk_analysis']['position_sizing']['position_value']:,.0f}원",
            f"손절가: {analysis['risk_analysis']['position_sizing']['stop_price']:.2f}",
            f"변동성 수준: {analysis['risk_analysis']['position_sizing']['volatility_level']}",
            "",
            "목표가:",
        ])

        # 목표가 출력
        if 'targets' in analysis['risk_analysis']['targets']:
            for target, price in analysis['risk_analysis']['targets']['targets'].items():
                report_lines.append(f"  - {target}: {price:.2f}")

        report_lines.extend([
            "",
            "[ 최종 판단 ]",
            "-" * 40,
            f"액션: {analysis['final_decision']['action']}",
            f"신뢰도: {analysis['final_decision']['confidence']:.1f}/10",
            f"근거: {analysis['final_decision']['reasoning']}",
            "",
            "[ 투자 권고 ]",
            "-" * 40,
            analysis['technical_scoring']['recommendation'],
            "=" * 80
        ])

        return "\n".join(report_lines)


# 기존 analysis_tools.py와의 통합 메서드
def integrate_with_existing_system(analyzer_instance, ticker: str):
    """
    기존 AdvancedTechnicalAnalyzer와 통합

    Args:
        analyzer_instance: 기존 AdvancedTechnicalAnalyzer 인스턴스
        ticker: 분석할 종목

    Returns:
        통합 분석 결과
    """
    # 기존 분석기의 DataFrame 가져오기
    df = analyzer_instance.df

    # 새로운 기관급 분석기 생성
    institutional = InstitutionalAnalyzer(df, ticker)

    # 종합 분석 실행
    institutional_result = institutional.comprehensive_analysis()

    # 기존 분석 결과와 병합
    existing_results = {
        "trend_analysis": analyzer_instance.trend_analysis() if hasattr(analyzer_instance, 'trend_analysis') else {},
        "rsi_divergence": analyzer_instance.rsi_divergence_analysis() if hasattr(analyzer_instance, 'rsi_divergence_analysis') else {},
        "bollinger": analyzer_instance.bollinger_squeeze_analysis() if hasattr(analyzer_instance, 'bollinger_squeeze_analysis') else {},
        "macd": analyzer_instance.macd_momentum_analysis() if hasattr(analyzer_instance, 'macd_momentum_analysis') else {}
    }

    # 통합 결과 반환
    return {
        "institutional_analysis": institutional_result,
        "traditional_analysis": existing_results,
        "combined_signal": _combine_signals(institutional_result, existing_results),
        "report": institutional.generate_report()
    }


def _combine_signals(institutional: Dict, traditional: Dict) -> Dict:
    """신호 통합"""
    inst_signal = institutional['final_decision']['action']
    inst_confidence = institutional['final_decision']['confidence']

    # 기존 신호들 수집
    trad_signals = []
    for analysis in traditional.values():
        if isinstance(analysis, dict) and 'signal' in analysis:
            trad_signals.append(analysis['signal'])

    # 다수결 원칙
    buy_count = trad_signals.count('buy') + (1 if inst_signal == 'BUY' else 0)
    sell_count = trad_signals.count('sell') + (1 if inst_signal == 'SELL' else 0)

    if buy_count > sell_count + 1:
        combined = "BUY"
    elif sell_count > buy_count + 1:
        combined = "SELL"
    else:
        combined = "HOLD"

    return {
        "signal": combined,
        "confidence": inst_confidence,
        "agreement_level": "high" if buy_count > 3 or sell_count > 3 else "medium"
    }


# 사용 예제
if __name__ == "__main__":
    # 테스트 데이터 생성
    import numpy as np

    dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
    test_df = pd.DataFrame({
        'Open': np.random.randn(100).cumsum() + 100,
        'High': np.random.randn(100).cumsum() + 102,
        'Low': np.random.randn(100).cumsum() + 98,
        'Close': np.random.randn(100).cumsum() + 100,
        'Volume': np.random.randint(1000000, 10000000, 100),
        'RSI': np.random.uniform(30, 70, 100),
        'ATR_14': np.random.uniform(1, 5, 100)
    }, index=dates)

    # MA 계산
    test_df['MA5'] = test_df['Close'].rolling(5).mean()
    test_df['MA20'] = test_df['Close'].rolling(20).mean()
    test_df['MA60'] = test_df['Close'].rolling(60).mean()

    # 분석 실행
    analyzer = InstitutionalAnalyzer(test_df, ticker="TEST.KS")
    print(analyzer.generate_report())