#!/usr/bin/env python3
"""
향상된 Single LLM 분석 - 점수 집계 개선
- 평균 대신 총점 사용
- 신호 강도 기반 신뢰도
- 한국 주식 통화 처리
"""

import numpy as np
from datetime import datetime


class EnhancedCompositeScoreCalculator:
    """개선된 종합 점수 계산기"""

    @staticmethod
    def compute_composite_score(tool_results, ticker=""):
        """
        전체 결과를 종합하여 최종 스코어 산출

        주요 개선사항:
        1. 평균이 아닌 총점/가중치 사용
        2. 신호 강도 기반 신뢰도 계산
        3. 한국 주식 여부 확인
        """

        if not tool_results:
            return {
                "ticker": ticker,
                "analysis_date": datetime.now().isoformat(),
                "final_signal": "HOLD",
                "composite_score": 0.0,
                "confidence": 0,
                "signal_distribution": {"buy": 0, "sell": 0, "neutral": 0},
                "tool_count": 0,
                "tool_summaries": [],
                "tool_details": []
            }

        # 한국 주식 여부 확인
        is_korean = ticker.endswith('.KS') or ticker.endswith('.KQ') or (ticker.isdigit() and len(ticker) == 6)
        currency = "₩" if is_korean else "$"

        scores = []
        signals = {"buy": 0, "sell": 0, "neutral": 0}
        tool_summaries = []

        # 점수별 가중치 (강한 신호에 더 높은 가중치)
        strong_signals = 0  # |score| > 5
        moderate_signals = 0  # 2 < |score| <= 5
        weak_signals = 0  # |score| <= 2

        for r in tool_results:
            score = r.get("score", 0)
            signal = r.get("signal", "neutral")
            scores.append(score)
            signals[signal] = signals.get(signal, 0) + 1

            # 신호 강도 분류
            abs_score = abs(score)
            if abs_score > 5:
                strong_signals += 1
            elif abs_score > 2:
                moderate_signals += 1
            else:
                weak_signals += 1

            tool_summaries.append({
                "tool": r.get("tool", "unknown"),
                "name": r.get("name", ""),
                "signal": signal,
                "score": score,
                "detail": r.get("detail", ""),
            })

        # 총점 계산 (평균이 아닌 합계)
        total_score = sum(scores)
        avg_score = float(np.mean(scores))
        total_tools = len(tool_results)

        # 정규화된 점수 (도구 수로 나눈 평균의 3배로 스케일링)
        # 이렇게 하면 많은 도구가 같은 방향을 가리킬 때 더 강한 신호
        normalized_score = total_score / max(total_tools, 1) * 3

        # 최종 신호 결정 (정규화된 점수 기준)
        if normalized_score > 3:
            final_signal = "BUY"
        elif normalized_score < -3:
            final_signal = "SELL"
        else:
            final_signal = "HOLD"

        # 신뢰도 계산 (의견 일치도 + 신호 강도)
        max_agreement = max(signals.values())
        agreement_ratio = max_agreement / total_tools if total_tools > 0 else 0

        # 강한 신호 비율
        strong_ratio = strong_signals / total_tools if total_tools > 0 else 0

        # 종합 신뢰도 (의견 일치도 50% + 신호 강도 50%)
        confidence = round((agreement_ratio * 5 + strong_ratio * 5), 1)
        confidence = min(10, max(0, confidence))  # 0-10 범위

        # 신호가 약하면 신뢰도 하향
        if strong_signals == 0 and moderate_signals < 3:
            confidence = min(confidence, 4.0)

        return {
            "ticker": ticker,
            "analysis_date": datetime.now().isoformat(),
            "final_signal": final_signal,
            "composite_score": round(normalized_score, 2),
            "total_score": round(total_score, 2),
            "average_score": round(avg_score, 2),
            "confidence": confidence,
            "signal_distribution": signals,
            "signal_strength": {
                "strong": strong_signals,
                "moderate": moderate_signals,
                "weak": weak_signals
            },
            "tool_count": total_tools,
            "tool_summaries": tool_summaries,
            "tool_details": tool_results,
            "currency": currency
        }