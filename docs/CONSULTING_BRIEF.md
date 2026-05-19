# Stock AI Analysis System V2 — 컨설팅 브리프

> **목적**: 외부 컨설턴트(투자 전략 · SRE · 리스크 · 데이터 엔지니어링)가 본 시스템을 평가·자문하기 위한 종합 명세.
> **작성일**: 2026-05-13
> **대상 코드베이스**: `/home/ubuntu/stock_auto` (git: `main`, baseline f3b4926)
> **분량**: 본문 약 25페이지 · 파일·라인 인용 다수

---

## 0. 임원 요약 (TL;DR)

`stock_auto`는 **8개 LLM 에이전트 + 24개 분석 도구 + 진입 계획 + 5모델 ML 앙상블**로 한국·미국 주식의 매수/매도/관망 신호를 생성하는 **개인용 듀얼 노드 의사결정 보조 시스템**이다.

| 축 | 현 상태 | 한 줄 평 |
|---|---|---|
| 아키텍처 | testdev(RTX 5070) + Mac Studio(M1 Max) Tailscale 듀얼 노드, Docker Compose 4-Phase 배포 완료 | SRE 관점 견고, 단일 사용자 dev 전제(network_mode: host) |
| 분석 방법론 | 7개 에이전트 병렬 → Decision Maker 충돌 해결, 신호=`signal/confidence/reasoning/evidence` 스키마 | 멀티에이전트로 편향 완화, 다만 기술지표 후행성·횡보장 약세 잔존 |
| 리스크 관리 | ATR 기반 손절 + Fractional Kelly(½) + Markowitz 포트폴리오 + Drift 리밸런싱 | 프레임워크는 기관급, 그러나 일일 손실 한도·VaR·다중 신호 자금배분 규칙 부재 |
| 데이터 파이프라인 | yfinance + FDR + DART + Google News, SQLite WAL, 인메모리 OHLCV 캐시 | TTL 캐시·재시도·신호 사후평가가 미구현 → stale 데이터 위험 |

**컨설팅 우선순위 (저자 추천)**:
1. 다중 에이전트가 같은 종목에 동시 BUY 시 자금 배분 규칙 명문화 + 일일 손실 한도
2. OHLCV 캐시 TTL & 재시도 → 신호 freshness audit
3. `signal_outcomes` 테이블 활용한 실제 hit-rate 측정 루프 가동
4. 백테스트 가정(naive Sharpe rf=0, auto_adjust 블랙박스) 투명화 + Walk-Forward overfitting_ratio 정기 보고

---

## 1. 시스템 개요

### 1.1 목적과 사용자

- **목적**: 매일 1회 워치리스트(현재 한국 2 + 미국 5종목)의 매수/매도/관망 신호와 진입가·손절·익절·수량을 산출.
- **사용자**: 1인 (개인 투자자) — 운영자 = 의사결정자.
- **운영 모드**: `TRADING_MODE: Literal["paper", "dry_run", "approval", "live"]` — 현재 `paper` 기본.

### 1.2 듀얼 노드 토폴로지

```
                Tailscale Tailnet (testffa97.ts.net)
                ┌──────────────────────────────────────────┐
   testdev (Linux/RTX 5070)                  hsptest-macstudio (macOS M1 Max 32GB)
   ├─ webui (Streamlit:8501)                 └─ Homebrew Ollama (LaunchAgent)
   ├─ agent-api (FastAPI:8100)                   :8080  (관례 11434 아님)
   └─ Ollama (host:11434)                        모델: qwen2.5:32b-q4_K_M (~19GB),
       모델: qwen3:14b-q4_K_M (~10GB)                  gpt-oss:20b, llama3.1:8b
       역할: Ollama 전용 GPU 점유
```

- **호스트 매핑**: `hsptest-macstudio:8080` (MagicDNS, IP 변동 무관).
- **Mac Studio 포트 8080 결정 이유**: macOS LaunchAgent 환경에서 11434 충돌 회피, 본 프로젝트 관례.
- **GPU 격리 원칙**: RTX 5070은 Ollama 추론 전용, TensorFlow LSTM·ML 학습은 의도적으로 빼서 추론 처리량 보호.

### 1.3 디렉토리 구조

```
stock_auto/
├ compose.yaml                     # dev/mac 프로파일
├ .env / .env.example              # 60+ 키 SSOT
├ Makefile                         # 14개 운영 타깃
├ mcp_server.py / *_extended.py    # Claude Desktop MCP (22 tools)
├ chart_agent_service/             # FastAPI agent-api
│  ├ service.py (67 endpoints)
│  ├ config.py  (Pydantic Settings 60+ field)
│  ├ analysis_tools.py (16 tools, 103KB)
│  ├ ml_predictor.py / backtest_engine.py
│  ├ paper_trader.py / signal_tracker.py
│  ├ risk_management.py / portfolio_optimizer.py
│  ├ portfolio_rebalancer.py
│  ├ screener.py / entry_plan.py
│  ├ db.py (SQLite WAL)
│  ├ data_collector.py / news_analyzer.py / macro_context.py
│  ├ institutional_scoring.py / institutional_analysis_integration.py
│  ├ data_sources/  brokers/  execution/
│  └ trading_costs.py / tick_size.py / currency_utils.py
├ stock_analyzer/                  # Streamlit webui + scanner
│  ├ webui.py (Streamlit, ~5,100줄, 10 render_* 페이지)
│  ├ multi_agent.py (8 agents)
│  ├ enhanced_decision_maker.py
│  ├ dual_node_config.py (라우팅/폴백)
│  ├ local_engine.py / scanner.py
│  ├ ticker_validator.py / ticker_verifier.py / ticker_manager.py
│  ├ dart_api.py / korean_stock_verifier*.py
│  ├ ml_pipeline_fix.py
│  └ watchlist.txt
└ docs/                            # 운영/배포 문서
```

---

## 2. 시스템 아키텍처 / 운영

### 2.1 Docker Compose

`compose.yaml` — 2개 프로파일(`dev`, `mac`).

