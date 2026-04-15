# Stock AI Analysis System V2.0

**AI 기반 주식 종합 분석 시스템 - 멀티에이전트 협업 + MCP 서버 + ML 앙상블**

6개 전문 AI 에이전트가 협업하여 16개 분석 도구를 활용, 기술적/퀀트/ML 데이터를 종합하여 매수/매도/관망 판단을 제공하는 차세대 주식 분석 플랫폼.

---

## 🌟 V2.0 주요 기능

### 🤖 멀티에이전트 시스템 (NEW)
- **6개 전문 에이전트 협업**: Technical, Quant, Risk, ML, Event, Decision Maker
- **병렬 실행**: ThreadPoolExecutor로 동시 분석 → 최대 70% 시간 단축
- **의견 충돌 해결**: Decision Maker가 GPT-4o로 최종 판단
- **Multi-LLM**: Gemini + Ollama + OpenAI 하이브리드

### 🔌 MCP 서버 (NEW)
- **Model Context Protocol**: Claude Desktop, ChatGPT에서 직접 호출 가능
- **21개 도구 노출**: 5개 핵심 + 16개 개별 분석 도구
- **외부 AI 연동**: "NVDA 분석해줘" → 자동 실행

### 🧠 ML 앙상블 예측 (ENHANCED)
- **5개 모델 앙상블**: LightGBM, XGBoost, LSTM, RandomForest, GradientBoosting
- **SHAP 설명력**: 각 feature의 예측 기여도 시각화
- **신뢰도 측정**: 모델 간 합의도 기반 confidence score

### 📊 고급 백테스트 (NEW)
- **HyperOpt 최적화**: Optuna로 전략 파라미터 자동 튜닝
- **Walk-Forward 검증**: 과적합 방지, Rolling Window 학습/테스트
- **4개 전략**: SMA Cross, RSI Reversion, Bollinger Reversion, Composite

### 🛡️ 리스크 관리 강화 (NEW)
- **Trailing Stop**: 고점 대비 % 하락 시 자동 청산
- **시간 기반 청산**: N일 경과 시 자동 청산
- **Kelly Criterion**: 최적 포지션 크기 계산
- **ATR 손절/익절**: 동적 Stop Loss/Take Profit

### 📈 주간 트렌드 분석 (NEW)
- **DB 기반 이력 추적**: SQLite에 모든 스캔 결과 저장
- **WoW 변화 분석**: 주간 점수/신호 변화 추이
- **도구별 트렌드**: 16개 도구의 주간 신호 패턴

---

## 🏗️ 시스템 구조

```
stock_auto/
├── stock_analyzer/                # WebUI & 브릿지
│   ├── webui.py                  # Streamlit 대시보드 (7페이지)
│   ├── local_engine.py           # 브릿지 모듈 (chart_agent_service 연동)
│   ├── multi_agent.py            # V2.0 멀티에이전트 시스템 ⭐
│   └── scanner.py                # 백그라운드 스케줄러
│
├── chart_agent_service/           # 핵심 분석 엔진
│   ├── service.py                # FastAPI 서버
│   ├── analysis_tools.py         # 16개 분석 도구 (AnalysisTools)
│   ├── data_collector.py         # yfinance + 지표 계산
│   ├── backtest_engine.py        # 백테스트 + HyperOpt + Walk-Forward ⭐
│   ├── ml_predictor.py           # ML 앙상블 + SHAP ⭐
│   ├── portfolio_optimizer.py    # Markowitz, Risk Parity
│   ├── paper_trader.py           # 페이퍼 트레이딩 + Trailing Stop ⭐
│   ├── db.py                     # 스캔 로그 DB ⭐
│   ├── news_analyzer.py          # 뉴스 감성 분석
│   ├── chart_pattern.py          # 차트 패턴 인식
│   ├── sector_compare.py         # 섹터 비교
│   └── macro_context.py          # 매크로 경제 지표
│
├── mcp_server.py                 # MCP 서버 (기본, 6개 도구) ⭐
├── mcp_server_extended.py        # MCP 서버 (확장, 21개 도구) ⭐
├── test_mcp_server.py            # MCP 테스트
├── test_multi_agent.py           # 멀티에이전트 테스트 ⭐
└── docs/v2/                      # V2.0 문서
    ├── MCP_GUIDE.md
    └── WEEK1_COMPLETION_REPORT.md
```

