# Stock AI Agent — 차기 버전 (V2.0) 개발 계획서

**작성일:** 2026-04-14
**대상 버전:** V2.0 (MCP 서버 + 멀티에이전트 + 포트폴리오 리밸런싱)
**현재 버전:** V1.0 (16개 분석 도구 + ML 앙상블 + HyperOpt + Walk-Forward)

---

## 1. Executive Summary

### 1.1 현재 상태 (V1.0 완료)

| 기능 영역 | 현황 | 코드량 |
|---|---|---|
| 기술 분석 | 16개 도구 (SMA, RSI, 볼린저, MACD, ADX, 거래량, 피보나치, 변동성, 평균회귀, 모멘텀, 지지저항, 자기상관, 리스크, 켈리, 베타, 이벤트) | 1,761줄 |
| ML 예측 | RF, GB, **LightGBM, XGBoost, LSTM** 앙상블 + **SHAP 설명력** | 502줄 |
| 백테스트 | SMA Cross, RSI Reversion, Bollinger Reversion, Composite + **HyperOpt** + **Walk-Forward** | 517줄 |
| 페이퍼 트레이딩 | 기본 주문 + **Trailing Stop** + **시간 기반 청산** | 340줄 |
| 포트폴리오 | Markowitz, Risk Parity | 225줄 |
| 데이터 수집 | yfinance + 4개 확장 모듈 (뉴스, 차트패턴, 섹터, 매크로) | 1,009줄 |
| WebUI | Streamlit 7개 페이지 | 2,155줄 |
| **합계** | | **~6,500줄** |

### 1.2 V2.0 목표

**핵심 목표:** 외부 AI 에이전트와의 연동 + 내부 역할 분리 + 자동화 강화

| 우선순위 | 기능 | 참고 프로젝트 | 예상 공수 |
|:---:|---|---|:---:|
| **6** | **MCP 서버 노출** | OpenBB | 1주 |
| **7** | **멀티에이전트 아키텍처** | PRISM-INSIGHT | 2주 |
| **8** | **포트폴리오 리밸런싱 자동화** | FinRL | 1주 |
| 9 | 실시간 데이터 스트리밍 (선택) | NautilusTrader | 3주 |
| 10 | 성능 최적화 (선택) | vectorbt | 2주 |

**예상 총 개발 기간:** 4주 (코어 기능 6-8번만) ~ 9주 (전체 포함)

---

## 2. 우선순위 6: MCP 서버 노출 (OpenBB 참조)

### 2.1 개요

**목표:** 16개 분석 도구 + ML/백테스트 기능을 Model Context Protocol 서버로 노출하여, Claude Desktop, ChatGPT, 기타 AI 에이전트에서 직접 호출 가능하게 함.