| 서비스 | 이미지 | 포트 | 네트워크 | 비고 |
|---|---|---|---|---|
| `agent-api` | stock-auto/agent-api:local (7.76GB) | 8100 | `host` | TF/LSTM 유지, Ollama 직접 호출 |
| `webui` | stock-auto/webui:local (2.06GB) | 8501 | `host` | TF 제거(74% 슬림, c0b3bd6) |
| `ollama-heavy` (mac 프로파일) | ollama/ollama | 8080 | bridge | 현재 미사용(Homebrew 운영 중) |

`network_mode: host` — 단일 사용자 dev 환경 전제. 멀티테넌트 운영 시 bridge + `extra_hosts`로 전환 필요.

### 2.2 설정 시스템 (Pydantic Settings)

`chart_agent_service/config.py` — `BaseSettings` 60+ 필드.

- **Literal 검증**: `TRADING_STYLE: Literal["scalping","swing","longterm"]`, `TRADING_MODE: Literal["paper","dry_run","approval","live"]`, `DEFAULT_LLM_PROVIDER: Literal["ollama","gemini","openai"]`.
- **범위 검증**: `MULTI_AGENT_MAX_WORKERS: Field(default=2, ge=1, le=16)`, `SCAN_PARALLEL_WORKERS: Field(default=3, ge=1, le=16)`.
- **로드 순서**: 루트 `.env` → 환경변수 재정의(pydantic-settings ≥ 2.0).
- **호환 인터페이스**: 모듈 레벨 상수 export(`config.py:111~217`) — 기존 `from config import X` 코드 호환.
- **기동 시 검증**: enum 위반 시 즉시 `ValidationError`.

### 2.3 FastAPI 서비스 (`chart_agent_service/service.py`)

19개 엔드포인트 (서비스 라인 ~492-832):

| 경로 | 메서드 | 용도 |
|---|---|---|
| `/health` | GET | Ollama 연결 + 메타 |
| `/results`, `/results/{ticker}` | GET | 캐시된 분석 결과 |
| `/scan`, `/scan/{ticker}` | POST | 워치리스트/단일 스캔 |
| `/chart/{ticker}` | GET | 차트 PNG |
| `/backtest/{ticker}` | GET | 4 전략 백테스트 |
| `/ml/{ticker}` | GET | 5모델 앙상블 |
| `/portfolio/optimize` | GET | Markowitz/리스크패리티 |
| `/ranking` | GET | 팩터 크로스섹션 |
| `/paper/order` | POST | 페이퍼 트레이딩 |

### 2.4 듀얼 노드 라우팅 & 폴백 (`stock_analyzer/dual_node_config.py`)

```python
# 노드 정의 (라인 16~40)
LLM_NODES = {
    "rtx_5070":   {"url": "http://localhost:11434",
                   "models": {"qwen3_14b": "qwen3:14b-q4_K_M", ...}},
    "mac_studio": {"url": "http://hsptest-macstudio:8080",
                   "models": {"qwen_32b": "qwen2.5:32b-instruct-q4_K_M", ...}},
}

# 헬스체크 (라인 156~198) — 과거 /health 404 잠복버그 → /api/tags 사용으로 수정
def is_mac_studio_available() -> bool:
    response = get_http_session().get(f"{mac_url}/api/tags", timeout=2)
    return response.status_code == 200

# 폴백 (Mac 다운 → 모든 에이전트 RTX 5070 + qwen_14b + timeout 240s)
def get_fallback_config(agent_name: str): ...
```

| 에이전트 | LLM 제공자 | 노드 | 모델 | 결정 근거 |
|---|---|---|---|---|
| Decision Maker | Gemini | – | – | 최종 충돌 해결, 외부 LLM |
| Value Investor | Gemini | – | – | 재무제표/장기 가치 |
| Event Analyst | Gemini | – | – | 최신 컨텍스트 필요 |
| Geopolitical | Gemini | – | – | 지정학 추론 |
| Technical | Ollama | Mac Studio | qwen2.5:32b | 수치/지표 |
| Quant | Ollama | Mac Studio | qwen2.5:32b | 통계 정밀도 |
| Risk Manager | Ollama | Mac Studio | qwen2.5:32b | Kelly/ATR |
| ML Specialist | Ollama | Mac Studio | qwen2.5:32b | 앙상블 해석 |

> ⚠️ README 표에는 "Risk Manager → RTX 5070 llama3.1:8b"로 적혀 있으나 코드는 모든 Ollama 에이전트를 Mac Studio qwen_32b로 라우팅한다(`dual_node_config.py`). **README와 코드 사이 불일치** — 컨설팅 시점 확인 필요.

### 2.5 멀티에이전트 오케스트레이션 (`stock_analyzer/multi_agent.py`)

```python
class MultiAgentOrchestrator:                              # line ~1384
    def __init__(self):
        self.max_workers = int(os.getenv("MULTI_AGENT_MAX_WORKERS", "2"))
        self.mac_studio_available = is_mac_studio_available()

    def run_all_agents(self, ticker):
        _ma_timeout = int(os.getenv("MULTI_AGENT_TIMEOUT", "300"))
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = [ex.submit(agent.call, ticker) for agent in self.agents]
            for fut in as_completed(futures, timeout=_ma_timeout):
                result = fut.result(timeout=_fallback_timeout + 10)
```

- **결과 스키마**: `AgentResult(agent_name, signal, confidence(0-10), reasoning, evidence, llm_provider, execution_time, error)` — `multi_agent.py:40~54`.
- **타임아웃 환경변수**: `MULTI_AGENT_TIMEOUT=300`, `MULTI_AGENT_LLM_TIMEOUT=240`, 워커 4 권장 (Mac 2 + RTX 2 병렬).
- **복원력**: Future timeout → 해당 에이전트만 0점 처리, Decision Maker는 잔여 결과로 결정.

### 2.6 빌드/이미지

- `chart_agent_service/Dockerfile`: 멀티스테이지(builder + runtime), 비루트 `app:app`, TF/CUDA 유지(7.76GB).
- `stock_analyzer/Dockerfile`: builder 단계에서 `sed '/^tensorflow/d'`로 TF 제외(2.06GB, 74% ↓).
- **TF 제거 결정 이유 (c0b3bd6)**: webui 자체에서 LSTM import 시 `google.protobuf.runtime_version.VersionError`로 어차피 실패 — 변경 전부터 동작 불가. ML Specialist 호출은 agent-api(`/ml/{ticker}`)로 위임.

