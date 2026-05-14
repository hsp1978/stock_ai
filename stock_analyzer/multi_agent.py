#!/usr/bin/env python3
"""
Multi-Agent System for Stock Analysis
Week 2-3: 8개 전문 에이전트 협업 시스템 (Fincept Terminal 벤치마킹)

에이전트 구성:
- TechnicalAnalyst: 차트 패턴, 기술 지표 전문
- QuantAnalyst: 통계 모델, 수학적 분석 전문
- RiskManager: 리스크 관리, 포지션 사이징 전문
- MLSpecialist: 머신러닝 예측 전문
- EventAnalyst: 뉴스, 매크로 이벤트 전문
- GeopoliticalAnalyst: 지정학 리스크, 환율 영향 분석 (NEW)
- ValueInvestor: Warren Buffett/Benjamin Graham 가치 투자 (NEW)
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

    def _get_stock_name_for_agent(self, ticker: str) -> Optional[str]:
        """에이전트용 종목명 가져오기 (한글명 우선)"""
        try:
            # 한국 주식인 경우 종목명 조회
            if ticker.endswith('.KS') or ticker.endswith('.KQ') or (ticker.isdigit() and len(ticker) == 6):
                import json
                import os
                code = ticker.replace('.KS', '').replace('.KQ', '')

                # 1. korean_stocks_database.json 최우선
                try:
                    db_file = os.path.join(os.path.dirname(__file__), 'korean_stocks_database.json')
                    if os.path.exists(db_file):
                        with open(db_file, 'r', encoding='utf-8') as f:
                            db_data = json.load(f)
                            stocks = db_data.get('stocks', {})
                            if code in stocks:
                                return stocks[code]['name']
                except:
                    pass

                # 2. korean_stock_favorites.json
                try:
                    favorites_file = os.path.join(os.path.dirname(__file__), 'korean_stock_favorites.json')
                    if os.path.exists(favorites_file):
                        with open(favorites_file, 'r', encoding='utf-8') as f:
                            favorites = json.load(f)
                            if code in favorites:
                                return favorites[code]
                except:
                    pass
        except:
            pass
        return None

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

        # 종목명 가져오기
        stock_name = self._get_stock_name_for_agent(ticker)
        stock_display = f"{stock_name}({ticker})" if stock_name else ticker

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
{stock_display} 종목에 대한 분석 결과를 해석하고, 매수/매도/중립 판단을 내리세요.

## 분석 결과
{evidence_text}

## 요구사항
다음 JSON 형식으로만 응답하세요:
{{
  "signal": "buy" 또는 "sell" 또는 "neutral",
  "confidence": 0-10 사이의 숫자,
  "reasoning": "판단 근거 (한국어, 최소 3문장, 최대 5문장)"
}}

[개선 #9] reasoning 최소 기준:
- 반드시 3문장 이상으로 작성하세요
- 각 문장은 구체적인 지표나 수치를 언급해야 합니다
- 단순한 요약이 아닌 분석적 해석을 포함하세요
- 예시: "RSI가 30 이하로 과매도 구간입니다. MACD는 골든크로스를 형성했습니다. 거래량이 평균 대비 2배 증가하여 매수 신호가 강합니다."

중요: JSON 형식만 출력하세요. 다른 텍스트는 포함하지 마세요."""

        return prompt

    def _call_llm(self, prompt: str) -> str:
        """LLM 호출 (LiteLLM Router 경유 — Step 9)."""
        try:
            from llm.router import call_agent_llm, get_router
            response = call_agent_llm(get_router(), self.name, prompt)
            return json.dumps(
                {
                    "signal": response.signal,
                    "confidence": response.confidence,
                    "reasoning": response.reasoning,
                    "key_evidence": response.key_evidence,
                    "risk_flags": response.risk_flags,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            # Router 자체 import/초기화 실패 시만 여기 진입 (call_agent_llm는 예외 미방출)
            return self._empty_response_json(f"LLM Router 오류: {exc}")

    def _call_gemini(self, prompt: str) -> str:
        """Gemini API 호출"""
        try:
            import google.generativeai as genai

            api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
            if not api_key:
                return '{"signal": "neutral", "confidence": 0, "reasoning": "Gemini API key not found"}'

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'))

            response = model.generate_content(prompt)
            return response.text

        except Exception:
            return self._empty_response_json("Gemini 서비스 일시 장애")

    @staticmethod
    def _empty_response_json(reason: str = "LLM 응답 없음") -> str:
        return f'{{"signal": "neutral", "confidence": 0, "reasoning": "{reason}"}}'

    def _call_ollama(self, prompt: str) -> str:
        """Ollama API 호출 (듀얼 노드 지원, GPU 메모리 보호)"""
        import time

        # GPU 메모리 체크 (선택적)
        try:
            import subprocess
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                mem_used = int(result.stdout.strip())
                # GPU 메모리가 90% 이상이면 대기
                if mem_used > 11000:  # 12GB GPU 기준 90%
                    time.sleep(2)  # 짧은 대기
        except Exception:
            pass  # nvidia-smi 실행 실패는 무시

        try:
            from dual_node_config import (
                get_llm_config, get_fallback_config,
                performance_monitor, get_http_session,
            )

            session = get_http_session()
            llm_config = get_llm_config(self.name)
            start_time = datetime.now()

            # 첫 번째 시도: 할당된 노드
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    response = session.post(
                        f"{llm_config['url']}/api/generate",
                        json={
                            "model": llm_config['model'],
                            "prompt": prompt,
                            "stream": False,
                            "think": False,  # qwen3 thinking 모드 비활성화 — 미지원 모델은 무시
                            "options": {
                                "temperature": 0.0,
                                # Ollama API 의 num_gpu 는 "GPU 에 올릴 레이어 수" 이며,
                                # 1 로 두면 99% 의 레이어를 CPU 로 오프로드해 추론이 10x 이상
                                # 느려진다. 옵션을 빼서 Ollama 자동 결정에 맡긴다.
                                "num_thread": 4  # CPU 스레드 제한
                            }
                        },
                        # Mac Studio(32GB)는 32B 모델을 OLLAMA_NUM_PARALLEL=1 로
                        # 직렬 처리하므로 4개 에이전트가 큐잉될 때 마지막 에이전트
                        # 대기 시간을 고려해 240s 기본. .env: MULTI_AGENT_LLM_TIMEOUT
                        timeout=int(os.getenv("MULTI_AGENT_LLM_TIMEOUT", "240"))
                    )

                    if response.status_code == 200:
                        exec_time = (datetime.now() - start_time).total_seconds()
                        performance_monitor.record(self.name, exec_time, llm_config['node'])
                        text = (response.json().get('response') or '').strip()
                        return text if text else json.dumps({
                            "decision": "NEUTRAL",
                            "confidence": 0.0,
                            "reasoning": "LLM 응답 없음",
                            "risks": ["응답 없음"],
                            "opportunities": []
                        }, ensure_ascii=False)
                    elif attempt < max_retries - 1:
                        # 재시도 전 대기 (지수 백오프)
                        time.sleep(2 ** attempt)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise  # 마지막 시도에서는 예외 발생
                    time.sleep(2 ** attempt)

            # Mac Studio 연결 실패 시 폴백
            if llm_config['node'] == 'mac_studio':
                fallback = get_fallback_config(self.name)
                response = session.post(
                    f"{fallback['url']}/api/generate",
                    json={
                        "model": fallback['model'],
                        "prompt": prompt,
                        "stream": False,
                        "think": False,  # qwen3 thinking 모드 비활성화
                        "options": {
                            "temperature": 0.0,
                            # num_gpu 제거 — Ollama 자동 결정 (위와 동일 이유)
                            "num_thread": 4
                        }
                    },
                    timeout=fallback.get('timeout', 120)
                )

                if response.status_code == 200:
                    exec_time = (datetime.now() - start_time).total_seconds()
                    performance_monitor.record(self.name, exec_time, fallback['node'])
                    text = (response.json().get('response') or '').strip()
                    return text if text else BaseAgent._empty_response_json()

        except Exception:
            # 내부 에러 상세를 응답에 노출하지 않음 (정보 누설 방지)
            return self._empty_response_json("LLM 서비스 일시 장애")

    def _call_openai(self, prompt: str) -> str:
        """OpenAI API 호출"""
        try:
            from openai import OpenAI

            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                return self._empty_response_json("OPENAI_API_KEY 환경변수 미설정")

            client = OpenAI(api_key=api_key)

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a stock market expert. Always respond in valid JSON format."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,  # 결정론적 출력을 위해 0으로 고정
                max_tokens=500
            )

            content = response.choices[0].message.content or ''
            return content.strip() if content.strip() else self._empty_response_json()

        except Exception:
            return self._empty_response_json("OpenAI 서비스 일시 장애")

    def _parse_response(self, response: str) -> tuple[str, float, str]:
        """LLM 응답 파싱"""

        # None 또는 빈 응답 처리
        if response is None or not response:
            return "neutral", 0.0, "LLM 서비스 일시 장애"

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

            # [의미론 일관성] confidence가 0이면 신호도 강제로 neutral
            # "buy + confidence 0"은 "근거 없는 buy"로 모순. 확신 없으면 중립.
            if confidence == 0.0 and signal != "neutral":
                signal = "neutral"

            # [개선 #9] reasoning 최소 기준 검증
            sentences = [s.strip() for s in reasoning.split('.') if s.strip()]
            if len(sentences) < 3:
                # reasoning이 너무 짧으면 경고 추가
                reasoning = reasoning + f" [경고: reasoning {len(sentences)}문장 < 최소 3문장]"

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

    def __init__(self, llm_provider: str = None):
        # 환경 변수에서 기본값 가져오기
        if llm_provider is None:
            llm_provider = os.getenv('DEFAULT_LLM_PROVIDER', 'ollama')
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
            llm_provider=llm_provider
        )


