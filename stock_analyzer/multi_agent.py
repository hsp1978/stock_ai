#!/usr/bin/env python3
"""
Multi-Agent System for Stock Analysis
Week 2-3: 6개 전문 에이전트 협업 시스템

에이전트 구성:
- TechnicalAnalyst: 차트 패턴, 기술 지표 전문
- QuantAnalyst: 통계 모델, 수학적 분석 전문
- RiskManager: 리스크 관리, 포지션 사이징 전문
- MLSpecialist: 머신러닝 예측 전문
- EventAnalyst: 뉴스, 매크로 이벤트 전문
- DecisionMaker: 최종 의사결정 및 충돌 해결
"""

import os
import sys
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback

# 프로젝트 경로 설정
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
_SERVICE_DIR = os.path.join(_PROJECT_ROOT, 'chart_agent_service')

if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

from config import DEFAULT_TEST_TICKER

from data_collector import fetch_ohlcv, calculate_indicators
from analysis_tools import AnalysisTools


@dataclass
class AgentResult:
    """에이전트 분석 결과"""
    agent_name: str
    signal: str  # buy/sell/neutral
    confidence: float  # 0-10
    reasoning: str
    evidence: List[Dict[str, Any]]  # 도구 실행 결과
    llm_provider: str
    execution_time: float = 0.0
    error: Optional[str] = None

    def to_dict(self):
        """딕셔너리 변환"""
        return asdict(self)