**참고 프로젝트:**
- [OpenBB](https://github.com/OpenBB-finance/OpenBB): MCP server로 금융 데이터 API 노출
- [MCP Specification](https://modelcontextprotocol.io/): Anthropic 공식 스펙

### 2.2 기술 스택

```
mcp-server (Python SDK)
├── mcp-python >= 0.3.0
├── pydantic >= 2.0
└── asyncio (표준 라이브러리)
```

### 2.3 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│ Claude Desktop / ChatGPT / Custom AI Agent                  │
└────────────────────┬────────────────────────────────────────┘
                     │ MCP Protocol (stdio/SSE)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ mcp_server.py (FastMCP)                                     │
│ ┌─────────────┬─────────────┬─────────────┬───────────────┐ │
│ │ Technical   │ ML Predict  │ Backtest    │ Portfolio     │ │
│ │ Tools (16)  │ (5 models)  │ (HyperOpt)  │ (Optimize)    │ │
│ └─────────────┴─────────────┴─────────────┴───────────────┘ │
│                              │                               │
│                              ▼                               │
│                     local_engine.py                          │
└─────────────────────────────────────────────────────────────┘
```

### 2.4 구현 계획

#### Phase 1: MCP 서버 기본 골격 (Day 1-2)

**파일:** `mcp_server.py`

```python
from mcp.server.fastmcp import FastMCP
from local_engine import (
    engine_scan_ticker,
    engine_ml_predict,
    engine_backtest_optimize,
    engine_backtest_walk_forward,
    engine_portfolio_optimize,
)

mcp = FastMCP("Stock AI Agent")

@mcp.tool()
def analyze_stock(ticker: str) -> dict:
    """Analyze a stock using 16 technical analysis tools"""
    return engine_scan_ticker(ticker)

@mcp.tool()
def predict_ml(ticker: str, use_ensemble: bool = True) -> dict:
    """Predict stock direction using ML ensemble (LightGBM, XGBoost, LSTM)"""
    return engine_ml_predict(ticker, ensemble=use_ensemble)

@mcp.tool()
def optimize_strategy(ticker: str, strategy: str = "rsi_reversion") -> dict:
    """Optimize backtest strategy parameters using Optuna"""
    return engine_backtest_optimize(ticker, strategy, n_trials=30)

@mcp.tool()
def backtest_walk_forward(ticker: str, strategy: str = "rsi_reversion") -> dict:
    """Walk-forward backtest to detect overfitting"""
    return engine_backtest_walk_forward(ticker, strategy, n_splits=3)

@mcp.tool()
def optimize_portfolio(method: str = "markowitz") -> dict:
    """Optimize portfolio allocation (Markowitz or Risk Parity)"""
    return engine_portfolio_optimize(method)

if __name__ == "__main__":
    mcp.run()
```

**설치:**
```bash
pip install mcp
```

**Claude Desktop 설정:** `~/Library/Application Support/Claude/claude_desktop_config.json`
```json
{
  "mcpServers": {
    "stock-ai": {
      "command": "python",
      "args": ["/home/ubuntu/stock_auto/mcp_server.py"]
    }
  }
}
```

#### Phase 2: 개별 도구 노출 (Day 3-4)

**목표:** 16개 도구를 개별 MCP tool로 노출

```python
from analysis_tools import AnalysisTools
from data_collector import fetch_ohlcv, calculate_indicators

@mcp.tool()
def rsi_analysis(ticker: str) -> dict:
    """Analyze RSI divergence for a stock"""
    df = fetch_ohlcv(ticker)
    df = calculate_indicators(df)
    tools = AnalysisTools(ticker, df)
    return tools.rsi_divergence_analysis()

@mcp.tool()
def bollinger_analysis(ticker: str) -> dict:
    """Analyze Bollinger Bands squeeze"""
    df = fetch_ohlcv(ticker)
    df = calculate_indicators(df)
    tools = AnalysisTools(ticker, df)
    return tools.bollinger_squeeze_analysis()

# ... 나머지 14개 도구 동일 패턴
```

#### Phase 3: 스트리밍 응답 지원 (Day 5)

**목표:** 긴 작업(Walk-Forward 백테스트, ML 앙상블)에 대해 진행 상황 스트리밍

```python
@mcp.tool()
async def backtest_walk_forward_stream(ticker: str, strategy: str = "rsi_reversion"):
    """Walk-forward backtest with progress streaming"""
    yield {"status": "starting", "progress": 0}

    result = engine_backtest_walk_forward(ticker, strategy, n_splits=5)

    for i, split in enumerate(result["splits"]):
        yield {
            "status": "progress",
            "progress": (i + 1) / len(result["splits"]) * 100,
            "split": split
        }

    yield {"status": "complete", "result": result}
```

#### Phase 4: 테스트 및 문서화 (Day 6-7)

**테스트 스크립트:** `test_mcp_server.py`
```python
import subprocess
import json

def test_mcp_tool(tool_name: str, params: dict):
    """MCP tool 호출 테스트"""
    proc = subprocess.Popen(
        ["python", "mcp_server.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True
    )

    request = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": params
        },
        "id": 1
    }

    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()

    response = proc.stdout.readline()
    return json.loads(response)

# 테스트
result = test_mcp_tool("analyze_stock", {"ticker": "NVDA"})
print(f"Signal: {result['result']['final_signal']}")
```

**문서:** `docs/MCP_GUIDE.md`

### 2.5 성공 지표

- [ ] Claude Desktop에서 "Analyze NVDA stock" 프롬프트로 16개 도구 결과 수신
- [ ] ChatGPT에서 MCP plugin으로 ML 예측 호출 성공
- [ ] 응답 시간 < 30초 (ML 앙상블 포함)
- [ ] 에러율 < 1%

---

## 3. 우선순위 7: 멀티에이전트 아키텍처 (PRISM-INSIGHT 참조)

### 3.1 개요

**목표:** 단일 LLM 판단 → 역할별 전문 에이전트 분리 → 의견 충돌을 통한 편향 제거

**참고 프로젝트:**
- [PRISM-INSIGHT](https://github.com/PRISM-INSIGHT/prism): 14개 역할별 AI 에이전트
- [AutoGen](https://github.com/microsoft/autogen): Microsoft 멀티에이전트 프레임워크

### 3.2 에이전트 역할 정의

| 에이전트 | 담당 도구 | 역할 | LLM |
|---|---|---|---|
| **TechnicalAnalyst** | trend_ma, rsi_divergence, bollinger_squeeze, macd_momentum, adx_trend_strength, volume_profile | 기술적 분석 전문가. 차트 패턴, 지표 해석 | Gemini |
| **QuantAnalyst** | fibonacci, volatility_regime, mean_reversion, momentum_rank, support_resistance, correlation_regime | 퀀트 전략 전문가. 수학적 모델, 통계 분석 | Gemini |
| **RiskManager** | risk_position_sizing, kelly_criterion, beta_correlation | 리스크 관리 전문가. 포지션 크기, 손익 비율 | Ollama |
| **MLSpecialist** | LightGBM, XGBoost, LSTM, SHAP | 머신러닝 전문가. 예측 모델, 설명력 | Ollama |
| **EventAnalyst** | event_driven, news_analyzer, macro_context | 이벤트/뉴스 전문가. 실적, 매크로 해석 | Gemini |
| **DecisionMaker** | (모든 에이전트 결과 종합) | 최종 의사결정자. 반대 의견 조정 | OpenAI GPT-4o |

### 3.3 아키텍처

```
┌──────────────────────────────────────────────────────────────┐
│                        User Query                            │
│                     "Analyze NVDA"                           │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                    Orchestrator                              │
│  (병렬 실행 관리 + 결과 수집)                                  │
└──┬────┬────┬────┬────┬────────────────────────────────────┬──┘
   │    │    │    │    │                                    │
   ▼    ▼    ▼    ▼    ▼                                    ▼
┌─────┐┌─────┐┌─────┐┌─────┐┌──────────┐         ┌──────────────┐
│Tech-││Quant││Risk ││ML   ││Event     │         │Decision      │
│nical││Anal-││Mgr  ││Spec ││Analyst   │────────▶│Maker         │
│Anal.││yst  │└─────┘└─────┘└──────────┘         │(종합 + 충돌  │
└─────┘└─────┘                                    │  해결)       │
  │      │      │      │        │                 └──────┬───────┘
  │      │      │      │        │                        │
  ▼      ▼      ▼      ▼        ▼                        ▼
┌────────────────────────────────────────┐    ┌───────────────────┐
│      도구 실행 결과 (JSON)              │    │  최종 리포트      │
│  - signal: buy/sell/neutral            │    │  + 근거           │
│  - score: -10 ~ +10                    │    │  + 반대 의견      │
│  - detail: "..."                       │    │  + 리스크         │
└────────────────────────────────────────┘    └───────────────────┘
```

### 3.4 구현 계획

#### Phase 1: 에이전트 클래스 구현 (Day 1-3)

**파일:** `multi_agent.py`

```python
from typing import List, Dict
from dataclasses import dataclass
from local_engine import _call_gemini, _call_ollama, _call_openai
from analysis_tools import AnalysisTools

@dataclass
class AgentResult:
    agent_name: str
    signal: str  # buy/sell/neutral
    confidence: float  # 0-10
    reasoning: str
    evidence: List[dict]  # 도구 실행 결과
    llm_provider: str

class BaseAgent:
    def __init__(self, name: str, tools: List[str], llm_provider: str):
        self.name = name
        self.tools = tools
        self.llm_provider = llm_provider

    def analyze(self, ticker: str, analysis_tools: AnalysisTools) -> AgentResult:
        """도구 실행 → LLM 해석"""
        evidence = []
        for tool_name in self.tools:
            tool_fn = getattr(analysis_tools, tool_name)
            result = tool_fn()
            evidence.append(result)

        # LLM에 결과 전달
        prompt = self._build_prompt(ticker, evidence)

        if self.llm_provider == "gemini":
            response = _call_gemini(prompt)
        elif self.llm_provider == "ollama":
            response = _call_ollama(prompt)
        else:
            response = _call_openai(prompt)

        # 응답 파싱 (signal, confidence 추출)
        signal, confidence = self._parse_response(response)

        return AgentResult(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            reasoning=response,
            evidence=evidence,
            llm_provider=self.llm_provider
        )

    def _build_prompt(self, ticker: str, evidence: List[dict]) -> str:
        return f"""당신은 {self.name} 전문가입니다.
{ticker} 종목에 대한 분석 결과를 해석하고, 매수/매도/관망 판단을 내리세요.

## 분석 결과
{json.dumps(evidence, indent=2, ensure_ascii=False)}

## 요구사항
- signal: buy/sell/neutral 중 하나
- confidence: 0-10 점수
- reasoning: 판단 근거 (한국어, 3-5문장)

JSON 형식으로 응답:
{{"signal": "buy", "confidence": 7.5, "reasoning": "..."}}
"""

    def _parse_response(self, response: str) -> tuple[str, float]:
        # JSON 파싱 또는 정규식
        import json
        try:
            data = json.loads(response)
            return data.get("signal", "neutral"), data.get("confidence", 5.0)
        except:
            # 폴백: 텍스트에서 추출
            signal = "neutral"
            confidence = 5.0
            if "buy" in response.lower():
                signal = "buy"
            elif "sell" in response.lower():
                signal = "sell"
            return signal, confidence


class TechnicalAnalyst(BaseAgent):
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
            llm_provider="gemini"
        )