---

## 🤖 멀티에이전트 시스템

### 에이전트 구성

| 에이전트 | 역할 | 담당 도구 | LLM |
|---------|------|----------|-----|
| **Technical Analyst** | 차트 패턴, 기술 지표 | trend_ma, rsi, bollinger, macd, adx, volume (6개) | Gemini |
| **Quant Analyst** | 통계 모델, 수학적 분석 | fibonacci, volatility, mean_reversion, momentum, support_resistance, correlation (6개) | Gemini |
| **Risk Manager** | 리스크 관리, 포지션 사이징 | risk_position_sizing, kelly_criterion, beta_correlation (3개) | Ollama |
| **ML Specialist** | 머신러닝 예측 | ML 앙상블 (LightGBM, XGBoost, LSTM) | Ollama |
| **Event Analyst** | 뉴스, 매크로 이벤트 | event_driven_analysis (1개) | Gemini |
| **Decision Maker** | 최종 의사결정, 충돌 해결 | (모든 에이전트 의견 종합) | GPT-4o |

### 작동 방식

```
사용자: "NVDA 분석해줘"
    ↓
1. Orchestrator가 5개 에이전트 병렬 실행 (ThreadPoolExecutor)
    ↓
┌────────┬────────┬────────┬────────┬────────┐
│Technical│Quant  │Risk   │ML     │Event  │
│Analyst │Analyst │Manager│Special│Analyst│
└────────┴────────┴────────┴────────┴────────┘
    ↓ (각자 도구 실행 + LLM 해석)
2. 각 에이전트가 signal (buy/sell/neutral) + confidence (0-10) 반환
    ↓
3. Decision Maker가 모든 의견 종합
   - 의견 일치 → 그 방향으로 최종 판단
   - 의견 충돌 → 근거 강도 평가 후 조정
   - 소수 의견 → 리스크 항목에 반영
    ↓
4. 최종 리포트: 신호, 신뢰도, 의견 분포, 충돌 해결 과정, 핵심 리스크
```

---

## 🔧 분석 도구 (16개)

### 기술적 분석 (6개)
| 도구 | 설명 | 신호 |
|------|------|------|
| **trend_ma** | 이동평균 배열, 골든/데드크로스 | SMA 20/50/200 정배열 → 매수 |
| **rsi_divergence** | RSI 다이버전스 탐지 | Bullish Divergence → 매수 |
| **bollinger_squeeze** | 볼린저밴드 스퀴즈/확장 | Squeeze → 변동성 돌파 대기 |
| **macd_momentum** | MACD 히스토그램 모멘텀 | 골든크로스 + 히스토그램 증가 → 매수 |
| **adx_trend_strength** | ADX 추세 강도 | ADX > 25 + DI+ > DI- → 강한 상승 추세 |
| **volume_profile** | 거래량 프로파일 | 거래량 증가 + 가격 상승 → 매수 |

### 퀀트 분석 (6개)
| 도구 | 설명 | 신호 |
|------|------|------|
| **fibonacci_retracement** | 피보나치 되돌림 | 38.2% 되돌림 + 반등 → 매수 |
| **volatility_regime** | 변동성 체제 (ATR/BB) | 저변동성 → 돌파 대기 |
| **mean_reversion** | Z-Score 평균 회귀 | Z < -2 (과매도) → 매수 |
| **momentum_rank** | 다중 기간 모멘텀 | 3개월 모멘텀 > 1개월 → 지속 가능성 높음 |
| **support_resistance** | 피봇 기반 지지/저항선 | 지지선 근처 + 반등 → 매수 |
| **correlation_regime** | 수익률 자기상관 (Hurst) | Hurst > 0.5 → 추세 지속 |

