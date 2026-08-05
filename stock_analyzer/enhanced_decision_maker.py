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
from typing import List, Dict, Any, Optional
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

    def _decision_horizon_days(self) -> int:
        try:
            from decision_context import default_horizon_days
            return default_horizon_days()
        except Exception:
            return 7

    def _build_decision_context(
        self,
        signal: str,
        confidence: float,
        horizon_days: int,
        reasoning: str,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        try:
            from decision_context import build_decision_context
            return build_decision_context(
                source="multi_agent",
                role="deep_validation",
                signal=signal,
                confidence=confidence,
                horizon_days=horizon_days,
                reasoning=reasoning,
                metadata=metadata or {},
            )
        except Exception:
            return {
                "schema_version": "decision_context.v1",
                "source": "multi_agent",
                "role": "deep_validation",
                "signal": signal,
                "confidence": confidence,
                "horizon_days": horizon_days,
                "reasoning": reasoning,
                "metadata": metadata or {},
            }

    @staticmethod
    def _signed_confidence(signal: str, confidence: float) -> float:
        """Convert normalized signal + 0-10 confidence into signed score."""
        direction = {"buy": 1.0, "sell": -1.0, "neutral": 0.0}.get(signal, 0.0)
        return direction * confidence

    @staticmethod
    def _avg_signed_score(scores: List[float]) -> float:
        return sum(scores) / len(scores) if scores else 0.0

    # 손익비 하한 — 이 아래에서는 방향이 맞아도 기대값이 성립하지 않는다.
    MIN_RISK_REWARD = 0.8

    # 정량 근거가 상쇄돼 0에 가까울 때 정성 판단에 허용하는 최대 기여.
    # 강도 임계(>10 moderate)보다 낮게 둬서, 서술만으로는 '강한 신호'가
    # 만들어지지 않게 한다.
    NARRATIVE_FLOOR = 5.0

    def _min_risk_reward(self, agent_results) -> Optional[float]:
        """에이전트 evidence에서 지지/저항 기준 R/R 최솟값을 뽑는다.

        여러 에이전트가 같은 도구를 돌리면 보수적으로 최솟값을 쓴다.
        """
        values: List[float] = []
        for result in agent_results:
            if getattr(result, "error", None):
                continue
            for ev in (result.evidence or []):
                if ev.get("tool") != "support_resistance_analysis":
                    continue
                rr = (ev.get("result") or {}).get("risk_reward_ratio")
                if isinstance(rr, (int, float)) and rr > 0:
                    values.append(float(rr))
        return min(values) if values else None

    # 강도 사다리 — 낮은 순. 내부자 특수 라벨은 'strong' 티어로 취급한다.
    _STRENGTH_LADDER = ("very_weak", "weak", "moderate", "strong", "very_strong")
    _INSIDER_LEVELS = ("strong_sell_signal", "strong_buy_signal")
    # 이 신뢰도 아래에서는 '강한 신호'라고 표기할 수 없다.
    STRENGTH_CAP_CONFIDENCE = 5.0

    @classmethod
    def cap_strength_by_confidence(cls, strength_level: str, confidence: float) -> str:
        """신뢰도가 낮으면 강도 라벨을 낮춘다.

        strength_level은 abs(total_score)만 보고, confidence는 의견 일치도에서
        따로 나온다. 그래서 "신뢰도 4.55 / 강도 strong"처럼 서로 모순되는 조합이
        그대로 출력됐다 (2026-07-30 감사). 둘 중 어느 쪽을 믿어야 하는지
        사용자가 알 수 없으므로, 낮은 신뢰도에서는 강도를 눌러 표기를 일치시킨다.
        """
        if confidence >= cls.STRENGTH_CAP_CONFIDENCE:
            return strength_level

        cap = "weak"
        if strength_level in cls._INSIDER_LEVELS:
            return cap
        if strength_level not in cls._STRENGTH_LADDER:
            return strength_level
        if cls._STRENGTH_LADDER.index(strength_level) <= cls._STRENGTH_LADDER.index(cap):
            return strength_level
        return cap

    @staticmethod
    def apply_execution_readiness(decision: Dict) -> Dict:
        """진입 계획 부착 후 실행 가능성을 판정한다 (in-place 갱신).

        aggregate() 안에서는 판정할 수 없다 — orchestrator가 aggregate() 반환
        뒤에 entry_plan을 붙이기 때문이다. 여기서 하지 않으면 execution_ready가
        항상 False가 되어 모든 방향성 신호의 신뢰도가 상한에 걸린다.

        진입 계획 생성이 실패했을 때만(손절 미산출 등) 신호를 유지한 채
        실행 불가임을 표시하고 신뢰도 상한을 건다.
        """
        signal = (decision.get("final_signal") or decision.get("signal") or "").lower()
        plan = decision.get("entry_plan") or {}
        ready = bool(
            plan.get("limit_price") is not None and plan.get("stop_loss") is not None
        )
        decision["execution_ready"] = ready

        if signal in ("buy", "sell") and not ready:
            warns = list(decision.get("warnings") or [])
            if "NO_ENTRY_PLAN_NOT_EXECUTABLE" not in warns:
                warns.append("NO_ENTRY_PLAN_NOT_EXECUTABLE")
            decision["warnings"] = warns
            for key in ("final_confidence", "confidence"):
                if isinstance(decision.get(key), (int, float)):
                    decision[key] = min(float(decision[key]), 5.0)
        return decision

    def _apply_risk_reward_gate(self, final_decision: Dict, rr: Optional[float]) -> Dict:
        """R/R 하한 미달이면 매수를 관망으로 강등한다.

        기존에는 `_collect_agent_risks`가 "손익비 불리: R/R 0.20 < 0.8" 문자열만
        만들고 신호를 막지 못했다 (2026-07-30 감사). R/R 0.20은 잠재 손실이
        잠재 수익의 5배라는 뜻이라, 방향 판단과 무관하게 진입 부적격이다.
        """
        if rr is None or rr >= self.MIN_RISK_REWARD:
            return final_decision
        if (final_decision.get("signal") or "").lower() != "buy":
            return final_decision

        gated = dict(final_decision)
        gated["signal"] = "neutral"
        gated["confidence"] = min(float(gated.get("confidence", 0) or 0), 3.0)
        gated["rr_downgraded"] = True
        msg = f"손익비 하한 미달(R/R {rr:.2f} < {self.MIN_RISK_REWARD}) vs 매수 신호"
        prev = gated.get("conflicts")
        gated["conflicts"] = f"{prev}, {msg}" if prev and prev != "없음" else msg
        gated["reasoning"] = (
            f"{gated.get('reasoning', '')} / R/R {rr:.2f}로 진입 부적격 → 관망 전환"
        ).strip()
        return gated

    def _apply_reflect_guard(self, final_decision: Dict, reflect_flags: List[str]) -> Dict:
        """
        그룹 다수가 최종 신호와 정면 충돌하면 경고만 하지 않고 관망으로 강등한다.
        """
        signal = (final_decision.get("signal") or "neutral").lower()
        severe = (
            ("REFLECT_INCONSISTENT_3_SELL_VS_FINAL_BUY" in reflect_flags and signal == "buy")
            or ("REFLECT_INCONSISTENT_3_BUY_VS_FINAL_SELL" in reflect_flags and signal == "sell")
        )
        if not severe:
            return final_decision

        guarded = dict(final_decision)
        guarded["signal"] = "neutral"
        guarded["confidence"] = min(float(guarded.get("confidence", 0) or 0), 3.0)
        # 최종 confidence 산출 단계에서 보너스/패널티 적용 후 cap을 재적용하기 위한 표식.
        guarded["reflect_downgraded"] = True
        conflict = guarded.get("conflicts")
        reflect_msg = "그룹 다수 의견과 최종 신호 충돌"
        guarded["conflicts"] = (
            f"{conflict}, {reflect_msg}" if conflict and conflict != "없음" else reflect_msg
        )
        guarded["reasoning"] = (
            f"{guarded.get('reasoning', '')} / 그룹 reflect 검증 실패로 관망 전환"
        ).strip()
        risks = list(guarded.get("risks") or [])
        risks.extend(reflect_flags)
        guarded["risks"] = risks
        return guarded

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
        horizon_days = self._decision_horizon_days()

        # 2. 에이전트 의견 및 점수 집계 (신호 정규화 적용)
        signal_counts = {"buy": 0, "sell": 0, "neutral": 0}
        weighted_votes = {"buy": 0.0, "sell": 0.0, "neutral": 0.0}  # 신뢰도 가중 표
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
        fundamental_scores = []
        macro_scores = []
        insider_signal = None  # 내부자 거래 신호
        insider_score = 0
        tool_agent_verdicts: Dict[str, str] = {}  # Technical/Quant 에이전트 자체 판단

        for result in agent_results:
            if result.error:
                failed_agents.append(result.agent_name)
                continue

            # confidence 0.0은 LLM/데이터 실패의 안전 응답이다. 이를 neutral 표로
            # 집계하면 유효한 buy/sell 의견이 실패 표에 희석된다.
            if result.confidence <= 0:
                failed_agents.append(f"{result.agent_name} (0.0 confidence)")
                continue

            # 신호 정규화
            normalized_signal = normalize_signal(result.signal)
            signal_counts[normalized_signal] += 1
            weighted_votes[normalized_signal] += result.confidence
            confidence_sum += result.confidence
            valid_agents += 1
            signed_confidence = self._signed_confidence(normalized_signal, result.confidence)

            # 에이전트별 점수 분류
            # Technical/Quant는 '도구 점수'로만 집계된다 — 에이전트 자신의
            # 판단은 총점에 들어가지 않으므로, 최종 신호와 반대일 때 드러나도록
            # 별도로 기록한다 (2026-08 감사: Quant sell 6.5가 소리 없이 사라졌다).
            if "Technical" in result.agent_name:
                technical_scores.append(self._extract_scores(result))
                tool_agent_verdicts[result.agent_name] = normalized_signal
            elif "Quant" in result.agent_name:
                quant_scores.append(self._extract_scores(result))
                tool_agent_verdicts[result.agent_name] = normalized_signal
            elif "Risk" in result.agent_name:
                risk_scores.append(signed_confidence)
            elif "ML" in result.agent_name:
                ml_scores.append(signed_confidence)
                # ML 정확도 추출 (evidence에서)
                for ev in result.evidence:
                    ml_result = ev.get("result", {})
                    if "ensemble" in ml_result:
                        # 각 모델의 정확도 수집.
                        # 키 이원화 주의: ml_pipeline_fix(주 경로)는 "accuracy",
                        # 레거시 ml_predictor는 "test_accuracy"를 쓴다. 한쪽만 읽으면
                        # ML 정확도 가중치 규칙이 사문화된다 (2026-07 감사에서 발견).
                        models = ml_result.get("models", {})
                        for model_data in models.values():
                            acc = model_data.get("test_accuracy", model_data.get("accuracy"))
                            if isinstance(acc, (int, float)) and acc > 0:
                                ml_accuracies.append(float(acc))
            elif "Event" in result.agent_name:
                event_scores.append(signed_confidence)
                # 내부자 거래 신호 추출
                for ev in result.evidence:
                    if ev.get("tool") == "insider_trading_analysis":
                        insider_result = ev.get("result", {})
                        insider_signal = normalize_signal(insider_result.get("signal", "neutral"))
                        insider_score = insider_result.get("score", 0)
            elif "Value" in result.agent_name:
                fundamental_scores.append(signed_confidence)
            elif "Geopolitical" in result.agent_name:
                macro_scores.append(signed_confidence)

        # [중요] 에이전트 전원 장애 체크
        if valid_agents == 0:
            # 모든 에이전트가 실패한 경우 - 분석 무효화
            failure_reasoning = f"모든 에이전트 분석 실패: {', '.join(failed_agents[:3])}... 분석 신뢰 불가"
            return {
                "final_signal": "neutral",
                "final_confidence": 0.0,
                "consensus": f"유효 의견 0명 (실패 {len(failed_agents)}명 제외, 전원 장애)",
                "conflicts": "전체 에이전트 장애",
                "reasoning": failure_reasoning,
                "key_risks": ["전체 LLM 서비스 장애", "분석 완전 무효", "시스템 점검 필요"],
                "agent_count": len(agent_results),
                "valid_agent_count": 0,
                "excluded_failed_count": len(failed_agents),
                "signal_distribution": signal_counts,
                "analyzed_at": datetime.now().isoformat(),
                "horizon_days": horizon_days,
                "decision_schema_version": "decision_context.v1",
                "decision_context": self._build_decision_context(
                    "neutral",
                    0.0,
                    horizon_days,
                    failure_reasoning,
                    {
                        "system_failure": True,
                        "excluded_failed_count": len(failed_agents),
                        "signal_distribution": signal_counts,
                    },
                ),
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
            ml_accuracies, insider_signal, insider_score,
            fundamental_scores=fundamental_scores,
            macro_scores=macro_scores,
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
            fundamental_risks,
            weighted_votes=weighted_votes,
        )

        # reflect sanity check
        try:
            if group_results:
                from agent_groups import reflect
                reflect_flags = reflect(group_results, final_decision["signal"])
                if reflect_flags:
                    final_decision = self._apply_reflect_guard(final_decision, reflect_flags)
        except Exception:
            pass

        # 6.5. [리스크 정합] 에이전트가 보고한 리스크를 핵심 리스크에 병합
        # 리스크 요약이 본문(켈리 음수, R/R 열위, 지정학, 밸류 우려)과 모순되지 않도록 한다.
        agent_risks = self._collect_agent_risks(agent_results)
        merged_risks = [r for r in (final_decision.get("risks") or []) if r != "특별한 리스크 없음"]
        for risk in agent_risks:
            if risk not in merged_risks:
                merged_risks.append(risk)
        final_decision["risks"] = merged_risks if merged_risks else ["특별한 리스크 없음"]

        # 6.6. [켈리 게이트] 켈리 비중 음수(통계적 엣지 없음)인데 buy면 신뢰도 상한 적용
        kelly_no_bet = any("켈리" in r and ("음수" in r or "엣지 부족" in r) for r in agent_risks)
        if kelly_no_bet and final_decision["signal"] == "buy":
            final_decision["confidence"] = min(float(final_decision["confidence"]), 3.0)
            kelly_msg = "켈리 기준 베팅 부적합 vs 매수 신호 충돌"
            prev_conflict = final_decision.get("conflicts")
            final_decision["conflicts"] = (
                f"{prev_conflict}, {kelly_msg}" if prev_conflict and prev_conflict != "없음" else kelly_msg
            )

        # 6.7. [R/R 하드 게이트] 손익비 하한 미달이면 매수를 관망으로 강등.
        # 경고 문자열만으로는 신호가 그대로 나가 실행 가능한 것처럼 보인다.
        min_rr = self._min_risk_reward(agent_results)
        rr_blocked = (
            min_rr is not None
            and min_rr < self.MIN_RISK_REWARD
            and final_decision["signal"] == "buy"
        )
        if rr_blocked:
            final_decision = self._apply_risk_reward_gate(final_decision, min_rr)

        # 6.8. [실행 가능성] entry_plan은 orchestrator가 aggregate() 반환 뒤에
        # 붙이므로 여기서는 판정할 수 없다. apply_execution_readiness()를
        # 진입 계획 생성 직후에 호출한다 (multi_agent).

        # 6.9. [도구 에이전트 판단 충돌] Technical/Quant의 자체 판단은 총점에
        # 들어가지 않으므로, 최종 신호와 정면 충돌하면 경고로 드러낸다.
        final_sig = (final_decision.get("signal") or "").lower()
        opposed = [
            name for name, verdict in tool_agent_verdicts.items()
            if verdict in ("buy", "sell") and final_sig in ("buy", "sell")
            and verdict != final_sig
        ]
        if opposed:
            final_decision["confidence"] = min(float(final_decision["confidence"]), 6.0)
            msg = f"{', '.join(sorted(opposed))} 판단이 최종 신호({final_sig})와 반대"
            prev = final_decision.get("conflicts")
            final_decision["conflicts"] = (
                f"{prev}, {msg}" if prev and prev != "없음" else msg
            )

        # 7. 경고 메시지 수집
        warnings = []
        if opposed:
            warnings.append("TOOL_AGENT_VERDICT_CONFLICT")
        if rr_blocked:
            warnings.append(f"RR_BELOW_MIN_{self.MIN_RISK_REWARD}")
        if kelly_no_bet and final_decision["signal"] == "buy":
            warnings.append("KELLY_NEGATIVE_NO_BET")
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
        # reflect 강등 시 보너스가 더해져도 cap(3.0)을 넘지 않도록 최종 재적용.
        if final_decision.get("reflect_downgraded"):
            final_confidence = min(final_confidence, 3.0)
        # R/R 강등도 동일 — 보너스로 cap이 무력화되면 게이트가 사문화된다.
        if final_decision.get("rr_downgraded"):
            final_confidence = min(final_confidence, 3.0)

        # 강도 라벨을 최종 신뢰도와 일치시킨다. 강도는 abs(total_score)만 보고
        # 산출되므로 여기(신뢰도 확정 후)에서만 정합을 맞출 수 있다.
        raw_strength = signal_strength.get("strength_level")
        capped_strength = self.cap_strength_by_confidence(raw_strength, final_confidence)
        if capped_strength != raw_strength:
            signal_strength["strength_level_raw"] = raw_strength
            signal_strength["strength_level"] = capped_strength
            signal_strength["strength_capped_by_confidence"] = True

        decision_context = self._build_decision_context(
            final_decision["signal"],
            final_confidence,
            horizon_days,
            final_decision["reasoning"],
            {
                "signal_distribution": signal_counts,
                "signal_strength_level": signal_strength.get("strength_level"),
                "signal_total_score": signal_strength.get("total_score"),
                "domain_contributions": signal_strength.get("domain_contributions", {}),
                "agreement_level": agreement_level,
                "signal_std": signal_std,
                "valid_agent_count": valid_agents,
                "excluded_failed_count": len(failed_agents),
            },
        )
        result = {
            "final_signal": final_decision["signal"],
            "final_confidence": final_confidence,
            "consensus": f"{signal_counts['buy']}명 매수, {signal_counts['sell']}명 매도, {signal_counts['neutral']}명 중립",
            "conflicts": final_decision["conflicts"],
            "reasoning": final_decision["reasoning"],
            "key_risks": final_decision["risks"],
            "agent_count": len(agent_results),
            "valid_agent_count": valid_agents,
            "excluded_failed_count": len(failed_agents),
            "signal_distribution": signal_counts,
            "analyzed_at": datetime.now().isoformat(),
            "horizon_days": horizon_days,
            "decision_schema_version": decision_context["schema_version"],
            "decision_context": decision_context,
            "currency": currency,
            "market_info": market_info,
            "signal_strength": signal_strength,
            # 실행 가능성 — 소비자(텔레그램/주문 라우터)가 '바로 실행 가능한 신호'와
            # '방향 의견'을 구분할 수 있어야 한다.
            "min_risk_reward": min_rr,
            "tool_agent_verdicts": tool_agent_verdicts,
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

    def _collect_agent_risks(self, agent_results) -> List[str]:
        """에이전트 evidence에서 명시적 리스크를 추출해 핵심 리스크로 승격한다.

        대상: 켈리 음수/no_trade, 지지저항 R/R 열위, 지정학 리스크, 밸류 저퀄리티,
        펀더멘털 데이터 품질 경고.
        """
        risks: List[str] = []

        def add(risk: str) -> None:
            if risk and risk not in risks:
                risks.append(risk)

        for result in agent_results:
            if getattr(result, "error", None):
                continue
            for ev in (result.evidence or []):
                tool = ev.get("tool", "")
                tool_result = ev.get("result", {}) or {}
                if tool == "kelly_criterion_analysis":
                    kelly_full = tool_result.get("kelly_full_pct")
                    if kelly_full is not None and kelly_full <= 0:
                        win_rate = tool_result.get("win_rate") or 0
                        wl_ratio = tool_result.get("win_loss_ratio") or 0
                        add(
                            f"켈리 비중 음수 ({kelly_full:+.1f}%, 승률 {win_rate:.1%}, "
                            f"W/L {wl_ratio:.2f}) → 통계적 엣지 없음, 신규 베팅 부적합"
                        )
                    elif tool_result.get("no_trade_warning"):
                        add(str(tool_result["no_trade_warning"]))
                elif tool == "support_resistance_analysis":
                    rr = tool_result.get("risk_reward_ratio")
                    if rr is not None and 0 < rr < 0.8:
                        add(f"손익비 불리: 지지/저항 기준 R/R {rr:.2f} < 0.8")
                elif tool == "geopolitical_analysis":
                    for risk in (tool_result.get("risks") or [])[:3]:
                        add(f"지정학: {risk}")
                elif tool == "value_investing_analysis":
                    roe = tool_result.get("roe")
                    if roe is not None and 0 <= roe < 0.05:
                        add(f"저ROE {roe:.1%}: 자본 효율 열위")
                    dte = tool_result.get("debt_to_equity")
                    if dte is not None and dte > 150:
                        add(f"높은 부채비율 {dte:.0f}%")
                    for warn in (tool_result.get("data_quality_warnings") or []):
                        add(f"펀더멘털 데이터 품질: {warn}")

        return risks

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
        keywords = ["고변동성", "변동성 증가", "volatility high", "high volatility"]
        negations = ["없", "않", "아니", "not ", "no ", "낮"]

        for result in agent_results:
            reasoning = result.reasoning.lower()

            # 고변동성 키워드 체크 — 같은 문장에 부정어가 있으면 제외
            # ("고변동성 우려는 없음" 같은 문장의 오탐 방지)
            for sentence in reasoning.replace("!", ".").replace("?", ".").split("."):
                if any(k in sentence for k in keywords) and not any(n in sentence for n in negations):
                    volatility_mentions.append(result.agent_name)
                    break

        is_high_volatility = len(volatility_mentions) >= 2  # 2개 이상 에이전트가 언급하면 고변동성

        return {
            "is_high": is_high_volatility,
            "mentioned_by": volatility_mentions
        }

    def _calculate_signal_strength(self, tech_analysis, quant_analysis,
                                  risk_scores, ml_scores, event_scores,
                                  ml_accuracies=None, insider_signal=None,
                                  insider_score=0, fundamental_scores=None,
                                  macro_scores=None) -> Dict:
        """신호 강도 계산 (ML 정확도 가중치 및 내부자 거래 반영)"""
        fundamental_scores = fundamental_scores or []
        macro_scores = macro_scores or []

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

            # NOTE: 과거 '방향 일치 보너스'(ml_weight += 0.3)는 제거됨.
            # ml_scores는 ML 에이전트당 1개(현재 ML Specialist 단일)라서
            # all_buy/all_sell이 항상 참 → 단일 신호에 상시 가산되는 무의미한
            # 보너스가 됐다. 앙상블 '내부 모델별' 방향을 추출할 수 있게 되면
            # 그때 모델 간 합의 보너스로 재도입한다.

        # ML 점수 조정
        ml_contribution = 0
        if ml_scores:
            ml_avg = sum(ml_scores) / len(ml_scores)
            # ml_scores는 signal 방향을 반영한 signed confidence(-10~10)이다.
            ml_contribution = (ml_avg / 2.0) * ml_weight

        # 내부자 거래 신호 강화.
        # 주의: Event 에이전트 confidence(내부자 정보가 이미 반영된 판단)가
        # event_contribution으로 별도 가산되므로 완전 독립 신호가 아니다.
        # 이중 반영을 감안해 과거 2.0배 → 1.5배로 하향 (2026-07 감사).
        insider_contribution = insider_score * 1.5

        # 도구 점수로 직접 반영되지 않던 에이전트 도메인을 별도 contribution으로 반영
        risk_contribution = self._avg_signed_score(risk_scores) * 0.7
        event_contribution = self._avg_signed_score(event_scores) * 0.5
        fundamental_contribution = self._avg_signed_score(fundamental_scores) * 0.7
        macro_contribution = self._avg_signed_score(macro_scores) * 0.5

        # ── 정량 vs 정성 비중 정합 (2026-08 감사) ──────────────────
        # 기술·퀀트는 '도구 점수'로, Risk/Event/Value/Macro는 'LLM 판단
        # (signed confidence)'으로 들어간다. 검증 가능한 쪽이 아니라 검증이
        # 어려운 쪽이 총점을 지배할 수 있었다 — 111770.KS 실측에서 도메인
        # 보정이 총점의 59%였다.
        #
        # 원칙: 정성 판단은 정량 근거를 넘지 못한다. 도구·ML·내부자 합계의
        # 절댓값을 상한으로 쓰고, 정량이 0에 가까울 때만 바닥값을 허용한다
        # (바닥값을 0으로 두면 도구가 상쇄된 종목에서 신호가 전부 사라진다).
        quantitative_contribution = (
            tech_analysis["total_score"]
            + quant_analysis["total_score"]
            + ml_contribution
            + insider_contribution
        )
        narrative_raw = (
            risk_contribution + event_contribution
            + fundamental_contribution + macro_contribution
        )
        narrative_cap = max(abs(quantitative_contribution), self.NARRATIVE_FLOOR)
        narrative_contribution = max(-narrative_cap, min(narrative_cap, narrative_raw))
        narrative_capped = abs(narrative_raw) > narrative_cap

        # 전체 점수 (정량 + 상한이 걸린 정성)
        total_score = quantitative_contribution + narrative_contribution

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
            "domain_contributions": {
                "risk": risk_contribution,
                "event": event_contribution,
                "fundamental": fundamental_contribution,
                "macro": macro_contribution,
            },
            "insider": {
                "signal": insider_signal,
                "score": insider_score,
                "contribution": insider_contribution
            },
            # 정량/정성 내역 — 총점이 무엇으로 만들어졌는지 리포트에서 확인 가능해야
            # 한다. narrative_capped가 True면 정성 판단이 상한에 걸린 것이다.
            "quantitative_contribution": round(quantitative_contribution, 2),
            "narrative_raw": round(narrative_raw, 2),
            "narrative_contribution": round(narrative_contribution, 2),
            "narrative_cap": round(narrative_cap, 2),
            "narrative_capped": narrative_capped,
            "total_score": total_score,
            "strength_level": strength_level
        }

    def _make_final_decision(self, signal_counts, signal_strength,
                            volatility_check, tech_analysis, quant_analysis, currency,
                            fundamental_risks=None, weighted_votes=None) -> Dict:
        """최종 판단 (내부자 거래 특별 처리 포함)"""
        weighted_votes = weighted_votes or {"buy": 0.0, "sell": 0.0, "neutral": 0.0}

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
        minority_note = None
        if signal_counts["buy"] > 0 or signal_counts["sell"] > 0:
            # 다수결 기반
            if signal_counts["buy"] > signal_counts["sell"] + signal_counts["neutral"]:
                base_signal = "buy"
            elif signal_counts["sell"] > signal_counts["buy"] + signal_counts["neutral"]:
                base_signal = "sell"
            # [정합성] 점수 보조 경로: 소수(1명) 의견이 최종 신호를 결정하지 못하도록
            # 최소 2명 지지 + 신뢰도 가중 우세를 함께 요구한다.
            elif (
                total_score > 5
                and signal_counts["buy"] >= 2
                and signal_counts["buy"] > signal_counts["sell"]
                and weighted_votes["buy"] > weighted_votes["sell"]
            ):
                base_signal = "buy"
            elif (
                total_score < -5
                and signal_counts["sell"] >= 2
                and signal_counts["sell"] > signal_counts["buy"]
                and weighted_votes["sell"] > weighted_votes["buy"]
            ):
                base_signal = "sell"
            else:
                base_signal = "neutral"
                dominant = "buy" if signal_counts["buy"] >= signal_counts["sell"] else "sell"
                if signal_counts[dominant] == 1 and signal_counts["neutral"] >= 2:
                    minority_note = (
                        f"소수 의견 차단: {dominant} 1명 vs 중립 {signal_counts['neutral']}명 "
                        f"— 단일 에이전트 의견으로 신호를 채택하지 않음"
                    )
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
        # [산술 정합] 종합 점수의 모든 성분을 표기해 합계가 재검산 가능하도록 한다.
        reasoning_parts = []
        ml_contribution = float(signal_strength.get("ml_adjusted", {}).get("contribution", 0) or 0)
        insider_contribution = float(signal_strength.get("insider", {}).get("contribution", 0) or 0)
        domain = signal_strength.get("domain_contributions", {})
        domain_total = sum(float(v or 0) for v in domain.values())
        reasoning_parts.append(
            f"종합 점수: {total_score:+.1f} = 기술 {tech_analysis['total_score']:+.1f} "
            f"+ 퀀트 {quant_analysis['total_score']:+.1f} + ML {ml_contribution:+.1f} "
            f"+ 내부자 {insider_contribution:+.1f} + 도메인 {domain_total:+.1f}"
        )
        if any(abs(float(v or 0)) > 0 for v in domain.values()):
            reasoning_parts.append(
                "도메인 보정: "
                f"Risk {domain.get('risk', 0):+.1f}, "
                f"Event {domain.get('event', 0):+.1f}, "
                f"Value {domain.get('fundamental', 0):+.1f}, "
                f"Macro {domain.get('macro', 0):+.1f}"
            )
        reasoning_parts.append(f"신호 강도: {strength_level}")

        # [레벨 구분] 에이전트 표결과 하위 지표 신호를 명확히 분리해 표기한다.
        vote_summary = (
            f"에이전트 표결: 매수 {signal_counts['buy']}명 / 매도 {signal_counts['sell']}명 "
            f"/ 중립 {signal_counts['neutral']}명"
        )
        if base_signal == "buy":
            reasoning_parts.append(
                f"매수 우세 — {vote_summary} "
                f"(하위 지표: 기술 buy {tech_analysis['buy_count']}개, 퀀트 buy {quant_analysis['buy_count']}개)"
            )
        elif base_signal == "sell":
            reasoning_parts.append(
                f"매도 우세 — {vote_summary} "
                f"(하위 지표: 기술 sell {tech_analysis['sell_count']}개, 퀀트 sell {quant_analysis['sell_count']}개)"
            )
        else:
            reasoning_parts.append(f"중립 — {vote_summary}")
            if minority_note:
                reasoning_parts.append(minority_note)

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