class QuantAnalyst(BaseAgent):
    """퀀트 분석 전문가"""

    def __init__(self, llm_provider: str = None):
        if llm_provider is None:
            llm_provider = os.getenv('DEFAULT_LLM_PROVIDER', 'ollama')
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
            llm_provider=llm_provider
        )


class RiskManager(BaseAgent):
    """리스크 관리 전문가"""

    def __init__(self, llm_provider: str = None):
        if llm_provider is None:
            llm_provider = os.getenv('DEFAULT_LLM_PROVIDER', 'ollama')
        super().__init__(
            name="Risk Manager",
            tools=[
                "risk_position_sizing",
                "kelly_criterion_analysis",
                "beta_correlation_analysis",
            ],
            llm_provider=llm_provider
        )


class MLSpecialist(BaseAgent):
    """머신러닝 전문가"""

    def __init__(self, llm_provider: str = None):
        if llm_provider is None:
            llm_provider = os.getenv('DEFAULT_LLM_PROVIDER', 'ollama')
        super().__init__(
            name="ML Specialist",
            tools=[],  # ML 도구는 별도 처리
            llm_provider=llm_provider
        )

    def analyze(self, ticker: str, analysis_tools: AnalysisTools) -> AgentResult:
        """ML 예측 전용 분석 (한국 주식 대응 강화)"""
        start_time = datetime.now()

        try:
            # 개선된 ML 파이프라인 사용
            try:
                from ml_pipeline_fix import enhanced_ml_ensemble
                from data_collector import fetch_ohlcv, calculate_indicators

                df = fetch_ohlcv(ticker)
                df = calculate_indicators(df)
                ml_result = enhanced_ml_ensemble(ticker, df, debug=False)

                # 모델이 0개인 경우 체크
                if ml_result["ensemble"]["model_count"] == 0:
                    # 기존 ml_predictor로 폴백 시도
                    from ml_predictor import run_ml_prediction
                    ml_result_fallback = run_ml_prediction(ticker, df, ensemble=True)
                    if ml_result_fallback.get("ensemble", {}).get("model_count", 0) > 0:
                        ml_result = ml_result_fallback
            except ImportError:
                # ml_pipeline_fix가 없으면 기존 사용
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
            prediction = ensemble.get("prediction", "NEUTRAL")
            probability = ensemble.get("up_probability", 0.5)
            model_count = ensemble.get("model_count", 0)
            avg_accuracy = ensemble.get("avg_accuracy", 0)
            warnings = ml_result.get("warnings", [])

            # 모델이 0개인 경우 특별 처리
            if model_count == 0:
                # 종목명 가져오기
                stock_name = self._get_stock_name_for_agent(ticker)
                stock_display = f"{stock_name}({ticker})" if stock_name else ticker

                prompt = f"""당신은 ML Specialist 전문가입니다.
{stock_display} 종목의 머신러닝 예측이 실패했습니다.

## ML 예측 실패
- 모델 개수: 0
- 경고: {', '.join(warnings) if warnings else '데이터 품질 문제'}

ML 모델이 작동하지 않으므로 중립 판단을 내려야 합니다.

다음 JSON 형식으로만 응답하세요:
{{
  "signal": "neutral",
  "confidence": 0,
  "reasoning": "ML 모델 학습 실패 - {warnings[0] if warnings else '데이터 부족'}"
}}"""
            else:
                avg_accuracy_str = f"{avg_accuracy:.1%}" if avg_accuracy > 0 else "N/A"
                # 종목명 가져오기
                stock_name = self._get_stock_name_for_agent(ticker)
                stock_display = f"{stock_name}({ticker})" if stock_name else ticker

                prompt = f"""당신은 ML Specialist 전문가입니다.
{stock_display} 종목의 머신러닝 앙상블 예측 결과를 해석하세요.

## ML 예측 결과
- 예측: {prediction}
- 상승 확률: {probability:.1%}
- 모델 개수: {model_count}
- 평균 정확도: {avg_accuracy_str}
- 경고: {', '.join(warnings) if warnings else '없음'}

다음 JSON 형식으로만 응답하세요:
{{
  "signal": "buy" 또는 "sell" 또는 "neutral",
  "confidence": 0-10,
  "reasoning": "판단 근거"
}}"""

            response = self._call_llm(prompt)
            signal, confidence, reasoning = self._parse_response(response)

            # 모델 0개일 때 강제 조정
            if model_count == 0:
                signal = "neutral"
                confidence = 0.0
                reasoning = f"ML 모델 미작동: {', '.join(warnings) if warnings else '데이터 문제'}"

            # [개선 #5] ML 정확도 50% 미만 무시 규칙
            elif avg_accuracy > 0 and avg_accuracy < 0.5:  # 50% 미만
                signal = "neutral"
                confidence = 0.0
                reasoning = f"ML 정확도 {avg_accuracy:.1%}는 50% 미만으로 무작위 추측 수준 - 신호 무시"
                warnings.append(f"ML accuracy {avg_accuracy:.1%} < 50% threshold - ignoring signal")

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

    def __init__(self, llm_provider: str = None):
        if llm_provider is None:
            llm_provider = os.getenv('DEFAULT_LLM_PROVIDER', 'ollama')
        super().__init__(
            name="Event Analyst",
            tools=[
                "event_driven_analysis",
                "insider_trading_analysis",  # 내부자 거래 분석 추가
            ],
            llm_provider=llm_provider
        )