class BaseAgent:
    """에이전트 기본 클래스"""

    def __init__(self, name: str, tools: List[str], llm_provider: str):
        self.name = name
        self.tools = tools
        self.llm_provider = llm_provider

    def analyze(self, ticker: str, analysis_tools: AnalysisTools) -> AgentResult:
        """
        도구 실행 → LLM 해석 → 신호 생성

        Args:
            ticker: 종목 심볼
            analysis_tools: 분석 도구 인스턴스

        Returns:
            AgentResult
        """
        start_time = datetime.now()

        try:
            # 1. 도구 실행
            evidence = []
            for tool_name in self.tools:
                try:
                    tool_method = getattr(analysis_tools, tool_name)
                    result = tool_method()
                    evidence.append({
                        "tool": tool_name,
                        "result": result
                    })
                except Exception as e:
                    evidence.append({
                        "tool": tool_name,
                        "error": str(e)
                    })

            # 2. LLM 프롬프트 생성
            prompt = self._build_prompt(ticker, evidence)

            # 3. LLM 호출
            response = self._call_llm(prompt)

            # 4. 응답 파싱
            signal, confidence, reasoning = self._parse_response(response)

            execution_time = (datetime.now() - start_time).total_seconds()

            return AgentResult(
                agent_name=self.name,
                signal=signal,
                confidence=confidence,
                reasoning=reasoning,
                evidence=evidence,
                llm_provider=self.llm_provider,
                execution_time=execution_time
            )

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            return AgentResult(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning=f"Error: {str(e)}",
                evidence=[],
                llm_provider=self.llm_provider,
                execution_time=execution_time,
                error=str(e)
            )

    def _build_prompt(self, ticker: str, evidence: List[Dict[str, Any]]) -> str:
        """LLM 프롬프트 생성"""

        # 증거 요약
        evidence_summary = []
        for item in evidence:
            if "error" in item:
                continue
            result = item.get("result", {})
            tool_name = item.get("tool", "unknown")
            signal = result.get("signal", "neutral")
            score = result.get("score", 0)
            detail = result.get("detail", "")

            evidence_summary.append(f"- {tool_name}: {signal} (score: {score:+.1f}) - {detail[:100]}")

        evidence_text = "\n".join(evidence_summary) if evidence_summary else "No data available"

        prompt = f"""당신은 {self.name} 전문가입니다.
{ticker} 종목에 대한 분석 결과를 해석하고, 매수/매도/중립 판단을 내리세요.

## 분석 결과
{evidence_text}

## 요구사항
다음 JSON 형식으로만 응답하세요:
{{
  "signal": "buy" 또는 "sell" 또는 "neutral",
  "confidence": 0-10 사이의 숫자,
  "reasoning": "판단 근거 (한국어, 3-5문장)"
}}

중요: JSON 형식만 출력하세요. 다른 텍스트는 포함하지 마세요."""

        return prompt

    def _call_llm(self, prompt: str) -> str:
        """LLM 호출"""

        if self.llm_provider == "gemini":
            return self._call_gemini(prompt)
        elif self.llm_provider == "ollama":
            return self._call_ollama(prompt)
        elif self.llm_provider == "openai":
            return self._call_openai(prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {self.llm_provider}")

    def _call_gemini(self, prompt: str) -> str:
        """Gemini API 호출"""
        try:
            import google.generativeai as genai

            api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
            if not api_key:
                return '{"signal": "neutral", "confidence": 0, "reasoning": "Gemini API key not found"}'

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.0-flash')

            response = model.generate_content(prompt)
            return response.text

        except Exception as e:
            return f'{{"signal": "neutral", "confidence": 0, "reasoning": "Gemini error: {str(e)[:50]}"}}'

    def _call_ollama(self, prompt: str) -> str:
        """Ollama API 호출"""
        try:
            import requests

            ollama_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
            model = os.getenv('OLLAMA_MODEL', 'llama3.1:8b')

            response = requests.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False
                },
                timeout=60
            )

            if response.status_code == 200:
                return response.json().get('response', '')
            else:
                return f'{{"signal": "neutral", "confidence": 0, "reasoning": "Ollama connection failed"}}'

        except Exception as e:
            return f'{{"signal": "neutral", "confidence": 0, "reasoning": "Ollama error: {str(e)[:50]}"}}'

    def _call_openai(self, prompt: str) -> str:
        """OpenAI API 호출"""
        try:
            from openai import OpenAI

            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                return '{"signal": "neutral", "confidence": 0, "reasoning": "OpenAI API key not found"}'

            client = OpenAI(api_key=api_key)

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a stock market expert. Always respond in valid JSON format."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )

            return response.choices[0].message.content

        except Exception as e:
            return f'{{"signal": "neutral", "confidence": 0, "reasoning": "OpenAI error: {str(e)[:50]}"}}'

    def _parse_response(self, response: str) -> tuple[str, float, str]:
        """LLM 응답 파싱"""

        # JSON 추출 시도
        try:
            # JSON 블록 찾기
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            elif "```" in response:
                json_start = response.find("```") + 3
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            else:
                json_str = response.strip()

            # JSON 파싱
            data = json.loads(json_str)
            signal = data.get("signal", "neutral").lower()
            confidence = float(data.get("confidence", 5.0))
            reasoning = data.get("reasoning", "No reasoning provided")

            # 유효성 검사
            if signal not in ["buy", "sell", "neutral"]:
                signal = "neutral"
            confidence = max(0.0, min(10.0, confidence))

            return signal, confidence, reasoning

        except json.JSONDecodeError:
            # JSON 파싱 실패 시 텍스트 분석
            signal = "neutral"
            confidence = 5.0

            response_lower = response.lower()
            if "buy" in response_lower or "매수" in response_lower:
                signal = "buy"
                confidence = 6.0
            elif "sell" in response_lower or "매도" in response_lower:
                signal = "sell"
                confidence = 6.0

            return signal, confidence, response[:200]


# ============================================
# 전문 에이전트 구현
# ============================================

class TechnicalAnalyst(BaseAgent):
    """기술적 분석 전문가"""

    def __init__(self):
        super().__init__(
            name="Technical Analyst",
            tools=[
                "trend_ma_analysis",
                "rsi_divergence_analysis",
                "bollinger_squeeze_analysis",
                "macd_momentum_analysis",
                "adx_trend_strength_analysis",
                "volume_profile_analysis",
            ],
            llm_provider="ollama"  # Gemini 할당량 초과로 Ollama 사용
        )