### 2.7 Phase 로드맵

| Phase | 날짜 | 내용 | 상태 |
|---|---|---|---|
| 0 | 2026-04-28 | Baseline 스냅샷 | ✅ |
| 1 | 2026-04-28 | Mac Studio Tailscale 노출 + `/api/tags` 헬스체크 | ✅ |
| 2 | 2026-04-28 | `.env` 단일화 + Pydantic Settings | ✅ |
| 3 | 2026-04-29 | Compose `dev`/`mac` 프로파일 + 운영 검증 | ✅ |
| 4 | 2026-04-29 | 이미지 최적화 + 정리 | ✅ |
| **5** (제안) | – | 모니터링(Prometheus/Grafana), CI/CD, 신호 사후평가 배치 | ❌ |

---

## 3. 분석 방법론 — 투자 전략

### 3.1 의사결정 흐름 (한 화면 요약)

```
워치리스트 → fetch_ohlcv (yfinance, auto_adjust=True)
            ↓
calculate_indicators (SMA/EMA/RSI/Bollinger/ATR/ADX/MACD/OBV)
            ↓
7개 에이전트 병렬 (각 에이전트 = 도구 N개 호출 → LLM 해석 → AgentResult)
            ↓
EnhancedDecisionMaker:
  ① 신호 정규화/집계 (buy/sell/neutral 카운트, confidence 합)
  ② 점수 합산 (technical+quant+ML+insider, ML는 정확도 기반 가중치)
  ③ 신호 강도 분류 (very_weak ~ very_strong)
  ④ 충돌 해결 + 펀더멘털 검증 + 신뢰도 평활화
            ↓
최종 출력 = {signal, confidence, reasoning, evidence,
             entry_plan(split_entry/order_type), stop_loss, take_profit, qty}
```

### 3.2 24개 분석 도구 + 진입 계획 (`chart_agent_service/analysis_tools.py`)

#### A. 기술적 (6개)

| 도구 | 핵심 수식/임계값 | 한계 |
|---|---|---|
| `trend_ma` | 골든크로스(SMA20·50 prev/curr) +4, 거래량 ≥1.5× MA20 ∧ ≥8봉 유지 → 돌파 +5, RSI>70이면 -2 차감, 정배열(20>50>200) +4, 역배열 -4 | 횡보장 정배열은 무신호; 추세전환 초기 3–5봉 지체 |
| `rsi_divergence` | 30봉 피벗 탐색; **regime-aware** — ADX>25이면 OB=80/OS=20, 아니면 70/30. bullish_regular/hidden ±4, RSI>OB -3, RSI<OS +3 | 다이버전스 ~60% 정확도, 추세장 오신호 |
| `bollinger_squeeze` | bb_width<avg×0.6 → +2(스퀴즈), pct_b>0.8 -2, <0.2 +2, 밴드 돌파 ±3 | 방향성 약함, 채찍질 |
| `macd_momentum` | (12/26/9) 크로스 ±4, hist 가속 ±2, hist 부호 ±1 | 후행 3–5봉 |
| `adx_trend_strength` | ADX>40 very_strong, >25 strong, DI 크로스 ±3 | ADX<20은 무신호, >40은 역시초 신호 가능 |
| `volume_profile` | `|Δvol_ratio|>0.5` 급변; OBV 5/20 추세 ±2; 가격↓ ∧ OBV↑ → accumulation +2 | 보조 신호 |

#### B. 퀀트 (6개)

| 도구 | 수식 | 한계 |
|---|---|---|
| `fibonacci_retracement` | 0.236/0.382/0.500/0.618/0.786 레벨 거리 기반 -10~+10 선형 배분 | 자기충족적, 과학적 유의성 약함 |
| `volatility_regime` | annualized_vol = std(daily_returns)·√252. >60% → -3, >100% → -5, <40% +2 | 과거 기반, 급변 감지 지체 |
| `mean_reversion` | z = (price-SMA20)/std20. |z|>1.5 → ±2. **실적발표 ±7일은 신뢰 50% 감액** | 추세장에서 역효과 |
| `momentum_rank` | 1/5/10/20일 수익률 순위 | 모멘텀 연속성 ~60% |
| `support_resistance` | 60봉 스윙 high/low, R/R = (R-price)/(price-S) ≥2.0 → +3, <1.0 → -3 | 스윙 정의 자의적 |
| `correlation_regime` | KOSPI/SPX와 상관계수 추이; Hurst 지수 추세 지속 | β 변동 감지용 |

#### C. 리스크/이벤트 (4개)

| 도구 | 핵심 |
|---|---|
| `risk_position_sizing` | 손절 ATR×`ATR_STOP_MULTIPLIER`(scalp 1.2 / swing 2.0 / long 3.0), 익절 = 손절폭 × `TAKE_PROFIT_RR_RATIO`(2.0), 지지선 vs ATR 중 더 보수적 손절 채택. tick_size 정합. R/R<1.0 → 포지션 50% 축소 |
| `kelly_criterion` | Kelly Full = win_rate − (1−win_rate)/(avg_win/avg_loss); Kelly Half = Full/2; 상한 = `MAX_POSITION_PCT`/2 (=10%). 데이터 <60일이면 미생성. Sharpe>1.5 +2점 |
| `beta_correlation` | β = cov(stock, bench)/var(bench). β>2.0 위험 경고, β<0 헤지 특성 처리 |
| `event_driven` | 배당락/스플릿/구조조정/실적시즌 감지 |

추가: `insider_trading` (analysis_tools.py:1660~1875) — SEC Form 4/공정거래위 데이터, open_market_purchase = +4까지, sale = -4까지, 실적시즌 가중치 ×1.5.

#### 도구 간 중복/한계