class GeopoliticalAnalyst(BaseAgent):
    """지정학/거시경제 분석 전문가 - Fincept Terminal 벤치마킹"""

    def __init__(self, llm_provider: str = None):
        if llm_provider is None:
            llm_provider = os.getenv('DEFAULT_LLM_PROVIDER', 'ollama')
        super().__init__(
            name="Geopolitical Analyst",
            tools=[],  # 별도 분석 로직 사용
            llm_provider=llm_provider
        )

    def analyze(self, ticker: str, analysis_tools: AnalysisTools) -> AgentResult:
        """지정학적 리스크 및 환율 영향 분석"""
        start_time = datetime.now()

        try:
            import yfinance as yf

            # 종목 정보 가져오기
            stock = yf.Ticker(ticker)
            info = stock.info or {}

            # 1. 환율 영향 평가
            currency = info.get('currency', 'USD')
            country = info.get('country', 'Unknown')
            sector = info.get('sector', 'Unknown')

            # 2. 지정학적 리스크 평가
            geopolitical_risks = []
            fx_exposure = "LOW"

            # 한국/중국/일본 종목 - 환율 리스크
            if ticker.endswith(('.KS', '.KQ', '.T', '.SS', '.SZ', '.HK')):
                fx_exposure = "HIGH"
                geopolitical_risks.append("동아시아 지정학적 긴장 (한반도, 대만)")
                geopolitical_risks.append("USD/KRW 환율 변동성")

            # 미국 외 종목 - 일반 환율 리스크
            elif currency != 'USD':
                fx_exposure = "MEDIUM"
                geopolitical_risks.append(f"{currency} 환율 변동 리스크")

            # 섹터별 지정학적 리스크 (None 체크 추가)
            if sector is not None and sector in ['Energy', 'Materials']:
                geopolitical_risks.append("원자재 가격 변동성 (공급망, 지정학)")
            elif sector is not None and sector in ['Technology', 'Communication Services']:
                geopolitical_risks.append("미중 기술 패권 경쟁")
            elif sector is not None and sector in ['Consumer Cyclical', 'Consumer Defensive']:
                geopolitical_risks.append("글로벌 소비 심리, 무역 정책 변화")

            # 국가별 특수 리스크 (None 체크 추가)
            if country is not None and country in ['China', 'Hong Kong']:
                geopolitical_risks.append("중국 규제 리스크, 미중 무역 분쟁")
            elif country is not None and country in ['Russia', 'Ukraine']:
                geopolitical_risks.append("러시아-우크라이나 전쟁, 제재 리스크")
            elif country is not None and country in ['Taiwan']:
                geopolitical_risks.append("대만 해협 긴장, 반도체 공급망 리스크")

            # 증거 구성
            evidence = [{
                "tool": "geopolitical_analysis",
                "result": {
                    "currency": currency,
                    "country": country,
                    "sector": sector,
                    "fx_exposure": fx_exposure,
                    "risks": geopolitical_risks,
                    "risk_count": len(geopolitical_risks)
                }
            }]

            # 프롬프트 생성
            risks_text = "\n".join(f"- {risk}" for risk in geopolitical_risks) if geopolitical_risks else "- 특별한 리스크 없음"

            # 종목명 가져오기
            stock_name = self._get_stock_name_for_agent(ticker)
            stock_display = f"{stock_name}({ticker})" if stock_name else ticker

            prompt = f"""당신은 Geopolitical Analyst 전문가입니다.
{stock_display} 종목의 지정학적 리스크와 환율 영향을 평가하세요.

## 분석 정보
- 국가: {country}
- 통화: {currency}
- 섹터: {sector}
- 환율 노출도: {fx_exposure}

## 식별된 지정학적 리스크
{risks_text}

다음 JSON 형식으로만 응답하세요:
{{
  "signal": "buy" 또는 "sell" 또는 "neutral",
  "confidence": 0-10,
  "reasoning": "판단 근거 (지정학적 관점에서, 최소 3문장)"
}}

지침:
- 리스크가 3개 이상이거나 HIGH 환율 노출이면 → 보수적 판단 (매도 or 중립)
- 리스크가 적고 안정적이면 → 긍정적 신호 가능
- 환율이 유리하게 움직이는 구간이면 언급"""

            response = self._call_llm(prompt)
            signal, confidence, reasoning = self._parse_response(response)

            # 리스크 과다 시 신호 조정
            if len(geopolitical_risks) >= 3 and signal == "buy":
                confidence = max(1.0, confidence - 2.0)
                reasoning += " [경고: 지정학적 리스크 높음]"

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
                reasoning=f"Geopolitical Analysis Error: {str(e)}",
                evidence=[],
                llm_provider=self.llm_provider,
                execution_time=execution_time,
                error=str(e)
            )


