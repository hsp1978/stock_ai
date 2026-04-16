#!/usr/bin/env python3
"""
조건부 진입 전략 모듈 (Conditional Entry Strategy)
- 과열 상태 회피
- 조정 시점 진입
- 분할 매수 전략
- Kelly 기준 포지션 사이징
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple
from datetime import datetime


class ConditionalEntryStrategy:
    """조건부 진입 전략"""

    def __init__(self):
        # 과열 판단 기준
        self.RSI_OVERBOUGHT = 70
        self.RSI_OVERSOLD = 30
        self.RSI_NEUTRAL = 50

        # 피보나치 되돌림 레벨
        self.FIB_LEVELS = {
            "0.236": 0.236,
            "0.382": 0.382,
            "0.500": 0.500,
            "0.618": 0.618,
            "0.786": 0.786
        }

        # Kelly 기준 최대 포지션
        self.KELLY_MAX_POSITION = 0.25  # 최대 25%
        self.KELLY_HALF_POSITION = 0.125  # Kelly Half (12.5%)

    def calculate_entry_conditions(self, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        진입 조건 계산

        Args:
            analysis_data: 전체 분석 데이터

        Returns:
            진입 전략 딕셔너리
        """
        # 필요한 지표 추출
        technical_data = self._extract_technical_data(analysis_data)
        ml_data = self._extract_ml_data(analysis_data)
        insider_data = self._extract_insider_data(analysis_data)

        # 과열 상태 체크
        overheat_status = self._check_overheat(technical_data)

        # 피보나치 레벨 계산
        fib_levels = self._calculate_fibonacci_levels(technical_data)

        # Kelly 기준 포지션 사이징
        kelly_sizing = self._calculate_kelly_sizing(analysis_data)

        # 진입 전략 결정
        entry_strategy = self._determine_entry_strategy(
            technical_data,
            overheat_status,
            fib_levels,
            kelly_sizing,
            insider_data,
            ml_data
        )

        return entry_strategy

    def _extract_technical_data(self, analysis_data: Dict) -> Dict:
        """기술적 지표 추출"""
        technical = {}

        # Single LLM 분석에서 추출
        if "single_llm_analysis" in analysis_data:
            tools = analysis_data["single_llm_analysis"].get("tools", [])
            for tool in tools:
                if tool.get("tool") == "rsi_divergence_analysis":
                    technical["rsi"] = tool.get("rsi_current", 50)
                    technical["rsi_signal"] = tool.get("signal", "neutral")

                elif tool.get("tool") == "trend_ma_analysis":
                    technical["price_vs_sma"] = tool.get("price_vs_sma", {})
                    technical["ma_alignment"] = tool.get("alignment", "neutral")

                elif tool.get("tool") == "mean_reversion_analysis":
                    technical["z_score"] = tool.get("z_score_20d", 0)
                    technical["reversion_probability"] = tool.get("reversion_probability", 0)

                elif tool.get("tool") == "fibonacci_retracement_analysis":
                    technical["fibonacci"] = tool
                    technical["current_fib_level"] = tool.get("current_level", 0.5)

                elif tool.get("tool") == "support_resistance_analysis":
                    technical["support"] = tool.get("support_level", 0)
                    technical["resistance"] = tool.get("resistance_level", 0)
                    technical["risk_reward"] = tool.get("risk_reward_ratio", 0)

        # 현재 가격
        technical["current_price"] = analysis_data.get("current_price", 0)

        return technical

    def _extract_ml_data(self, analysis_data: Dict) -> Dict:
        """ML 예측 데이터 추출"""
        ml = {}

        if "ml_prediction" in analysis_data:
            ml_pred = analysis_data["ml_prediction"]
            ensemble = ml_pred.get("ensemble", {})
            ml["signal"] = ensemble.get("signal", "neutral")
            ml["up_probability"] = ensemble.get("up_probability", 0.5)

            # 모델별 정확도
            models = ml_pred.get("models", {})
            accuracies = []
            for model_data in models.values():
                if "test_accuracy" in model_data:
                    accuracies.append(model_data["test_accuracy"])

            ml["avg_accuracy"] = sum(accuracies) / len(accuracies) if accuracies else 0.5

        return ml

    def _extract_insider_data(self, analysis_data: Dict) -> Dict:
        """내부자 거래 데이터 추출"""
        insider = {"signal": "neutral", "score": 0}

        # Multi-agent 분석에서 추출
        if "multi_agent" in analysis_data:
            agents = analysis_data["multi_agent"].get("agent_results", [])
            for agent in agents:
                if agent.get("agent") == "Event Analyst":
                    # Evidence 확인
                    reasoning = agent.get("reasoning", "")
                    if "내부자 매도" in reasoning:
                        insider["signal"] = "sell"
                        insider["score"] = -4
                    elif "내부자 매수" in reasoning:
                        insider["signal"] = "buy"
                        insider["score"] = 4

        return insider

    def _check_overheat(self, technical_data: Dict) -> Dict:
        """과열 상태 체크"""
        overheat = {
            "is_overheated": False,
            "is_oversold": False,
            "heat_level": "normal",
            "indicators": []
        }

        # RSI 체크
        rsi = technical_data.get("rsi", 50)
        if rsi > self.RSI_OVERBOUGHT:
            overheat["is_overheated"] = True
            overheat["indicators"].append(f"RSI {rsi:.1f} (과매수)")
        elif rsi < self.RSI_OVERSOLD:
            overheat["is_oversold"] = True
            overheat["indicators"].append(f"RSI {rsi:.1f} (과매도)")

        # Z-Score 체크
        z_score = technical_data.get("z_score", 0)
        if z_score > 1.5:
            overheat["is_overheated"] = True
            overheat["indicators"].append(f"Z-score {z_score:.2f} (1.5σ 상단)")
        elif z_score < -1.5:
            overheat["is_oversold"] = True
            overheat["indicators"].append(f"Z-score {z_score:.2f} (1.5σ 하단)")

        # Heat level 결정
        if overheat["is_overheated"]:
            if rsi > 75 and z_score > 2:
                overheat["heat_level"] = "extreme_hot"
            else:
                overheat["heat_level"] = "hot"
        elif overheat["is_oversold"]:
            if rsi < 25 and z_score < -2:
                overheat["heat_level"] = "extreme_cold"
            else:
                overheat["heat_level"] = "cold"

        return overheat

    def _calculate_fibonacci_levels(self, technical_data: Dict) -> Dict:
        """피보나치 레벨 계산"""
        fib = technical_data.get("fibonacci", {})

        if not fib:
            # 기본값 반환
            return {
                "swing_high": 0,
                "swing_low": 0,
                "levels": {},
                "current_level": 0.5
            }

        return {
            "swing_high": fib.get("swing_high", 0),
            "swing_low": fib.get("swing_low", 0),
            "levels": fib.get("fib_levels", {}),
            "current_level": fib.get("current_level", 0.5),
            "near_support": fib.get("near_support_level", None)
        }

    def _calculate_kelly_sizing(self, analysis_data: Dict) -> Dict:
        """Kelly 기준 포지션 사이징"""

        # Kelly 기본값
        kelly = {
            "kelly_fraction": 0.04,  # 기본 4%
            "recommended_size": 0.02,  # Kelly Half (2%)
            "max_position": self.KELLY_MAX_POSITION,
            "confidence_adjusted": 0.02
        }

        # Risk/Position Sizing 도구에서 Kelly 추출
        if "single_llm_analysis" in analysis_data:
            tools = analysis_data["single_llm_analysis"].get("tools", [])
            for tool in tools:
                if tool.get("tool") == "kelly_criterion_analysis":
                    kelly["kelly_fraction"] = tool.get("kelly_percentage", 4) / 100
                    kelly["win_probability"] = tool.get("win_probability", 0.5)
                    kelly["avg_win"] = tool.get("avg_win", 0)
                    kelly["avg_loss"] = tool.get("avg_loss", 0)

        # 최종 신뢰도로 조정
        confidence = analysis_data.get("multi_agent", {}).get("final_decision", {}).get("final_confidence", 5) / 10
        kelly["confidence_adjusted"] = kelly["kelly_fraction"] * confidence

        # Kelly Half 적용 (보수적)
        kelly["recommended_size"] = min(kelly["confidence_adjusted"] / 2, self.KELLY_HALF_POSITION)

        return kelly

    def _determine_entry_strategy(self, technical_data: Dict,
                                 overheat_status: Dict,
                                 fib_levels: Dict,
                                 kelly_sizing: Dict,
                                 insider_data: Dict,
                                 ml_data: Dict) -> Dict:
        """진입 전략 결정"""

        current_price = technical_data.get("current_price", 0)
        support = technical_data.get("support", 0)
        resistance = technical_data.get("resistance", 0)

        # 기본 전략
        strategy = {
            "recommendation": "WAIT",  # BUY_NOW, BUY_ON_DIP, WAIT, AVOID
            "entry_type": "none",  # immediate, scaled, conditional, none
            "position_size": kelly_sizing["recommended_size"],
            "entry_points": [],
            "stop_loss": 0,
            "take_profit": [],
            "reasoning": [],
            "risk_warnings": []
        }

        # 1. 내부자 대규모 매도 시 회피
        if insider_data["score"] <= -4:
            strategy["recommendation"] = "AVOID"
            strategy["reasoning"].append("내부자 대규모 매도 신호 - 진입 회피")
            strategy["risk_warnings"].append("CEO/임원진 집중 매각 관측")
            return strategy

        # 2. 극단적 과열 시 대기
        if overheat_status["heat_level"] == "extreme_hot":
            strategy["recommendation"] = "WAIT"
            strategy["reasoning"].append(f"극단적 과열 상태 - {', '.join(overheat_status['indicators'])}")
            strategy["risk_warnings"].append("단기 급락 위험 높음")

            # 조정 대기 진입점 설정
            fib_382 = fib_levels["levels"].get("0.382", 0)
            fib_500 = fib_levels["levels"].get("0.500", 0)

            if fib_382 > 0:
                strategy["entry_points"] = [
                    {"level": "피보나치 0.382", "price": fib_382, "size": 0.3},
                    {"level": "피보나치 0.500", "price": fib_500, "size": 0.4},
                    {"level": "20일 이평선", "price": support, "size": 0.3}
                ]
                strategy["entry_type"] = "conditional"
                strategy["reasoning"].append("조정 시 분할 진입 권고")

            return strategy

        # 3. 과매도 + 내부자 매수 시 즉시 진입
        if overheat_status["is_oversold"] and insider_data["score"] >= 2:
            strategy["recommendation"] = "BUY_NOW"
            strategy["entry_type"] = "immediate"
            strategy["position_size"] = min(kelly_sizing["recommended_size"] * 1.5,
                                          self.KELLY_HALF_POSITION)
            strategy["reasoning"].append("과매도 + 내부자 매수 신호")

            # 손절/익절 설정
            strategy["stop_loss"] = current_price * 0.95
            strategy["take_profit"] = [
                {"level": "1차 목표", "price": resistance, "size": 0.3},
                {"level": "2차 목표", "price": current_price * 1.10, "size": 0.4},
                {"level": "3차 목표", "price": current_price * 1.15, "size": 0.3}
            ]

            return strategy

        # 4. 정상 구간에서 신호 기반 판단
        final_signal = technical_data.get("ma_alignment", "neutral")

        if final_signal == "bullish" and not overheat_status["is_overheated"]:
            strategy["recommendation"] = "BUY_ON_DIP"
            strategy["entry_type"] = "scaled"
            strategy["reasoning"].append("상승 추세 - 조정 시 분할 매수")

            # 분할 진입점
            strategy["entry_points"] = [
                {"level": "현재가 -2%", "price": current_price * 0.98, "size": 0.3},
                {"level": "피보나치 0.382", "price": fib_levels["levels"].get("0.382", support),
                 "size": 0.4},
                {"level": "주요 지지선", "price": support, "size": 0.3}
            ]

            strategy["stop_loss"] = support * 0.97
            strategy["take_profit"] = [{"level": "목표가", "price": resistance, "size": 1.0}]

        elif final_signal == "bearish":
            strategy["recommendation"] = "AVOID"
            strategy["reasoning"].append("하락 추세 - 진입 회피")
            strategy["risk_warnings"].append("추세 하락 전환")

        else:
            strategy["recommendation"] = "WAIT"
            strategy["reasoning"].append("방향성 불명확 - 관망")

        return strategy

    def generate_entry_report(self, strategy: Dict[str, Any]) -> str:
        """진입 전략 리포트 생성"""
        report = []

        report.append(f"### 진입 전략: {strategy['recommendation']}")
        report.append("")

        # 권고사항
        if strategy["recommendation"] == "BUY_NOW":
            report.append("**즉시 진입 권고**")
        elif strategy["recommendation"] == "BUY_ON_DIP":
            report.append("**조정 시 분할 진입 권고**")
        elif strategy["recommendation"] == "WAIT":
            report.append("**대기 권고**")
        elif strategy["recommendation"] == "AVOID":
            report.append("**진입 회피 권고**")

        # 포지션 크기
        report.append(f"- 권장 포지션: {strategy['position_size']*100:.1f}%")

        # 진입점
        if strategy["entry_points"]:
            report.append("\n**진입 포인트:**")
            for entry in strategy["entry_points"]:
                report.append(f"- {entry['level']}: ${entry['price']:.2f} (비중 {entry['size']*100:.0f}%)")

        # 손절/익절
        if strategy["stop_loss"] > 0:
            report.append(f"\n**손절가:** ${strategy['stop_loss']:.2f}")

        if strategy["take_profit"]:
            report.append("\n**목표가:**")
            for tp in strategy["take_profit"]:
                report.append(f"- {tp['level']}: ${tp['price']:.2f}")

        # 근거
        if strategy["reasoning"]:
            report.append("\n**판단 근거:**")
            for reason in strategy["reasoning"]:
                report.append(f"- {reason}")

        # 리스크 경고
        if strategy["risk_warnings"]:
            report.append("\n**⚠️ 리스크 경고:**")
            for warning in strategy["risk_warnings"]:
                report.append(f"- {warning}")

        return "\n".join(report)


# 테스트
if __name__ == "__main__":
    strategy_calculator = ConditionalEntryStrategy()

    # 테스트 데이터
    test_data = {
        "current_price": 54.32,
        "single_llm_analysis": {
            "tools": [
                {"tool": "rsi_divergence_analysis", "rsi_current": 73.5, "signal": "sell"},
                {"tool": "mean_reversion_analysis", "z_score_20d": 1.61,
                 "reversion_probability": 0.107},
                {"tool": "support_resistance_analysis", "support_level": 51.15,
                 "resistance_level": 56.55, "risk_reward_ratio": 0.7},
                {"tool": "fibonacci_retracement_analysis",
                 "fib_levels": {"0.382": 52.98, "0.500": 51.67, "0.618": 50.36},
                 "current_level": 0.236}
            ]
        },
        "multi_agent": {
            "final_decision": {
                "final_signal": "neutral",
                "final_confidence": 5.0
            }
        }
    }

    result = strategy_calculator.calculate_entry_conditions(test_data)
    report = strategy_calculator.generate_entry_report(result)

    print(report)