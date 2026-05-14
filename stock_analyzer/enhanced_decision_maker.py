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

    def __init__(self, llm_provider: str = None):
        import os
        self.name = "Enhanced Decision Maker"
        if llm_provider is None:
            llm_provider = os.getenv('DEFAULT_LLM_PROVIDER', 'ollama')
        self.llm_provider = llm_provider
        self.previous_confidence = None  # 이전 신뢰도 추적
        self.confidence_history = []  # 신뢰도 이력 추적 (최대 5개)

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

        # 1. 티커 검증 및 시장 정보 가져오기
        from ticker_validator import validate_ticker, get_market_info

        is_valid, fixed_ticker, error_msg = validate_ticker(ticker)
        if not is_valid and fixed_ticker:
            ticker = fixed_ticker  # 자동 수정된 티커 사용

        market_info = get_market_info(ticker)
        currency = market_info["currency"]
        benchmark = market_info["benchmark"]

        # 2. 에이전트 의견 및 점수 집계 (신호 정규화 적용)
        signal_counts = {"buy": 0, "sell": 0, "neutral": 0}
        confidence_sum = 0.0
        valid_agents = 0
        failed_agents = []  # 실패한 에이전트 추적

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
                failed_agents.append(result.agent_name)
                continue

            # 신호 정규화
            normalized_signal = normalize_signal(result.signal)
            signal_counts[normalized_signal] += 1
            confidence_sum += result.confidence

            # [중요 수정] confidence 0.0인 경우도 실패로 간주
            if result.confidence > 0:
                valid_agents += 1
            else:
                failed_agents.append(f"{result.agent_name} (0.0 confidence)")

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

        # [중요] 에이전트 전원 장애 체크
        if valid_agents == 0:
            # 모든 에이전트가 실패한 경우 - 분석 무효화
            return {
                "final_signal": "neutral",
                "final_confidence": 0.0,
                "consensus": f"0명 매수, 0명 매도, {len(agent_results)}명 중립 (전원 장애)",
                "conflicts": "전체 에이전트 장애",
                "reasoning": f"모든 에이전트 분석 실패: {', '.join(failed_agents[:3])}... 분석 신뢰 불가",
                "key_risks": ["전체 LLM 서비스 장애", "분석 완전 무효", "시스템 점검 필요"],
                "agent_count": len(agent_results),
                "valid_agent_count": 0,
                "signal_distribution": signal_counts,
                "analyzed_at": datetime.now().isoformat(),
                "currency": currency,
                "market_info": market_info,
                "warnings": ["⚠️ 전체 에이전트 장애로 V2 분석 무효. V1 지표만 참고하세요."],
                "system_failure": True
            }

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

        # 5.4. [Step 6] STRONG_*_CONFIRMATION flag 탐지 → conviction +0.1
        strong_confirmation_bonus = 0.0
        _STRONG_FLAGS = {"STRONG_BULLISH_CONFIRMATION", "STRONG_BEARISH_CONFIRMATION"}
        for result in agent_results:
            for ev in (result.evidence or []):
                flags = ev.get("flags") or ev.get("result", {}).get("flags") or []
                if _STRONG_FLAGS & set(flags):
                    strong_confirmation_bonus += 0.1
                    break  # 에이전트당 최대 1회

        # 5.5. [개선] Beta와 P/E 필수 체크 추가
        fundamental_risks = self._check_fundamental_risks(ticker)

        # 5.6. [Step 7] Regime-aware 가중치 적용
        current_regime = None
        regime_weights = None
        regime_weighted_score = None
        try:
            from regime.detector import detect_market_regime, fetch_market_features
            from regime.models import MacroContext, REGIME_WEIGHTS
            import os
            vix_hint = float(os.getenv("CURRENT_VIX", "20"))
            ctx = MacroContext(vix=vix_hint)
            mkt = fetch_market_features()
            current_regime = detect_market_regime(ctx, mkt)
            regime_weights = REGIME_WEIGHTS[current_regime]
        except Exception:
            pass

        # 5.7. [Step 8] 4-그룹 분할 + confidence-weighted vote
        group_results = {}
        reflect_flags: List[str] = []
        try:
            from agent_groups import aggregate_by_group, reflect, group_weighted_score
            group_results = aggregate_by_group(agent_results)
            # regime-aware 그룹 합산
            regime_weighted_score = group_weighted_score(
                group_results,
                regime_weights,
            )
        except Exception:
            pass

        # 5.8. [Step 12] Variance-aware aggregation
        signal_std: float | None = None
        agreement_level: str | None = None
        variance_penalty = 0.0
        try:
            if group_results:
                from agent_groups import aggregate_with_variance
                vagg = aggregate_with_variance(group_results, regime_weights)
                signal_std = vagg["std"]
                agreement_level = vagg["agreement"]
                if vagg["agreement"] == "low":
                    variance_penalty = 0.3   # conviction ×0.7
        except Exception:
            pass

        # 6. 최종 판단
        final_decision = self._make_final_decision(
            signal_counts,
            signal_strength,
            volatility_check,
            tech_analysis,
            quant_analysis,
            currency,
            fundamental_risks
        )

        # reflect sanity check
        try:
            if group_results:
                from agent_groups import reflect
                reflect_flags = reflect(group_results, final_decision["signal"])
        except Exception:
            pass

        # 7. 경고 메시지 수집
        warnings = []
        if not is_valid and fixed_ticker:
            warnings.append(f"티커 자동 수정: {error_msg}")
        if not is_valid and not fixed_ticker:
            warnings.append(f"티커 검증 실패: {error_msg}")

        # Fundamental 경고 추가
        if fundamental_risks['warnings']:
            warnings.extend(fundamental_risks['warnings'])

        # reflect 플래그 경고 추가
        if reflect_flags:
            warnings.extend(reflect_flags)

        # HIGH_VARIANCE 경고 추가
        if agreement_level == "low":
            warnings.append("HIGH_VARIANCE_WAIT")

        # 8. 결과 구성 (STRONG_*_CONFIRMATION 보너스 + variance 패널티 반영)
        raw_confidence = final_decision["confidence"] + strong_confirmation_bonus
        final_confidence = min(10.0, raw_confidence * (1.0 - variance_penalty))
        result = {
            "final_signal": final_decision["signal"],
            "final_confidence": final_confidence,
            "consensus": f"{signal_counts['buy']}명 매수, {signal_counts['sell']}명 매도, {signal_counts['neutral']}명 중립",
            "conflicts": final_decision["conflicts"],
            "reasoning": final_decision["reasoning"],
            "key_risks": final_decision["risks"],
            "agent_count": len(agent_results),
            "signal_distribution": signal_counts,
            "analyzed_at": datetime.now().isoformat(),
            "currency": currency,
            "market_info": market_info,
            "signal_strength": signal_strength,
            "volatility_status": volatility_check,
            "technical_analysis": tech_analysis,
            "quant_analysis": quant_analysis,
            "fundamental_risks": fundamental_risks,
            "warnings": warnings if warnings else None,
            "regime": current_regime.value if current_regime else None,
            "regime_weighted_score": regime_weighted_score,
            "group_results": {k.value: v.to_dict() for k, v in group_results.items()},
            "reflect_flags": reflect_flags,
            "signal_std": signal_std,
            "agreement_level": agreement_level,
        }

        return result

    def _check_fundamental_risks(self, ticker: str) -> Dict:
        """[개선] Beta와 P/E 필수 체크"""
        import yfinance as yf

        warnings = []
        critical_risks = []

        # 입력 검증: 빈/비문자열 티커는 즉시 단락
        if not ticker or not isinstance(ticker, str) or not ticker.strip():
            return {
                "beta": None,
                "pe_trailing": None,
                "pe_forward": None,
                "week52_decline": None,
                "warnings": ["Invalid ticker for fundamental check"],
                "critical_risks": []
            }

        try:
            stock = yf.Ticker(ticker.strip())
            info = stock.info or {}

            # info가 비어있거나 기본값만 있는 경우: 데이터 없음 명시
            if not info or len(info) <= 1:
                return {
                    "beta": None,
                    "pe_trailing": None,
                    "pe_forward": None,
                    "week52_decline": None,
                    "warnings": [f"Fundamental 데이터 없음: {ticker}"],
                    "critical_risks": []
                }

            # 섹터별 임계값 조정 (성장주 부당 거부 방지)
            sector = (info.get('sector') or '').lower()
            growth_sectors = {'technology', 'communication services', 'consumer cyclical', 'healthcare'}
            is_growth = sector in growth_sectors

            # Beta 임계값: 성장주는 1.5~2.5가 정상, 일반 섹터는 1.0~1.5
            beta_critical = 3.0 if is_growth else 2.0
            beta_warning = 2.0 if is_growth else 1.5

            beta = info.get('beta')
            if beta is not None:
                if beta > beta_critical:
                    critical_risks.append(
                        f"Beta {beta:.2f} > {beta_critical:.1f}: 극단적 변동성 ({sector or '?'} 섹터 기준)"
                    )
                elif beta > beta_warning:
                    warnings.append(f"Beta {beta:.2f}: 고변동성 ({sector or '?'} 섹터)")
                elif beta < 0:
                    warnings.append(f"Beta {beta:.2f}: 역상관 종목")

            # P/E 임계값: 성장주는 P/E 100+ 정상, 일반은 50+ 경고
            pe_critical = 300 if is_growth else 200
            pe_warning_high = 150 if is_growth else 100
            pe_warning_mid = 80 if is_growth else 50

            pe_trailing = info.get('trailingPE')
            pe_forward = info.get('forwardPE')

            if pe_trailing is not None:
                # 적자 체크가 먼저 (P/E < 0이 P/E > pe_critical 분기를 통과하면 안 됨)
                if pe_trailing < 0:
                    critical_risks.append(f"P/E {pe_trailing:.1f}: 적자 기업")
                elif pe_trailing > pe_critical:
                    critical_risks.append(
                        f"P/E {pe_trailing:.1f} > {pe_critical}: 극도 과대평가 ({sector or '?'} 기준)"
                    )
                elif pe_trailing > pe_warning_high:
                    warnings.append(f"P/E {pe_trailing:.1f}: 심각한 과대평가")
                elif pe_trailing > pe_warning_mid:
                    warnings.append(f"P/E {pe_trailing:.1f}: 과대평가 가능성")
                # Forward PE 와 비교: trailing↑ but forward↓ 면 실적 개선 기대
                if pe_forward is not None and pe_trailing > pe_warning_mid and pe_forward < pe_warning_mid:
                    warnings.append(f"단, Forward P/E {pe_forward:.1f} → 실적 개선 전망")

            # 52주 하락률 체크
            week52_high = info.get('fiftyTwoWeekHigh')
            current_price = info.get('currentPrice', info.get('regularMarketPrice'))

            if week52_high and current_price:
                decline_pct = (week52_high - current_price) / week52_high * 100
                if decline_pct > 50:
                    warnings.append(f"52주 고점 대비 {decline_pct:.1f}% 하락")
                elif decline_pct > 30:
                    warnings.append(f"52주 고점 대비 {decline_pct:.1f}% 하락")

            # 실적 발표일 체크 (시장 시간대 기준)
            earnings_date = info.get('earningsTimestamp')
            if earnings_date:
                from datetime import datetime, timezone
                # earningsTimestamp는 UTC unix timestamp
                earnings_dt = datetime.fromtimestamp(earnings_date, tz=timezone.utc)
                # 시장 기준 현재 시각: 한국 종목은 KST, 그 외는 ET
                tz_name = "Asia/Seoul" if (ticker.upper().endswith(".KS") or ticker.upper().endswith(".KQ")) else "America/New_York"
                try:
                    from zoneinfo import ZoneInfo
                    market_tz = ZoneInfo(tz_name)
                except Exception:
                    market_tz = timezone.utc
                now_market = datetime.now(tz=market_tz)
                days_to_earnings = (earnings_dt.astimezone(market_tz) - now_market).days

                if 0 <= days_to_earnings <= 7:
                    warnings.append(f"실적 발표 {days_to_earnings}일 전: 변동성 급증 예상")
                elif -7 <= days_to_earnings < 0:
                    warnings.append(f"실적 발표 {abs(days_to_earnings)}일 경과")

            return {
                "beta": beta,
                "pe_trailing": pe_trailing,
                "pe_forward": pe_forward,
                "week52_decline": decline_pct if 'decline_pct' in locals() else None,
                "warnings": warnings,
                "critical_risks": critical_risks
            }

        except Exception:
            return {
                "beta": None,
                "pe_trailing": None,
                "pe_forward": None,
                "week52_decline": None,
                "warnings": ["Fundamental 데이터 수집 실패"],
                "critical_risks": []
            }

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

        # ML 가중치 조정 (정확도 기반 - 50% 미만은 무시)
        ml_weight = 1.0  # 기본 가중치
        ml_note = None
        if ml_accuracies:
            avg_accuracy = sum(ml_accuracies) / len(ml_accuracies)
            if avg_accuracy < 0.50:  # 50% 미만 정확도
                ml_weight = 0.0  # 신호 완전 무시
                ml_note = f"ML 정확도 {avg_accuracy:.1%} < 50%: 신호 제외"
            elif avg_accuracy < 0.55:  # 50-55%
                ml_weight = 0.3  # 약한 참고
                ml_note = f"ML 정확도 {avg_accuracy:.1%}: 약한 참고"
            elif avg_accuracy < 0.60:  # 55-60%
                ml_weight = 0.7  # 보통 가중치
            else:  # 60% 이상
                ml_weight = 1.0  # 정상 가중치

            # 전 모델 동일 방향 시 보너스 (정확도 50% 이상인 경우만)
            if avg_accuracy >= 0.50 and len(ml_scores) >= 4:
                # 모든 ML 점수가 같은 방향인지 체크
                all_buy = all(score > 5 for score in ml_scores)
                all_sell = all(score < 5 for score in ml_scores)
                if all_buy or all_sell:
                    ml_weight += 0.3  # 방향 일치 보너스

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

        # 신호 강도 분류 (개선된 기준)
        # 기술 6개 + 퀀트 6개 = 12개 도구, 각 ±10점 범위
        # 이론적 최대: ±120점 (모든 도구가 같은 방향)
        # 실제로는 ±30점 이상이면 매우 강한 신호
        strength_level = "weak"  # 약함
        abs_score = abs(total_score)
        if abs_score > 30:
            strength_level = "very_strong"  # 매우 강함
        elif abs_score > 20:
            strength_level = "strong"  # 강함
        elif abs_score > 10:
            strength_level = "moderate"  # 보통
        elif abs_score > 5:
            strength_level = "weak"  # 약함
        else:
            strength_level = "very_weak"  # 매우 약함

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
                "avg_accuracy": sum(ml_accuracies) / len(ml_accuracies) if ml_accuracies else 0,
                "note": ml_note
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
                            volatility_check, tech_analysis, quant_analysis, currency,
                            fundamental_risks=None) -> Dict:
        """최종 판단 (내부자 거래 특별 처리 포함)"""

        # 1. 점수 기반 판단
        total_score = signal_strength["total_score"]
        strength_level = signal_strength["strength_level"]
        insider_signal = signal_strength.get("insider", {}).get("signal")
        insider_score = signal_strength.get("insider", {}).get("score", 0)

        # [중요] 에이전트 의견 검증
        # 0명 매수인데 buy 신호 방지
        if signal_counts["buy"] == 0 and signal_counts["sell"] == 0:
            # 모든 에이전트가 neutral인 경우
            return {
                "signal": "neutral",
                "confidence": 2.0,
                "conflicts": "전체 에이전트 중립",
                "reasoning": f"모든 에이전트가 중립 의견 ({signal_counts['neutral']}명). 지표 점수({total_score:+.1f})는 참고용",
                "risks": ["방향성 부재", "신호 약함", "추가 정보 필요"]
            }

        # 2. 내부자 거래 강한 신호 시 우선 처리
        if strength_level in ["strong_sell_signal", "strong_buy_signal"]:
            # 단, 에이전트가 반대 의견인 경우 체크
            if strength_level == "strong_sell_signal" and signal_counts["buy"] > signal_counts["sell"]:
                # 내부자는 매도인데 에이전트는 매수가 더 많음 - 충돌
                pass  # 계속 진행하여 일반 로직 적용
            elif strength_level == "strong_buy_signal" and signal_counts["sell"] > signal_counts["buy"]:
                # 내부자는 매수인데 에이전트는 매도가 더 많음 - 충돌
                pass  # 계속 진행하여 일반 로직 적용
            else:
                # 충돌 없으면 내부자 신호 우선
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

        # 3. 기본 신호 결정 (에이전트 의견 반영)
        # 에이전트 의견이 있는 경우 우선 고려
        if signal_counts["buy"] > 0 or signal_counts["sell"] > 0:
            # 다수결 기반
            if signal_counts["buy"] > signal_counts["sell"] + signal_counts["neutral"]:
                base_signal = "buy"
            elif signal_counts["sell"] > signal_counts["buy"] + signal_counts["neutral"]:
                base_signal = "sell"
            elif total_score > 5 and signal_counts["buy"] > signal_counts["sell"]:
                base_signal = "buy"
            elif total_score < -5 and signal_counts["sell"] > signal_counts["buy"]:
                base_signal = "sell"
            else:
                base_signal = "neutral"
        else:
            # 모든 에이전트가 neutral인 경우 점수 기반 (약하게)
            if total_score > 10:  # 기준 상향 (5 → 10)
                base_signal = "buy"
            elif total_score < -10:  # 기준 하향 (-5 → -10)
                base_signal = "sell"
            else:
                base_signal = "neutral"

        # [추가 검증] 0명 매수인데 buy 신호 최종 차단
        if signal_counts["buy"] == 0 and base_signal == "buy":
            base_signal = "neutral"
            strength_level = "very_weak"

        # 4. 고변동성 상황에서 신호 강도 체크
        if volatility_check["is_high"]:
            if strength_level in ["weak", "very_weak"]:
                # 고변동성 + 약한 신호 = HOLD
                return {
                    "signal": "neutral",
                    "confidence": 3.0,
                    "conflicts": "고변동성 상황에서 신호가 약함",
                    "reasoning": f"현재 고변동성 상황이며 신호 강도가 {strength_level} (총점: {total_score:+.1f}). 관망 권고.",
                    "risks": ["고변동성 리스크", "약한 신호 강도", "방향성 불명확"]
                }

        # 4. 기술적 vs 퀀트 충돌 체크
        tech_dir = signal_strength["technical"]["direction"]
        quant_dir = signal_strength["quantitative"]["direction"]

        conflicts = []
        if tech_dir != quant_dir and tech_dir != "neutral" and quant_dir != "neutral":
            conflicts.append(f"기술적({tech_dir}) vs 퀀트({quant_dir}) 충돌")

        # 5. 신뢰도 계산 (strength_level 기반으로 개선)
        # 신호 강도에 따른 신뢰도 범위 설정
        if strength_level == "very_strong":
            raw_confidence = min(10, max(8.0, abs(total_score) / 4))
        elif strength_level == "strong":
            raw_confidence = min(8.0, max(6.0, abs(total_score) / 4))
        elif strength_level == "moderate":
            raw_confidence = min(6.5, max(4.0, abs(total_score) / 4))
        elif strength_level == "weak":
            raw_confidence = min(4.0, max(2.0, abs(total_score) / 5))
        else:  # very_weak
            raw_confidence = min(2.0, abs(total_score) / 5)

        # Variance 기반 boundary 적용
        confidence = self._apply_confidence_smoothing(raw_confidence)

        # 5.5. [개선] Critical Fundamental Risks 체크
        if fundamental_risks and fundamental_risks.get('critical_risks'):
            # Critical risk가 있으면 신호 약화
            for risk in fundamental_risks['critical_risks']:
                if 'Beta' in risk and base_signal == 'buy':
                    # 고베타 종목 매수 시 신뢰도 하락
                    confidence = max(1.0, confidence - 2.0)
                elif 'P/E' in risk and '200' in risk:
                    # P/E 200 초과 시 매수 신호 약화
                    if base_signal == 'buy':
                        base_signal = 'neutral'
                        confidence = min(3.0, confidence)
                elif 'P/E' in risk and '적자' in risk:
                    # 적자 기업은 특별 경고
                    if base_signal == 'buy':
                        confidence = max(1.0, confidence - 3.0)

        # 6. 리스크 요인
        risks = []
        if volatility_check["is_high"]:
            risks.append("고변동성 구간")
        if strength_level in ["weak", "very_weak"]:
            risks.append(f"{strength_level.replace('_', ' ')} 신호 강도")
        if conflicts:
            risks.extend(conflicts)

        # ML 모델 정확도가 낮은 경우
        ml_note = signal_strength.get("ml_adjusted", {}).get("note")
        if ml_note and "신호 제외" in ml_note:
            risks.append(ml_note)

        # Fundamental risks 추가
        if fundamental_risks:
            if fundamental_risks.get('critical_risks'):
                risks.extend(fundamental_risks['critical_risks'])
            # 일반 경고는 warnings에만 포함됨

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

    def _apply_confidence_smoothing(self, raw_confidence: float) -> float:
        """
        신뢰도 smoothing 적용 - 급격한 변동 방지

        원칙:
        1. 이전 신뢰도와 현재 신뢰도 차이가 5 이상이면 완화
        2. 최근 5개 신뢰도 이력의 variance가 크면 조정
        3. 최소 변동 단위를 0.5로 설정
        """
        import numpy as np

        smoothed_confidence = raw_confidence

        # 이력 관리 (최대 5개)
        self.confidence_history.append(raw_confidence)
        if len(self.confidence_history) > 5:
            self.confidence_history.pop(0)

        # 이전 신뢰도가 있는 경우
        if self.previous_confidence is not None:
            diff = abs(raw_confidence - self.previous_confidence)

            # 급격한 변동 감지 (5 이상)
            if diff > 5.0:
                # 이전 값과의 가중 평균 (새 값 60%, 이전 값 40%)
                smoothed_confidence = raw_confidence * 0.6 + self.previous_confidence * 0.4

                # 최대 변동폭 제한 (3.0)
                max_change = 3.0
                if raw_confidence > self.previous_confidence:
                    smoothed_confidence = min(smoothed_confidence, self.previous_confidence + max_change)
                else:
                    smoothed_confidence = max(smoothed_confidence, self.previous_confidence - max_change)

        # 이력이 충분한 경우 variance 체크
        if len(self.confidence_history) >= 3:
            variance = np.var(self.confidence_history)

            # 높은 variance (>4.0) 시 이동평균 적용
            if variance > 4.0:
                moving_avg = np.mean(self.confidence_history[-3:])
                # 현재 값 50%, 이동평균 50%
                smoothed_confidence = smoothed_confidence * 0.5 + moving_avg * 0.5

        # 최소 변동 단위 0.5 적용
        smoothed_confidence = round(smoothed_confidence * 2) / 2

        # 범위 제한 (1~10)
        smoothed_confidence = max(1.0, min(10.0, smoothed_confidence))

        # 이전 신뢰도 업데이트
        self.previous_confidence = smoothed_confidence

        return smoothed_confidence