class QuantAnalyst(BaseAgent):
    """퀀트 분석 전문가"""

    def __init__(self):
        super().__init__(
            name="Quant Analyst",
            tools=[
                "fibonacci_retracement_analysis",
                "volatility_regime_analysis",
                "mean_reversion_analysis",
                "momentum_rank_analysis",
                "support_resistance_analysis",
                "correlation_regime_analysis",
            ],
            llm_provider="ollama"  # Gemini 할당량 초과로 Ollama 사용
        )


class RiskManager(BaseAgent):
    """리스크 관리 전문가"""

    def __init__(self):
        super().__init__(
            name="Risk Manager",
            tools=[
                "risk_position_sizing",
                "kelly_criterion_analysis",
                "beta_correlation_analysis",
            ],
            llm_provider="ollama"
        )


class MLSpecialist(BaseAgent):
    """머신러닝 전문가"""

    def __init__(self):
        super().__init__(
            name="ML Specialist",
            tools=[],  # ML 도구는 별도 처리
            llm_provider="ollama"
        )

    def analyze(self, ticker: str, analysis_tools: AnalysisTools) -> AgentResult:
        """ML 예측 전용 분석"""
        start_time = datetime.now()

        try:
            # ML 예측 실행
            from ml_predictor import run_ml_prediction
            from data_collector import fetch_ohlcv, calculate_indicators

            df = fetch_ohlcv(ticker)
            df = calculate_indicators(df)
            ml_result = run_ml_prediction(ticker, df, ensemble=True)

            # 증거 구성
            evidence = [{
                "tool": "ml_ensemble",
                "result": ml_result
            }]

            # 프롬프트 생성
            ensemble = ml_result.get("ensemble", {})
            prediction = ensemble.get("prediction", "neutral")
            probability = ensemble.get("up_probability", 0.5)

            prompt = f"""당신은 ML Specialist 전문가입니다.
{ticker} 종목의 머신러닝 앙상블 예측 결과를 해석하세요.

## ML 예측 결과
- 예측: {prediction}
- 상승 확률: {probability:.1%}
- 모델 개수: {ensemble.get('model_count', 0)}

다음 JSON 형식으로만 응답하세요:
{{
  "signal": "buy" 또는 "sell" 또는 "neutral",
  "confidence": 0-10,
  "reasoning": "판단 근거"
}}"""

            response = self._call_llm(prompt)
            signal, confidence, reasoning = self._parse_response(response)

            execution_time = (datetime.now() - start_time).total_seconds()

            return AgentResult(
                agent_name=self.name,
                signal=signal,
                confidence=confidence,
                reasoning=reasoning,
                evidence=evidence,
                llm_provider=self.llm_provider,
                execution_time=execution_time
            )

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            return AgentResult(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning=f"ML Error: {str(e)}",
                evidence=[],
                llm_provider=self.llm_provider,
                execution_time=execution_time,
                error=str(e)
            )


class EventAnalyst(BaseAgent):
    """이벤트/뉴스 분석 전문가"""

    def __init__(self):
        super().__init__(
            name="Event Analyst",
            tools=[
                "event_driven_analysis",
            ],
            llm_provider="ollama"  # Gemini 할당량 초과로 Ollama 사용
        )


