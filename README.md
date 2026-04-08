# Stock AI Analysis System

LLM 기반 주식 종합 분석 시스템. 16개 분석 도구를 활용한 에이전트가 기술적/퀀트/거시경제 데이터를 종합하여 매수/매도/관망 판단을 제공한다.

## 주요 기능

- **16-Tool 차트 분석 에이전트**: 기술적 분석 6개 + 퀀트 분석 6개 + 확장 분석 4개
- **GPT-4o / Ollama 이중 LLM 지원**: OpenAI function calling + 로컬 LLM 자동 선택
- **Streamlit 대시보드**: 시장 지수, 종목별 점수, 상세 분석 리포트
- **텔레그램 알림**: 매수/매도 신호 자동 발송
- **Mac Studio FastAPI 에이전트**: 30분 주기 자동 스캔 서비스
- **리스크 관리**: ATR 기반 손절/익절, 켈리 기준 포지션 사이징

## 시스템 구조

```
stock_analyzer/
  config/settings.py        # 시스템 설정 (API 키, 지표 파라미터)
  core/
    data_collector.py       # yfinance + FRED API 데이터 수집
    indicators.py           # 기술 지표 계산 (자체 구현, pandas-ta 미사용)
  analysis/
    chart_agent.py          # 16-Tool LLM 에이전트 (핵심)
  risk/                     # 리스크 관리 모듈
  visualization/            # 차트 생성 (matplotlib/plotly)
  notification/             # 텔레그램 알림
  webui.py                  # Streamlit 대시보드
  main.py                   # CLI 진입점
  agent_client.py           # FastAPI 에이전트 서비스
```

## 분석 도구 (16개)

### 기술적 분석 (6개)
| # | 도구 | 설명 |
|---|------|------|
| 1 | trend_ma_analysis | 이동평균선 배열, 골든/데드크로스 |
| 2 | rsi_divergence_analysis | RSI 다이버전스 탐지 |
| 3 | bollinger_squeeze_analysis | 볼린저밴드 스퀴즈/확장 |
| 4 | macd_momentum_analysis | MACD 히스토그램 모멘텀 |
| 5 | adx_trend_strength_analysis | ADX 추세 강도 판별 |
| 6 | volume_profile_analysis | 거래량 프로파일 분석 |

### 퀀트 분석 (6개)
| # | 도구 | 설명 |
|---|------|------|
| 7 | fibonacci_retracement_analysis | 피보나치 되돌림 수준 |
| 8 | volatility_regime_analysis | 변동성 체제 (ATR/BB 기반) |
| 9 | mean_reversion_analysis | Z-Score 평균 회귀 신호 |
| 10 | momentum_rank_analysis | 다중 기간 모멘텀 순위 |
| 11 | support_resistance_analysis | 피봇 기반 지지/저항선 |
| 12 | correlation_regime_analysis | 수익률 자기상관 (Hurst) |

### 확장 분석 (4개)
| # | 도구 | 설명 |
|---|------|------|
| 13 | stochastic_analysis | Stochastic %K/%D 크로스, 과매수/과매도 |
| 14 | ichimoku_analysis | 일목균형표 구름, 전환/기준선 크로스 |
| 15 | sector_relative_strength_analysis | SPY/섹터 ETF 대비 상대강도 |
| 16 | market_sentiment_analysis | VIX, CMF, Williams %R, 거시지표 종합 심리 |

## 기술 지표

| 지표 | 컬럼명 | 파라미터 |
|------|--------|----------|
| SMA | SMA_20, SMA_50, SMA_200 | 20/50/200일 |
| EMA | EMA_12, EMA_26 | 12/26일 |
| RSI | RSI | 14일 |
| MACD | MACD, MACDs, MACDh | 12/26/9 |
| Bollinger Bands | BBU, BBM, BBL | 20일, 2.0 std |
| ADX/DI | ADX, DMP, DMN | 14일 |
| ATR | ATR | 14일 |
| OBV | OBV | - |
| Stochastic | STOCH_K, STOCH_D | K=14, D=3, Smooth=3 |
| Ichimoku | ICHI_TENKAN/KIJUN/SENKOU_A/B/CHIKOU | 9/26/52 |
| Williams %R | WILLIAMS_R | 14일 |
| CMF | CMF | 20일 |