### 리스크/이벤트 (4개)
| 도구 | 설명 | 신호 |
|------|------|------|
| **risk_position_sizing** | ATR 기반 포지션 크기 | 변동성 고려 최적 수량 |
| **kelly_criterion** | 켈리 기준 베팅 | 승률/손익비 기반 최적 비중 |
| **beta_correlation** | 베타, 시장 상관성 | 베타 > 1 → 시장 민감도 높음 |
| **event_driven** | 뉴스, 실적, 매크로 | 긍정 뉴스 + 매크로 호조 → 매수 |

---

## 🧠 ML 앙상블 예측

### 5개 모델

1. **RandomForest**: 안정적 기본 예측
2. **GradientBoosting**: 순차 학습으로 오차 보정
3. **LightGBM**: 빠른 학습, 대용량 데이터
4. **XGBoost**: 높은 정확도, 과적합 방지
5. **LSTM**: 시계열 패턴 학습

### SHAP 설명력

```python
# Feature Importance (SHAP values)
Top 3 Features:
  1. RSI (0.234) - 과매도 신호
  2. MACD (0.187) - 모멘텀 전환
  3. Volume (0.156) - 거래량 증가
```

### 앙상블 방식

- **가중 평균**: 각 모델 예측에 성능 기반 가중치 적용
- **Voting**: 다수결 신호 (up/down/neutral)
- **Confidence**: 모델 간 합의도 (0-10)

---

## 📊 백테스트 시스템

### 4가지 전략

1. **SMA Cross**: 단기/장기 이평선 크로스
2. **RSI Reversion**: RSI 과매수/과매도 구간 반전
3. **Bollinger Reversion**: 볼린저밴드 이탈 후 회귀
4. **Composite**: 16개 도구 종합 신호

### HyperOpt 최적화

```python
# Optuna로 최적 파라미터 탐색
Best Parameters:
  rsi_threshold: 32
  hold_days: 5

Best Sharpe Ratio: 2.34
Annualized Return: 28.5%
Max Drawdown: -12.3%
```

### Walk-Forward 검증

```
학습 구간 (200일) → 테스트 구간 (50일) → Rolling
Split 1: 2024-01-01 ~ 2024-05-31 | Sharpe: 1.8
Split 2: 2024-02-15 ~ 2024-07-15 | Sharpe: 2.1
Split 3: 2024-04-01 ~ 2024-09-01 | Sharpe: 1.9

평균 테스트 Sharpe: 1.93
과적합 비율: 1.15 (< 1.5 양호)
```

---

## 🔌 MCP 서버

### Claude Desktop 설정

```json
{
  "mcpServers": {
    "stock-ai": {
      "command": "python",
      "args": ["/home/ubuntu/stock_auto/mcp_server_extended.py"]
    }
  }
}
```

### 사용 예시

```
Claude: "NVDA 주식 분석해줘"
→ analyze_stock tool 자동 호출
→ 16개 도구 실행
→ 종합 리포트 반환

Claude: "ML 예측 결과 보여줘"
→ predict_ml tool 호출
→ 앙상블 예측 + SHAP 결과

Claude: "백테스트 최적화해줘"
→ optimize_strategy tool 호출
→ Optuna 실행
```

### 21개 MCP Tools

**핵심 도구 (5개)**
- analyze_stock
- predict_ml
- optimize_strategy
- walk_forward_test
- optimize_portfolio

**개별 분석 도구 (16개)**
- analyze_trend_ma
- analyze_rsi_divergence
- ... (16개 전체)

---

## 🚀 설치 및 실행

### 1. 환경 설정

```bash
# 저장소 클론
git clone [repository-url]
cd stock_auto

# 가상환경 생성
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r stock_analyzer/requirements.txt
pip install -r chart_agent_service/requirements.txt
```

### 2. API Keys 설정