- **`trend_ma` ↔ `adx_trend_strength`** : 둘 다 추세 강도; 앙상블이 가중치 자동 조절(중복가산 5% 미만이라 무시 가능).
- **`rsi_divergence` ↔ `mean_reversion`** : 과매수/매도 중복 — RSI는 regime-aware 임계값으로 차별화.
- **`bollinger_squeeze` ↔ `volatility_regime`** : BB는 price-action, vol_regime은 annualized 통계 — 시간 스케일 다름.
- 공통 약점: ① 후행성 3–5봉, ② 횡보장 신뢰 <50%, ③ 한국 거래정지(volume=0) NaN 처리 필수.

### 3.3 스크리너 (`chart_agent_service/screener.py`)

KOSPI+KOSDAQ 시총 ≥2,000억 원 (~280종목) 대상.

**가점**(최대 100):

| 요소 | 점수 |
|---|---|
| MACD 골든크로스(10봉 이내) | +30 ~ +20 (1봉 전 30점 → 10봉 전 20점) |
| MACD 상승 유지 | +15 |
| MA 정배열(5>20>60) | +20 |
| RSI>50 ∧ 상승기울기 | +20 |
| 3일 중 2일 양봉 + 거래량↑ | +20 |
| 20일선 지지 확인 | +10 |

**감점** (f3b4926 추가):

| 요소 | 점수 | 임계 |
|---|---|---|
| MACD 데드크로스 | -20 | – |
| RSI 과매수 | -15 | >78 |
| 거래량 5일 연속 감소 | -10 | – |
| 종가 < SMA120 | -10 | – |
| 고변동성 | -15 | annualized >60% |
| 극고변동성 | -25 | >100% |

**펀더멘털 필터** (f3b4926): `EPS<0 ∧ P/B>5.0` → 자동 실격(0점). 신뢰도 7+ 기준 상향(이전 6 → 7), 스크리너 단독 신뢰 금지 경고. API 최소 시총 파라미터는 `min_market_cap_100m`(억원)이며, 기존 `min_market_cap_bn`은 호환 alias로만 유지한다.

### 3.4 신호 정규화 (`stock_analyzer/signal_normalizer.py`)

- 매핑: `{BUY, Buy, LONG, bullish, strong_buy} → "buy"` 등 약 30가지 변형 통일.
- 점수→신호: `score>2.0 buy`, `<-2.0 sell`, 그 외 neutral.
- 신뢰도: `clamp(confidence, 0, 10)`.

### 3.5 Decision Maker — 충돌 해결 (`stock_analyzer/enhanced_decision_maker.py`)

```python
# (1) 신호 카운트 + ML 정확도 추적                          # line 55~112
signal_counts = {"buy":0,"sell":0,"neutral":0}
for r in agent_results:
    if r.error or r.confidence == 0:  continue           # 실패 간주
    signal_counts[normalize(r.signal)] += 1

# (2) 점수 합산                                              # line 134~537
total = technical_score + quant_score \
       + ml_weight * ml_contribution \
       + 2 * insider_contribution                         # 내부자 ×2

# (3) ML 정확도 기반 가중치
if avg_acc < 0.50:  ml_weight = 0.0    # 무작위 수준 → 무시
elif avg_acc < 0.55: ml_weight = 0.3
elif avg_acc < 0.60: ml_weight = 0.7
else:                ml_weight = 1.0
if all_models_same_dir and avg_acc>=0.5: ml_weight += 0.3

# (4) 신호 강도 (점수 절댓값 기준)
±30+: very_strong | ±20~30: strong | ±10~20: moderate | ±5~10: weak | <5: very_weak

# (5) 펀더멘털 거부 조건
β>3.0(growth) or β>2.0(general); P/E>300(growth) or >200; 52w 고점 -30% 이상
실적발표 ±7일 → 평균회귀 신뢰 -50%

# (6) 신뢰도 평활화 (line 711~764)
|new - prev| > 5 → weighted (0.6·new + 0.4·prev)
recent_5_variance > 4 → moving average
min step = 0.5
```

### 3.6 ML 앙상블 (`stock_analyzer/ml_pipeline_fix.py`, `chart_agent_service/ml_predictor.py`)

- **모델 5종**: RandomForest, GradientBoosting, LightGBM, XGBoost, LSTM.
- **피처 ~20–25**: return_1/5/10/20d, MA ratios(5/10/20/50), volatility_10/20d, rsi+Δrsi, volume_ratio/spike, high-low range, day_of_week, foreign_pressure(한국 시뮬레이션).
- **라벨**: `(close.shift(-5) > close).astype(int)` — 5일 후 **방향** 이진 분류(수익률 크기 미반영).
- **분할**: train 80% / test 20% + `TimeSeriesSplit(n_splits=3)` Walk-Forward.
- **데이터 누수 방지**: 라벨에 명시적 `.shift(-5)`; 피처는 pct_change/rolling만 사용. 단 `forward_fill` 호출 시 미래 데이터 침투 가능성 — 코드상 fill은 ATR/ADX 결측 보정에만 사용.
- **HyperOpt**: Optuna 20 trials per WF split(`backtest_engine.py:451~541`).
- **SHAP**: `ml_predictor.py:194~200`에 스켈레톤만; **현재 호출 미작동**.
- **앙상블 산출**: `{prediction: UP/DOWN, up_probability, signal, model_count, avg_accuracy}` — 결정에는 `up_probability` 평균 + Decision Maker가 정확도 기반 가중.

### 3.7 진입/청산 (`chart_agent_service/entry_plan.py`, `stock_analyzer/entry_strategy.py`)

**주문 유형 결정 로직** (`entry_plan.py:95~143`):

```python
if rsi > 70:
    order_type, timing = "limit", "pullback"
    limit_price = price * (1 - 0.3 * atr_pct/100)
elif bb_squeeze:
    order_type, timing = "limit", "breakout_confirm"
    limit_price = bb_upper * 1.005
elif trend_weak:
    order_type = "wait"
else:
    order_type, timing = "limit", "immediate"
    limit_price = price + 0.1 * atr_pct/100
```

**분할 진입(tranche)** (`entry_plan.py:146~198`):

| confidence | 분할 비중 (1차/2차/3차) | 트리거 |
|---|---|---|
| ≥8 | 60 / 40 / – | 즉시 / RSI<50 ∨ 20일선 터치 |
| 6–8 | 40 / 30 / 30 | 즉시 / -1% / 지지선·20일선 |
| <6 | 30 / 0 / – | 탐색 진입만 ("신뢰도 낮음" 경고) |