## 거시경제 데이터 (FRED API)

| 지표 | FRED ID | 설명 |
|------|---------|------|
| Fed Funds Rate | FEDFUNDS | 연방기금금리 |
| 10Y Treasury | DGS10 | 10년 국채 수익률 |
| 2Y Treasury | DGS2 | 2년 국채 수익률 |
| CPI | CPIAUCSL | 소비자물가지수 |
| Unemployment | UNRATE | 실업률 |
| VIX | VIXCLS | 공포지수 |
| GDP Growth | A191RL1Q225SBEA | 실질 GDP 성장률 (분기) |
| ISM PMI | MANEMP | 제조업 고용지수 (PMI 프록시) |
| Consumer Sentiment | UMCSENT | 미시간 소비자심리지수 |
| Initial Claims | ICSA | 신규 실업수당 청구건수 (주간) |
| M2 Money | M2SL | M2 통화량 |

## 대시보드 시장 지수

대시보드 상단에 주요 시장 지수를 실시간 표시 (5분 캐시):

| 그룹 | 지수 |
|------|------|
| US Market | S&P 500, NASDAQ, DOW |
| KR Market | KOSPI, KOSDAQ, USD/KRW |
| Commodities | Gold, Silver, Copper, Natural Gas |

## 신뢰도 산출

4가지 차원을 가중 합산하여 0~10 범위의 신뢰도를 산출:

| 차원 | 비중 | 설명 |
|------|------|------|
| 의견 일치도 | 30% | 16개 도구 중 다수 신호 비율 |
| 점수 강도 | 25% | 개별 점수 절대값 평균 |
| 점수 일관성 | 25% | 점수 분산이 낮을수록 높음 |
| 방향 정합성 | 20% | 다수 신호 방향과 평균 점수 부호 일치 |

## 설치 및 실행

```bash
# 의존성 설치
cd stock_analyzer
pip install -r requirements.txt
pip install streamlit

# 환경 변수 설정 (.env)
OPENAI_API_KEY=sk-...
FRED_API_KEY=...
OLLAMA_BASE_URL=http://localhost:11434
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# CLI 분석
python main.py AAPL

# WebUI
streamlit run webui.py --server.port 8501

# FastAPI 에이전트 서비스
python agent_client.py
```

## 변경 이력

### v1.2 (2025-04-08) - 대시보드 시장 지수
- 대시보드 상단에 주요 시장 지수 10개 표시 (US/KR/원자재)
- yfinance 일괄 수집 + 5분 캐시 (`st.cache_data`)
- 등락률 기반 색상 카드 UI (다크 테마)

### v1.1 (2025-04-08) - 16-Tool 확장 + 다차원 신뢰도
- 기술 지표 4개 추가: Stochastic, Ichimoku, Williams %R, CMF
- FRED 거시경제 지표 5개 추가: GDP, PMI, 소비자심리, 실업수당, M2
- 섹터 상대강도 분석: SPY/섹터 ETF 대비 상대수익률
- 에이전트 분석 도구 12개 -> 16개 확장
- 신뢰도 계산 개선: 단순 일치도 -> 4차원 가중 합산
- pandas 3.0 호환성 수정 (`applymap` -> `map`)

### v1.0 (2025-04-08) - 초기 릴리스
- CLI 기반 주식 분석 + 12개 분석 도구 에이전트
- GPT-4o multimodal / Ollama 로컬 LLM 지원
- 텔레그램 알림 + Streamlit 대시보드
- Mac Studio FastAPI 에이전트 서비스
- 리스크 관리 (ATR 손절, 켈리 기준 사이징)