class QuantAnalyst(BaseAgent):
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
            llm_provider="gemini"
        )


class RiskManager(BaseAgent):
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


class DecisionMaker:
    def __init__(self):
        self.name = "Decision Maker"
        self.llm_provider = "openai"

    def aggregate(self, ticker: str, agent_results: List[AgentResult]) -> dict:
        """에이전트 결과 종합 + 충돌 해결"""
        prompt = f"""당신은 최종 의사결정자입니다.
여러 전문가의 {ticker} 분석 결과를 종합하여 최종 판단을 내리세요.

## 전문가 의견
"""
        for result in agent_results:
            prompt += f"\n### {result.agent_name} ({result.llm_provider})"
            prompt += f"\n- 신호: {result.signal}"
            prompt += f"\n- 신뢰도: {result.confidence}/10"
            prompt += f"\n- 근거: {result.reasoning}\n"

        prompt += """
## 요구사항
1. 전문가 의견이 일치하면 → 그 방향으로 최종 판단
2. 의견이 충돌하면 → 각 의견의 근거 강도를 평가하고 조정
3. 소수 의견도 반영 (예: 5명 매수, 1명 매도 → "매수하되 X 리스크 주의")

다음 형식으로 응답:
{
  "final_signal": "buy/sell/neutral",
  "final_confidence": 7.5,
  "consensus": "4명 매수, 2명 중립",
  "conflicts": "Risk Manager는 변동성 과다로 중립 의견. 하지만 Technical/Quant 분석이 강력한 매수 신호를 보여 최종 매수 판단.",
  "reasoning": "...",
  "key_risks": ["변동성 스파이크", "실적 발표 임박"]
}
"""
        response = _call_openai(prompt)

        try:
            return json.loads(response)
        except:
            return {
                "final_signal": "neutral",
                "final_confidence": 5.0,
                "reasoning": response
            }