**52주 고점 가드** (f3b4926): `entry_plan` 호출 시 `week52_high` 파라미터 추가. 진입가 > 52w high 면 진입 보류.

**손절·익절** (호가단위 정합):
```python
stop_loss   = round_to_tick(price - atr*ATR_STOP_MULTIPLIER,             ticker, side="down")
take_profit = round_to_tick(price + atr*ATR_STOP_MULTIPLIER*TAKE_PROFIT_RR_RATIO, ticker, side="up")
```

**Trailing Stop**: `risk_management.py:160~217` + `paper_trader.py:288~299`. `peak = max since entry`, `trailing = peak·(1-trailing_pct)`, 동적 조정 `max(trailing_pct, ATR_pct·0.5)`.

---

## 4. 리스크 관리 / 포지션 사이징

### 4.1 단일 종목 사이징 — ATR + Kelly

**기본 ATR 공식** (`risk_management.py:29~93`):

```
risk_amount  = account_size * RISK_PER_TRADE_PCT       (기본 1.0%)
stop_dist    = ATR * ATR_STOP_MULTIPLIER
shares       = risk_amount / stop_dist                  → round_to_tick
position_val = shares * price
cap          = MAX_POSITION_PCT (20%)                   → 상한 적용
```

**Kelly** (`analysis_tools.py:1355~1463`):

```
W/L         = avg_win / avg_loss
kelly_full  = win_rate − (1 − win_rate) / W/L
kelly_half  = kelly_full / 2
position_pct= min(kelly_half * 100, MAX_POSITION_PCT/2)  → 상한 10%
```

- `kelly_full < 1%` 또는 데이터 <60일 → "no_trade" 신호.
- Sharpe 보너스: >1.5 +2, <-0.5 -2 (`ANNUAL_RISK_FREE_RATE` 환경변수, 기본 0%).

### 4.2 포트폴리오 — Markowitz + Drift 리밸런싱

`portfolio_optimizer.py:29~77`:
```
mu       = returns.mean() * 252         # 연환산
cov      = returns.cov() * 252
bounds   = [(0, 0.4)] * n               # 종목당 ≤ 40%
sum w    = 1                            # fully invested
objective: maximize (port_ret - rf) / port_vol     # rf=5% 기본
```

`portfolio_rebalancer.py:73~109`:
- 정기: 7일
- 임계: `L1(current - target) > 5%` 즉시
- 거래비용 `TRANSACTION_COST_PCT = 0.001` (0.1%) per trade

### 4.3 종합 리스크 점수 (0~100, 높을수록 위험)

`risk_management.py:437~479`:

| 구성요소 | 가중 | 산식 |
|---|---|---|
| 포지션 비중 | 0–30 | 20% 초과 시 30 |
| 변동성 | 0–30 | extreme 30 |
| 손실 상태 | 0–20 | -10% 시 20 |
| 일일 리스크 | 0–20 | `ATR*shares/position_val > 5%` 시 20 |

임계: `>70` 즉시 축소 / `>50` 강화 모니터링 / `>30` 정상 / `≤30` 안정.

### 4.4 백테스트 (`chart_agent_service/backtest_engine.py`)

**4 전략**: SMA Cross / RSI Reversion / Bollinger Reversion / Composite(현재 도구 결과는 look-ahead 방지를 위해 과거 replay 생략).

**메트릭** (`_compute_stats`):

```python
total_return   = (eq_final / eq_initial - 1) * 100
annualized     = ((eq_final / eq_initial) ** (252/n_days) - 1) * 100
sharpe         = mean(daily_ret) / std(daily_ret) * sqrt(252)   # rf 미차감 (naive)
max_dd         = min((eq - cummax) / cummax) * 100
win_rate       = wins / total_trades
profit_factor  = gross_profit / max(abs(gross_loss), 1e-10)
```

**거래비용** (`trading_costs.py`):
```
한국: commission 0.015% + slippage 0.05% + sell_tax 0.18%  → roundtrip ≈ 0.41%
미국: commission 0%      + slippage 0.05%                  → roundtrip ≈ 0.10%
```

**Walk-Forward** (`backtest_engine.py:451~541`):
```
train_len = 252  (1년)
test_len  = 63   (3개월)
step      = (total - 252 - 63) / (n_splits-1)
optimizer = Optuna 20 trials
report    = overfitting_ratio = avg_train_sharpe / avg_test_sharpe
```

### 4.5 페이퍼 트레이딩 (`chart_agent_service/paper_trader.py`)

- 상태 영속화: JSON (`paper_trading_state.json`).
- 통화 처리: `is_korean_stock()` → ₩/$ 분기 (currency_utils + tick_size).
- 자동 청산 조건(line 265~343): Trailing Stop / 고정 Stop Loss / 고정 Take Profit / Time Stop.
- 신호 처리(line 227~262): `HOLD` 또는 `confidence<5` → 무시; BUY → 1차 tranche 발주.

### 4.6 신호 추적 (`chart_agent_service/signal_tracker.py`)

- 평가 기간 7/14/30일.
- `OUTCOME_THRESHOLD_PCT = 2.0` → BUY: >+2% win, <-2% loss / SELL은 부호 반대.

### 4.7 컨설팅 핵심 의문 응답

| 질문 | 답 |
|---|---|
| Sharpe 2.34, CAGR 28.5%의 가정? | **naive Sharpe(rf=0)** + 거래비용 차감(한국 0.41%/회) + ATR 기반 손절 가정. 표본 기간 편향(상승장 적합) 가능. Walk-Forward `overfitting_ratio` 보고서로 검증 필요. |
| 동일 종목 다중 BUY 시 자금 배분? | **현재 규칙 없음** — 각 시그널이 독립적으로 `process_agent_signal()` 호출, 1차 tranche를 각각 주문 → 의도치 않은 비중 누적 위험. → **즉시 보강 권고**. |
| 손절 ATR vs %? Trailing 알고리즘? | 기본 ATR 기반. 옵션으로 `stop_loss_price` 고정값 지원. Trailing은 `peak·(1-pct)`, 동적 `max(trailing_pct, ATR_pct·0.5)`. |