class ValueInvestor(BaseAgent):
    """가치 투자 전문가 (Warren Buffett/Benjamin Graham 스타일) - Fincept Terminal 벤치마킹"""

    def __init__(self, llm_provider: str = None):
        if llm_provider is None:
            llm_provider = os.getenv('DEFAULT_LLM_PROVIDER', 'ollama')
        super().__init__(
            name="Value Investor",
            tools=[],  # 별도 분석 로직 사용
            llm_provider=llm_provider
        )

    def analyze(self, ticker: str, analysis_tools: AnalysisTools) -> AgentResult:
        """Warren Buffett/Benjamin Graham 가치 투자 원칙 적용"""
        start_time = datetime.now()

        try:
            import yfinance as yf

            stock = yf.Ticker(ticker)
            info = stock.info or {}

            # 1. 재무 지표 수집
            pe_ratio = info.get('trailingPE')
            forward_pe = info.get('forwardPE')
            pb_ratio = info.get('priceToBook')
            roe = info.get('returnOnEquity')
            debt_to_equity = info.get('debtToEquity')
            profit_margin = info.get('profitMargins')
            current_price = info.get('currentPrice', info.get('regularMarketPrice'))

            # 2. 안전마진 (Margin of Safety) 계산
            margin_of_safety = None
            if forward_pe and forward_pe > 0:
                # 간단한 내재가치 추정: 정상 P/E 15 가정
                intrinsic_pe = 15
                if forward_pe < intrinsic_pe:
                    margin_of_safety = (intrinsic_pe - forward_pe) / intrinsic_pe * 100

            # 3. 퀄리티 체크 (해자/Moat)
            quality_score = 0
            quality_factors = []

            if roe and roe > 0.15:  # ROE > 15%
                quality_score += 2
                quality_factors.append(f"높은 ROE {roe:.1%}")
            elif roe and roe > 0.10:
                quality_score += 1
                quality_factors.append(f"양호한 ROE {roe:.1%}")

            if profit_margin and profit_margin > 0.20:  # 이익률 > 20%
                quality_score += 2
                quality_factors.append(f"높은 이익률 {profit_margin:.1%}")
            elif profit_margin and profit_margin > 0.10:
                quality_score += 1
                quality_factors.append(f"양호한 이익률 {profit_margin:.1%}")

            if debt_to_equity is not None and debt_to_equity < 50:  # 부채비율 < 50%
                quality_score += 2
                quality_factors.append(f"낮은 부채비율 {debt_to_equity:.1f}%")
            elif debt_to_equity is not None and debt_to_equity < 100:
                quality_score += 1
                quality_factors.append(f"적정 부채비율 {debt_to_equity:.1f}%")

            # 4. 밸류에이션
            valuation = "UNKNOWN"
            if pe_ratio:
                if pe_ratio < 15:
                    valuation = "UNDERVALUED"
                elif pe_ratio < 25:
                    valuation = "FAIR"
                else:
                    valuation = "OVERVALUED"

            # 증거 구성
            evidence = [{
                "tool": "value_investing_analysis",
                "result": {
                    "pe_ratio": pe_ratio,
                    "forward_pe": forward_pe,
                    "pb_ratio": pb_ratio,
                    "roe": roe,
                    "debt_to_equity": debt_to_equity,
                    "profit_margin": profit_margin,
                    "quality_score": quality_score,
                    "quality_factors": quality_factors,
                    "valuation": valuation,
                    "margin_of_safety": margin_of_safety,
                    "current_price": current_price
                }
            }]

            # 프롬프트 생성
            quality_text = "\n".join(f"- {f}" for f in quality_factors) if quality_factors else "- 데이터 부족"

            # 지표 포매팅 (조건부 표현식 미리 계산)
            pe_str = f"{pe_ratio:.2f}" if pe_ratio else 'N/A'
            forward_pe_str = f"{forward_pe:.2f}" if forward_pe else 'N/A'
            pb_str = f"{pb_ratio:.2f}" if pb_ratio else 'N/A'
            roe_str = f"{roe:.1%}" if roe else 'N/A'
            debt_str = f"{debt_to_equity:.1f}%" if debt_to_equity is not None else 'N/A'
            margin_str = f"{profit_margin:.1%}" if profit_margin else 'N/A'
            safety_str = f"{margin_of_safety:+.1f}%" if margin_of_safety else 'N/A'

            # 종목명 가져오기
            stock_name = self._get_stock_name_for_agent(ticker)
            stock_display = f"{stock_name}({ticker})" if stock_name else ticker

            prompt = f"""당신은 Value Investor 전문가입니다 (Warren Buffett/Benjamin Graham 철학).
{stock_display} 종목을 가치 투자 관점에서 분석하세요.

## 재무 지표
- P/E Ratio: {pe_str}
- Forward P/E: {forward_pe_str}
- P/B Ratio: {pb_str}
- ROE: {roe_str}
- 부채비율: {debt_str}
- 이익률: {margin_str}

## 퀄리티 평가
- 퀄리티 점수: {quality_score}/6
{quality_text}

## 밸류에이션
- 현재 평가: {valuation}
- 안전마진: {safety_str}

다음 JSON 형식으로만 응답하세요:
{{
  "signal": "buy" 또는 "sell" 또는 "neutral",
  "confidence": 0-10,
  "reasoning": "가치 투자 관점의 판단 근거 (최소 3문장)"
}}

Warren Buffett 원칙:
1. 훌륭한 기업 (ROE, 이익률, 해자)
2. 합리적인 가격 (P/E < 25, 안전마진 존재)
3. 장기 보유 가능성

Benjamin Graham 원칙:
1. 안전마진 확보 (내재가치 > 현재가)
2. 재무 건전성 (낮은 부채비율)
3. 저평가 (P/E, P/B 낮음)"""

            response = self._call_llm(prompt)
            signal, confidence, reasoning = self._parse_response(response)

            # 과대평가 시 신호 조정
            if valuation == "OVERVALUED" and signal == "buy":
                confidence = max(1.0, confidence - 3.0)
                reasoning += " [경고: 밸류에이션 과대평가]"

            # 퀄리티 낮으면 신뢰도 하락
            if quality_score < 2 and signal == "buy":
                confidence = max(1.0, confidence - 2.0)
                reasoning += " [경고: 기업 퀄리티 낮음]"

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
                reasoning=f"Value Investing Analysis Error: {str(e)}",
                evidence=[],
                llm_provider=self.llm_provider,
                execution_time=execution_time,
                error=str(e)
            )