```

#### Phase 2: Orchestrator 구현 (Day 4-6)

**파일:** `multi_agent.py` (추가)

```python
class MultiAgentOrchestrator:
    def __init__(self):
        self.agents = [
            TechnicalAnalyst(),
            QuantAnalyst(),
            RiskManager(),
            # MLSpecialist(), EventAnalyst() 추가 가능
        ]
        self.decision_maker = DecisionMaker()

    def analyze(self, ticker: str) -> dict:
        """병렬 에이전트 실행 → 결과 종합"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # 데이터 수집
        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)
        tools = AnalysisTools(ticker, df)

        # 병렬 실행
        agent_results = []
        with ThreadPoolExecutor(max_workers=len(self.agents)) as executor:
            futures = {
                executor.submit(agent.analyze, ticker, tools): agent
                for agent in self.agents
            }

            for future in as_completed(futures):
                agent = futures[future]
                try:
                    result = future.result(timeout=60)
                    agent_results.append(result)
                    print(f"  ✓ {agent.name}: {result.signal} ({result.confidence:.1f}/10)")
                except Exception as e:
                    print(f"  ✗ {agent.name}: {e}")

        # 의사결정자가 종합
        final = self.decision_maker.aggregate(ticker, agent_results)

        return {
            "ticker": ticker,
            "multi_agent_mode": True,
            "agent_results": [
                {
                    "agent": r.agent_name,
                    "signal": r.signal,
                    "confidence": r.confidence,
                    "reasoning": r.reasoning[:200],  # 요약
                    "llm_provider": r.llm_provider,
                }
                for r in agent_results
            ],
            "final_decision": final,
            "analyzed_at": datetime.now().isoformat(),
        }
```

#### Phase 3: local_engine.py 연동 (Day 7-9)

```python
# local_engine.py에 추가
from multi_agent import MultiAgentOrchestrator

_orchestrator = None

def engine_multi_agent_analyze(ticker: str) -> dict:
    """멀티에이전트 분석 (병렬 실행 + 충돌 해결)"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MultiAgentOrchestrator()

    ticker = ticker.upper()
    try:
        return _sanitize(_orchestrator.analyze(ticker))
    except Exception as e:
        return {"error": str(e)}


# 디스패처에 추가
def engine_dispatch_get(path: str) -> Optional[dict]:
    # ... 기존 코드 ...
    elif path.startswith("/multi-agent/"):
        ticker = path.split("/multi-agent/")[1].split("?")[0]
        return engine_multi_agent_analyze(ticker)
```

#### Phase 4: 비교 분석 + 문서화 (Day 10-14)

**비교 대시보드:** `webui.py`에 "Multi-Agent" 페이지 추가

```python
# webui.py 추가
def page_multi_agent():
    st.title("🤖 Multi-Agent Analysis")

    ticker = st.selectbox("Ticker", load_watchlist())

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Single LLM (V1.0)")
        result_v1 = engine_scan_ticker(ticker)
        st.metric("Signal", result_v1["final_signal"])
        st.metric("Score", f"{result_v1['composite_score']:+.1f}")

    with col2:
        st.subheader("Multi-Agent (V2.0)")
        result_v2 = engine_multi_agent_analyze(ticker)
        st.metric("Final Signal", result_v2["final_decision"]["final_signal"])
        st.metric("Consensus", result_v2["final_decision"]["consensus"])

    st.subheader("Agent Opinions")
    for agent in result_v2["agent_results"]:
        with st.expander(f"{agent['agent']} — {agent['signal']} ({agent['confidence']}/10)"):
            st.write(agent["reasoning"])

    st.subheader("Conflict Resolution")
    st.write(result_v2["final_decision"]["conflicts"])
