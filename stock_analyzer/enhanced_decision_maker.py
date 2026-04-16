#!/usr/bin/env python3
"""
향상된 Decision Maker - 멀티에이전트 시스템 개선
- 정확한 점수 집계
- 신호 강도 기반 판단
- 고변동성 상황 체크
- 한국 주식 통화 처리
- ML 모델 정확도 기반 가중치 조정
- 내부자 거래 신호 강화
"""

import json
from typing import List, Dict, Any
from datetime import datetime
from signal_normalizer import SignalNormalizer, normalize_signal


class EnhancedDecisionMaker:
    """개선된 의사결정자 - 점수와 신호 강도를 정확히 분석"""

    def __init__(self):
        self.name = "Enhanced Decision Maker"
        self.llm_provider = "openai"

    def aggregate(self, ticker: str, agent_results: List[Any]) -> Dict[str, Any]:
        """
        에이전트 결과 종합 및 최종 판단

        주요 개선사항:
        1. 정확한 점수 집계
        2. 신호 강도 체크
        3. 고변동성 상황 판단
        4. 한국 주식 통화 처리
        5. ML 모델 정확도 기반 가중치 조정
        6. 내부자 거래 신호 강화
        """

        # 1. 한국 주식 여부 판단
        is_korean = self._is_korean_stock(ticker)
        currency = "₩" if is_korean else "$"

        # 2. 에이전트 의견 및 점수 집계 (신호 정규화 적용)
        signal_counts = {"buy": 0, "sell": 0, "neutral": 0}
        confidence_sum = 0.0
        valid_agents = 0

        # 점수 상세 집계
        technical_scores = []
        quant_scores = []
        risk_scores = []
        ml_scores = []
        ml_accuracies = []  # ML 정확도 추적
        event_scores = []
        insider_signal = None  # 내부자 거래 신호
        insider_score = 0

        for result in agent_results:
            if result.error:
                continue

            # 신호 정규화
            normalized_signal = normalize_signal(result.signal)
            signal_counts[normalized_signal] += 1
            confidence_sum += result.confidence
            valid_agents += 1

            # 에이전트별 점수 분류
            if "Technical" in result.agent_name:
                technical_scores.append(self._extract_scores(result))
            elif "Quant" in result.agent_name:
                quant_scores.append(self._extract_scores(result))
            elif "Risk" in result.agent_name:
                risk_scores.append(result.confidence)
            elif "ML" in result.agent_name:
                ml_scores.append(result.confidence)
                # ML 정확도 추출 (evidence에서)
                for ev in result.evidence:
                    ml_result = ev.get("result", {})
                    if "ensemble" in ml_result:
                        # 각 모델의 정확도 수집
                        models = ml_result.get("models", {})
                        for model_data in models.values():
                            if "test_accuracy" in model_data:
                                ml_accuracies.append(model_data["test_accuracy"])
            elif "Event" in result.agent_name:
                event_scores.append(result.confidence)
                # 내부자 거래 신호 추출
                for ev in result.evidence:
                    if ev.get("tool") == "insider_trading_analysis":
                        insider_result = ev.get("result", {})
                        insider_signal = normalize_signal(insider_result.get("signal", "neutral"))
                        insider_score = insider_result.get("score", 0)

        # 3. 점수 집계 및 분석
        tech_analysis = self._analyze_technical_scores(technical_scores)
        quant_analysis = self._analyze_quant_scores(quant_scores)

        # 4. 고변동성 체크
        volatility_check = self._check_volatility(agent_results)

        # 5. 신호 강도 계산 (ML 정확도 및 내부자 거래 반영)
        signal_strength = self._calculate_signal_strength(
            tech_analysis, quant_analysis, risk_scores, ml_scores, event_scores,
            ml_accuracies, insider_signal, insider_score
        )

        # 6. 최종 판단
        final_decision = self._make_final_decision(
            signal_counts,
            signal_strength,
            volatility_check,
            tech_analysis,
            quant_analysis,
            currency
        )

        # 7. 결과 구성
        result = {
            "final_signal": final_decision["signal"],
            "final_confidence": final_decision["confidence"],
            "consensus": f"{signal_counts['buy']}명 매수, {signal_counts['sell']}명 매도, {signal_counts['neutral']}명 중립",
            "conflicts": final_decision["conflicts"],
            "reasoning": final_decision["reasoning"],
            "key_risks": final_decision["risks"],
            "agent_count": len(agent_results),
            "signal_distribution": signal_counts,
            "analyzed_at": datetime.now().isoformat(),
            "currency": currency,
            "signal_strength": signal_strength,
            "volatility_status": volatility_check,
            "technical_analysis": tech_analysis,
            "quant_analysis": quant_analysis
        }

        return result

    def _is_korean_stock(self, ticker: str) -> bool:
        """한국 주식 여부 판단"""
        return ticker.endswith('.KS') or ticker.endswith('.KQ') or ticker.isdigit()

    def _extract_scores(self, result) -> Dict[str, float]:
        """에이전트 결과에서 점수 추출"""
        scores = {}

        for evidence in result.evidence:
            if "error" in evidence:
                continue

            tool_result = evidence.get("result", {})
            tool_name = evidence.get("tool", "")
            score = tool_result.get("score", 0)
            signal = tool_result.get("signal", "neutral")

            scores[tool_name] = {
                "score": score,
                "signal": signal
            }

        return scores

    def _analyze_technical_scores(self, tech_scores_list: List[Dict]) -> Dict:
        """기술적 분석 점수 집계"""
        if not tech_scores_list:
            return {"total_score": 0, "buy_count": 0, "sell_count": 0, "neutral_count": 0, "avg_strength": 0}

        total_score = 0
        buy_count = 0
        sell_count = 0
        neutral_count = 0

        for scores in tech_scores_list:
            for tool_name, tool_data in scores.items():
                score = tool_data["score"]
                signal = tool_data["signal"]

                total_score += score

                if signal == "buy":
                    buy_count += 1
                elif signal == "sell":
                    sell_count += 1
                else:
                    neutral_count += 1

        # 평균 신호 강도 계산
        total_tools = buy_count + sell_count + neutral_count
        avg_strength = abs(total_score) / total_tools if total_tools > 0 else 0

        return {
            "total_score": total_score,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "neutral_count": neutral_count,
            "avg_strength": avg_strength
        }

    def _analyze_quant_scores(self, quant_scores_list: List[Dict]) -> Dict:
        """퀀트 분석 점수 집계"""
        if not quant_scores_list:
            return {"total_score": 0, "buy_count": 0, "sell_count": 0, "neutral_count": 0, "avg_strength": 0}

        total_score = 0
        buy_count = 0
        sell_count = 0
        neutral_count = 0

        for scores in quant_scores_list:
            for tool_name, tool_data in scores.items():
                score = tool_data["score"]
                signal = tool_data["signal"]

                total_score += score

                if signal == "buy":
                    buy_count += 1
                elif signal == "sell":
                    sell_count += 1
                else:
                    neutral_count += 1

        # 평균 신호 강도 계산
        total_tools = buy_count + sell_count + neutral_count
        avg_strength = abs(total_score) / total_tools if total_tools > 0 else 0

        return {
            "total_score": total_score,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "neutral_count": neutral_count,
            "avg_strength": avg_strength
        }

    def _check_volatility(self, agent_results) -> Dict:
        """고변동성 체크"""
        volatility_mentions = []

        for result in agent_results:
            reasoning = result.reasoning.lower()

            # 고변동성 키워드 체크
            if any(keyword in reasoning for keyword in ["고변동성", "변동성 증가", "volatility high", "high volatility"]):
                volatility_mentions.append(result.agent_name)

        is_high_volatility = len(volatility_mentions) >= 2  # 2개 이상 에이전트가 언급하면 고변동성

        return {
            "is_high": is_high_volatility,
            "mentioned_by": volatility_mentions
        }

    def _calculate_signal_strength(self, tech_analysis, quant_analysis,
                                  risk_scores, ml_scores, event_scores,
                                  ml_accuracies=None, insider_signal=None,
                                  insider_score=0) -> Dict:
        """신호 강도 계산 (ML 정확도 가중치 및 내부자 거래 반영)"""

        # 기술적 분석 강도
        tech_strength = tech_analysis["avg_strength"]
        tech_direction = "buy" if tech_analysis["total_score"] > 0 else "sell" if tech_analysis["total_score"] < 0 else "neutral"

        # 퀀트 분석 강도
        quant_strength = quant_analysis["avg_strength"]
        quant_direction = "buy" if quant_analysis["total_score"] > 0 else "sell" if quant_analysis["total_score"] < 0 else "neutral"

        # ML 가중치 조정 (정확도 기반)
        ml_weight = 1.0  # 기본 가중치
        if ml_accuracies:
            avg_accuracy = sum(ml_accuracies) / len(ml_accuracies)
            if avg_accuracy < 0.5:  # 50% 미만 정확도
                ml_weight = 0.3  # 가중치 대폭 감소
            elif avg_accuracy < 0.55:  # 50-55%
                ml_weight = 0.5  # 가중치 감소
            elif avg_accuracy > 0.6:  # 60% 이상
                ml_weight = 1.2  # 가중치 약간 증가

        # ML 점수 조정
        ml_contribution = 0
        if ml_scores:
            ml_avg = sum(ml_scores) / len(ml_scores)
            # ML이 매도 신호일 때 가중치 적용
            if ml_avg < 5:  # 매도 경향
                ml_contribution = -(5 - ml_avg) * ml_weight
            elif ml_avg > 5:  # 매수 경향
                ml_contribution = (ml_avg - 5) * ml_weight

        # 내부자 거래 신호 강화 (2배 가중치)
        insider_contribution = insider_score * 2.0

        # 전체 점수 (기술 + 퀀트 + ML조정 + 내부자)
        total_score = (tech_analysis["total_score"] +
                      quant_analysis["total_score"] +
                      ml_contribution +
                      insider_contribution)

        # 신호 강도 분류
        strength_level = "weak"  # 약함
        if abs(total_score) > 25:
            strength_level = "strong"  # 강함
        elif abs(total_score) > 12:
            strength_level = "moderate"  # 보통

        # 내부자 거래가 강한 경우 특별 처리
        if abs(insider_score) >= 4:
            if insider_signal == "sell":
                strength_level = "strong_sell_signal"
            elif insider_signal == "buy":
                strength_level = "strong_buy_signal"

        return {
            "technical": {
                "direction": tech_direction,
                "strength": tech_strength,
                "score": tech_analysis["total_score"]
            },
            "quantitative": {
                "direction": quant_direction,
                "strength": quant_strength,
                "score": quant_analysis["total_score"]
            },
            "ml_adjusted": {
                "weight": ml_weight,
                "contribution": ml_contribution,
                "avg_accuracy": sum(ml_accuracies) / len(ml_accuracies) if ml_accuracies else 0
            },
            "insider": {
                "signal": insider_signal,
                "score": insider_score,
                "contribution": insider_contribution
            },
            "total_score": total_score,
            "strength_level": strength_level
        }

    def _make_final_decision(self, signal_counts, signal_strength,
                            volatility_check, tech_analysis, quant_analysis, currency) -> Dict:
        """최종 판단 (내부자 거래 특별 처리 포함)"""

        # 1. 점수 기반 판단
        total_score = signal_strength["total_score"]
        strength_level = signal_strength["strength_level"]
        insider_signal = signal_strength.get("insider", {}).get("signal")
        insider_score = signal_strength.get("insider", {}).get("score", 0)

        # 2. 내부자 거래 강한 신호 시 우선 처리
        if strength_level in ["strong_sell_signal", "strong_buy_signal"]:
            if strength_level == "strong_sell_signal":
                return {
                    "signal": "sell",
                    "confidence": 8.0,
                    "conflicts": "없음",
                    "reasoning": f"강한 내부자 매도 신호 감지 (점수: {insider_score}). CEO/임원진 대규모 매각. 총점: {total_score:+.1f}",
                    "risks": ["내부자 대규모 매도", "분배 국면 가능성"]
                }
            else:  # strong_buy_signal
                return {
                    "signal": "buy",
                    "confidence": 8.0,
                    "conflicts": "없음",
                    "reasoning": f"강한 내부자 매수 신호 감지 (점수: {insider_score}). CEO/임원진 대규모 매수. 총점: {total_score:+.1f}",
                    "risks": ["단기 과열 가능성"]
                }

        # 3. 기본 신호 결정
        if total_score > 5:
            base_signal = "buy"
        elif total_score < -5:
            base_signal = "sell"
        else:
            base_signal = "neutral"

        # 4. 고변동성 상황에서 신호 강도 체크
        if volatility_check["is_high"]:
            if strength_level == "weak":
                # 고변동성 + 약한 신호 = HOLD
                return {
                    "signal": "neutral",
                    "confidence": 3.0,
                    "conflicts": "고변동성 상황에서 신호가 약함",
                    "reasoning": f"현재 고변동성 상황이며 신호 강도가 약함 (총점: {total_score:+.1f}). 관망 권고.",
                    "risks": ["고변동성 리스크", "약한 신호 강도", "방향성 불명확"]
                }

        # 4. 기술적 vs 퀀트 충돌 체크
        tech_dir = signal_strength["technical"]["direction"]
        quant_dir = signal_strength["quantitative"]["direction"]

        conflicts = []
        if tech_dir != quant_dir and tech_dir != "neutral" and quant_dir != "neutral":
            conflicts.append(f"기술적({tech_dir}) vs 퀀트({quant_dir}) 충돌")

        # 5. 신뢰도 계산
        confidence = min(10, abs(total_score) / 3)
        if strength_level == "weak":
            confidence = min(confidence, 4.0)
        elif strength_level == "moderate":
            confidence = min(confidence, 7.0)

        # 6. 리스크 요인
        risks = []
        if volatility_check["is_high"]:
            risks.append("고변동성 구간")
        if strength_level == "weak":
            risks.append("약한 신호 강도")
        if conflicts:
            risks.extend(conflicts)

        # 7. 판단 근거
        reasoning_parts = []
        reasoning_parts.append(f"종합 점수: {total_score:+.1f} (기술: {tech_analysis['total_score']:+.1f}, 퀀트: {quant_analysis['total_score']:+.1f})")
        reasoning_parts.append(f"신호 강도: {strength_level}")

        if base_signal == "buy":
            reasoning_parts.append(f"매수 신호 우세 (기술 {tech_analysis['buy_count']}개, 퀀트 {quant_analysis['buy_count']}개)")
        elif base_signal == "sell":
            reasoning_parts.append(f"매도 신호 우세 (기술 {tech_analysis['sell_count']}개, 퀀트 {quant_analysis['sell_count']}개)")
        else:
            reasoning_parts.append("중립 구간 - 방향성 불명확")

        return {
            "signal": base_signal,
            "confidence": round(confidence, 1),
            "conflicts": ", ".join(conflicts) if conflicts else "없음",
            "reasoning": " / ".join(reasoning_parts),
            "risks": risks if risks else ["특별한 리스크 없음"]
        }