class DecisionMaker:
    """최종 의사결정자 - 에이전트 의견 종합 및 충돌 해결"""

    def __init__(self):
        self.name = "Decision Maker"
        self.llm_provider = "openai"

    def aggregate(self, ticker: str, agent_results: List[AgentResult]) -> Dict[str, Any]:
        """
        에이전트 결과 종합 및 최종 판단

        Args:
            ticker: 종목 심볼
            agent_results: 에이전트 분석 결과 리스트

        Returns:
            최종 판단 결과
        """

        # 에이전트 의견 집계
        signals = {"buy": 0, "sell": 0, "neutral": 0}
        total_confidence = 0.0

        for result in agent_results:
            if result.error:
                continue
            signals[result.signal] += 1
            total_confidence += result.confidence

        # 프롬프트 생성
        prompt = self._build_decision_prompt(ticker, agent_results, signals)

        # OpenAI 호출
        try:
            response = self._call_openai(prompt)
            decision = self._parse_decision(response)

            # 기본값 추가
            decision["agent_count"] = len(agent_results)
            decision["signal_distribution"] = signals
            decision["analyzed_at"] = datetime.now().isoformat()

            return decision

        except Exception as e:
            # 폴백: 단순 다수결
            majority_signal = max(signals.items(), key=lambda x: x[1])[0]
            avg_confidence = total_confidence / len(agent_results) if agent_results else 0

            return {
                "final_signal": majority_signal,
                "final_confidence": avg_confidence,
                "consensus": f"{signals['buy']}명 매수, {signals['sell']}명 매도, {signals['neutral']}명 중립",
                "conflicts": "Decision Maker 오류로 단순 다수결 적용",
                "reasoning": f"Error: {str(e)}",
                "key_risks": ["Decision Maker 실행 실패"],
                "agent_count": len(agent_results),
                "signal_distribution": signals,
                "analyzed_at": datetime.now().isoformat(),
                "error": str(e)
            }

    def _build_decision_prompt(self, ticker: str, agent_results: List[AgentResult], signals: Dict[str, int]) -> str:
        """의사결정 프롬프트 생성"""

        prompt = f"""당신은 최종 의사결정자입니다.
여러 전문가의 {ticker} 분석 결과를 종합하여 최종 판단을 내리세요.

## 전문가 의견 요약
총 {len(agent_results)}명의 전문가 의견:
- 매수: {signals['buy']}명
- 매도: {signals['sell']}명
- 중립: {signals['neutral']}명

## 전문가별 상세 의견
"""

        for result in agent_results:
            prompt += f"\n### {result.agent_name} ({result.llm_provider})"
            prompt += f"\n- 신호: {result.signal}"
            prompt += f"\n- 신뢰도: {result.confidence:.1f}/10"
            prompt += f"\n- 근거: {result.reasoning[:200]}"
            if result.error:
                prompt += f"\n- 오류: {result.error}"
            prompt += "\n"

        prompt += """
## 요구사항
1. 전문가 의견이 일치하면 → 그 방향으로 최종 판단
2. 의견이 충돌하면 → 각 의견의 근거 강도를 평가하고 조정
3. 소수 의견도 리스크로 반영 (예: 5명 매수, 1명 매도 → "매수하되 X 리스크 주의")
4. 각 전문가의 신뢰도를 가중치로 고려

다음 JSON 형식으로만 응답하세요:
{
  "final_signal": "buy/sell/neutral",
  "final_confidence": 0-10,
  "consensus": "의견 분포 요약",
  "conflicts": "의견 충돌 시 조정 과정 설명",
  "reasoning": "최종 판단 근거 (3-5문장)",
  "key_risks": ["주요 리스크1", "주요 리스크2"]
}"""

        return prompt

    def _call_openai(self, prompt: str) -> str:
        """OpenAI API 호출"""
        from openai import OpenAI

        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OpenAI API key not found")

        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert decision maker for stock trading. Always respond in valid JSON format."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1000
        )

        return response.choices[0].message.content

    def _parse_decision(self, response: str) -> Dict[str, Any]:
        """응답 파싱"""

        try:
            # JSON 추출
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            elif "```" in response:
                json_start = response.find("```") + 3
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            else:
                json_str = response.strip()

            data = json.loads(json_str)

            # 필수 필드 검증
            required_fields = ["final_signal", "final_confidence", "reasoning"]
            for field in required_fields:
                if field not in data:
                    data[field] = "N/A"

            # 기본값 설정
            data.setdefault("consensus", "Unknown")
            data.setdefault("conflicts", "None")
            data.setdefault("key_risks", [])

            return data

        except json.JSONDecodeError:
            return {
                "final_signal": "neutral",
                "final_confidence": 5.0,
                "consensus": "Parsing failed",
                "conflicts": "Response parsing error",
                "reasoning": response[:200],
                "key_risks": ["Decision parsing failed"]
            }


# ============================================
# Orchestrator - 병렬 실행 관리
# ============================================