```

### 3.5 성공 지표

- [ ] 6개 에이전트 병렬 실행 완료 시간 < 120초
- [ ] 의견 충돌 비율 > 20% (건전한 토론 지표)
- [ ] 최종 판단 정확도 > 단일 LLM 대비 +5% (백테스트 검증)
- [ ] LLM 비용 < 3배 (병렬 실행 + 캐싱 최적화)

---

## 4. 우선순위 8: 포트폴리오 리밸런싱 자동화 (FinRL 참조)

### 4.1 개요

**목표:** 주기적 또는 신호 변경 시 자동 리밸런싱 + paper_trader와 연동하여 실시간 포트폴리오 관리

**참고 프로젝트:**
- [FinRL](https://github.com/AI4Finance-Foundation/FinRL): DRL 기반 포트폴리오 관리
- Quantopian (Archive): 리밸런싱 API 설계 참고

### 4.2 기능 명세

| 기능 | 설명 | 구현 |
|---|---|---|
| **자동 리밸런싱** | N일 주기 or 신호 변경 시 자동 비중 조정 | `portfolio_rebalancer.py` |
| **거래비용 반영** | 리밸런싱 시 수수료 0.1% 적용 | `portfolio_optimizer.py` |
| **목표 비중 추적** | Markowitz/Risk Parity 목표 대비 실제 비중 drift 계산 | `portfolio_rebalancer.py` |
| **Paper Trader 연동** | 리밸런싱 주문을 paper_trader에 자동 전송 | `local_engine.py` |

### 4.3 아키텍처

```
┌────────────────────────────────────────────────────────────┐
│                 Rebalancing Trigger                        │
│  - 주기적 (매주 월요일)                                      │
│  - 신호 변경 (BUY → SELL)                                   │
│  - Drift 임계값 초과 (비중 ±5% 이상)                        │
└──────────────────┬─────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────┐
│          Portfolio Rebalancer                            │
│  1. 현재 포지션 조회 (paper_trader)                        │
│  2. 최신 신호 조회 (latest_results)                        │
│  3. 목표 비중 계산 (Markowitz/Risk Parity)                 │
│  4. 거래 주문 생성 (target - current)                      │
│  5. 거래비용 계산 (0.1% per trade)                         │
│  6. 주문 실행 (paper_trader)                               │
└──────────────────┬───────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────┐
│          Paper Trader                                    │
│  - execute_paper_order() 호출                             │
│  - 포지션 업데이트                                         │
│  - 히스토리 기록                                           │
└──────────────────────────────────────────────────────────┘
```

### 4.4 구현 계획

#### Phase 1: Rebalancer 모듈 (Day 1-3)

**파일:** `chart_agent_service/portfolio_rebalancer.py`

```python
"""
포트폴리오 자동 리밸런싱
- 주기적 or 신호 변경 시 리밸런싱
- 거래비용 반영
- paper_trader 연동
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
import os

from config import OUTPUT_DIR
from paper_trader import get_portfolio_status, execute_paper_order, update_position_prices
from portfolio_optimizer import markowitz_optimize, risk_parity_optimize

REBALANCE_STATE_FILE = os.path.join(OUTPUT_DIR, "rebalance_state.json")
TRANSACTION_COST_PCT = 0.001  # 0.1% per trade

def _load_rebalance_state() -> dict:
    if os.path.exists(REBALANCE_STATE_FILE):
        with open(REBALANCE_STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "last_rebalance_date": None,
        "rebalance_count": 0,
        "total_transaction_costs": 0.0,
        "target_weights": {},
    }

def _save_rebalance_state(state: dict):
    with open(REBALANCE_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def compute_drift(current_weights: Dict[str, float], target_weights: Dict[str, float]) -> float:
    """목표 비중 대비 현재 비중 drift 계산"""
    drift = 0.0
    all_tickers = set(current_weights.keys()) | set(target_weights.keys())
    for ticker in all_tickers:
        current = current_weights.get(ticker, 0.0)
        target = target_weights.get(ticker, 0.0)
        drift += abs(current - target)
    return drift


def should_rebalance(last_rebalance_date: Optional[str], drift: float,
                     rebalance_interval_days: int = 7,
                     drift_threshold: float = 0.05) -> tuple[bool, str]:
    """리밸런싱 필요 여부 판단"""
    # 1. 주기적 리밸런싱
    if last_rebalance_date:
        last_date = datetime.fromisoformat(last_rebalance_date)
        days_since = (datetime.now() - last_date).days
        if days_since >= rebalance_interval_days:
            return True, f"주기 도래 ({days_since}일 경과)"
    else:
        return True, "최초 리밸런싱"

    # 2. Drift 임계값 초과
    if drift > drift_threshold:
        return True, f"Drift 초과 ({drift:.1%} > {drift_threshold:.1%})"

    return False, "리밸런싱 불필요"


def compute_rebalancing_orders(current_positions: Dict[str, dict],
                                target_weights: Dict[str, float],
                                total_equity: float,
                                current_prices: Dict[str, float]) -> List[dict]:
    """리밸런싱 주문 계산"""
    orders = []

    # 현재 비중 계산
    current_weights = {}
    for ticker, pos in current_positions.items():
        value = pos["qty"] * current_prices.get(ticker, pos["current_price"])
        current_weights[ticker] = value / total_equity if total_equity > 0 else 0

    # 목표 비중 대비 차이
    all_tickers = set(current_weights.keys()) | set(target_weights.keys())

    for ticker in all_tickers:
        current_w = current_weights.get(ticker, 0.0)
        target_w = target_weights.get(ticker, 0.0)
        delta_w = target_w - current_w

        if abs(delta_w) < 0.01:  # 1% 미만 차이는 무시
            continue

        delta_value = delta_w * total_equity
        price = current_prices.get(ticker, 0)
        if price <= 0:
            continue

        delta_qty = int(delta_value / price)

        if delta_qty > 0:
            action = "BUY"
        elif delta_qty < 0:
            action = "SELL"
            delta_qty = abs(delta_qty)
        else:
            continue

        # 거래비용 계산
        transaction_cost = abs(delta_value) * TRANSACTION_COST_PCT

        orders.append({
            "ticker": ticker,
            "action": action,
            "qty": delta_qty,
            "price": price,
            "target_weight": target_w,
            "current_weight": current_w,
            "delta_weight": delta_w,
            "transaction_cost": round(transaction_cost, 2),
            "reason": "Rebalancing"
        })

    return orders


def execute_rebalancing(method: str = "markowitz",
                        rebalance_interval_days: int = 7,
                        drift_threshold: float = 0.05,
                        dry_run: bool = False) -> dict:
    """포트폴리오 자동 리밸런싱 실행

    Args:
        method: "markowitz" or "risk_parity"
        rebalance_interval_days: 리밸런싱 주기 (일)
        drift_threshold: Drift 임계값 (0.05 = 5%)
        dry_run: True면 실제 주문 없이 시뮬레이션만
    """
    state = _load_rebalance_state()

    # 1. 현재 포지션 조회
    portfolio = get_portfolio_status()
    current_positions = portfolio["positions"]
    total_equity = portfolio["total_equity"]

    if not current_positions:
        return {"status": "skipped", "reason": "포지션 없음"}

    # 2. 목표 비중 계산
    tickers = list(current_positions.keys())
    if method == "risk_parity":
        opt_result = risk_parity_optimize(tickers)
    else:
        opt_result = markowitz_optimize(tickers)

    if opt_result.get("error"):
        return {"status": "failed", "reason": opt_result["error"]}

    target_weights = opt_result["weights"]

    # 3. Drift 계산
    current_weights = {
        ticker: (pos["qty"] * pos["current_price"]) / total_equity
        for ticker, pos in current_positions.items()
    }
    drift = compute_drift(current_weights, target_weights)

    # 4. 리밸런싱 필요 여부 판단
    need_rebalance, reason = should_rebalance(
        state["last_rebalance_date"], drift,
        rebalance_interval_days, drift_threshold
    )

    if not need_rebalance:
        return {
            "status": "skipped",
            "reason": reason,
            "drift": round(drift, 4),
            "current_weights": current_weights,
            "target_weights": target_weights,
        }

    # 5. 리밸런싱 주문 계산
    current_prices = {ticker: pos["current_price"] for ticker, pos in current_positions.items()}
    orders = compute_rebalancing_orders(current_positions, target_weights, total_equity, current_prices)

    if not orders:
        return {"status": "skipped", "reason": "주문 필요 없음 (모든 비중 1% 이내)"}

    # 6. 주문 실행
    executed_orders = []
    total_cost = 0.0

    if not dry_run:
        for order in orders:
            result = execute_paper_order(
                order["ticker"],
                order["action"],
                order["qty"],
                order["price"],
                reason=order["reason"]
            )
            executed_orders.append(result)
            total_cost += order["transaction_cost"]

        # 상태 업데이트
        state["last_rebalance_date"] = datetime.now().isoformat()
        state["rebalance_count"] += 1
        state["total_transaction_costs"] += total_cost
        state["target_weights"] = target_weights
        _save_rebalance_state(state)

    return {
        "status": "executed" if not dry_run else "dry_run",
        "reason": reason,
        "drift": round(drift, 4),
        "method": method,
        "orders": orders,
        "executed_orders": executed_orders if not dry_run else [],
        "total_transaction_cost": round(total_cost, 2),
        "current_weights": current_weights,
        "target_weights": target_weights,
        "rebalance_count": state["rebalance_count"],
    }
```

#### Phase 2: local_engine 연동 (Day 4-5)

```python
# local_engine.py에 추가
from portfolio_rebalancer import execute_rebalancing

def engine_portfolio_rebalance(method: str = "markowitz",
                                interval_days: int = 7,
                                drift_threshold: float = 0.05,
                                dry_run: bool = False) -> dict:
    """포트폴리오 자동 리밸런싱"""
    try:
        return _sanitize(execute_rebalancing(method, interval_days, drift_threshold, dry_run))
    except Exception as e:
        return {"error": str(e)}

# 디스패처 추가
def engine_dispatch_post(path: str) -> Optional[dict]:
    # ... 기존 코드 ...
    elif path.startswith("/portfolio/rebalance"):
        method = "markowitz"
        interval = 7
        drift = 0.05
        dry_run = False
        if "method=" in path:
            method = path.split("method=")[1].split("&")[0]
        if "interval=" in path:
            try:
                interval = int(path.split("interval=")[1].split("&")[0])
            except ValueError:
                pass
        if "drift=" in path:
            try:
                drift = float(path.split("drift=")[1].split("&")[0])
            except ValueError:
                pass
        if "dry_run=true" in path.lower():
            dry_run = True
        return engine_portfolio_rebalance(method, interval, drift, dry_run)
```

#### Phase 3: 스케줄러 연동 (Day 6-7)

**파일:** `stock_analyzer/scanner.py` (기존 파일 확장)

```python
# scanner.py에 추가
from apscheduler.schedulers.background import BackgroundScheduler
from local_engine import engine_portfolio_rebalance

def scheduled_rebalance():
    """주기적 리밸런싱 작업"""
    print(f"\n[{datetime.now()}] 포트폴리오 리밸런싱 체크 시작")
    result = engine_portfolio_rebalance(method="markowitz", interval_days=7, drift_threshold=0.05)

    if result["status"] == "executed":
        print(f"  ✓ 리밸런싱 실행: {len(result['orders'])}개 주문")
        print(f"  ✓ 거래비용: ${result['total_transaction_cost']:.2f}")
    else:
        print(f"  ○ {result['status']}: {result['reason']}")

# 기존 scheduler에 추가
scheduler = BackgroundScheduler()

# 매주 월요일 09:30에 리밸런싱 체크
scheduler.add_job(
    scheduled_rebalance,
    trigger='cron',
    day_of_week='mon',
    hour=9,
    minute=30,
    id='rebalancing'
)

scheduler.start()
```

### 4.5 성공 지표

- [ ] 리밸런싱 실행 시 거래비용 정확히 계산 (0.1% per trade)
- [ ] Drift 5% 초과 시 자동 리밸런싱 트리거
- [ ] 백테스트 결과: 리밸런싱 O vs X 비교 시 Sharpe Ratio +10% 이상
- [ ] 주기적 리밸런싱 누락률 < 1%

---

## 5. 구현 일정 (4주 계획)

### Week 1: MCP 서버 노출

| Day | 작업 | 담당 | 결과물 |
|:---:|---|---|---|
| 1-2 | MCP 서버 기본 골격 (5개 메인 tool) | Backend | `mcp_server.py` |
| 3-4 | 16개 도구 개별 노출 | Backend | 21개 MCP tools |
| 5 | 스트리밍 응답 지원 | Backend | 긴 작업 진행률 표시 |
| 6-7 | 테스트 + Claude Desktop 연동 확인 | QA | `test_mcp_server.py` + `docs/MCP_GUIDE.md` |

### Week 2-3: 멀티에이전트 아키텍처

| Day | 작업 | 담당 | 결과물 |
|:---:|---|---|---|
| 1-3 | 에이전트 클래스 구현 (6개) | Backend | `multi_agent.py` (BaseAgent + 6 agents) |
| 4-6 | Orchestrator + 병렬 실행 | Backend | `MultiAgentOrchestrator` |
| 7-9 | local_engine 연동 + 디스패처 | Backend | `/multi-agent/{ticker}` API |
| 10-12 | WebUI 비교 페이지 | Frontend | "Multi-Agent" 페이지 |
| 13-14 | 백테스트 비교 + 문서화 | QA | 정확도 검증 리포트 |

### Week 4: 포트폴리오 리밸런싱 자동화

| Day | 작업 | 담당 | 결과물 |
|:---:|---|---|---|
| 1-3 | Rebalancer 모듈 구현 | Backend | `portfolio_rebalancer.py` |
| 4-5 | local_engine 연동 | Backend | `/portfolio/rebalance` API |
| 6-7 | 스케줄러 연동 + 백테스트 | Backend | 매주 월요일 자동 실행 |

**총 4주 (20 작업일)**

---

## 6. 기술 스택 및 의존성

### 6.1 신규 의존성

```
# MCP 서버 (우선순위 6)
mcp >= 0.3.0

# 멀티에이전트 (우선순위 7)
# (기존 의존성 사용: httpx, google-generativeai)

# 리밸런싱 (우선순위 8)
# (기존 의존성 사용: apscheduler)
```

**추가 설치:**
```bash
pip install mcp
```

### 6.2 LLM 비용 예상

| 에이전트 | LLM | 토큰/호출 | 비용/호출 | 호출/종목 | 비용/종목 |
|---|---|---|---|---|---|
| TechnicalAnalyst | Gemini | 2,000 | $0.002 | 1 | $0.002 |
| QuantAnalyst | Gemini | 2,000 | $0.002 | 1 | $0.002 |
| RiskManager | Ollama | 1,500 | $0.000 | 1 | $0.000 |
| MLSpecialist | Ollama | 3,000 | $0.000 | 1 | $0.000 |
| EventAnalyst | Gemini | 1,500 | $0.0015 | 1 | $0.0015 |
| DecisionMaker | GPT-4o | 4,000 | $0.012 | 1 | $0.012 |
| **합계** | | | | 6 | **$0.0175** |

**월간 비용 예상 (10종목 * 30일):**
- Single LLM (V1.0): $0.005 * 10 * 30 = **$1.5/월**
- Multi-Agent (V2.0): $0.0175 * 10 * 30 = **$5.25/월**
- **증가율:** 3.5배

**절감 방안:**
1. 캐싱: 동일 종목 1시간 이내 재분석 시 캐시 사용 → 비용 50% 절감
2. Ollama 활용: Risk/ML 에이전트는 로컬 LLM → 비용 40% 절감
3. 선택적 실행: 신호 변경 시에만 전체 에이전트 실행 → 비용 60% 절감

**최적화 후:** ~$2.5/월 (V1.0 대비 1.7배)

---

## 7. 리스크 및 대응 방안

| 리스크 | 확률 | 영향 | 대응 방안 |
|---|:---:|:---:|---|
| MCP 프로토콜 변경 | 중 | 높음 | mcp 패키지 버전 고정 (0.3.x), 공식 스펙 추적 |
| 멀티에이전트 응답 시간 > 2분 | 높음 | 중 | 타임아웃 60초 설정, 실패한 에이전트는 skip |
| 에이전트 의견 충돌 해결 실패 | 중 | 중 | DecisionMaker에 fallback 로직 (단순 다수결) |
| LLM 비용 초과 (월 $20 이상) | 중 | 중 | 캐싱 + Ollama 우선 사용 + 일일 호출 제한 |
| 리밸런싱 거래비용 과다 | 낮음 | 중 | Drift threshold 5% → 10% 상향 조정 |
| 백테스트 검증 실패 (정확도 개선 없음) | 중 | 높음 | 멀티에이전트 가중치 조정 또는 V1.0 병행 운영 |

**Critical Path:**
- Week 2 Day 4-6 (Orchestrator 구현) — 가장 복잡한 병렬 처리 로직
- Week 3 Day 13-14 (백테스트 비교) — 멀티에이전트 효과 검증 필수

**Mitigation:**
- Day 1에 Orchestrator 간소화 버전 먼저 구현 (순차 실행)
- Day 3에 병렬 실행으로 전환
- 백테스트 실패 시 "소프트 멀티에이전트" 대안 (단일 LLM에 역할별 섹션 프롬프트)

---

## 8. 성공 지표 (KPI)

### 8.1 정량 지표

| 지표 | V1.0 현황 | V2.0 목표 | 측정 방법 |
|---|---|---|---|
| **분석 정확도** | 56% | 61% | 100개 종목 * 3개월 백테스트 승률 |
| **Sharpe Ratio** | 1.2 | 1.5 | 포트폴리오 백테스트 (1년) |
| **응답 시간** | 30초 | 90초 | 평균 분석 완료 시간 |
| **LLM 비용** | $1.5/월 | $2.5/월 | Gemini + OpenAI 사용량 |
| **MCP 호출 성공률** | — | 99% | 1,000회 테스트 |
| **에이전트 충돌 해결률** | — | 95% | 의견 불일치 → 최종 판단 성공 비율 |
| **리밸런싱 누락률** | — | <1% | 주기 도래 시 실행 성공 비율 |

### 8.2 정성 지표

- [ ] Claude Desktop에서 "Analyze NVDA using multi-agent" 프롬프트로 6개 에이전트 의견 확인 가능
- [ ] 사용자가 "왜 매수인가?" 질문 시 SHAP + 멀티에이전트 근거 제시 가능
- [ ] 포트폴리오 리밸런싱 히스토리에서 drift 변화 추적 가능
- [ ] WebUI에서 Single LLM vs Multi-Agent 비교 대시보드 제공

---

## 9. 차차기 버전 (V3.0) 예비 로드맵

V2.0 성공 시 검토할 추가 기능:

| 우선순위 | 기능 | 공수 | 참고 프로젝트 |
|:---:|---|:---:|---|
| 9 | 실시간 데이터 스트리밍 | 3주 | NautilusTrader, Alpaca API |
| 10 | Rust/Cython 성능 최적화 | 2주 | NautilusTrader, polars |
| 11 | 소셜 미디어 감성 분석 | 1주 | Cluefin (Twitter/Reddit) |
| 12 | 옵션 전략 분석 | 2주 | QuantLib |
| 13 | 앙상블 백테스트 (Stacking) | 1주 | FinRL |
| 14 | 웹 대시보드 (React) | 3주 | OpenBB Terminal |

---

## 10. 체크리스트 (착수 전 확인)

### 개발 환경
- [ ] Python 3.10+ 설치
- [ ] venv 활성화
- [ ] requirements.txt 최신 상태 (mcp 포함)
- [ ] Ollama 실행 중 (http://localhost:11434)
- [ ] Gemini API Key 유효
- [ ] OpenAI API Key 유효 (GPT-4o 접근 가능)

### 코드베이스
- [ ] V1.0 기능 정상 작동 확인 (test_new_features.py 통과)
- [ ] local_engine.py 디스패처 확장 가능 상태
- [ ] paper_trader.py Trailing Stop 동작 확인
- [ ] 백테스트 결과 DB 저장 확인 (db.py)

### 문서
- [ ] DESIGN_SYSTEM.md 신규 기능 가이드 작성 완료
- [ ] AGENT_INSTRUCTION.md 업데이트 (제거 금지 항목)
- [ ] ROADMAP_V2.md (본 문서) 팀 공유

### 외부 서비스
- [ ] Claude Desktop 설치 (MCP 테스트용)
- [ ] GitHub Actions CI/CD 파이프라인 (선택)

---

## 11. 승인 및 착수

**작성자:** Claude Code Assistant
**검토자:** [프로젝트 오너 이름]
**승인 일자:** _________
**착수 예정일:** _________

**서명:**

___________________________
프로젝트 오너

---

## 부록 A: 참고 자료

### 오픈소스 프로젝트

1. **OpenBB** — MCP 서버 참고
   - GitHub: https://github.com/OpenBB-finance/OpenBB
   - MCP Server 구현: `openbb-mcp/server.py`

2. **PRISM-INSIGHT** — 멀티에이전트 참고
   - GitHub: https://github.com/PRISM-INSIGHT/prism
   - 14개 역할별 에이전트 아키텍처

3. **FinRL** — 포트폴리오 자동화 참고
   - GitHub: https://github.com/AI4Finance-Foundation/FinRL
   - DRL 기반 리밸런싱

4. **AutoGen** — 멀티에이전트 프레임워크
   - GitHub: https://github.com/microsoft/autogen
   - 에이전트 간 대화 프로토콜

### 기술 문서

- Model Context Protocol: https://modelcontextprotocol.io/
- Optuna Documentation: https://optuna.readthedocs.io/
- SHAP Documentation: https://shap.readthedocs.io/

### 내부 문서

- `DESIGN_SYSTEM.md` — 디자인 토큰 및 신규 기능 가이드
- `AGENT_INSTRUCTION.md` — 코딩 규칙 및 제거 금지 항목
- `test_new_features.py` — V1.0 통합 테스트

---

**End of Document**