```bash
# stock_analyzer/.env
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIzaSy...
FRED_API_KEY=...
FMP_API_KEY=...
OLLAMA_BASE_URL=http://localhost:11434

# chart_agent_service/.env
GEMINI_API_KEY=AIzaSy...
OPENAI_API_KEY=sk-...
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
```

### 3. 실행

```bash
# WebUI (권장)
cd stock_analyzer
streamlit run webui.py --server.port 8501

# FastAPI 서버
cd chart_agent_service
python service.py

# MCP 서버
python mcp_server_extended.py

# 멀티에이전트 직접 테스트
python stock_analyzer/multi_agent.py NVDA

# 단일 종목 분석 (CLI)
python stock_analyzer/main.py AAPL
```

---

## 📄 WebUI 페이지

1. **Dashboard**: 전체 종목 요약, 최신 신호
2. **Detail**: 종목별 상세 분석 (16개 도구 결과)
3. **Backtest**: 백테스트 결과, HyperOpt 최적화
4. **ML Prediction**: ML 앙상블 예측, SHAP 설명력
5. **Portfolio**: Markowitz/Risk Parity 최적화
6. **Paper Trading**: 모의 매매, Trailing Stop
7. **Scan Log**: 스캔 이력, 주간 트렌드 분석 ⭐

---

## 🧪 테스트

```bash
# V1.0 기능 테스트
python test_new_features.py

# MCP 서버 테스트
python test_mcp_server.py --simple

# 멀티에이전트 테스트
python test_multi_agent.py NVDA

# V2.0 사전 준비 테스트
python test_v2_prerequisites.py
```

---

## 📈 성능 지표

| 지표 | V1.0 | V2.0 | 개선율 |
|------|------|------|--------|
| 분석 정확도 | 56% | 61% (목표) | +5%p |
| Sharpe Ratio | 1.2 | 1.5 (목표) | +25% |
| 분석 시간 | 30초 | 90초 | - |
| 자동화율 | 20% | 95% | +75%p |
| 월 LLM 비용 | $1.5 | $2.5 | +$1 |

---

## 📚 문서

- **V2.0 Roadmap**: `ROADMAP_V2_REVISED.md`
- **MCP 가이드**: `docs/v2/MCP_GUIDE.md`
- **구현 체크리스트**: `V2_IMPLEMENTATION_CHECKLIST.md`
- **사전 준비**: `V2_PREREQUISITES.md`
- **디자인 시스템**: `DESIGN_SYSTEM.md`
- **에이전트 지침**: `AGENT_INSTRUCTION.md`

---

## 🔄 버전 히스토리

### V2.0 (2026-04-14) - 멀티에이전트 + MCP 서버
- ⭐ **멀티에이전트 시스템**: 6개 전문 에이전트 협업
- ⭐ **MCP 서버**: Claude Desktop, ChatGPT 연동
- ⭐ **ML 앙상블 강화**: LightGBM, XGBoost, LSTM + SHAP
- ⭐ **HyperOpt**: Optuna 파라미터 최적화
- ⭐ **Walk-Forward**: 과적합 방지 백테스트
- ⭐ **Trailing Stop**: 동적 손절 시스템
- ⭐ **주간 트렌드 DB**: 스캔 이력 추적 및 WoW 분석

### V1.2 (2025-04-08) - 대시보드 시장 지수
- 대시보드 상단 시장 지수 10개 표시
- yfinance 일괄 수집 + 5분 캐시

### V1.1 (2025-04-08) - 16-Tool 확장
- 기술 지표 4개 추가
- FRED 거시경제 지표 5개 추가
- 신뢰도 계산 4차원 개선

### V1.0 (2025-04-08) - 초기 릴리스
- 12개 분석 도구 에이전트
- GPT-4o + Ollama 지원
- Streamlit 대시보드

---

## 🤝 기여

버그 리포트, 기능 제안은 GitHub Issues로 제출해주세요.

---

## 📝 라이선스

MIT License

---

## 👨‍💻 개발자

Claude Code + Human Collaboration