### 4.8 리스크 한도 현황

| 항목 | 현재값 | 위치 | 비고 |
|---|---|---|---|
| 일일 손실 한도 | **없음** | – | 누적 P&L 모니터만 |
| 종목 집중 한도 | 20% | `MAX_POSITION_PCT` | 단일 포지션 상한 |
| 전체 노출 한도 | 100% | rebalancer | fully invested |
| Risk per trade | 1.0% | `RISK_PER_TRADE_PCT` | 거래당 손실 |
| Kelly 상한 | 10% | `MAX_POSITION_PCT/2` | Kelly Half |
| Drift 리밸런싱 | 5% | rebalancer | L1 norm |

---

## 5. 데이터 파이프라인 / 품질

### 5.1 수집 소스

| 소스 | 라이브러리 | 용도 | 비고 |
|---|---|---|---|
| Yahoo Finance | `yfinance` | OHLCV (기본), 회사 정보, 뉴스 | 15분 지연, `auto_adjust=True` |
| FinanceDataReader | `fdr` | 한국 KRX 종목명·OHLCV | 한국 우선, 한글명 정확 |
| DART (전자공시) | 자체 `dart_api.py` | 공시 검색 | API 키 필수, 회사명 매핑 후 검색 |
| Google News RSS | `feedparser` | 뉴스 메타 | yfinance 뉴스와 병합 |
| FRED · FMP | `.env` 키 정의 | 매크로/펀더멘털 | 일부 코드 경로에서 사용 |
| Alpaca · Polygon · KIS | `data_sources/` 슬롯만 | 미구현 | Phase 2.3~2.4 예약 |

### 5.2 OHLCV 캐싱 (`data_collector.py:26~73`)

```python
prefetch_ohlcv_batch(tickers):
    yf.download(tickers, period=DEFAULT_HISTORY_PERIOD, auto_adjust=True)
    _ohlcv_cache[(ticker.upper(), period)] = df

# clear_ohlcv_cache(): 스캔 시작 전에만 호출
# 만료 로직 없음 → 런타임 stale 위험
# yf.download() 실패 시 except → pass (재시도 없음)
```

⚠️ 컨설팅 발견: **TTL·재시도·신선도 메타데이터 부재**.

### 5.3 데이터베이스 (`chart_agent_service/db.py`)

SQLite + WAL.

| 테이블 | 용도 | 쓰기 시점 | 사용 |
|---|---|---|---|
| `scan_log` | 종목별 스캔 결과 | 각 분석 후 | 활용 중 |
| `signal_outcomes` | 신호 사후평가 (7/14/30d 수익률) | 별도 배치 (미구현) | **사용 안 함** |
| `screener_results` | 스크리너 상위 N | 스크리너 실행 후 | 활용 중 |

- 마이그레이션: `ALTER TABLE ... ADD COLUMN entry_price` 등 `OperationalError` catch 패턴.
- 인덱스: `ticker`, `scanned_at`, `run_id`, `signal`.

### 5.4 종목 검증 3계층

| Layer | 파일 | 검증 |
|---|---|---|
| 형식 | `ticker_validator.py:54~92` | 한국 `^[0-9A-Z]{6}\.(KS|KQ)$`, 미국 `^[A-Z][A-Z0-9]{0,4}([.\-][A-Z])?$` |
| 존재 | `ticker_verifier.py:18~83` | `yf.Ticker().info` → 회사명, 가격 |
| 품질 | `ticker_verifier.py:96~193` | 50일+ 데이터, 거래량, 마지막 거래일 ≤5일, A~F 등급 + `can_analyze` |

**한국/미국 차이**:

| 항목 | 한국 | 미국 |
|---|---|---|
| 우선 소스 | FDR → yfinance | yfinance |
| 통화 | KRW | USD |
| 시장시간 | 09:00–15:30 KST | 09:30–16:00 EST |
| 특수 형식 | `0126Z0.KS`(FDR만 지원) | BRK.B 등 클래스주 |

**상장폐지/거래정지**: `info.currentPrice` 또는 `history()` 공백 → 경고만, 분석 차단 로직 없음.

### 5.5 DART 한국 공시 (`stock_analyzer/dart_api.py`)

- `DART_API_KEY` 필요.
- 흐름: 종목코드 → yfinance로 회사명 조회 → DART `corpCode.xml`에서 매핑 → `list.json` 공시 검색.
- 추출 가능 항목: 배당, 재무제표, 감사보고 — 코드 상 주석만 있고 **본격 구현 보류**.

### 5.6 뉴스 & 매크로

- **뉴스**: yfinance(.news 속성) + Google News RSS, Ollama 30초 타임아웃 감성분석. 실패 시 `{"sentiment":"neutral","score":0}`.
- **매크로** (`macro_context.py`): VIX, US10Y, DXY, WTI, S&P500, Gold. 1M 트렌드 + 1W Δ. regime 매핑: VIX>25 → risk_off, USD strong → headwind. 최종 신호에 ~15% 가중.

### 5.7 정합성 위험

| 영역 | 위험 |
|---|---|
| Timezone | 한국 종가 06:30 UTC vs 미국 21:00 UTC, 교차 비교 시 시차 + 15분 지연 |
| 분할/배당 | `auto_adjust=True` 블랙박스 — `actions` audit 없음 |
| 휴장일 | 주말만 제외, 한국 공휴일/미국 holiday 미반영 → indicator forward-fill 위험 |
| 다중 소스 충돌 | FDR vs yfinance 가격 편차 미감지(폴백만) |
| Stale 캐시 | 만료 없음, 실패 시 pass → 이전 캐시 사용 |

### 5.8 워치리스트

- SSOT: `stock_analyzer/watchlist.txt` (현재 7 종목, 가변).
- 복사본: `chart_agent_service/watchlist.txt` — **수동 동기화** (자동화 없음).
- WebUI 사이드바에서 편집 권장.

---

## 6. MCP 서버 (Claude Desktop 연동)

`mcp_server.py` (기본 6) + `mcp_server_extended.py` (확장 22).

**핵심 5**: `analyze_stock`, `predict_ml`, `optimize_strategy`, `walk_forward_backtest`, `portfolio_optimize`.