class DecisionMaker:
    """최종 의사결정자 - 에이전트 의견 종합 및 충돌 해결"""

    def __init__(self, llm_provider: str = None):
        self.name = "Decision Maker"
        if llm_provider is None:
            llm_provider = os.getenv('DEFAULT_LLM_PROVIDER', 'ollama')
        self.llm_provider = llm_provider

    def aggregate(self, ticker: str, agent_results: List[AgentResult]) -> Dict[str, Any]:
        """
        에이전트 결과 종합 및 최종 판단

        Args:
            ticker: 종목 심볼
            agent_results: 에이전트 분석 결과 리스트

        Returns:
            최종 판단 결과
        """

        # 에이전트 의견 집계 (실패/거짓-neutral 제외 + confidence 가중)
        signals = {"buy": 0, "sell": 0, "neutral": 0}
        weighted_signals = {"buy": 0.0, "sell": 0.0, "neutral": 0.0}
        total_confidence = 0.0
        valid_results = 0
        excluded_failed = 0

        for result in agent_results:
            # 명시적 에러는 제외
            if result.error:
                excluded_failed += 1
                continue
            # confidence=0 + neutral 조합은 LLM 호출 실패의 산물 → 다수결 오염 방지
            if result.confidence == 0.0 and result.signal == "neutral":
                excluded_failed += 1
                continue
            signals[result.signal] += 1
            weighted_signals[result.signal] += result.confidence
            total_confidence += result.confidence
            valid_results += 1

        # 프롬프트 생성
        prompt = self._build_decision_prompt(ticker, agent_results, signals)

        # LLM 호출 (듀얼 노드 지원)
        try:
            response = self._call_llm(prompt)
            decision = self._parse_decision(response)

            # 기본값 추가
            decision["agent_count"] = len(agent_results)
            decision["valid_agent_count"] = valid_results
            decision["excluded_failed_count"] = excluded_failed
            decision["signal_distribution"] = signals
            decision["weighted_signal_distribution"] = {
                k: round(v, 2) for k, v in weighted_signals.items()
            }
            decision["analyzed_at"] = datetime.now().isoformat()

            # 신뢰도 칼리브레이션 (과거 적중률 기반)
            # 학습 데이터 부족 시 raw 그대로 반환됨
            try:
                sys.path.insert(0, _SERVICE_DIR) if _SERVICE_DIR not in sys.path else None
                from signal_tracker import get_calibrator
                calib = get_calibrator(horizon=7)
                raw_conf = float(decision.get("final_confidence", 0))
                final_signal = decision.get("final_signal", "neutral")
                adjusted = calib.adjust(raw_conf, final_signal)
                if adjusted != raw_conf:
                    decision["raw_confidence"] = round(raw_conf, 2)
                    decision["final_confidence"] = adjusted
                    decision["calibration_applied"] = True
                    decision["calibration_status"] = calib.status()
                else:
                    decision["calibration_applied"] = False
                    decision["calibration_status"] = calib.status()
            except Exception:
                decision["calibration_applied"] = False

            return decision

        except Exception as e:
            # 폴백: confidence 가중 다수결
            if any(weighted_signals.values()):
                majority_signal = max(weighted_signals.items(), key=lambda x: x[1])[0]
            else:
                majority_signal = "neutral"
            avg_confidence = (total_confidence / valid_results) if valid_results else 0

            consensus_msg = (
                f"{signals['buy']}명 매수, {signals['sell']}명 매도, {signals['neutral']}명 중립"
            )
            if excluded_failed:
                consensus_msg += f" (실패 {excluded_failed}명 제외)"

            return {
                "final_signal": majority_signal,
                "final_confidence": avg_confidence,
                "consensus": consensus_msg,
                "conflicts": "Decision Maker 오류로 confidence 가중 다수결 적용",
                "reasoning": "최종 LLM 의사결정 실패. 유효 에이전트의 confidence 가중치로 결론.",
                "key_risks": ["Decision Maker 실행 실패", "내부 LLM 일시 장애"],
                "agent_count": len(agent_results),
                "valid_agent_count": valid_results,
                "excluded_failed_count": excluded_failed,
                "signal_distribution": signals,
                "weighted_signal_distribution": {k: round(v, 2) for k, v in weighted_signals.items()},
                "analyzed_at": datetime.now().isoformat(),
                "error": "Decision Maker 호출 실패"  # 사용자에게는 내부 메시지 노출 안 함
            }

    def _build_decision_prompt(self, ticker: str, agent_results: List[AgentResult], signals: Dict[str, int]) -> str:
        """의사결정 프롬프트 생성"""

        # 종목명 가져오기
        stock_name = None
        try:
            if ticker.endswith('.KS') or ticker.endswith('.KQ') or (ticker.isdigit() and len(ticker) == 6):
                import json
                import os
                favorites_file = os.path.join(os.path.dirname(__file__), 'korean_stock_favorites.json')
                if os.path.exists(favorites_file):
                    with open(favorites_file, 'r', encoding='utf-8') as f:
                        favorites = json.load(f)
                        code = ticker.replace('.KS', '').replace('.KQ', '')
                        if code in favorites:
                            stock_name = favorites[code]
        except:
            pass

        stock_display = f"{stock_name}({ticker})" if stock_name else ticker

        prompt = f"""당신은 최종 의사결정자입니다.
여러 전문가의 {stock_display} 분석 결과를 종합하여 최종 판단을 내리세요.

## 전문가 의견 요약
총 {len(agent_results)}명의 전문가 의견:
- 매수: {signals['buy']}명
- 매도: {signals['sell']}명
- 중립: {signals['neutral']}명

## 전문가별 상세 의견
"""

        def _sanitize(s) -> str:
            # 프롬프트 인젝션 방지: 제어 문자/JSON 구조 파괴 문자 제거
            if s is None or not s:
                return ""
            # str로 변환 (다른 타입 처리)
            s = str(s)
            return (
                s.replace("\n", " ")
                 .replace("\r", " ")
                 .replace("`", "'")
                 .replace("}", "")
                 .replace("{", "")
                 .strip()
            )

        for result in agent_results:
            prompt += f"\n### {result.agent_name} ({_sanitize(result.llm_provider)})"
            prompt += f"\n- 신호: {_sanitize(result.signal)}"
            prompt += f"\n- 신뢰도: {result.confidence:.1f}/10"
            prompt += f"\n- 근거: {_sanitize(result.reasoning)[:200]}"
            if result.error:
                prompt += f"\n- 오류: {_sanitize(result.error)[:100]}"
            prompt += "\n"

        prompt += """
## 요구사항
1. 전문가 의견이 일치하면 → 그 방향으로 최종 판단
2. 의견이 충돌하면 → 각 의견의 근거 강도를 평가하고 조정
3. 소수 의견도 리스크로 반영 (예: 5명 매수, 1명 매도 → "매수하되 X 리스크 주의")
4. 각 전문가의 신뢰도를 가중치로 고려 (신뢰도 9 vs 3은 동등하지 않음)

## 충돌 해결 우선순위 (추세 vs 평균회귀)
- Quant Analyst의 regime이 "trending" (Hurst > 0.6)이면 → 추세 추종 전략 우선
  · Mean reversion 신호(예: RSI 과매수)는 "추세 강도 확인용"으로만 활용
- regime이 "mean_reverting" (Hurst < 0.4)이면 → 평균 회귀 전략 우선
  · Trend-following 신호는 "단기 노이즈"로 처리
- regime이 "random_walk" 또는 모호하면 → 리스크 관리 신호(Risk Manager)에 가중치
- 거래량 부족 경고가 있으면 → confidence를 보수적으로 (최대 -2 감점)

다음 JSON 형식으로만 응답하세요:
{
  "final_signal": "buy/sell/neutral",
  "final_confidence": 0-10,
  "consensus": "의견 분포 요약",
  "conflicts": "의견 충돌 시 조정 과정 설명 (regime 기반 우선순위 명시)",
  "reasoning": "최종 판단 근거 (3-5문장)",
  "key_risks": ["주요 리스크1", "주요 리스크2"]
}"""

        return prompt

    def _call_llm(self, prompt: str) -> str:
        """LLM 호출 (LiteLLM Router 경유 — BaseAgent와 동일하게 통일)."""
        try:
            from llm.router import call_agent_llm, get_router
            from llm.schemas import DecisionMakerResponse
            resp = call_agent_llm(get_router(), self.name, prompt, DecisionMakerResponse)
            return json.dumps(
                {
                    "final_signal": resp.final_signal,
                    "final_confidence": resp.final_confidence,
                    "consensus": resp.consensus,
                    "conflicts": resp.conflicts,
                    "reasoning": resp.reasoning,
                    "key_risks": resp.key_risks,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            # Router import/초기화 실패 시만 여기 진입 (call_agent_llm는 예외 미방출)
            return json.dumps(
                {
                    "final_signal": "neutral",
                    "final_confidence": 0.0,
                    "consensus": "LLM Router 오류",
                    "conflicts": "None",
                    "reasoning": f"LLM Router 오류: {exc}",
                    "key_risks": ["LLM_ROUTER_ERROR"],
                },
                ensure_ascii=False,
            )

    def _call_gemini(self, prompt: str) -> str:
        """Gemini API 호출"""
        try:
            import google.generativeai as genai

            api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
            if not api_key:
                return json.dumps({
                    "final_signal": "neutral",
                    "final_confidence": 0,
                    "consensus": "Gemini API key not found",
                    "conflicts": "None",
                    "reasoning": "Gemini API key not configured",
                    "key_risks": ["API key missing"]
                }, ensure_ascii=False)

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'))

            response = model.generate_content(prompt)
            return response.text

        except Exception as e:
            return json.dumps({
                "final_signal": "neutral",
                "final_confidence": 0,
                "consensus": "Gemini service error",
                "conflicts": "None",
                "reasoning": f"Gemini API error: {str(e)[:100]}",
                "key_risks": ["Gemini service failure"]
            }, ensure_ascii=False)

    def _call_openai(self, prompt: str) -> str:
        """OpenAI API 호출"""
        from openai import OpenAI

        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY 환경변수 미설정")

        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert decision maker for stock trading. Always respond in valid JSON format."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,  # 결정론적 출력을 위해 0으로 고정
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

    def __init__(self, llm_provider: str = None, agent_providers: Dict[str, str] = None):
        """
        Args:
            llm_provider: 모든 에이전트가 사용할 기본 LLM provider ('gemini', 'openai', 'ollama')
            agent_providers: 특정 에이전트별 provider 설정 (선택사항)
                예: {"Technical Analyst": "gemini", "ML Specialist": "openai"}
        """
        # 기본 provider 설정
        if llm_provider is None:
            llm_provider = os.getenv('DEFAULT_LLM_PROVIDER', 'ollama')

        # dual_node_config 에서 에이전트별 provider 자동 로드
        # (agent_providers 명시 인수가 있으면 그걸 우선)
        if agent_providers is None:
            agent_providers = {}
        try:
            from dual_node_config import get_llm_config as _get_cfg
            _agent_names = [
                "Technical Analyst", "Quant Analyst", "Risk Manager",
                "ML Specialist", "Event Analyst", "Geopolitical Analyst",
                "Value Investor", "Decision Maker",
            ]
            for _name in _agent_names:
                if _name not in agent_providers:
                    _p = _get_cfg(_name).get("provider", "ollama")
                    if _p != "ollama":  # ollama 는 기존 _call_ollama 로 처리
                        agent_providers[_name] = _p
        except Exception:
            pass

        # Ollama 를 쓰는 에이전트가 있으면 헬스체크
        self.ollama_healthy = True
        _all_providers = set(agent_providers.values()) | {llm_provider}
        if "ollama" in _all_providers:
            self.ollama_healthy = self._check_ollama_health()

        # 에이전트 생성 — 각 에이전트별 provider 는 agent_providers 로 결정
        self.agents = [
            TechnicalAnalyst(agent_providers.get("Technical Analyst", llm_provider)),
            QuantAnalyst(agent_providers.get("Quant Analyst", llm_provider)),
            RiskManager(agent_providers.get("Risk Manager", llm_provider)),
            MLSpecialist(agent_providers.get("ML Specialist", llm_provider)),
            EventAnalyst(agent_providers.get("Event Analyst", llm_provider)),
            GeopoliticalAnalyst(agent_providers.get("Geopolitical Analyst", llm_provider)),
            ValueInvestor(agent_providers.get("Value Investor", llm_provider)),
        ]

        # 병렬 실행 워커 수 설정
        self.max_workers = int(os.getenv('MULTI_AGENT_MAX_WORKERS', '2'))

        # Mac Studio 연결 확인
        self.mac_studio_available = False
        try:
            from dual_node_config import is_mac_studio_available
            self.mac_studio_available = is_mac_studio_available()
            if not self.mac_studio_available:
                print("  ⚠️ Mac Studio 연결 불가 - 로컬 GPU 전용 모드 (병렬 제한: 2)")
                self.max_workers = 2
        except Exception:
            pass

        # Decision Maker provider — dual_node_config 에서 읽거나 기본값 사용
        _dm_provider = agent_providers.get("Decision Maker", llm_provider)
        try:
            from enhanced_decision_maker import EnhancedDecisionMaker
            self.decision_maker = EnhancedDecisionMaker(_dm_provider)
        except ImportError:
            self.decision_maker = DecisionMaker(_dm_provider)

    def _check_ollama_health(self) -> bool:
        """Ollama 서버 상태 체크"""
        try:
            import requests
            ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            response = requests.get(f"{ollama_url}/api/tags", timeout=3)
            if response.status_code == 200:
                # 모델 목록 확인
                tags = response.json().get('models', [])
                if len(tags) > 0:
                    print(f"  ✅ Ollama 서버 정상 ({len(tags)}개 모델 사용 가능)")
                    return True
                else:
                    print("  ⚠️ Ollama 서버는 실행 중이나 모델 없음")
                    return False
            else:
                print(f"  ❌ Ollama 서버 응답 이상: {response.status_code}")
                return False
        except requests.exceptions.Timeout:
            # 콘솔 로그 제거 - 이미 ollama_healthy 상태로 파악 가능
            return False
        except requests.exceptions.ConnectionError:
            # 콘솔 로그 제거 - 이미 ollama_healthy 상태로 파악 가능
            return False
        except Exception:
            # 콘솔 로그 제거 - 이미 ollama_healthy 상태로 파악 가능
            return False

    def _get_stock_name(self, ticker: str) -> Optional[str]:
        """티커로부터 종목명 가져오기 (한글명 우선)"""
        try:
            # 한국 주식인 경우 종목명 조회
            if ticker.endswith('.KS') or ticker.endswith('.KQ') or (ticker.isdigit() and len(ticker) == 6):
                code = ticker.replace('.KS', '').replace('.KQ', '')

                # 1. korean_stocks_database.json 최우선 확인
                try:
                    import json
                    import os
                    db_file = os.path.join(os.path.dirname(__file__), 'korean_stocks_database.json')
                    if os.path.exists(db_file):
                        with open(db_file, 'r', encoding='utf-8') as f:
                            db_data = json.load(f)
                            stocks = db_data.get('stocks', {})
                            if code in stocks:
                                return stocks[code]['name']
                except:
                    pass

                # 2. korean_stock_favorites.json 확인
                try:
                    import json
                    import os
                    favorites_file = os.path.join(os.path.dirname(__file__), 'korean_stock_favorites.json')
                    if os.path.exists(favorites_file):
                        with open(favorites_file, 'r', encoding='utf-8') as f:
                            favorites = json.load(f)
                            if code in favorites:
                                return favorites[code]
                except:
                    pass

                # 3. KoreanStockData에서 시도 (영문명 반환될 수 있음)
                try:
                    from korean_stocks import KoreanStockData
                    ksd = KoreanStockData()
                    name = ksd.get_stock_name(ticker)
                    if name and name != ticker:  # 실제 종목명을 가져온 경우
                        return name
                except:
                    pass

            # 기타 주식의 경우 yfinance에서 종목명 시도
            try:
                import yfinance as yf
                stock = yf.Ticker(ticker)
                info = stock.info
                if info:
                    name = info.get('longName') or info.get('shortName')
                    if name:
                        return name
            except:
                pass

        except Exception:
            pass

        return None

    def analyze(self, ticker: str) -> Dict[str, Any]:
        """
        멀티에이전트 분석 실행

        Args:
            ticker: 종목 심볼

        Returns:
            최종 분석 결과
        """

        # 한국 주식 종목명 가져오기
        stock_name = self._get_stock_name(ticker)

        if stock_name:
            print(f"\n[MultiAgent] {stock_name}({ticker}) 분석 시작...")
        else:
            print(f"\n[MultiAgent] {ticker} 분석 시작...")
        start_time = datetime.now()
        warnings = []

        # Ollama 장애 시 경고
        if not self.ollama_healthy and hasattr(self, 'agents'):
            ollama_agents = [a.name for a in self.agents if a.llm_provider == 'ollama']
            if ollama_agents:
                warnings.append(f"⚠️ Ollama 서버 장애로 {len(ollama_agents)}개 에이전트가 실패할 수 있습니다")
                print(f"  ⚠️ 경고: Ollama 서버 장애 감지 - {', '.join(ollama_agents[:3])}... 에이전트 영향")

        try:
            # 0. 한글 포함 여부 체크 - 한글이 있으면 바로 종목 추천
            import re
            has_korean = bool(re.search(r'[가-힣]', ticker))

            if has_korean:
                # 한글이 포함되어 있으면 바로 종목 추천 시도
                from ticker_suggestion import suggest_ticker

                suggestion_result = suggest_ticker(ticker, max_results=5)

                # 95% 이상 매치가 있으면 자동 선택
                if suggestion_result['best_match']:
                    best = suggestion_result['suggestions'][0]
                    warnings.append(f"종목 자동 매칭: {ticker} → {best['ticker']} ({best['name']})")
                    ticker = best['ticker']
                    print(f"  ✅ 자동 선택: {best['name']} ({best['ticker']}) [{best['score']*100:.0f}%]")
                else:
                    # 추천 목록 반환
                    if suggestion_result['found']:
                        return {
                            "ticker": ticker,
                            "multi_agent_mode": True,
                            "error": "정확한 종목을 찾을 수 없습니다. 아래 추천 목록에서 선택해주세요.",
                            "suggestions": suggestion_result['suggestions'],
                            "suggestion_message": suggestion_result['formatted'],
                            "analyzed_at": datetime.now().isoformat(),
                        }
                    else:
                        return {
                            "ticker": ticker,
                            "multi_agent_mode": True,
                            "error": f"'{ticker}'와 일치하는 종목을 찾을 수 없습니다",
                            "suggestions": None,
                            "suggestion_message": "일치하는 종목을 찾을 수 없습니다",
                            "analyzed_at": datetime.now().isoformat(),
                        }

            # 한글이 없으면 기존 티커 형식 검증
            from ticker_validator import validate_ticker, get_market_info, fix_common_ticker_errors

            is_valid, fixed_ticker, error_msg = validate_ticker(ticker)
            if not is_valid:
                if fixed_ticker:
                    warnings.append(f"티커 자동 수정: {ticker} → {fixed_ticker}")
                    ticker = fixed_ticker
                else:
                    # 자동 수정 시도
                    auto_fixed = fix_common_ticker_errors(ticker)
                    if auto_fixed:
                        warnings.append(f"티커 자동 수정: {ticker} → {auto_fixed}")
                        ticker = auto_fixed
                    else:
                        # 형식이 유효하지 않아도 추천 시도
                        from ticker_suggestion import suggest_ticker

                        suggestion_result = suggest_ticker(ticker, max_results=5)

                        # 95% 이상 매치가 있으면 자동 선택
                        if suggestion_result['best_match']:
                            best = suggestion_result['suggestions'][0]
                            warnings.append(f"종목 자동 매칭: {ticker} → {best['ticker']} ({best['name']})")
                            ticker = best['ticker']
                            print(f"  ✅ 자동 선택: {best['name']} ({best['ticker']}) [{best['score']*100:.0f}%]")
                        else:
                            # 추천 목록 반환
                            return {
                                "ticker": ticker,
                                "multi_agent_mode": True,
                                "error": f"유효하지 않은 티커 형식: {error_msg}",
                                "suggestions": suggestion_result['suggestions'] if suggestion_result['found'] else None,
                                "suggestion_message": suggestion_result['formatted'] if suggestion_result['found'] else "일치하는 종목을 찾을 수 없습니다",
                                "analyzed_at": datetime.now().isoformat(),
                            }

            # 0.5. 종목 실제 존재 여부 검증 (중요!)
            from ticker_verifier import verify_and_validate

            verification = verify_and_validate(ticker)

            if not verification['exists']:
                # 종목이 존재하지 않음 - 유사 종목 추천
                from ticker_suggestion import suggest_ticker

                suggestion_result = suggest_ticker(ticker, max_results=5)

                error_msgs = verification.get('errors', [])
                warn_msgs = verification.get('warnings', [])

                return {
                    "ticker": ticker,
                    "multi_agent_mode": True,
                    "error": "종목을 찾을 수 없습니다",
                    "details": {
                        "errors": error_msgs,
                        "warnings": warn_msgs,
                        "recommendation": verification.get('recommendation', '종목 코드를 다시 확인해주세요')
                    },
                    "suggestions": suggestion_result['suggestions'] if suggestion_result['found'] else None,
                    "suggestion_message": suggestion_result['formatted'] if suggestion_result['found'] else "일치하는 종목을 찾을 수 없습니다",
                    "analyzed_at": datetime.now().isoformat(),
                }

            # 분석 가능 여부 확인
            if not verification['can_analyze']:
                return {
                    "ticker": ticker,
                    "multi_agent_mode": True,
                    "company_name": verification.get('company_name'),
                    "error": "데이터 부족으로 분석 불가",
                    "details": {
                        "data_quality": verification.get('data_quality'),
                        "errors": verification.get('errors', []),
                        "warnings": verification.get('warnings', []),
                        "recommendation": verification.get('recommendation')
                    },
                    "analyzed_at": datetime.now().isoformat(),
                }

            # 회사명 확인됨 - 경고에 추가
            if verification.get('company_name'):
                print(f"  종목 확인: {verification['company_name']} ({ticker})")

            # 데이터 품질 경고 추가
            if verification.get('warnings'):
                warnings.extend(verification['warnings'])

            market_info = get_market_info(ticker)

            # 1. 데이터 수집
            print(f"  [1/3] 데이터 수집 중...")
            df = fetch_ohlcv(ticker)

            # 데이터 검증
            if df is None or df.empty:
                return {
                    "ticker": ticker,
                    "multi_agent_mode": True,
                    "error": "데이터 수집 실패: 종목 데이터를 가져올 수 없습니다",
                    "analyzed_at": datetime.now().isoformat(),
                }

            if len(df) < 100:
                warnings.append(f"데이터 부족: {len(df)}개 (최소 권장 100개)")

            df = calculate_indicators(df)
            tools = AnalysisTools(ticker, df)

            # 2. 병렬 에이전트 실행 (GPU 메모리 보호)
            print(f"  [2/3] {len(self.agents)}개 에이전트 병렬 실행 중 (워커: {self.max_workers})")
            agent_results = []

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # 각 에이전트에 작업 제출
                futures = {
                    executor.submit(agent.analyze, ticker, tools): agent
                    for agent in self.agents
                }

                # 완료된 작업 수집
                # MULTI_AGENT_TIMEOUT 으로 조정 가능 (.env). 워커 < 에이전트 수면
                # 직렬 가깝게 처리되므로 보수적 기본 300초.
                _ma_timeout = int(os.getenv("MULTI_AGENT_TIMEOUT", "300"))
                for future in as_completed(futures, timeout=_ma_timeout):
                    agent = futures[future]
                    try:
                        # future가 이미 as_completed 로 완료된 상태라 즉시 반환되지만,
                        # 안전을 위해 LLM 호출 timeout 보다 살짝 길게 둠.
                        result = future.result(timeout=int(os.getenv("MULTI_AGENT_LLM_TIMEOUT", "240")) + 10)
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

            # 4. 실전 진입 계획 생성 (매매 시점/분할/손절익절)
            try:
                sys.path.insert(0, _SERVICE_DIR) if _SERVICE_DIR not in sys.path else None
                from analysis_tools import AnalysisTools as _AT
                _at = _AT(ticker, df)

                # agent_results에서 evidence(도구 결과)를 평면화하여 진입 계획 입력으로
                flat_evidence = []
                for ar in agent_results:
                    if ar.evidence:
                        flat_evidence.extend(ar.evidence)

                entry_signal = final_decision.get("final_signal", "neutral")
                entry_confidence = float(final_decision.get("final_confidence", 5.0))
                entry_result = _at.entry_plan_analysis(
                    signal=entry_signal,
                    confidence=entry_confidence,
                    other_results=flat_evidence,
                )
                final_decision["entry_plan"] = entry_result.get("entry_plan")
                final_decision["entry_plan_formatted"] = entry_result.get("formatted")
            except Exception as _e:
                # 진입 계획 생성 실패는 전체 분석을 중단시키지 않음
                final_decision["entry_plan"] = None
                final_decision["entry_plan_error"] = "진입 계획 생성 실패"

            total_time = (datetime.now() - start_time).total_seconds()

            # 결과 구성
            result = {
                "ticker": ticker,
                "company_name": verification.get('company_name'),
                "multi_agent_mode": True,
                "market_info": market_info,
                "data_quality": verification.get('data_quality'),
                "warnings": warnings if warnings else None,
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
                "data_quality": {
                    "total_rows": len(df),
                    "has_sufficient_data": len(df) >= 100
                }
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