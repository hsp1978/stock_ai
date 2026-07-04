#!/usr/bin/env python3
"""
신호 정규화 유틸리티 (Signal Normalization)
- 전체 시스템에서 일관된 신호 라벨 사용
- buy/sell/neutral로 통일
- 신호 강도 및 신뢰도 표준화
"""

from typing import Dict, Tuple, Any


class SignalNormalizer:
    """신호 정규화 클래스"""

    # 표준 신호 매핑. normalize_signal()에서 lowercase/공백 정규화를 먼저 적용한다.
    SIGNAL_MAP = {
        # Buy 변형들
        "buy": "buy",
        "long": "buy",
        "bullish": "buy",
        "bull": "buy",
        "strong_buy": "buy",
        "buy_now": "buy",
        "buy_on_dip": "buy",
        "accumulate": "buy",
        "매수": "buy",
        "강한_매수": "buy",
        "상승": "buy",

        # Sell 변형들
        "sell": "sell",
        "short": "sell",
        "bearish": "sell",
        "bear": "sell",
        "strong_sell": "sell",
        "reduce": "sell",
        "매도": "sell",
        "강한_매도": "sell",
        "하락": "sell",

        # Neutral 변형들
        "neutral": "neutral",
        "hold": "neutral",
        "wait": "neutral",
        "resize": "neutral",
        "none": "neutral",
        "no_action": "neutral",
        "관망": "neutral",
        "보유": "neutral",
        "대기": "neutral",
        "중립": "neutral",
    }

    @classmethod
    def normalize_signal(cls, signal: str) -> str:
        """
        신호를 표준 형식으로 정규화

        Args:
            signal: 원본 신호 문자열

        Returns:
            정규화된 신호 (buy/sell/neutral)
        """
        if not signal:
            return "neutral"

        # SSOT(decision_context.normalize_trade_signal)에 위임한다. 단, 이 모듈은
        # stock_analyzer 단독 컨텍스트(chart_agent_service 미적재)에서도 import 되므로
        # 위임이 불가능하면 아래 SIGNAL_MAP fallback 으로 degrade 한다.
        # SIGNAL_MAP 은 SSOT 와 동일 규칙을 유지하는 미러이며 직접 수정 금지.
        try:
            from decision_context import normalize_trade_signal

            return normalize_trade_signal(signal)
        except Exception:
            pass

        # 공백/구분자/대소문자 정규화
        signal_clean = (
            str(signal)
            .strip()
            .replace("-", "_")
            .replace(" ", "_")
            .lower()
        )

        # 매핑 테이블에서 찾기 (fallback)
        normalized = cls.SIGNAL_MAP.get(signal_clean, "neutral")

        return normalized

    @classmethod
    def calculate_signal_from_score(cls, score: float,
                                   buy_threshold: float = 2.0,
                                   sell_threshold: float = -2.0) -> str:
        """
        점수 기반 신호 결정

        Args:
            score: 신호 점수
            buy_threshold: 매수 임계값 (기본값: 2.0)
            sell_threshold: 매도 임계값 (기본값: -2.0)

        Returns:
            신호 (buy/sell/neutral)
        """
        if score > buy_threshold:
            return "buy"
        elif score < sell_threshold:
            return "sell"
        else:
            return "neutral"

    @classmethod
    def normalize_confidence(cls, confidence: float,
                            min_val: float = 0,
                            max_val: float = 10) -> float:
        """
        신뢰도를 0-10 범위로 정규화

        Args:
            confidence: 원본 신뢰도
            min_val: 최소값 (기본값: 0)
            max_val: 최대값 (기본값: 10)

        Returns:
            정규화된 신뢰도 (0-10)
        """
        if confidence is None:
            return 5.0

        # 범위 제한
        normalized = max(min_val, min(max_val, float(confidence)))

        return round(normalized, 1)

    @classmethod
    def calculate_weighted_signal(cls, signals: list, weights: list = None) -> Tuple[str, float]:
        """
        여러 신호의 가중 평균 계산

        Args:
            signals: [(signal, score, confidence), ...] 형태의 리스트
            weights: 각 신호의 가중치 리스트 (없으면 동일 가중치)

        Returns:
            (최종 신호, 종합 점수)
        """
        if not signals:
            return "neutral", 0.0

        # 가중치 설정
        if weights is None:
            weights = [1.0] * len(signals)
        elif len(weights) != len(signals):
            weights = [1.0] * len(signals)

        # 정규화된 신호와 점수 수집
        buy_score = 0.0
        sell_score = 0.0
        neutral_score = 0.0
        total_weight = 0.0

        for i, (signal, score, confidence) in enumerate(signals):
            normalized_signal = cls.normalize_signal(signal)
            weight = weights[i] * (confidence / 10.0)  # 신뢰도로 가중치 조정

            if normalized_signal == "buy":
                buy_score += abs(score) * weight
            elif normalized_signal == "sell":
                sell_score += abs(score) * weight
            else:
                neutral_score += weight

            total_weight += weight

        if total_weight == 0:
            return "neutral", 0.0

        # 정규화
        buy_score /= total_weight
        sell_score /= total_weight
        neutral_score /= total_weight

        # 최종 신호 결정
        if buy_score > sell_score and buy_score > neutral_score:
            final_signal = "buy"
            final_score = buy_score
        elif sell_score > buy_score and sell_score > neutral_score:
            final_signal = "sell"
            final_score = -sell_score
        else:
            final_signal = "neutral"
            final_score = 0.0

        return final_signal, round(final_score, 2)

    @classmethod
    def normalize_result(cls, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        분석 결과 전체를 정규화

        Args:
            result: 원본 분석 결과 딕셔너리

        Returns:
            정규화된 결과 딕셔너리
        """
        normalized = result.copy()

        # 신호 정규화
        if "signal" in normalized:
            normalized["signal"] = cls.normalize_signal(normalized["signal"])

        # 최종 신호 정규화
        if "final_signal" in normalized:
            normalized["final_signal"] = cls.normalize_signal(normalized["final_signal"])

        # 신뢰도 정규화
        if "confidence" in normalized:
            normalized["confidence"] = cls.normalize_confidence(normalized["confidence"])

        if "final_confidence" in normalized:
            normalized["final_confidence"] = cls.normalize_confidence(normalized["final_confidence"])

        return normalized


# 전역 헬퍼 함수들
def normalize_signal(signal: str) -> str:
    """신호 정규화 헬퍼 함수"""
    return SignalNormalizer.normalize_signal(signal)


def calculate_signal_from_score(score: float,
                                buy_threshold: float = 2.0,
                                sell_threshold: float = -2.0) -> str:
    """점수 기반 신호 계산 헬퍼 함수"""
    return SignalNormalizer.calculate_signal_from_score(score, buy_threshold, sell_threshold)


def normalize_confidence(confidence: float) -> float:
    """신뢰도 정규화 헬퍼 함수"""
    return SignalNormalizer.normalize_confidence(confidence)


# 테스트
if __name__ == "__main__":
    # 신호 정규화 테스트
    test_signals = ["BUY", "SELL", "HOLD", "bullish", "bearish", "neutral", "LONG", "SHORT"]

    print("신호 정규화 테스트:")
    for signal in test_signals:
        normalized = normalize_signal(signal)
        print(f"  {signal:10} -> {normalized}")

    print("\n점수 기반 신호 테스트:")
    test_scores = [5.0, -5.0, 0.0, 2.5, -2.5, 1.0, -1.0]
    for score in test_scores:
        signal = calculate_signal_from_score(score)
        print(f"  점수 {score:+5.1f} -> {signal}")

    print("\n가중 신호 계산 테스트:")
    signals = [
        ("BUY", 4.0, 8.0),
        ("SELL", -3.0, 6.0),
        ("neutral", 0.0, 5.0),
    ]
    final_signal, final_score = SignalNormalizer.calculate_weighted_signal(signals)
    print(f"  입력 신호: {signals}")
    print(f"  최종 결과: {final_signal} (점수: {final_score})")