**개별 분석 도구**: RSI, Bollinger, MACD, Stochastic, ADX, ATR, MA, momentum, volatility, P/E, PEG, ROE, 부채비율, 차트 패턴, 뉴스 감정, 펀더멘털 헬스 등과 진입 계획 도구.

```json
{ "mcpServers": {
    "stock-ai": { "command": "python",
                  "args": ["/home/ubuntu/stock_auto/mcp_server_extended.py"] } } }
```

---

## 7. 강점 · 약점 · 컨설팅 권고

### 7.1 강점

1. **앙상블 다층 구조** — 24개 분석 도구 + 진입 계획 + 7 에이전트 + 5 ML 모델 + Decision Maker의 다단 합의로 단일 지표 편향 완화.
2. **자동 폴백** — Mac Studio 다운 시 RTX 5070으로 라우팅(2초 헬스체크).
3. **Pydantic Settings 일원화** — 60+ 필드 enum/range 검증, 기동 시 조기 실패.
4. **호가단위 정합** — 한/미 시장 자동 분기로 실제 체결 가능 가격 보장.
5. **신뢰도 평활화** — Whipsaw 방지(이전 vs 신규 신뢰도 weighted).
6. **이미지 다이어트** — webui 7.99→2.06GB (TF 제거).

### 7.2 약점

| 영역 | 약점 | 영향도 |
|---|---|---|
| 분석 방법론 | 모든 기술지표 후행 3–5봉, 횡보장 신뢰<50% | 중 |
| 분석 방법론 | 피보나치·지지저항 통계적 유의성 약함 | 중 |
| 분석 방법론 | 한국시장 특수성(외국인·공매도) 미반영 | 중 |
| ML | SHAP 호출 미작동 (스켈레톤만) | 낮음 |
| ML | 라벨이 5일 방향만(수익률 크기 무시) | 중 |
| 리스크 | 일일 손실 한도 부재 | **높음** |
| 리스크 | 다중 에이전트 동일 종목 신호 자금배분 규칙 부재 | **높음** |
| 리스크 | naive Sharpe(rf=0), Sharpe 2.34 의 표본 검증 미흡 | 중 |
| 리스크 | 테일 리스크(gap, VIX 급등) 대응 로직 부재 | **높음** |
| 데이터 | OHLCV 캐시 TTL·재시도 부재 | **높음** |
| 데이터 | `signal_outcomes` 미사용 → hit-rate 측정 불가 | **높음** |
| 데이터 | 분할/배당 audit 부재 | 중 |
| 데이터 | 휴장일·timezone 보정 부족 | 중 |
| 운영 | 모니터링/알림/CI 부재 | 중 |
| 운영 | `network_mode: host` — 단일 사용자 전제 | 낮음 (현재 운영자 1) |
| 운영 | README ↔ 코드 라우팅 표 불일치 | 낮음 (문서 갱신) |

### 7.3 우선순위별 권고

**P0 (즉시)**:
1. **일일 손실 한도 + 글로벌 kill-switch**: `DAILY_LOSS_LIMIT_PCT` 추가 (예: -3%/일). 초과 시 자동 신호 차단.
2. **다중 신호 자금배분 규칙 명문화**: 동일 종목 BUY 합산 시 confidence 가중 1회 주문 + 종목별 누적 상한 검증.
3. **OHLCV 캐시 TTL(예: 1h) + 지수 백오프 재시도** + 각 결과에 `data_freshness(as_of_date, age_hours, is_fresh)` 메타 부착. Stale 판정 시 신호 보류.

**P1 (1–2주 내)**:
4. **`signal_outcomes` 배치 활성화**: 주 1회 cron으로 7/14/30일 후 수익률 계산 → hit-rate, expectancy 산출 → ML/Decision Maker 가중치 피드백.
5. **백테스트 가정 투명화**: `rf` 명시, Walk-Forward overfitting_ratio 기본 출력, 분할/배당 actions audit 로그.
6. **휴장일/timezone 보정**: pandas_market_calendars 사용; forward-fill 금지 옵션.

**P2 (1개월)**:
7. **VaR/CVaR 도입**, β·상관 캡 (포트폴리오 상관계수>0.8 종목 제한).
8. **SHAP 실제 호출**, ML 라벨을 분류→회귀(수익률) 또는 다중 분류(상승/보합/하락)로 보강.
9. **Phase 5 — 모니터링**: `/metrics` 엔드포인트 + Prometheus + Grafana 대시보드(에이전트 latency, Ollama 응답시간, 캐시 hit, signal/day).
10. **CI/CD**: GitHub Actions에서 `docker compose build` + 핵심 path import smoke test.

**P3 (분기)**:
11. **다중 소스 일관성 검증**: FDR vs yfinance 가격 편차 모니터 + 임계 초과 시 신호 보류.
12. **한국 시장 특화**: pykrx 외국인 매매현황, 공매도 비율 통합.
13. **딥러닝 확장**: transformer 기반 시계열 모델 검토 (LSTM 대체).

---

## 8. 부록

### 8.1 핵심 파일 인덱스