class MultiAgentOrchestrator:
    """멀티에이전트 오케스트레이터 - 병렬 실행 및 결과 집계"""

    def __init__(self):
        self.agents = [
            TechnicalAnalyst(),
            QuantAnalyst(),
            RiskManager(),
            MLSpecialist(),
            EventAnalyst(),
        ]
        self.decision_maker = DecisionMaker()

    def analyze(self, ticker: str) -> Dict[str, Any]:
        """
        멀티에이전트 분석 실행

        Args:
            ticker: 종목 심볼

        Returns:
            최종 분석 결과
        """

        print(f"\n[MultiAgent] {ticker} 분석 시작...")
        start_time = datetime.now()

        try:
            # 1. 데이터 수집
            print(f"  [1/3] 데이터 수집 중...")
            df = fetch_ohlcv(ticker)
            df = calculate_indicators(df)
            tools = AnalysisTools(ticker, df)

            # 2. 병렬 에이전트 실행
            print(f"  [2/3] {len(self.agents)}개 에이전트 병렬 실행 중...")
            agent_results = []

            with ThreadPoolExecutor(max_workers=len(self.agents)) as executor:
                # 각 에이전트에 작업 제출
                futures = {
                    executor.submit(agent.analyze, ticker, tools): agent
                    for agent in self.agents
                }

                # 완료된 작업 수집
                for future in as_completed(futures, timeout=120):
                    agent = futures[future]
                    try:
                        result = future.result(timeout=60)
                        agent_results.append(result)

                        # 진행 상황 출력
                        status = "✓" if not result.error else "✗"
                        print(f"    {status} {agent.name}: {result.signal} ({result.confidence:.1f}/10) [{result.execution_time:.1f}s]")

                    except Exception as e:
                        print(f"    ✗ {agent.name}: Error - {str(e)[:50]}")
                        # 에러 발생 시에도 기본 결과 추가
                        agent_results.append(AgentResult(
                            agent_name=agent.name,
                            signal="neutral",
                            confidence=0.0,
                            reasoning=f"Execution failed: {str(e)}",
                            evidence=[],
                            llm_provider=agent.llm_provider,
                            error=str(e)
                        ))

            # 3. Decision Maker가 종합
            print(f"  [3/3] Decision Maker가 의견 종합 중...")
            final_decision = self.decision_maker.aggregate(ticker, agent_results)

            total_time = (datetime.now() - start_time).total_seconds()

            # 결과 구성
            result = {
                "ticker": ticker,
                "multi_agent_mode": True,
                "agent_results": [
                    {
                        "agent": r.agent_name,
                        "signal": r.signal,
                        "confidence": r.confidence,
                        "reasoning": r.reasoning[:300],  # 요약
                        "llm_provider": r.llm_provider,
                        "execution_time": r.execution_time,
                        "error": r.error
                    }
                    for r in agent_results
                ],
                "final_decision": final_decision,
                "total_execution_time": total_time,
                "analyzed_at": datetime.now().isoformat(),
            }

            print(f"\n[MultiAgent] 완료: {final_decision['final_signal']} (신뢰도: {final_decision.get('final_confidence', 0):.1f}/10) [{total_time:.1f}s]")

            return result

        except Exception as e:
            print(f"\n[MultiAgent] 오류: {str(e)}")
            traceback.print_exc()

            return {
                "ticker": ticker,
                "multi_agent_mode": True,
                "error": str(e),
                "analyzed_at": datetime.now().isoformat(),
            }


# ============================================
# 테스트 함수
# ============================================

def test_multi_agent(ticker=DEFAULT_TEST_TICKER):
    """멀티에이전트 시스템 테스트"""

    print("=" * 70)
    print("Multi-Agent System Test")
    print("=" * 70)

    orchestrator = MultiAgentOrchestrator()
    result = orchestrator.analyze(ticker)

    print("\n" + "=" * 70)
    print("결과")
    print("=" * 70)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    return result


if __name__ == "__main__":
    import sys

    ticker = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEST_TICKER
    test_multi_agent(ticker)