| 경로 | 라인 범위 | 설명 |
|---|---|---|
| `compose.yaml` | 1–88 | dev/mac 프로파일 |
| `.env.example` | 1–142 | 60+ 설정 키 SSOT |
| `Makefile` | 1–43 | 14 운영 타깃 |
| `chart_agent_service/config.py` | 19–217 | Pydantic Settings + 호환 export |
| `chart_agent_service/service.py` | 492–832 | 19 FastAPI 엔드포인트 |
| `chart_agent_service/analysis_tools.py` | 73–1875 | 24개 분석 도구 + 진입 계획 |
| `chart_agent_service/screener.py` | 1–160+ | 한국 종목 스크리너 |
| `chart_agent_service/backtest_engine.py` | 58–541 | 4 전략 + WF |
| `chart_agent_service/ml_predictor.py` | 138–250 | TSCV + 모델 학습 + (미사용) SHAP 슬롯 |
| `chart_agent_service/risk_management.py` | 29–494 | 사이징, 트레일링, 리스크 점수 |
| `chart_agent_service/portfolio_optimizer.py` | 29–77 | Markowitz |
| `chart_agent_service/portfolio_rebalancer.py` | 24–109 | 7d/5% 리밸런싱 |
| `chart_agent_service/paper_trader.py` | 106–343 | 페이퍼 + 자동 청산 |
| `chart_agent_service/signal_tracker.py` | 23–150 | 7/14/30d 평가 |
| `chart_agent_service/entry_plan.py` | 35–198 | 진입 계획, 분할 |
| `chart_agent_service/trading_costs.py` | 11–71 | 한/미 비용 |
| `chart_agent_service/tick_size.py` | 11–25 | 호가단위 |
| `chart_agent_service/db.py` | 15–105 | SQLite WAL 3-테이블 |
| `chart_agent_service/data_collector.py` | 26–177 | OHLCV 캐시 + 지표 |
| `chart_agent_service/news_analyzer.py` | – | yfinance + Google News + Ollama 감성 |
| `chart_agent_service/macro_context.py` | 14–99+ | VIX/US10Y/DXY 등 6개 |
| `stock_analyzer/webui.py` | 1–5136 | Streamlit, 10 페이지 |
| `stock_analyzer/multi_agent.py` | 40–1841 | 8 에이전트 + Orchestrator |
| `stock_analyzer/enhanced_decision_maker.py` | 18–764 | 충돌 해결 + 평활화 |
| `stock_analyzer/dual_node_config.py` | 16–264 | 라우팅 + 폴백 |
| `stock_analyzer/ml_pipeline_fix.py` | 19–250 | 피처/라벨/학습 파이프 |
| `stock_analyzer/signal_normalizer.py` | 1–117 | 신호/점수 정규화 |
| `stock_analyzer/entry_strategy.py` | 59–202 | Kelly + 과열 + 피보 |
| `stock_analyzer/ticker_validator.py` | 54–92 | 형식 검증 |
| `stock_analyzer/ticker_verifier.py` | 18–270 | 존재 + 품질 + 한·미 라우팅 |
| `stock_analyzer/korean_stock_verifier_fdr.py` | 155–229 | FDR 우선 한국 검증 |
| `stock_analyzer/dart_api.py` | 20–100 | DART 공시 |
| `mcp_server.py` / `mcp_server_extended.py` | – | MCP 도구 6/21 |
| `docs/DEPLOY_BASELINE.md` | – | Phase 0–4 체크리스트 |
| `docs/PHASE_3_OPERATION.md` | – | 운영 게이트 |

### 8.2 환경변수 핵심 표

| 키 | 기본 | 의미 |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | RTX Ollama |
| `MAC_STUDIO_URL` | `http://hsptest-macstudio:8080` | Mac Studio Ollama |
| `OLLAMA_MODEL` | `qwen3:14b-q4_K_M` | 기본 모델 |
| `DEFAULT_LLM_PROVIDER` | `ollama` | `ollama`/`gemini`/`openai` |
| `TRADING_STYLE` | `swing` | `scalping`/`swing`/`longterm` |
| `TRADING_MODE` | `paper` | `paper`/`dry_run`/`approval`/`live` |
| `RISK_PER_TRADE_PCT` | 1.0 | 거래당 손실 한도 |
| `MAX_POSITION_PCT` | 20 | 단일 포지션 상한 |
| `TAKE_PROFIT_RR_RATIO` | 2.0 | 익절 R/R 배수 |
| `ANNUAL_RISK_FREE_RATE` | 0.0 | Sharpe 무위험률 |
| `MULTI_AGENT_MAX_WORKERS` | 2 (권장 4) | 병렬 워커 |
| `MULTI_AGENT_TIMEOUT` | 300 | 전체 에이전트 마감 (초) |
| `MULTI_AGENT_LLM_TIMEOUT` | 240 | 개별 LLM 호출 마감 |
| `TRADING_COMMISSION_PCT_KR` | 0.015 | 한국 수수료 |
| `TRADING_SLIPPAGE_PCT` | 0.05 | 공통 슬리피지 |
| `TRADING_SELL_TAX_PCT_KR` | 0.18 | 한국 매도세 |
| `TRANSACTION_COST_PCT` | 0.001 | 리밸런싱 비용 |
| `DART_API_KEY` / `FRED_API_KEY` / `FMP_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` | – | 외부 API 키 |

### 8.3 운영 명령어 요약

```bash
# 기동/종료
docker compose --profile dev up -d
docker compose --profile dev down

# 헬스 게이트
curl http://localhost:8100/health
curl http://localhost:8100/api/tags
open http://localhost:8501

# Mac Studio 폴백 시뮬
ssh hsptest-macstudio "brew services stop ollama"
docker exec stock-auto-webui python -c \
  "from dual_node_config import is_mac_studio_available; print(is_mac_studio_available())"
# False → RTX 5070 단독 모드

# 이미지 확인
docker images stock-auto/webui      # 2.06 GB
docker images stock-auto/agent-api  # 7.76 GB
```

### 8.4 결정 흐름 한 장 요약

```
fetch_ohlcv (yfinance + FDR)
   ↓
calculate_indicators (SMA/EMA/RSI/BB/ATR/ADX/MACD/OBV)
   ↓
[ Technical | Quant | Risk | ML | Event | Geo | Value ]  ── 7 에이전트 병렬
   │   │   │   │   │   │   │
   └────────── 분석 도구 호출 + LLM 해석 → AgentResult(signal, confidence, evidence) ──┐
                                                                                       ↓
                          EnhancedDecisionMaker (충돌해결 + 펀더멘털 검증 + 평활화)
                                                                                       ↓
                                              Final = { signal, confidence,
                                                        entry_plan(split, order_type, limit),
                                                        stop_loss(ATR), take_profit(R/R 2.0),
                                                        qty(risk_per_trade 1% + Kelly Half ≤ 10%) }
                                                                                       ↓
                                                  scan_log INSERT (SQLite WAL)
                                                                                       ↓
                                              ❎ signal_outcomes 평가 (미구현, P1)
```

---

**문서 끝.** 컨설팅 시 본 브리프를 출발점으로 §7.3의 P0–P3 우선순위 항목부터 검토하시면 바로 액션 가능합니다.
