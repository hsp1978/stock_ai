# Stock AI Analysis System V2 — 현재 시스템 설명서

> **작성 목적**: 외부 개선 의뢰(컨설팅) 전달용 현재 상태 기술서.
> **기준 시점**: 2026-09-10. 코드는 `fix/signal-eval-queue` (평가 큐 수리 반영, 운영 배포 완료).
> 그 직전 상태는 `main@58fa11c` (2026-08-18).
> **수치 출처**: 이 문서의 모든 숫자는 작성 시점에 실행 중인 시스템에서 직접 측정했다
> (`scan_log.db` 질의, `/health`·`/signal-accuracy` 응답, `docker`/`wc -l` 실측).
> 코드 주석·과거 브리프에 적힌 값과 다를 경우 **이 문서의 값이 실측**이다.

기존 `docs/CONSULTING_BRIEF.md`(도메인)·`docs/ARCHITECTURE_BRIEF.md`(아키텍처)는 2026-05-19
작성분으로, 이후 4개월간의 변경(신호 임계 재정합, R/R 게이트, 리포트 불변식, DB 커넥션 누수 수정,
토스증권 어댑터, 디자인 시스템 적용)이 반영돼 있지 않다. 두 문서는 **작성 시점 기록**으로만 참고하고,
현재 동작은 이 문서 → 코드 → `tests/` 순으로 확인할 것.

---

## 1. 한눈에 보기

| 항목 | 현재 값 |
|---|---|
| 목적 | 한국·미국 주식 워치리스트 EOD 분석 → 매수/매도/관망 + 진입가·손절·익절·수량 산출 |
| 사용자 | 운영자 1명 (개인 투자자) |
| 거래 단계 | `TRADING_MODE=paper` (실주문 없음). live 전환 전 60일 hit-rate 검증 게이트 존재 |
| 워치리스트 | 7종목 — `049430.KQ 328130.KQ FCX IBM IONQ MSFT PLTR` (운영 중 자주 변경) |
| 분석 주기 | 30분 스캔 + 매일 16:30 스크리너(표본 적립) + 17:30 멀티에이전트 배치 + 23:00 사후검증 |
| LLM | 8 에이전트 = Gemini 4 (gemini-3.6-flash, 폴백 3.5-flash) + Ollama 4 (Mac Studio qwen2.5:32b) |
| 분석 도구 | 24개 (방향성 22 + 비방향성 2: `risk_position_sizing`, `entry_plan_analysis`) |
| ML | 5모델 앙상블 (RF/GBM/LightGBM/XGBoost/LSTM) + SHAP + Optuna + Walk-Forward |
| 코드 규모 | 프로덕션 Python 약 54,000 라인 / 최대 파일 `service.py` 3,192 라인 (`webui.py` 는 350) |
| API | FastAPI 엔드포인트 83개 (`chart_agent_service/service.py`, 3,192 라인) |
| 테스트 | 65 파일 / 679 test, CI(GitHub Actions) 최근 실행 전부 success |
| 데이터 축적 | `scan_log` 69,341행 (2026-04-14~), `signal_outcomes` 5,018행 — 평가 완료 4,272 / 종결 53 / 대기 0 |
| 이미지 | agent-api 8.0GB / webui 1.97GB |

**가장 중요한 현재 상태 한 줄**: 2026-09-10까지 **성과 측정 루프가 정지**해 있었다 —
08월 로직 개편 이후 신호 3,744건 중 평가 완료 0건. 원인(평가 큐 아사)은 같은 날 수리해
소급 평가를 마쳤고(§13.1), 이제 **현재 로직의 실측치가 처음으로 존재한다**(§11).
표본 단위까지 바로잡은 결과(§13.2), 현재 로직의 정직한 실측은 **방향 보정 기대값 +0.72%
(독립 블록 117개)**, 리포트·주문 경로만 보면 **+0.29%(블록 100개)**다 — 우위를 주장하기엔
표본이 아직 부족하다.

---

## 2. 운영 맥락 — 이 시스템이 지금 무엇을 하고 있는가

1. **30분마다** 워치리스트 7종목에 24개 도구를 전수 실행하고, 로컬 단일 LLM
   (RTX 5070 / qwen3:14b)이 그 결과를 종합해 `scan_log`에 신호를 남긴다.
   임계값을 넘으면 텔레그램으로 알린다. (경량 경로 — 8 에이전트는 돌지 않는다)
2. **매일 17:30** (KRX 마감 이후) 멀티에이전트 V2 배치가 8개 LLM 에이전트를 돌려
   종목별 최종 리포트를 만들고 `signal_outcomes`에 표본을 적립한다.
3. **매일 23:00** 과거 신호의 7/14/30일 실현 수익률을 채워 hit-rate를 갱신하고
   신뢰도 칼리브레이터를 재학습한다.
4. 운영자는 Streamlit WebUI(17페이지)에서 결과를 열람하고, 페이퍼 계좌로 가상 매매하며,
   워치리스트를 편집한다. **실주문 경로는 코드로 존재하지만 활성화돼 있지 않다.**

이 시스템의 설계 이력은 "기능 추가"보다 **"거짓 정상 보고 제거"** 쪽에 훨씬 많은 노력이 들어가 있다
(§14). 개선 의뢰 시 이 맥락을 유지해 주는 것이 중요하다.

---

## 3. 인프라 · 배포

```
Tailscale Tailnet (testffa97.ts.net)
├─ testdev  (Ubuntu 24, RTX 5070 12GB)          ← 모든 서비스가 여기
│  ├─ stock-auto-webui     Streamlit :8501   (network_mode: host)
│  ├─ stock-auto-agent-api FastAPI  :8100    (network_mode: host, CUDA 비활성)
│  └─ Ollama (native, 호스트) :11434  qwen3:14b-q4_K_M — GPU 전용 점유
└─ hsptest-macstudio (macOS M1 Max 32GB)
   └─ Ollama (Homebrew) :8080  qwen2.5:32b-instruct-q4_K_M, gpt-oss:20b
```

- 오케스트레이션: `docker compose --profile dev up -d` (2 서비스). `Makefile` 14 타깃.
- **GPU 정책**: RTX 5070은 Ollama 전용. agent-api 컨테이너는 `CUDA_VISIBLE_DEVICES=-1`로
  TensorFlow가 GPU를 잡지 못하게 막는다 — LSTM이 VRAM을 잡으면 Ollama가 CPU로 밀려
  추론이 10배 이상 느려지고 에이전트 호출이 연쇄 타임아웃된다.
- **Mac Studio 폴백**: `dual_node_config.py`가 `/api/tags`로 헬스를 확인(TTL 10초, 실패 2회 시
  차단, 쿨다운 90초)하고, 다운 시 Ollama 에이전트 4개를 RTX 5070 + qwen 14B로 강등한다.
  Gemini 에이전트 4개는 Mac Studio 상태와 무관하다.
- **장애 대비 설정**(둘 다 실제 사고 후 추가): `ulimits.nofile 16384/65536`,
  json-file 로그 `max-size 50m × 5`. 2026-08-18에 SQLite 커넥션 누수로 fd가 고갈되고
  그 스택트레이스가 7일간 241GB를 쌓아 디스크를 채운 사고가 있었다.
- 시크릿: `.env` 63개 키가 SSOT. git·docker 이미지에서 모두 제외.

### 3.1 컨테이너별 마운트 차이 (개선 작업 시 함정)

| 경로 | agent-api | webui |
|---|---|---|
| `stock_analyzer/` 전체 | `:ro` 마운트 → **재빌드 없이 재시작만으로 반영** | 이미지에 baked → **재빌드 필요** |
| `stock_analyzer/watchlist.txt` | rw 마운트 (API가 쓴다) | rw 마운트 (공유 SSOT) |
| `chart_agent_service/{output,data,charts}` | rw 마운트 | 없음 |

즉 `webui.py` 수정은 이미지 재빌드가 필요하고, `multi_agent.py` 수정은 재시작으로 충분하다.
HTTP 200은 코드 반영의 증거가 아니다.

---

## 4. 코드베이스 지도

프로덕션 Python 53,834 라인 (venv·archive 제외). 상위 파일:

| 파일 | 라인 | 역할 |
|---|---:|---|
| `stock_analyzer/webui.py` | 350 | Streamlit 부팅·내비·커맨드바·라우팅. 화면은 `ui/pages/` 17개로 분리 완료(§13.9a) |
| `chart_agent_service/service.py` | 3,192 | FastAPI 83 엔드포인트 + APScheduler 5 잡 |
| `chart_agent_service/analysis_tools.py` | 3,087 | 24 도구 + `ChartAnalysisAgent` (도구 실행 오케스트레이션) |
| `stock_analyzer/multi_agent.py` | 2,406 | 8 에이전트 클래스 + `MultiAgentOrchestrator` |
| `stock_analyzer/local_engine.py` | 1,895 | webui↔agent-api 브릿지 (직접 import + HTTP 이중 경로) |
| `stock_analyzer/enhanced_decision_maker.py` | 1,423 | 점수 합산·충돌 해결·게이트·평활화 (**신호 판정의 실질 본체**) |
| `chart_agent_service/screener.py` | 1,034 | KOSPI/KOSDAQ 전체 기술적 스크리너 |
| `chart_agent_service/db.py` | 806 | SQLite WAL, 스레드-로컬 커넥션 |

디렉토리 요약:

```
chart_agent_service/          # agent-api (FastAPI)
├ analysis_tools.py           # 24 도구 + 도구 카탈로그(TOOL_DEFINITIONS)
├ ml_predictor.py             # 5모델 앙상블 + SHAP
├ backtest_engine.py / backtest_metrics.py   # 4전략 + DSR/PBO
├ risk_management.py          # ATR 사이징, 샹들리에 청산, 트레일링 스톱
├ portfolio_optimizer.py / portfolio_rebalancer.py
├ signal_tracker.py           # 사후 평가 + ConfidenceCalibrator
├ llm_calibrator.py           # ECE + Isotonic Regression
├ ic_ensemble.py              # IC 가중 앙상블 (60일 표본 필요)
├ paper_trader.py             # 페이퍼 계좌 (JSON 상태)
├ screener.py / sector_compare.py / quant_indicators.py
├ macro_context.py / news_analyzer.py / dart_client.py
├ signal_agg/                 # SignalAggregator (conviction 합성, 노출 한도)
├ safety/kill_switch.py       # 포트폴리오 수준 자동 정지
├ execution/                  # order_router, approval_queue, audit_log
├ brokers/                    # base, paper, dry_run, alpaca, toss(+auth), factory, safety
├ data_sources/               # yfinance, fdr, pykrx, alpaca, toss, factory
├ regime/                     # 룰 기반 5-state 체제 판정
├ llm/                        # LiteLLM Router 3-tier + circuit breaker + schemas
├ market_cal/                 # pandas_market_calendars (XKRX/NYSE)
└ jobs/                       # evaluate_signal_outcomes, calibration_metrics

stock_analyzer/               # webui (Streamlit) + 에이전트 정의
├ webui.py                   # 350줄 — 부팅·내비·커맨드바·라우팅 (§13.9a)
├ ui/                        # 공용 8모듈 + pages/ 17페이지 (분해 완료 2026-09-14)
├ report_format.py, report_invariants.py, report_schema.py
├ multi_agent.py, enhanced_decision_maker.py, agent_groups.py, signal_normalizer.py
├ dual_node_config.py, local_engine.py, gpu_monitor.py
├ korean_stocks.py, ticker_{manager,validator,verifier,suggestion}.py, krx_fundamentals.py
└ watchlist.txt              # SSOT (webui·agent-api 공유)
```

---

## 5. 분석 파이프라인

### 5.1 전체 흐름 (일일 배치 = 최종 리포트 경로)

```
watchlist.txt (7종목)
   ↓ prefetch_ohlcv_batch  — yfinance 1회 배치 다운로드 + TTL 캐시
[데이터 계층]  OHLCV / 펀더멘털 / 뉴스 / 거시 / 외국인·공매도 / DART 공시
   ↓
[도구 계층]  24개 분석 도구 → 각 도구가 {signal, score, 근거 필드} 반환
   ↓                              score 개별 범위 [-6, +8]
[에이전트 계층]  8 LLM 에이전트 — 자기 담당 도구 결과를 근거로 서술 + signal/confidence(0~10)
   ↓            Gemini 4개 · Mac Studio Ollama 4개 병렬 (max_workers=2, 전체 300s)
[그룹 계층]  agent_groups.py — Technical/Fundamental/Macro/Risk 4그룹 confidence-weighted vote
   ↓            한 도메인이 죽어도 나머지 그룹 신호는 유지
[판정 계층]  EnhancedDecisionMaker
   ↓            정량 기여(도구 평균) + 정성 기여(LLM 서술, 상한 있음) → total_score
   ↓            → 신호/강도/신뢰도 → R/R 하드 게이트 → 신뢰도 평활화 → execution_ready
[검증 계층]  report_invariants.py — 리포트 자기 정합성 불변식. 위반 시 execution_ready=False
   ↓            report_schema.py — 출력 필드 레지스트리 (소비자 없는 필드 차단)
[출력]  Markdown 리포트 · WebUI · 텔레그램 · signal_outcomes 적립 · (선택) order_router
```

30분 주기 스캔은 별도의 경량 경로다(`analyze_ticker` → `ChartAnalysisAgent`):
24개 도구를 전수 실행한 뒤 **로컬 단일 LLM 1회 호출**(기본 `ai_mode="ollama"`,
RTX 5070 qwen3:14b)로 종합 판단을 받는다. Ollama가 응답하지 않으면 룰 기반
`compute_composite_score()`로 자동 강등되고, GPU 일시 해제 중에는 스캔 자체가 차단된다
(모델 재적재를 막기 위함). 8 에이전트·그룹 집계·불변식 검증은 이 경로에 없다.
이 때문에 `scan_log`(69,341행)와 멀티에이전트 리포트는 신호가 다를 수 있고,
`decision_context.py`가 두 경로의 신호 어휘·horizon(기본 7일)을 강제로 통일한다.

### 5.2 24개 분석 도구

| 그룹 | 도구 |
|---|---|
| 기술 (6) | `trend_ma`, `rsi_divergence`, `bollinger_squeeze`, `macd_momentum`, `adx_trend_strength`, `volume_profile` |
| 퀀트 (6) | `fibonacci_retracement`, `volatility_regime`, `mean_reversion`, `momentum_rank`, `support_resistance`, `correlation_regime`(Hurst) |
| 리스크·이벤트 (5) | `risk_position_sizing`※, `kelly_criterion`, `beta_correlation`, `event_driven`, `insider_trading` |
| 확장 (7) | `money_flow_index`, `rsi_mfi_combined`, `macd_rsi_cross`, `piotroski_fscore`, `altman_zscore`, `institutional_flow`(외국인/공매도), `dart_disclosure` |
| 실행 계획 | `entry_plan_analysis`※ — 진입 시점·3분할·손절/익절 |

※ `NON_DIRECTIONAL_TOOLS` — 방향 점수 집계에서 제외된다.

### 5.3 에이전트 라우팅 (`dual_node_config.py`)

| 에이전트 | provider | 모델 | 담당 |
|---|---|---|---|
| Technical Analyst | ollama / mac_studio | qwen2.5:32b | 기술 지표 패턴 |
| Quant Analyst | ollama / mac_studio | qwen2.5:32b | 통계·확률 |
| Risk Manager | ollama / mac_studio | qwen2.5:32b | Kelly/ATR/Beta |
| ML Specialist | ollama / mac_studio | qwen2.5:32b | 앙상블 예측 해석 |
| Value Investor | gemini | gemini-3.6-flash | 재무제표·밸류에이션 |
| Event Analyst | gemini | gemini-3.6-flash | 뉴스·내부자 거래 |
| Geopolitical Analyst | gemini | gemini-3.6-flash | 거시·지정학·FX 노출 |
| Decision Maker | gemini | gemini-3.6-flash | 충돌 해결·최종 판단 |

LLM 호출 규약: LiteLLM Router 3-tier 폴백(Gemini → Mac 32B → RTX 14B),
Pydantic 스키마 강제(자유 텍스트 금지), 개별 타임아웃 Gemini 30s / Ollama 240s,
`tenacity` 재시도 + `circuitbreaker`. 파싱 실패 시 **neutral 안전 응답**으로 떨어진다.
Ollama 컨텍스트는 `num_ctx=8192`(기본 4,096에서 상향 — 프롬프트 절단 사고 후), `keep_alive=1h`.

### 5.4 신호 판정 규칙 (2026-08 개편분)

| 규칙 | 값 / 동작 | 배경 |
|---|---|---|
| composite score 스케일 | **방향성 도구 평균**. 실측 분포 [-1.00, +2.04] (p50 +0.41) | 과거 ±2.0은 '합계' 스케일 잔재로 BUY 40일간 1건·SELL 도달 불가였다 |
| 신호 임계 | BUY ≥ **1.3** / SELL ≤ **-0.5** (`SIGNAL_*_THRESHOLD`) | 위 스케일에 정합 |
| 알림 임계 | BUY ≥ 1.2 / SELL ≤ -0.4 (`BUY_THRESHOLD`) | 신호 판정이 binding이 되도록 알림을 더 느슨하게 |
| R/R 하드 게이트 | 최소 risk/reward < **0.8** 이면 매수 → 관망 강등 | 경고만 띄우고 매수 신호를 그대로 내보낸 결함 수정 |
| 정성 기여 상한 | LLM 서술 기여가 정량(도구) 기여를 넘지 못한다 | 서술이 점수를 뒤집는 문제 |
| 신뢰도 하한 | `MIN_CONFIDENCE=5.0` 미만이면 강도 라벨을 weak 이하로 절하 | 강도·신뢰도 표기 모순 |
| 신뢰도 평활화 | 직전 5회 이력으로 급변 억제 | |
| 자기 정합성 | 합계 불일치 등 불변식 위반 시 `warnings`/`key_risks`에 노출 + `execution_ready=False` | "종합 +5.0 = 부분합 −1.0+1.0+0.0+16.5" 같은 모순 리포트가 사람 검산까지 살아남았다 |
| 출력 필드 | `report_schema.py`에 선언되지 않은 필드는 테스트가 차단 | 소비자 없는 죽은 필드(`regime_weighted_score`)가 기능 착시를 만들었다 |

`SignalAggregator`(`signal_agg/aggregator.py`)는 별도 경로로 conviction을
`agent 0.4 + ml 0.4 + tool 0.2`로 합성하고, 종목당 단일 active position 규칙과
노출 한도(종목 10% / 섹터 25% / 통화 60%)를 검사한다.

### 5.5 리스크·진입 계획

- 포지션 사이징: ATR 기반 (`RISK_PER_TRADE_PCT=1.0`, `ATR_STOP_MULTIPLIER=2.0`(swing),
  `MAX_POSITION_PCT=20`), Kelly 보조. 계좌 규모는 통화별 분리
  (`ACCOUNT_SIZE=100,000 USD` / `ACCOUNT_SIZE_KRW=100,000,000`) — 통일 시 고가 국내 종목 수량이 0으로 잘렸다.
- 익절: `TAKE_PROFIT_RR_RATIO=2.0`. 3분할 진입 40/30/30%. 재진입 쿨오프 3일.
- 트레일링 스톱·샹들리에 청산·시간 기반 청산은 `risk_management.py`/`paper_trader.py`에 구현.
- 거래비용 가정: 국내 수수료 0.015% + 매도세 0.18%(+거래세 0.20%), 미국 0%, 슬리피지 0.05%,
  무위험수익률 KR 3.5% / US 4.5% (`docs/BACKTEST_ASSUMPTIONS.md`).

---

## 6. ML · 백테스트 · 스크리너

- **ML 앙상블**: RF / GBM / LightGBM / XGBoost / LSTM → 5일 후 방향 확률.
  성능 기반 가중 + 모델 간 합의도를 confidence로, SHAP으로 feature importance.
  Optuna 하이퍼파라미터 탐색, Walk-Forward 과적합 검증. **CPU 추론** (GPU는 Ollama 전용).
- **백테스트**: SMA Cross / RSI Reversion / Bollinger Reversion / Composite 4전략.
  현재 도구 결과의 과거 replay는 look-ahead 방지를 위해 제외. 성과는 **DSR + PBO 보정 후** 해석하는 것이 규칙.
- **스크리너**: KOSPI+KOSDAQ 전체 → 시총 2,000억+ 필터(약 280종목) → 배치 OHLCV →
  기술 점수 0~100 + 감점 → 등급. `screener_results` 테이블에 785행 축적.
  워치리스트에 자동 등록하지 않는다(SSOT 정책).

---

## 7. 주문 실행 & 안전장치

```
entry_plan → OrderRequest → TradingSafety.require_all_checks → 모드별 분기 → AuditLog
```

| `TRADING_MODE` | 동작 | 현재 |
|---|---|---|
| `paper` | 내부 시뮬레이터 (JSON 상태) | ✅ 활성 |
| `dry_run` | 주문 생성만, 전송 없음 | 코드 존재 |
| `approval` | 승인 큐 + 텔레그램 콜백 승인 (TTL 30분) | 코드 존재 |
| `live` | 실제 브로커 전송 | 코드 존재, 미사용 |

- 브로커 어댑터: `paper`, `dry_run`, `alpaca`(구현), `toss`(구현 — OAuth2 client credentials,
  IP allowlist 필수, 국내·미국 주문/계좌 + 국내 시세), `kis`(슬롯만).
  자격증명 없으면 각각 dry_run / yfinance로 안전 폴백.
- 한도: 일일 $1,000 / ₩1,000,000, 단건 $200 / ₩200,000. `ENFORCE_MARKET_HOURS=False`.
- **GlobalKillSwitch**: 일손실 2%(경고)/3%(정지), 주간 DD 5%, 최고점 대비 DD 10%,
  연속손실 5회, VIX 30 초과 또는 20% 급등, 데이터 6시간 stale → 신규 주문 차단(쿨다운 24h).
  이벤트는 `kill_switch_events`에 append-only. 현재 발동 이력 0건.

---

## 8. 상태 저장소

| 저장소 | 위치 | 실측 |
|---|---|---|
| SQLite (WAL) | `chart_agent_service/output/scan_log.db` (11MB + WAL 4MB) | 아래 표 |
| 페이퍼 계좌 | `output/paper_trading_state.json` | 계좌 $100,000 / 현금 $38,874 / 포지션 2 / 청산 0 / 주문 4 |
| 분석 결과 JSON | `output/*.json` | **69,421 파일 / 1.6GB — 정리 cron 없음** |
| 워치리스트 | `stock_analyzer/watchlist.txt` | 7종목, 두 컨테이너 공유 rw 마운트 |
| 앱 상태 | `app_state` 테이블 8키 (job_status, 스캔이력, GPU pause, 알림 dedupe 등) | 재시작 복원용 |

| 테이블 | 행수 | 비고 |
|---|---:|---|
| `scan_log` | 69,341 | 2026-04-14 ~ 현재. 최근 60일 BUY 2,091 / HOLD 22,569 / SELL 1,705 |
| `signal_outcomes` | 5,013 | 2026-07-06 ~ 현재. buy 2,753 / sell 2,260 |
| `screener_results` | 785 | |
| `user_action_log` | 252 | page_view 204 / watchlist_edit 42 / manual_scan 6 |
| `app_state` | 8 | |
| `kill_switch_events` | 0 | |
| `signal_outcomes_legacy` | 0 | |

마이그레이션 도구 없음 — 스키마는 `db.py`의 `CREATE TABLE IF NOT EXISTS` + 임시 `ALTER`로 관리
(Alembic 도입은 미완). `db.py`는 스레드-로컬 커넥션 + 워커 스코프 해제(2026-08-18 누수 수정분)를 쓴다.

---

## 9. 스케줄러 (agent-api 프로세스 내 APScheduler)

| job id | 주기 | 내용 |
|---|---|---|
| `watchlist_scan` | 30분 | 워치리스트 도구 스캔 + 임계 초과 시 텔레그램 |
| `multi_agent_batch` | 매일 17:30 | 8 에이전트 V2 배치 → 리포트 + `signal_outcomes` 적립 |
| `daily_signal_validation` | 매일 23:00 | 사후 평가(7/14/30일) + 칼리브레이터 재학습 |
| `corporate_actions` | 매일 00:05 | 액면분할·배당 등 페이퍼 포지션 보정 |
| `data_health_check` | 60분 | 데이터 stale(24h) 감지 → data_health 강등 + 알림 |

모든 잡은 시작/성공/실패를 `app_state`에 기록하고 `/ops/jobs`로 노출한다.
잡 상태는 재시작 후에도 복원된다.

---

## 10. 관찰성

- `/health` — status, ollama 연결, **`ollama_runtime`(GPU/CPU 실적재 여부)**,
  `gpu_pause`, `alert_delivery`, 캐시/스캔 카운트, 스케줄러 상태, 마지막 신호검증 결과.
  현재 실측: `ollama_runtime.status=gpu` (qwen3:14b 10.8GB 전량 VRAM),
  알림 누적 성공 1,043 / 실패 7 (마지막 성공 2026-09-10 06:38).
- `/ops/jobs`, `/ops/data-health`, `/system-monitor`, `/gpu/{status,pause,extend,resume}`.
- 로깅은 여전히 상당 부분 `print()` 기반 → 컨테이너 stdout(로테이션 50MB×5).
  구조화 로깅·메트릭(Prometheus)은 미도입.
- 텔레그램: rich signal, daily digest, 승인 콜백. **전송 결과를 확인해 기록**한다
  (과거 `alert_sent=1`이 미발송을 덮던 결함 수정분 — 2026-07-31 이전 알림 이력은 신뢰 불가).

---

## 11. 측정 현황 — 실제 성과 숫자

> 2026-09-10 두 건의 수리를 거친 값이다. ① 평가 큐 아사 수리 + 소급 평가(§13.1),
> ② 표본 독립성 — 30분 스캔의 하루 최대 48회 반복 기록이 통계를 지배하던 문제(§13.2).
> 그 이전 이 문서가 담고 있던 숫자(win_rate 34.4% / 표본 812건, 그리고 수리 직후의
> 44.9% / 4,272건)는 **독립 표본이 아닌 원시 행 집계**였다.

### 11.1 표본 단위에 따라 지표가 얼마나 달라지는가

`/signal-accuracy` 실측 (7일 horizon, 180일, 2026-09-10):

| 표본 단위 | n | 독립 블록 | 승률 | 95% 구간 | 최다 소스 |
|---|---:|---:|---:|---|---|
| `none` (원시 행) | 4,272 | 378 | 44.9% | 40.0–50.0 | scan_agent 73.3% |
| **`ticker_day`** (기본) | 1,223 | 378 | **33.7%** | 29.0–38.5 | group_technical 23.3% |
| `ticker_horizon` (비겹침) | 378 | 378 | 29.4% | 25.0–34.1 | group_technical 23.3% |

원시 행으로 세면 승률이 11%p 높게 나오고, 표본의 73%가 한 소스(30분 스캔)에서 나온다.
`ticker_day`로 접으면 소스 구성이 대등해지고 승률은 33.7%로 내려간다.
**신뢰구간은 독립 블록 수(378) 기준**이다 — 행 수(4,272)로 계산하면 구간이 거짓으로 좁아진다.

### 11.2 로직 개편(2026-08-06) 전후 — 표본 단위 `ticker_day`

`signed`는 방향 보정 기대값(매수 +수익률 / 매도 −수익률)이며, 2026-09-10부터
`/signal-accuracy`가 이 값을 `avg_signed_return_pct`로 직접 반환한다(§13.3).
원시값은 `avg_raw_return_pct`로 따로 나온다.

| 구간 | n | 독립 블록 | signed 평균(7일) | signed 중앙값 | 양(+) 비율 |
|---|---:|---:|---:|---:|---:|
| 구 로직 (~08-05, KOSPI 급락 국면) | 935 | 261 | **−1.50%** | −0.06% | 46.6% |
| 신 로직 (08-06~) | 288 | 117 | **+0.72%** | +0.71% | 58.3% |
| 신 로직, `scan_agent` 제외 | 214 | 100 | **+0.29%** | +0.22% | 54.2% |
| 신 로직, `scan_agent`만 | 74 | **17** | +1.94% | +1.90% | 70.3% |

### 11.2b 시장 대비 초과수익 (2026-09-11 추가)

절대 수익만으로는 '시장이 올라서 오른 것'과 '신호가 맞아서 오른 것'을 구분할 수 없다.
`signal_outcomes`에 벤치마크 수익률(KOSDAQ `^KQ11` / KOSPI `^KS11` / S&P500 `^GSPC`)을
기록하고 방향 보정 초과수익을 계산한다 (§13.4). 소급 채움 4,352행 완료.

| 구간 | n | 독립 블록 | 절대 | **시장 대비** | 시장 상회율 |
|---|---:|---:|---:|---:|---:|
| 구 로직 (~08-05, 급락장) | 909 | 252 | −1.54% | **−1.39%** | 49.6% |
| 신 로직 (08-06~) | 297 | 124 | +0.66% | **+0.81%** | 57.9% |
| 신 로직, `scan_agent` 제외 | 221 | 107 | +0.23% | **+0.41%** | 53.4% |

전체 180일 창의 시장 상회율은 **51.7%** — 동전던지기와 구분되지 않는다.
소스별로는 **주력 경로가 시장을 밑돈다**: `group_technical` −2.27%, `group_risk` −2.10%,
`multi_agent_final` −1.89%. 유일한 플러스인 `group_macro`(+2.02%)도 신 로직 구간으로
좁히면 −0.05%(블록 25)로 사라진다 — 표본 편향이다.

**읽는 법**:

1. 원시 집계의 신 로직 +2.31%는 표본 단위를 적용하면 **+0.72%**로 줄어든다.
   그 차이는 대부분 30분 스캔의 반복 기록이 만든 것이다.
2. 그 스캔 표본조차 독립 블록이 **17개**뿐이다 — +1.94%는 통계라기보다 잡음이다.
3. 리포트·주문이 실제로 쓰는 경로(일일 멀티에이전트)는 +0.29%, 블록 100개.
   **아직 시장 대비 우위를 주장할 수 없다.**
4. win 정의는 7일 수익률이 신호 방향으로 ±2% 이상 움직인 경우다. ±2% 이내는 neutral로
   분리되므로 win_rate는 승률이 아니다.
5. 53건(`057050.KS`)은 거래 중단으로 평가 불가 — 종결 처리돼 통계에서 빠진다.
6. 방향 보정 전에는 매도 신호가 맞을수록 지표가 나빠졌다. 수정 후 실측(180일, `ticker_day`):
   전체 방향보정 **−0.98%** / 원시 −1.13%, 매도만 보면 **방향보정 +0.16%** / 원시 −0.16%로
   부호가 뒤집힌다 (§13.3).

### 11.2c 평가 기간 정합 (2026-09-11)

대표 평가 horizon 은 이제 매매 스타일의 **의도 보유기간**에서 파생된다 (§13.5).
현재 `swing` = 보유 10일 → 대표 horizon **14일**. 종전 7일 하드코딩은 보유 도중의
중간 성과를 재고 있었다.

| horizon | 구간 | n | 블록 | 절대 | 시장 대비 | 상회율 |
|---|---|---:|---:|---:|---:|---:|
| 7일 (종전 기본) | 전체 180일 | 1,232 | 385 | −0.98% | −0.85% | 51.7% |
| **14일 (현 기본)** | 전체 180일 | 1,141 | 230 | **−2.57%** | **−2.31%** | — |
| 7일 | 신 로직, scan 제외 | 221 | 107 | +0.23% | +0.41% | 53.4% |
| **14일** | 신 로직, scan 제외 | 172 | 67 | **+0.77%** | **+0.91%** | 58.1% |

방향이 갈린다 — 전체 창(급락장 포함)은 14일에서 더 나쁘고, 신 로직 구간은 더 좋다.
**독립 블록이 107 → 67로 줄어드는 것이 더 중요한 사실이다**: horizon 을 늘리면
관측 구간이 겹쳐 유효 표본이 줄어든다. 어느 쪽이든 우위를 주장할 크기가 아니다.

### 11.2d 밴드 제거 — 대표 지표를 방향 적중률 + 분포로 (2026-09-11)

win 정의가 "신호 방향으로 ±2% 이상"이었는데 **±2%에 근거가 없고**, horizon 이 길수록
넘기 쉬워져(14일 ±2%는 7일 ±2%보다 느슨) 기간 간 비교를 왜곡했다 — 실측으로 같은
데이터의 '승률'이 7일 33.6% → 14일 39.1%로 올라간다. 지표 개선이 아니라 밴드 효과다.

대표 지표를 임의 임계가 없는 것들로 바꿨다 (§13.6). 현재 실측 (14일, `ticker_day`, 180일):

| 지표 | 값 |
|---|---|
| **방향 적중률** | **51.9%** (n=1,141, 95% CI 45.3~58.1 / 독립 블록 230) |
| 절대 수익 분포 | p25 **−8.53%** / 중앙 **+0.14%** / p75 **+7.03%** (평균 −2.57%) |
| 초과수익 분포 | p25 −9.25% / 중앙 +0.38% / p75 +7.85% (평균 −2.31%, 시장 상회 51.4%) |
| [참고] ±2% 밴드 | 승 446 / 패 440 / 중립 255 → 밴드승률 39.1% |

**분포를 보니 평균만 볼 때 안 보이던 게 드러난다**: 중앙값은 절대·초과 모두 0 근처인데
평균은 −2.5% 안팎이다. 즉 **왼쪽 꼬리(대형 손실)가 평균을 끌어내리고 있다.**
방향은 반반 맞히지만 틀릴 때 더 크게 잃는 구조다 — 손절·포지션 사이징 쪽 문제로
읽히며, 신호 방향 자체를 더 손보는 것보다 우선순위가 높을 수 있다.

### 11.2e 왼쪽 꼬리 — 역행폭과 손절 시뮬레이션 (2026-09-12)

§11.2d에서 "틀릴 때 더 크게 잃는다"가 드러나, 보유 구간 중 **신호 반대 방향 최대 이동
(역행폭)** 을 기록해 손절이 어디서 걸렸을지 되짚었다 (§13.7). 소급 채움 4,356행 완료.

| 지표 (14일, `ticker_day`, 180일) | 값 |
|---|---|
| 꼬리 | p10 **−29.8%** / p90 +19.1% → tail_ratio **1.56** |
| 손익비 | 평균손실 18.4% / 평균이익 12.1% → **payoff 0.66** (손실 비중 48.0%) |
| 역행폭 분포 | p25 3.0% / 중앙 **7.4%** / p75 **15.5%** |

**방향 적중률 51.9% × payoff 0.66 = 구조적 적자.** 신호 방향이 아니라 손익 비대칭이
기대값을 만들고 있다.

#### 손절 시뮬레이션 — 그런데 기간에 따라 부호가 바뀐다

| 구간 | n | 손절 없음 | 손절 5% | 손절 10% | 손절 15% |
|---|---:|---:|---:|---:|---:|
| 전체 180일 | 1,141 | −2.57% | +0.63% (**+3.2%p**) | +0.88% (**+3.5%p**) | +0.88% (+3.4%p) |
| 구 로직 (~08-05, 급락장) | 909 | −3.56% | +0.91% (**+4.5%p**) | +1.01% (+4.6%p) | +0.78% (+4.4%p) |
| **신 로직 (08-06~)** | 232 | +1.33% | −0.46% (**−1.8%p**) | +0.37% (**−1.0%p**) | +1.23% (−0.1%p) |
| 신 로직, scan 제외 | 172 | +0.77% | −0.61% (−1.4%p) | +0.18% (−0.6%p) | +0.64% (−0.1%p) |

**집계값만 보면 "손절이 +3.5%p 개선"이지만 그 이득은 전부 급락장 표본에서 나온다.**
최근 구간에서는 손절이 오히려 손해고, 좁을수록 더 나쁘다 — 되돌아온 승자를 끊기 때문이다
(역행폭 중앙값이 7.4%인데 5% 손절은 절반을 발동시킨다).

시뮬레이션 가정도 낙관적이다: 역행폭이 손절폭을 넘으면 **그 가격에 정확히 청산**된다고
보며 슬리피지·갭·장중 경로를 반영하지 않는다. 이 caveat 는 API 응답
(`stop_simulation_caveat`)에도 실려 있다.

**결론**: 집계 기준으로 손절폭을 고정하면 급락장에 과적합된다. 손절은 국면(regime)에
따라 달라야 하며, 현재 표본(신 로직 독립 블록 79개)으로는 그 규칙을 정할 수 없다.

### 11.3 데이터 규모

| 항목 | 값 |
|---|---|
| `signal_outcomes` | 5,018행 — 평가 완료 4,272 / 종결 53 / 대기 0 |
| 평가된 발행 기간 | 2026-07-06 ~ 09-03 |
| 14일 / 30일 평가 | 3,468건 / 1,581건 (수리 전 237 / 0) |
| 칼리브레이터 표본 | 812 → 4,272 (원시 기준. 학습은 `ticker_day` 표본으로 한다) |

## 12. 품질 인프라

- **테스트**: `tests/unit/` 65 파일 / 679 test. LLM·외부 API는 mock(`respx`), 실호출 금지.
  테스트는 "함수가 무엇을 반환하는가" 층 외에 **리포트 자기 정합성 / 출력 필드 레지스트리 /
  임계값 도달 가능성 / 알림 전송 관측성** 같은 회귀 방지 층이 별도로 있다.
- **CI**: `.github/workflows/ci.yml` — ruff(bug-class만: F601/F811/F821/F823/E9) +
  pytest + 의존성 smoke import(과거 `litellm`/`opendartreader` 누락 회귀 방지).
  최근 5회 실행 모두 success (마지막 2026-08-18).
  스타일 규칙(F401 73건, F841 35건, I001 등)은 **의도적으로 미강제**.
- **로컬 실행 주의**: 루트 `venv/`에는 `uvicorn`·`pytest`가 없어 `pytest`가 수집 단계에서 깨진다.
  실제 검증은 CI 또는 컨테이너 환경에서 한다.
- Python 3.12 고정 (3.13 미검증 — `opendartreader<0.2.3` 핀이 이 제약과 묶여 있다).
  포매팅 `ruff format`, 라인 100자, 신규 코드 타입 힌트 필수.

---

## 13. 알려진 부채 · 이번 조사에서 확인된 결함

### 13.1 ✅ 수리 완료 (2026-09-10) — 사후 평가 파이프라인 아사

**증상**: `signal_tracker.evaluate_past_signals`의 질의가 `ORDER BY issued_at DESC LIMIT 500`
이었고 horizon 도래 여부를 보지 않았다. 하루 100건 이상 적립되는 규모에서 매 런이 최신 5일치
500건(전부 미도래)만 집어 `processed 0 / skipped_not_due 500`을 반복했다.

수리 전 실측: 미평가 4,201건 / `scan_agent` 3,796건 중 평가 11건 / `return_30d` 0건 /
08-06 이후 발행분 평가 0건. 그 40일 동안 검증 잡은 `status=completed`로 보고했다.
`ConfidenceCalibrator`·`llm_calibrator`(ECE·Isotonic)·`ic_ensemble`(IC 가중)이 모두 이 테이블을
입력으로 쓰므로, 신뢰도 보정과 소스 가중치가 7월 표본에 고정돼 있었다.

**수리 내용** (`fix/signal-eval-queue`, 커밋 2건):

| 변경 | 내용 |
|---|---|
| 후보 선정 | 도래한 horizon이 남은 행만, `issued_at ASC`(오래된 것부터) — 신규 유입이 백로그를 밀어내지 못한다 |
| 창·배치 | `SIGNAL_EVAL_DAYS_BACK=90`, `SIGNAL_EVAL_BATCH_LIMIT=2000` (config·.env로 노출) |
| 시세 조회 | 티커별 1회 배치 프리페치 — 종전 (행 × horizon) 개별 호출이면 백로그 4,300행에 1만 회 이상 왕복 |
| 종결 상태 | `eval_state='unresolved'` — 30일 horizon + grace 14일이 지나도 시세가 없는 심볼은 큐에서 제외, 카운트로만 유지 |
| 관측성 | 결과에 `pending_due`·`oldest_pending_days`·`expired_unevaluated`·`unresolved_total`·`skipped_no_price`·`prefetch.tickers_failed` 노출 |
| 경고 | 잔량 임계 초과 / 창 밖 미평가 / 최고령 대기 > 창의 80% / 시세 소스 **전면** 실패 / 종결 발생 시 검증 잡 `status=degraded` + ops 알림. 개별 티커 실패 하나로는 울리지 않는다 |

**운영 반영 결과**: 소급 평가 4,245건을 12초에 처리(티커 19개 배치 조회).
`return_7d` 812→4,272, `return_14d` 237→3,468, `return_30d` 0→1,581, 잔량 4,298→0,
칼리브레이터 표본 812→4,272. 이후 런은 `candidates 0 / backlog clear / status completed`.
회귀 테스트 10건(`tests/unit/test_signal_eval_queue.py`)이 아사 조건을 고정한다.

**후속 (같은 날 처리)**: 평가 가격 조회를 `data_collector` 다중 소스 체인으로 통일했고
(`reset_unresolved=true`로 종결분 재시도 포함), `.env`의 `DATA_SOURCE` 이중 선언을 정리하고
기동 시 중복 키 경고를 추가했다. `057050.KS` 53건은 세 소스 모두 2026-07-16 이후 데이터가
없어(거래 중단) 영구 평가 불가로 확정 — 종결 상태가 맞다. §13.3 참조.

### 13.2 ✅ 수리 완료 (2026-09-10) — 표본 독립성

평가 큐를 고쳐 표본이 생기자 드러난 후속 문제다. `signal_outcomes`를 읽는 세 곳
(`get_accuracy_stats` → `/signal-accuracy`·WebUI·`ConfidenceCalibrator`, `llm_calibrator`
→ ECE·isotonic, `ic_ensemble` → 소스별 IC 가중)이 전부 **원시 행**을 그대로 썼다.
30분 스캔이 종목당 하루 최대 48행을 남기고 7일 horizon이면 연속 날짜끼리도 겹치므로,
승률·신뢰구간·소스 가중이 모두 과대평가됐다.

| 변경 | 내용 |
|---|---|
| 표본 단위 | 기본 `ticker_day` = (종목, 소스, 발행일) 1건, 대표는 그날 마지막 행. `ticker_horizon`(비겹침), `none`(원시, 진단용) 선택 가능 |
| 신뢰구간 | **독립 블록 수** 기준 Wilson 95% (`win_rate_ci95`, `independent_blocks`) |
| 투명성 | `sampling.rows_raw` · `collapse_ratio` · `dominant_source_share_pct` 동시 보고. 한 소스가 70% 이상이면 WebUI가 경고를 띄운다 |
| 학습 입력 | `llm_calibrator`·`ic_ensemble`도 같은 표본 단위로 로드 |
| WebUI | 표본 단위 선택 + 표본/원시/블록/CI 표시. '과거 신호 재평가' 버튼에 박혀 있던 `days_back=45&limit=500`(= 큐 아사 조건) 제거 |

효과는 §11.1 표에 그대로 있다 — 같은 데이터의 승률이 44.9% → 33.7%로 내려간다.
회귀 테스트 10건(`tests/unit/test_sample_independence.py`).

### 13.3 ✅ 수리 완료 (2026-09-10) — 방향 보정

`signal_outcomes.return_7d`는 **가격 변화**다. 매도 신호는 가격이 내려가야 맞은 것인데,
지표 네 곳이 부호를 그대로 평균하거나 `> 0`으로 적중을 판정하고 있었다. 공통 결과는
**잘 맞춘 신호가 못 맞춘 것처럼 보이는 것**이다.

| 위치 | 증상 | 수정 |
|---|---|---|
| `/signal-accuracy`·WebUI·텔레그램 | `avg_return_pct`가 방향 무시 | `avg_signed_return_pct`(성과) / `avg_raw_return_pct`(진단)로 분리. 모호한 옛 키는 **삭제** — 남겨 두면 계속 잘못 읽힌다 |
| `llm_calibrator` | `hit = return_7d > 0` → 매도(표본의 44%)를 반대로 라벨링 | 방향 보정 수익률로 판정, neutral은 학습 대상에서 제외 |
| `ic_ensemble` | IC = corr(conviction, 원시수익률) → 잘 맞추는 매도 소스가 IC 음수 | 방향 보정 수익률과의 상관으로 계산 |
| `signal_performance_summary` VIEW | `hit_rate_7d = AVG(return_7d > 0)` | 방향별 판정 + `signed_expectancy`/`raw_expectancy` 병기. VIEW는 `IF NOT EXISTS`로 갱신되지 않으므로 `init_db`에서 DROP 후 재생성 |

실측 확인: `scan_agent`의 매도 1,371건 hit_rate가 0.249 → **0.751**로 뒤집혔다.

**부수 발견 — IC 앙상블은 켜진 적이 없다.** `/ic-weights`가 모든 소스를 `weight: 0.0`으로
보고하고 있었는데, 실제로는 누적 59일 < 최소 60일 요건이라 `compute_ic_weights()`가
**빈 dict**를 돌려주는 폴백 상태였다. '가중치 0(제외됨)'과 '가중 자체가 꺼짐'은 완전히
다른 뜻이다. 이제 `active`·`inactive_reason`·`applied_in_decisions`를 함께 반환한다.
그리고 `apply_ic_weights()`는 **호출부가 없다** — 계산만 되고 판정에 연결돼 있지 않다.

### 13.4 ✅ 완료 (2026-09-11) — 벤치마크 + 보정 홀드아웃

| 항목 | 수정 |
|---|---|
| 시장 대비 초과수익 부재 | `signal_outcomes`에 `benchmark_symbol`·`benchmark_return_{7,14,30}d` 추가. 지수는 종목당이 아니라 **시장당 1회** 프리페치. 초과수익도 방향 보정(`signed(종목) − signed(지수)`). 벤치마크 없는 행은 평균에서 제외하고 `benchmark_sample`로 보고 |
| `ece_after` 가 늘 0 | **학습 표본으로 재고 있었다**(isotonic 특성상 당연). out-of-time 홀드아웃(과거 학습 → 미래 평가) 도입. 옛 키 삭제, 학습 표본 값은 `ece_after_in_sample`로 이름에 박음. 홀드아웃 표본 부족 시 숫자를 만들지 않고 `insufficient` |

보정 성능 실측 변화 (동일 데이터, n=1,232):

| | 종전 보고 | 실제(홀드아웃) |
|---|---:|---:|
| ECE 보정 전 | 0.1989 | 0.1592 |
| ECE 보정 후 | **0.0000** | **0.0776** |
| 개선폭 | 0.1989 | **0.0816** |

보정은 실제로 효과가 있다 — 다만 오차가 사라지는 게 아니라 절반 정도 남는다.
종전 수치는 그 사실을 숨기고 있었다 (train 862 / holdout 370).

### 13.5 ✅ 완료 (2026-09-11) — 평가 기간 ↔ 보유기간 정합

보유기간이 세 곳에 흩어져 있었다: `entry_plan._HOLDING_DAYS_BY_STYLE`(2/10/60),
`signal_tracker.HORIZONS`(7/14/30, 기본 7 하드코딩), `decision_context`(기본 7).
스윙 10일 보유를 의도한 신호를 7일에 채점하고 있었다.

- 단일 출처를 `config._STYLE_PRESETS[...]["holding_days"]` 로 통일. `entry_plan` 이
  이 값을 읽는다.
- `primary_horizon_days()` — 의도 보유기간을 **덮는 가장 짧은** horizon (10일 → 14일).
- `/signal-accuracy` 기본 horizon, `decision_context.default_horizon_days()`,
  `ConfidenceCalibrator` 기본값이 모두 이 값을 쓴다. `DECISION_HORIZON_DAYS` 는 유지.
- `horizon_covers_holding` 을 응답에 실어, 덮지 못하는 조합(longterm 60일)을
  **조용히 넘기지 않는다**. WebUI 는 그 경우 경고를 띄운다.
- `/signal-accuracy/horizon` 신설 — 스타일·보유기간·대표 horizon 정합 상태.

### 13.6 ✅ 완료 (2026-09-11) — ±2% 밴드를 대표 지표에서 제거

- 대표 지표: `direction_hit_rate_pct`(부호만) + 초과수익 + **분포**(p25/중앙/p75).
  신뢰구간도 방향 적중률 기준으로 계산한다.
- 밴드 집계는 버리지 않고 `band_outcome` 에 **임계값·사유와 함께** 남긴다
  (큰 움직임만 세고 싶을 때 쓰되, 임계 의존이 같이 보이게).
- 최상위 `win_rate_pct`·`win_count`·`loss_count`·`neutral_count`·`win_rate_ci95` 삭제 —
  이름만 봐서는 임계 의존을 알 수 없었다.
- `ConfidenceCalibrator` 의 보정 대상도 방향 적중률로 바꿨다. `llm_calibrator` 는
  이미 부호 기준이라 두 보정기가 같은 정의를 쓰게 됐다.
- WebUI·텔레그램 다이제스트가 방향 적중률을 표시하고 밴드 승률은 부기로 남긴다.

### 13.7 ✅ 완료 (2026-09-12) — 역행폭 기록 + 손절 시뮬레이션

- `signal_outcomes.adverse_excursion_{7,14,30}d` — 보유 구간 중 **신호 반대 방향**
  최대 이동(양수 %). 매수는 저가, 매도는 고가 기준. 종료 시점 수익률만으로는
  되돌아온 손실(보유 중 −15% → 마감 −1%)이 보이지 않는다.
- 프리페치 구간을 **발행일부터**로 확장 (종전에는 보유 초반 봉이 프레임에 없었다).
- `tail`(p10/p90/tail_ratio/payoff_ratio) + `adverse_excursion_dist` +
  `stop_simulation`(3~15%) 을 `/signal-accuracy` 에 노출.
- 시뮬레이션 가정과 **기간별 부호 반전**을 `stop_simulation_caveat` 로 같이 낸다 —
  집계값만 보고 손절폭을 고정하면 급락장에 과적합된다 (§11.2e).

부수: 테스트 sys.path 순서 함정 수정. `test_agent_groups` 가 `stock_analyzer` 를
`sys.path[0]` 에 넣어, 그 뒤 수집되는 모듈의 `import service` 가 동명 모듈
(`news_analyzer`)을 잘못 잡아 깨졌다. analyzer 경로는 뒤에 붙인다.

### 13.8 ✅ 완료 (2026-09-12) — 스크리너 표본 적립 (종목 확대)

측정 체계를 다 고친 뒤(§13.1~13.7) 남은 병목은 **표본 수**였다. 신 로직 기준 독립
블록이 79~124개고, 7종목 워치리스트로는 기간을 기다려도 느리게 늘어난다 — 같은
종목의 연속 신호는 서로 겹치기 때문이다.

스크리너는 이미 KOSPI+KOSDAQ **910종목**을 매번 훑으면서 그 판단을 `screener_results`
에만 남기고 **평가 대상으로는 버리고** 있었다.

- `screener.record_screener_outcomes()` — 상위 결과를 `signal_outcomes`
  (`signal_source='screener'`)에 적립. 방향 있는 신호만, 상한 `SCREENER_RECORD_TOP_N=10`
  (평가 큐 폭증 방지). 건너뛴 수·오류 수를 반환해 '기록 없음'과 구분한다.
- 일일 스케줄 잡 `screener_batch` 추가 (16:30, KRX 마감 후 / 멀티에이전트 배치 앞).
  `/ops/jobs/screener_batch/run` 으로 수동 실행도 가능.
- 평가 파이프라인이 수익률·시장대비·역행폭을 자동으로 채운다 — **LLM 비용 0**.

첫 실행 실측 (2026-09-12): universe 910 → 상위 20 중 **10건 적립, 10종목 전부 다름,
그중 9종목은 기존 표본에 없던 신규**. 대비: `scan_agent` 는 3,911행이지만 **8종목**뿐이다.

| 소스 | 행 | 종목 수 |
|---|---:|---:|
| scan_agent | 3,911 | 8 |
| group_* / multi_agent_final | 1,221 | 14~18 |
| **screener (신규)** | 10 | **10** |

종목이 다르면 `ticker_day`·블록 기준으로 서로 독립이므로, 하루 10종목씩 쌓이면
독립 블록이 **하루 ~10개씩** 는다 (종전 1~2개).

부수: 테스트가 운영 DB의 잡 상태를 오염시키던 문제를 잡았다. `_record_job_*` 는
`app_state`(scan_log.db)에 쓰는데 테스트 컨테이너가 리포지토리를 그대로 마운트하므로,
패치 없이 호출하면 `/ops/jobs` 에 테스트 값이 뜬다(실제로 `"pykrx down"` 이 떴다).

### 13.9 구조적 부채 (기존 인식)

| # | 항목 | 현재 상태 |
|---|---|---|
| 1 | `webui.py` God file | **해소** (2026-09-14): 6,482 → 350 라인(−95%). `ui/` 공용 8모듈 + `ui/pages/` 17페이지 — 아래 §13.9a |
| 2 | 이중 호출 경로 (직접 import + HTTP) | `/paper`·`/trading`·`/gpu`만 HTTP 강제. 나머지는 여전히 이중. 단 판정 지점은 1곳으로 합침 — `webui.py` 에 있던 두 번째 `_USE_LOCAL_ENGINE` 제거 (2026-09-14) |
| 3 | `print()` 기반 로깅 | **해소** (2026-09-14): agent-api 188건 + webui 라이브러리 경로 179건 전환. CLI 블록 206건은 **의도적으로 유지** — 아래 §13.9c |
| 4 | 양방향 `sys.path` 주입 | 구조는 그대로. 단 **동명 모듈 충돌은 제거·차단** (2026-09-14, `test_module_shadowing.py`) — 아래 §13.9f |
| 5 | ~~분석 결과 JSON 무한 누적~~ | **해소** (2026-09-14): `output_retention` 잡 (JSON·PNG 30일, 03:30). 적발 시점 70,771개/1.58 GB, 하루 361개 증가 — 아래 §13.9b |
| 6 | ~~DB 마이그레이션 도구 부재~~ | **해소** (2026-09-15): Alembic 도입, 리비전 4개. 운영 DB 채택 완료 — 아래 §13.9k |
| 7 | FastAPI 핸들러 sync + blocking I/O | **부분 해소** (2026-09-15): 스레드 한도 40→80, `/health` async 전환으로 포화 시 7.33초→0.35초. 나머지 85개는 sync 유지 — 아래 §13.9l |
| 8 | 모델 버전 태그 핀 | `qwen3:14b-q4_K_M` 등 태그 고정이나 digest 핀은 아님 |
| 9 | 백테스트 Composite 전략의 과거 replay 제외 | look-ahead 회피 목적. 도구 신호의 역사적 성능은 미측정 |
| 10 | 단일 노드 SPOF | 구조는 그대로. **백업·복구 절차 추가** (2026-09-14): `state_backup` 잡(04:00) + `docs/RUNBOOK_BACKUP.md` + 복구 리허설 — 아래 §13.9g |

#### 13.9a `webui.py` 분해 (완료, 2026-09-12 ~ 09-14)

CLAUDE.md §6-10: **한 번에 분리하지 말 것.** 의존성이 낮은 순서로 8단계에 걸쳐 뗐다.

| 단계 | 대상 | 결과 |
|---|---|---|
| 1~5 | `ui/theme.py` `api_client.py` `market.py` `tickers.py` `format.py` | 6,482 → 4,383 |
| 6 | `pages/signal_accuracy.py` `screener.py` — 의존성이 `api_get/api_post` 뿐인 페이지 | |
| 7 | `ui/components.py` + 저결합 6페이지 (history, backtest, ml_predict, portfolio, ranking, paper_trade) | 4,383 → 3,911 |
| 8 | 독립 4페이지 (quant_indicators, system_monitor, trading, virtual_trade) + 추출 도구 | 3,911 → 2,813 |
| 9 | 홈 묶음 5함수 + `ui/korean_optional.py` | 2,813 → 2,276 |
| 10 | `ui/export.py` + dashboard·detail·scan_log + 죽은 이중 경로 제거 | 2,276 → 1,066 |
| 11 | `pages/multi_agent.py` + 빈 섹션 배너 정리 | 1,066 → **350** |

최종: **6,482 → 350 라인 (−95%)**. `ui/` 공용 8모듈 + `ui/pages/` 17페이지 = 약 6,600줄.
남은 `webui.py` 는 부팅(설정·`sys.path`·테마) + 내비게이션 + 커맨드바 + 라우팅이다.

##### 얻은 것 1 — 검사가 통과해도 화면은 죽는다

세 층위의 검사가 각각 다른 것을 놓쳤다. 실제로 겪은 순서대로:

| 결함 | `ast.parse` | 모듈 import | 렌더 호출 |
|---|---|---|---|
| `resolve_ticker` 를 함수 중간에서 절단 | 통과 (두 조각 모두) | — | 실패 |
| `ml_predict` 가 `get_ticker_display_name` 을 잃음 | 통과 | 통과 | 실패 |
| `render_signal_accuracy` 의 `KeyError: 'wins'` (#46 잔재) | 통과 | 통과 | 실패 |

마지막 건은 분해와 무관하게 **main 에서 이미 죽어 있던 페이지**였다. 테스트도 ruff 도
잡지 못했고 HTTP 200 이었다. 그래서 검증은 4단이다:

```bash
# 1. 원본(HEAD) 대비 사라진 최상위 심볼
python3 - <<'EOF'
import subprocess, re, pathlib, glob
orig = subprocess.run(['git','show','HEAD:stock_analyzer/webui.py'],
                      capture_output=True, text=True).stdout
f = lambda s: set(re.findall(r'^def (\w+)', s, re.M))
now = f(pathlib.Path('stock_analyzer/webui.py').read_text())
for p in glob.glob('stock_analyzer/ui/**/*.py', recursive=True):
    now |= f(pathlib.Path(p).read_text())
print(sorted(f(orig) - now) or "없음")
EOF

# 2. pytest + ruff (agent-api 컨테이너)
# 3. 스크립트 전체 실행 — Streamlit 은 죽어도 HTTP 200 이다 (§14-5)
docker exec stock-auto-webui python -c \
  "import runpy; runpy.run_path('/app/stock_analyzer/webui.py', run_name='__main__')"

# 4. 페이지 렌더 함수 직접 호출 — 실행해야만 드러나는 NameError
docker exec stock-auto-webui python -c "
import sys, importlib; sys.path.insert(0,'/app/stock_analyzer')
for m in ('home','dashboard','detail','multi_agent','scan_log','history','backtest',
          'ml_predict','portfolio','ranking','paper_trade','signal_accuracy',
          'screener','quant_indicators','system_monitor','trading','virtual_trade'):
    getattr(importlib.import_module(f'ui.pages.{m}'), f'render_{m}')()"
```

##### 얻은 것 2 — 추출을 손으로 하면 import 를 빠뜨린다

`scripts/extract_webui_page.py`. 함수 블록의 **자유변수를 AST 로 계산**해 필요한
import 만 생성하고, webui 로컬 함수·전역을 참조하면 **거부**한다 — "먼저 공용 모듈로
올려라"는 신호다. 실제로 `render_detail`(`export_comprehensive_data`·`get_chart_url`)과
홈 묶음(`_css_key`·`ticker_chip_html`)이 여기서 막혀 순서가 강제됐다.

##### 얻은 것 3 — 분해가 드러낸 은폐 2건

1. **한국장 도구가 조용히 사라졌다.** `except ImportError: print(...)` 로 사유를 버리고
   `if _KOREAN_STOCKS_AVAILABLE:` 로 섹션을 통째로 감췄다. 모듈이 깨져도 화면에는
   **기능이 원래 없는 것처럼** 보였다. → `ui/korean_optional.py` 가 사유를 보존하고,
   익스팬더는 항상 뜨며 안에서 `사유: ImportError: ...` 를 보여준다 (§14).
2. **`_USE_LOCAL_ENGINE` 이 두 곳에 있었다.** `webui.py` 와 `ui/api_client.py` 가 같은
   판정을 따로 했다. 둘이 다르게 실패하면 어느 경로로 도는지 알 수 없다. webui 쪽을
   제거해 판정 지점을 1곳으로 합쳤다.

##### 얻은 것 4 — 위치에 의존하는 검사는 분해를 못 견딘다

`test_design_system.py` 가 컴포넌트 규칙을 `webui.py` 안에서만 찾아, `ticker_chip_html`
이 옮겨지자 실패했다. **규칙이 깨진 게 아니라 검사가 깨졌다.** `_screen_source()`
(webui + `ui/**` 전체) 기준으로 바꿨다.

#### 13.9b `output/` 보존 정책 (2026-09-14)

정리 주체가 없었다. `crontab -l` 은 비어 있고 코드에도 삭제 경로가 없다. 그런데
CLAUDE.md Don't #7 은 **"30일 이상 파일 자동 정리 cron 유지"** 라고 적혀 있었다 —
문서가 **없는 통제를 있다고 말하던** 경우다. §13 의 실패 은폐가 문서에서 일어난 형태다.

적발 시점: JSON **70,771개 / 1.58 GB**, 하루 361개(약 7.7 MB) 증가.

두 산출물의 성격이 다르다:

| | 읽는 코드 | 처리 |
|---|---|---|
| 분석 JSON (`*_agent_*.json`) | **없다** — `json_path` 는 문자열로 기록될 뿐 아무도 다시 열지 않는다 (전수 확인). 내용은 `scan_log` DB 에 있다 | 30일 경과분 삭제 |
| 차트 PNG | **있다** — `engine_get_chart_path()` 가 상세 페이지에 띄운다 | 30일 + **참조 중이면 나이 무관 보존** |

삭제는 되돌릴 수 없으므로 `chart_agent_service/output_retention.py` 가 지키는 것:

1. `OUTPUT_DIR` **바로 아래 파일만** (하위 디렉토리·심볼릭 링크 제외)
2. **allowlist 패턴만** — `*.db*` 는 어떤 경우에도 건드리지 않고, 모르는 파일은 남긴다
3. `GET /ops/output-retention/preview` 로 **지우기 전에 확인** (dry-run 은 "지울 예정"이라고
   적는다 — 지웠다고 보고하지 않는다)
4. 실패는 세지 않고 **사유와 함께** 보고, 부분 실패는 `degraded`
5. 참조 목록을 못 읽으면 **차트는 아예 건너뛰고** `charts_evaluated: false` 로 남긴다 —
   모른 채로 지우면 화면이 깨진다

실측 (dry-run): 삭제 예정 **61,627개 / 1.24 GB**, 참조 중 차트 15개 보존.

#### 13.9c 로깅 (2026-09-14)

`print()` 573건이 문제로 적혀 있었지만, 실제 결함은 그보다 컸다: **로깅이 설정된 적이
없다.** `basicConfig`/`dictConfig` 호출이 리포지토리 어디에도 없었다. 그래서 이미
`logger.info(...)` 를 쓰고 있던 `data_collector`·`llm/router`·`llm_calibrator`·
`ic_ensemble` 의 로그가 **전부 버려지고 있었다** (루트 기본 레벨 WARNING).

로그를 남기는 것처럼 보이는 코드가 아무것도 남기지 않는 상태 — §13 의 전형이다.
`service.log` 도 2026-04-29 이후 갱신되지 않은 5MB 파일이 '최근 로그'처럼 남아 있었다.

`chart_agent_service/logging_setup.py`:
- 레벨·포맷(text/json)·회전 파일 핸들러를 env 로 설정, **적용 결과를 반환**한다
  (파일 핸들러가 실패해도 스트림 로깅은 유지하되 사유를 남긴다)
- uvicorn 핸들러 정리 — 같은 줄이 두 번 찍히지 않는다
- agent-api `print` 188건 → `logger.{info,warning,error}` (error 58 / warning 13 / info 117)

##### 로깅을 켜자 비밀이 새기 시작했다

켜자마자 첫 로그에 이게 찍혔다:

```
WARNING [data_collector] fundamentals failed via fmp: 403 ... ?apikey=svo6...
```

**로깅을 켠 것이 곧 자격증명을 유출하는 일이 됐다** (CLAUDE.md §6-2 위반).
`SecretRedactingFilter` 로 차단한다 — 쿼리스트링(`apikey`/`token`/`secret`/`password`),
`Bearer` 토큰, 그리고 **환경변수에 있는 실제 값**(8자 이상)을 마스킹한다.

마스킹은 필터가 아니라 **포맷 결과**에 건다. 필터가 도는 시점에 `record.exc_text` 는
아직 None 이고 트레이스백은 포맷 단계에서 만들어진다 — 테스트에서 실제로
`RuntimeError: https://...?apikey=...` 가 그대로 새어 나갔다. 예외 메시지야말로 URL 이
통째로 실리는 자리다.

실측: `apikey=***` 로 마스킹되고 `403` 진단 정보는 남는다.

##### 켜자마자 드러난 운영 사실 2건 (별도 과제)

1. `fundamentals failed via fmp: 403 Forbidden` — 한국 종목 펀더멘털이 FMP 에서
   계속 거절된다. data-health 의 `fundamentals_missing` 과 연결된다.
2. `dart_client get_corp_code 실패: pickle data was truncated` — DART corp_code
   캐시 파일이 손상돼 있다.

둘 다 이전에도 일어나고 있었지만 **아무 데도 남지 않았다.**

##### webui 쪽 (2026-09-14 후속)

`stock_analyzer/` 의 print 385건은 성격이 둘로 갈린다:

| 위치 | 건수 | 처리 |
|---|---|---|
| 라이브러리 경로 (webui·agent 가 import) | 179 | → `logger` |
| `if __name__ == "__main__":` 아래 | 206 | **유지** — 사람이 스크립트를 직접 돌릴 때 보라고 있는 출력이다 |

전부 지우는 게 목표가 아니다. 테스트가 양쪽을 **모두** 고정한다 — 라이브러리 경로
print 0건, CLI print 100건 이상(일괄 치환으로 CLI 출력까지 사라지는 것을 막는다).

설정은 `stock_analyzer/app_logging.py` 가 `chart_agent_service/logging_setup.py` 를
**그대로 재사용**한다 (동일 함수 객체임을 테스트로 고정). 설정을 두 벌 두면 한쪽만
고쳐지고, 비밀값 마스킹이 한쪽에만 걸린다. 실측: webui 컨테이너에서
`redaction: enabled`, `apikey=***`.

##### webui 로깅을 켜자 드러난 것 (별도 과제)

```
ERROR [stock_auto.local_engine] news_analyzer import 실패 (HTTP fallback):
  cannot import name 'fetch_news_with_sentiment' from 'news_analyzer'
  (/app/stock_analyzer/news_analyzer.py)
```

`stock_analyzer/news_analyzer.py` 가 `chart_agent_service/news_analyzer.py` 를 가린다
(안티패턴 #5, 양방향 `sys.path` 주입). 폴백이 동작하므로 기능은 돌지만 **in-proc
경로는 한 번도 쓰인 적이 없다.** 이전에는 이 사실이 아무 데도 남지 않았다.

#### 13.9d 펀더멘털 다중 소스 (2026-09-14)

로깅을 켠 첫 성과(§13.9c)를 따라간 결과다. `fundamentals failed via fmp: 403` 하나를
쫓다가 **5개 소스 중 4개가 죽어 있는 것**을 발견했다.

| 소스 | 상태 (적발 시점) | 원인 |
|---|---|---|
| naver | 빈 dict | `finance.naver.com/item/main.naver` 가 클라이언트 렌더링으로 바뀌어 HTML 에 PER·PBR·EPS 문자열이 **아예 없다** (HTTP 200, 119KB, 마커 0건) |
| finnhub | 빈 dict | 키 미설정 |
| alphavantage | 빈 dict | 키 미설정 |
| fmp | 403 | `/api/v3/` 가 legacy 로 폐기. 키는 유효하다 |
| yfinance | 동작 | 유일. KR 은 16/20 부분 |

빈 결과는 `continue` 로 흘러 아무 기록도 남지 않았다. 그래서 '다중 소스 폴백'이
실제로는 **yfinance 단일 소스**였다. CLAUDE.md §5-5 의 "다중 소스" 전제가 깨져 있었다.

**수정**
- naver → `m.stock.naver.com/api/stock/{code}/integration` (JSON). 한국 시총 표기
  `1,455조 7,234억` 을 파싱한다
- fmp → `/stable/` 엔드포인트. 402(플랜 미포함)는 `PlanRestricted` 로 분리해 오류에
  쌓지 않는다. KRX 심볼은 402 확정이라 호출 자체를 하지 않는다
- 소스별 결말을 `_source_status` 로 보고: `ok` / `not_configured` / `plan_restricted` /
  `no_data` / `no_usable_fields` / `error`

**측정 (실 컨테이너)**

| 종목 | 전 | 후 |
|---|---|---|
| 005930.KS | partial 16/20 (yfinance) | **full 19/20** (naver+yfinance) |
| 049430.KQ | partial | partial 9/20 + **왜 부분인지 명시** |
| AAPL | full 20/20 | full 20/20 (변화 없음) |

##### 배당수익률 단위가 소스마다 달랐다

`dividend_yield` 한 필드에 세 가지 단위가 섞여 있었다 — yfinance 퍼센트(0.33),
alphavantage 분수(0.0044), 그리고 **FMP 는 배당 '금액'($1.06)을 수익률 자리에 넣고
있었다**(=106%). 현재 소비처가 0이라 드러나지 않았을 뿐이다.

분수로 통일하되 **단위를 값 크기로 추측하지 않는다.** 처음엔 "1을 넘으면 퍼센트"
규칙을 썼는데 네이버의 `0.67%` 가 이미 분수로 읽혔다 — 1% 미만 배당은 흔하다.
소스가 아는 것을 소스가 선언한다(`_as_yield_fraction(value, unit)`).

실측: AAPL 0.0033 / 005930.KS 0.0067 / 049430.KQ 0.0315 — 전부 분수.

#### 13.9e DART corpCode 캐시 경합 (2026-09-14)

로깅을 켠 뒤 나온 두 번째 줄(§13.9c): `get_corp_code(049430.KQ) 실패: pickle data
was truncated`.

원인은 OpenDartReader 생성자다:

```python
if not os.path.exists(fn_cache):
    df = dart_list.corp_codes(api_key)
    df.to_pickle(fn_cache)      # 8.5MB 를 최종 경로에 직접 쓴다
self.corp_codes = pd.read_pickle(fn_cache)
```

`to_pickle` 이 도는 동안 파일은 **이미 존재한다.** 병렬 스캔(워커 3)의 다른 스레드가
`os.path.exists` 를 True 로 보고 반쯤 쓰인 파일을 읽는다. 게다가 잘린 파일은 그날 내내
남으므로 **하루 종일 DART 조회가 죽는다** — 그리고 DART 도구는 방향성 도구라 조용히
score 0이 되어 신호를 희석한다.

`get_corp_code()` 가 호출마다 `OpenDartReader(api_key)` 를 새로 만든 것도 겹쳤다.
119,183행 스냅샷을 매번 파싱했다.

**수정**
- 캐시 생성은 임시 파일 → `os.replace` (같은 디렉토리 내 원자적 교체). 반쯤 쓰인
  파일이 보이는 순간이 없다
- 손상된 캐시는 **지우고 다시 만든다** — 그날 내내 같은 실패를 반복하지 않는다
- 스냅샷은 프로세스당 하루 1회만 읽고 조회는 메모리에서. 리더 인스턴스도 하루 1회
- 락은 `RLock` — `get_dart_reader()` 가 락을 잡은 채 `_load_corp_frame()` 을 부른다.
  일반 `Lock` 이면 그 자리에서 교착이고 스캔 스레드가 통째로 멈춘다
  (테스트가 120초 타임아웃으로 잡아냈다)

**실측 (실 컨테이너)**
- 손상 캐시 주입 → 경고 로그 후 삭제·재생성(8,584,967 bytes), 조회 성공
- 캐시 삭제 후 병렬 5회 첫 호출 → 생성 1회, 결과 일치, 1.3초
- 반복 20회: 0.71초 → **0.072초** (절대값은 작다. 요점은 경합·손상 제거다)

#### 13.9f 모듈 가림 (2026-09-14)

§13.9c 로 webui 로깅을 켠 직후 나온 줄:

```
ERROR [stock_auto.local_engine] news_analyzer import 실패 (HTTP fallback):
  cannot import name 'fetch_news_with_sentiment' from 'news_analyzer'
  (/app/stock_analyzer/news_analyzer.py)
```

`stock_analyzer/` 와 `chart_agent_service/` 가 **둘 다 sys.path 에 들어간다**
(안티패턴 #5). 같은 파일명이 양쪽에 있으면 어느 쪽이 잡힐지는 **import 순서**가 정한다.
겹치던 이름은 하나였다 — `news_analyzer`.

| | 잡힌 모듈 | 결과 |
|---|---|---|
| webui | `stock_analyzer/news_analyzer.py` | `_DIRECT_NEWS=False` → 뉴스는 늘 HTTP 폴백. **`GeopoliticalAnalyst._fetch_news_context` 는 항상 `{'error': ...}`** → `_context_available` False → **뉴스 없이 지정학 분석** |
| agent-api | `chart_agent_service/news_analyzer.py` | 우연히 정상 — `service.py` 가 먼저 import 해 `sys.modules` 에 올려둔 덕이다. 순서가 바뀌면 같이 깨진다 |

`stock_analyzer/news_analyzer.py` 는 **아무도 import 하지 않는 레거시**였다
(`NewsAnalyzer`/`IntegratedAnalyzer` 참조 0). 즉 죽은 코드가 살아 있는 모듈을 가렸다.

기존 테스트 3개(`test_agent_groups`, `test_price_source_verification`,
`test_signal_outcome_recording`)가 이미 "stock_analyzer 를 앞에 넣으면 동명 모듈이
잘못 로드된다"는 주석과 함께 sys.path 순서를 조심하고 있었다 — **증상은 알려져
있었지만 원인을 없애지 않았다.**

**수정**: `legacy_news_analyzer.py` 로 개명(삭제하지 않고 경위를 docstring 에 기록) +
`tests/unit/test_module_shadowing.py` 로 재발 차단.

**실측 (webui, 수리 후)**

| | 전 | 후 |
|---|---|---|
| `news_analyzer.__file__` | `stock_analyzer/…` | `chart_agent_service/…` |
| `local_engine._DIRECT_NEWS` | `False` | **`True`** |
| `_fetch_news_context` | `{'error': …}` | 기사 **15건**, `_context_available=True` |

#### 13.9g 백업·복구 (2026-09-14)

백업이 없었다. 잃게 되는 것은 재생성 불가능한 것들이다 — `scan_log.db`(스캔 이력
70,840행 + `signal_outcomes` 5,442건 + `app_state`), 페이퍼 포지션, 거래 안전장치 DB,
워치리스트. **60일 검증 시계가 0부터 다시 시작된다.**

##### cp 로 백업하면 복원할 때 깨진다

DB 는 WAL 모드다. 실행 중에 `cp` 하면 `.db` 와 `-wal` 이 서로 다른 시점의 것이 되어
복원 시 깨지는데, **파일 크기도 개수도 멀쩡해 보인다** — 복구를 시도하는 순간에야
알게 된다. 백업이 있다고 믿는 상태가 백업이 없는 것보다 나쁠 수 있다.

`state_backup.py` 는 sqlite 온라인 백업 API(`Connection.backup()`)를 쓴다. 원본이
쓰이는 중에도 일관된 스냅샷을 만들고, **만든 다음 검증한다** — 체크섬 +
`PRAGMA integrity_check` + 행 수 기록.

- 분석 JSON·차트는 담지 않는다 (재생성 가능, 1.5GB)
- `.env` 는 **기본 미포함** — 백업이 곧 자격증명 사본이 된다. `include_env=True` 로
  명시할 때만 넣고 매니페스트에 경고를 남긴다
- 잡 결과: 검증 실패면 `error`, 대상 누락이면 `degraded`. 둘 다 ops 알림

##### 복구는 실제로 해 봐야 한다

`scripts/restore_drill.py` 가 운영 파일을 건드리지 않고 최신 아카이브를 임시 경로에
풀어 대조한다 (`make backup-drill`).

**2026-09-14 08:32 리허설 결과: 성공** — DB 5개 integrity ok, `scan_log` 70,840 /
`signal_outcomes` 5,442 / `app_state` 8행 일치, 파일 2개 크기 일치. 아카이브 2.83 MB,
생성 0.4초.

(운영 DB 와 3행 차이가 났는데, 백업 이후 스캔이 돈 만큼이다 — 온라인 백업이
**쓰이는 중인 DB** 에서 일관된 시점을 떠 왔다는 증거이기도 하다.)

##### 오프사이트 복제 (2026-09-14 추가)

목적지는 **코드가 정하지 않는다** (`OFFSITE_BACKUP_DEST`). 비어 있으면 아무 데도 보내지
않고 `disabled` 로 보고한다 — 설정 안 됨을 성공으로 덮지 않는다.

| 형태 | 실행 주체 | 이유 |
|---|---|---|
| `/mnt/backup/…` (로컬·마운트) | agent-api 가 직접, 매 백업 후 | 순수 Python 복사 — 컨테이너에 rsync 불필요 |
| `user@host:/path` (원격 SSH) | **호스트** `scripts/offsite_sync.sh` (cron) | SSH 개인키를 네트워크 노출 서비스 컨테이너에 넣지 않는다 |

원격 목적지가 설정된 채 컨테이너에서 시도되면, **어디서 돌려야 하는지**를 담은 에러로
끝난다 (조용히 건너뛰지 않는다).

**복사했다 ≠ 도착했다.** `rsync` 종료코드 0 은 전송이 끝났다는 뜻이다. 양쪽 경로 모두
복제 후 최신 아카이브의 sha256 을 **목적지에서 다시 계산해** 대조하고, 불일치·확인
불가는 `degraded` + ops 알림이다. 검증을 통과한 백업만 내보낸다 — 깨진 사본을 복제하면
오프사이트에도 깨진 것이 쌓인다.

**설정값 (2026-09-14): `/db4/stock_auto_backups`.** `/db4` 는 `sda`(1.8T)로 운영 데이터가
있는 `nvme0n1` 과 다른 물리 디스크다 — `df --output=source` 로 확인했다. 경로를 같은
디스크 안으로 바꾸면 복제도 `configured: true` 도 그대로지만 **대비만 사라진다.**

원격 노드 후보는 아직 미설정이다: `hsptest-macstudio`(문서상 듀얼 노드 파트너)는 5일째
offline, `parkhongnas` 는 SSH 는 열려 있으나 `ubuntu`+`id_ed25519` 로는 거부된다.

실측: 백업 2.83 MB → `/db4` 복제 후 sha256 일치, **오프사이트 사본으로 복구 리허설 성공**
(scan_log 70,864행, 운영과 차이 0).

##### 남은 한계 (문서에 명시)

- 오프사이트 사본은 `/db4`(`sda`, 운영 데이터의 `nvme0n1` 과 **다른 물리 디스크**)에 있다.
  디스크 고장은 대비되지만 **머신 자체 손실은 아니다** — 두 디스크가 같은 기계 안이다
- 서비스를 실제로 정지하고 갈아끼우는 전체 복구 절차는 **아직 돌려본 적 없다**
- `.env` 를 백업에 넣지 않으면 키 보관 장소를 따로 정해야 한다 — 지금은 정해져 있지 않다

#### 13.9h Mac Studio 가용 판정 — 도달성 ≠ 사용 가능 (2026-09-14)

`is_mac_studio_available()` 이 `/api/tags` 200 만 보고 **5일 내내 True** 를 돌려주는
동안, 그 노드는 32B 모델을 **CPU 로** 돌리고 있었다.

```
2026-09-09 13:50:37  openclaw-gateway 기동 (launchd KeepAlive, CPU 98% 점유)
2026-09-09 13:51:19  Ollama "failure during GPU discovery
                     — failed to finish discovery before timeout"
                     → load_tensors: offloaded 0/65 layers to GPU
```

Metal 자체는 정상 인식됐다 (`using device Metal (Apple M1 Max) - 25557 MiB free`).
CPU 포화 때문에 **기동 시점의 GPU 탐지가 타임아웃**됐고, 그 판정을 5일간 들고 있었다.

| | CPU 폴백 중 | 복구 후 |
|---|---|---|
| 32B q4 추론 | **0.5 tok/s** | **9.4 tok/s** (약 19배) |
| `/api/ps` `size_vram` | 0.0 GB | 25.8 GB (98%) |
| `/api/tags` | 200 | 200 ← **구분 불가** |

그동안 8개 중 4개 에이전트(Technical/Quant/Risk/ML)가 이 노드로 갔다. LLM 타임아웃은
240초, 전체 300초다 — 0.5 tok/s 로는 수백 토큰 응답이 전부 타임아웃이다.

##### 같은 검사가 이미 다른 노드에는 있었다

`service._ollama_runtime_status()` (#15) 가 로컬 RTX 노드에 대해 똑같이 `/api/ps` 의
`size_vram` 으로 CPU 폴백을 잡고 있었다. **한 노드에서 배운 것을 다른 노드에 옮기지
않은 것**이 이 결함의 정체다.

**수정**: `dual_node_config.mac_studio_runtime_status()` 추가. 도달성 확인 뒤
`/api/ps` 로 `gpu` / `cpu_fallback` / `idle` / `unknown` 을 판정하고,
`cpu_fallback` 이면 가용에서 뺀다 → 라우팅이 RTX 단독으로 돌아간다 (실측 확인).

- CPU 폴백은 **연결 실패가 아니다** — 연속 실패 카운터(`failures`)로 덮지 않는다
- 적재 모델이 없으면 `idle` = **판정 불가**이지 '정상'이 아니다. 이때는 도달성만으로
  가용을 유지한다 (기동 직후마다 노드가 빠지는 것을 막는다)
- `MAC_STUDIO_REQUIRE_GPU=false` 로 끌 수 있고, `MAC_STUDIO_MIN_GPU_FRACTION`
  (기본 0.5)로 부분 오프로드 허용 범위를 정한다
- System Monitor 화면에 `runtime` 을 띄운다 — CPU 폴백이면 빨간 경고

##### 복구 시 주의

`brew services restart ollama` 는 SSH 비대화형 세션에서 서비스를 되살리지 못했다
(`Bootstrap failed: 5: Input/output error`). `launchctl kickstart -k
gui/$(id -u)/homebrew.mxcl.ollama` 로 복구했다. 그 사이 몇 분간 8080 이 죽어 있었다.

#### 13.9i 스케줄 시각이 9시간 어긋나 있었다 (2026-09-15)

컨테이너에 `TZ` 를 주지 않으므로 APScheduler 는 `Etc/UTC` 로 돈다. 그런데 설정 주석은
**"서버 로컬 시간 기준"** 이라고 적혀 있었다. 운영자와 시장은 KST 다.

| 잡 | 설정(UTC) | 실제 KST | 주석이 말한 의도 |
|---|---|---|---|
| `screener_batch` | 16:30 | **01:30(+1)** | 16:30, KRX 마감 15:30 이후 |
| `multi_agent_batch` | 22:00 | **07:00** | 17:30 |
| `daily_signal_validation` | 23:00 | **08:00(+1)** | 23:00 |
| `corporate_actions` | 00:05 | **09:05** | 00:05 |
| `output_retention` | 03:30 | **12:30** | 03:30 (야간) |
| `state_backup` | 04:00 | **13:00** | 04:00 (야간) |

**실측 피해**: `signal_outcomes` 의 스크리너 표본이 `2026-09-14T16:38`(UTC)로 적립돼
있었다 = KST 9/15 01:38. 즉 **9/13 장 마감 데이터가 9/14 날짜로 기록**됐고,
`ticker_day` 중복 제거와 horizon 시작일이 하루씩 밀렸다. 데이터 자체는 마감 후라
유효하지만 날짜 귀속이 어긋난다.

##### TZ 를 KST 로 바꾸지 않은 이유

그 편이 주석을 전부 맞게 만들지만, `datetime.now()` 가 **KST naive** 를 뱉게 된다.
DB 에는 이미 `2026-09-15T02:14:12+00:00` 처럼 UTC aware 로 쌓여 있고 §5.5 가
"내부 저장은 UTC aware" 를 규정한다. 두 형식이 섞이면 horizon 계산이 **조용히**
틀어진다 — 시각 환산보다 훨씬 나쁜 고장이다.

**수정**: 크론 기본값을 UTC 로 환산(KST − 9)하고, 설정 주석에 UTC 임을 박았다.
문서화 자체가 이 결함의 원인이었으므로 주석도 테스트로 고정했다.

실측 (재기동 후): screener 07:30→KST 16:30, multi_agent 08:30→17:30,
validation 14:00→23:00, corporate 15:05→00:05, retention 18:30→03:30,
backup 19:00→04:00.

##### 곁에서 드러난 것 — 시계 의존 테스트

`test_non_overlapping_mode_keeps_one_row_per_horizon_block` 이 이날 실패했다
(main 에서도 재현). "20일 전과 19일 전은 같은 7일 블록" 을 가정했는데, 블록 인덱스는
**epoch 기준 절대 격자**(`(issued_at - 1970-01-01).days // horizon`)라 오늘이 격자
어디에 있느냐에 따라 갈린다 — 7일 중 1일은 경계다. 구현이 아니라 테스트의 가정이
틀렸다. 절대 격자는 의도된 설계다(질의 시점과 무관하게 경계가 일정해야 한다).
같은 블록에 드는 인접 이틀을 실행 시점에 계산하도록 고쳤고, 격자 기준점이 epoch
임을 고정하는 테스트를 추가했다.

#### 13.9j Gemini — 죽은 기본 모델 + 워크로드가 쿼터를 넘는 구조 (2026-09-15)

`fetch_news_with_sentiment` 검증 중 Gemini 가 429 를 뱉어 확인한 결과, 두 가지가
겹쳐 있었다.

##### 1. 기본 모델이 폐기됐다

```
gemini-2.0-flash → HTTP 404 NOT_FOUND
"This model models/gemini-2.0-flash is no longer available.
 Please update your code to use models/gemini-3.6-flash"
```

`config.GEMINI_MODEL` 기본값과 `router.build_router()` 의 폴백 기본값이 모두 이
모델이었다. `.env` 가 `gemini-2.5-flash` 로 덮어써서 운영은 돌았지만, **`.env` 없는
환경에서는 Gemini tier 가 통째로 실패**한다. 문서도 죽은 모델을 적고 있었다.

##### 2. 쿼터는 모델당 하루 20회, 워크로드는 배치 1회 28회

429 본문의 실제 쿼터:

```
quotaId    : GenerateRequestsPerDayPerProjectPerModel-FreeTier
quotaValue : 20
```

Gemini 에이전트 4개(Decision Maker · Value · Event · Geopolitical) ×
워치리스트 7종목 = **배치 한 번에 28회**. 스캔·뉴스 감성까지 더하면 배치 시작 전에
소진돼 있을 수도 있다. **기다려서 풀리는 문제가 아니라 한도를 넘는 구조**다.

##### 수정

쿼터가 **모델당** 계산되는 점을 이용한다. `agent-llm-primary-alt` tier 를 추가해
다른 모델(`gemini-3.5-flash`)을 한 단계 더 두면 예산이 따로 잡힌다 (20 + 20 = 40 > 28).

Router 의 내부 재시도·폴백은 좀비 스레드 방지로 꺼져 있다 (`num_retries=0`,
`fallbacks=[]`). 그래서 LiteLLM 에 맡기지 않고 `_model_candidates()` 의 **외부 루프**에
tier 를 넣었다 — deadline 예산(#14)·노드 가용성·타임아웃 상한이 그대로 적용된다.

후보 순서: `primary(3.6) → primary-alt(3.5) → secondary(Mac 32B) → tertiary(RTX 14B)`

실측: 3.6-flash 가 503 을 준 호출이 자동으로 3.5-flash 로 넘어가 8.4초에
`signal=buy, confidence=7.0` 을 받았다.

##### 남은 한계

40회/일도 넉넉하지 않다. 종목이 늘거나 스캔이 Gemini 를 쓰면 다시 넘친다. 구조적
해법은 유료 등급이다 — 28회/일 규모에서는 비용이 미미하다.

#### 13.9k 스키마 마이그레이션 (2026-09-15)

CLAUDE.md Don't #8 은 "Alembic migration 도입 후 마이그레이션 스크립트로만" 을
규정하고 있었지만 **도구가 없었다.** `init_db()` 가 이렇게 했다:

```python
conn.execute(_CREATE_TABLE)              # CREATE TABLE IF NOT EXISTS
try:
    conn.execute("ALTER TABLE signal_outcomes ADD COLUMN ...")
except sqlite3.OperationalError:
    pass    # 이미 존재
```

문제 셋:
1. **버전 기록이 없다** — 어떤 DB 가 어디까지 왔는지 알 방법이 없었다
2. **실패가 숨는다** — "이미 존재"와 진짜 오류가 같은 처리다 (§13-1)
3. 데이터 마이그레이션(백필·값 변환)을 넣을 자리가 없었다

##### SQLAlchemy 모델은 도입하지 않았다

DB 계층 전체가 raw `sqlite3` 다. 모델이 없으니 `--autogenerate` 는 쓸 수 없고,
마이그레이션은 `op.exec_driver_sql()` 로 직접 쓴다. Alembic 은 **버전 관리와 순서
보장**만 담당한다 — 그게 없던 부분이다. (alembic·SQLAlchemy 는 litellm 이 이미
transitive 로 끌어오고 있었지만, 이제 직접 의존이므로 requirements 에 명시했다.)

| 리비전 | 내용 |
|---|---|
| `0001_baseline` | 현재 스키마 전체. SQL 은 `db.py` 의 `_CREATE_*` 상수를 **그대로** 실행한다 (복사하면 갈린다) |
| `0002_signal_outcomes_columns` | Step 12 / 2026-09 에 손으로 추가했던 컬럼 10개 |
| `0003_scan_log_entry_price` | `scan_log.entry_price` |
| `0004_indexes` | 인덱스 — 컬럼 리비전 이후에 만든다 |

##### 두 번 틀렸고, 둘 다 테스트가 잡았다

**(1) 기존 DB 를 stamp 로 채택하려 했다.** "이미 최신이면 head, 아니면 베이스라인으로
stamp" 로 짰는데, 스키마가 **일부만** 있는 DB 에서 깨졌다 — stamp 는 0001 을
건너뛰므로 없는 테이블이 영영 안 만들어진다. `test_direction_adjusted_metrics` 가
잡았다. 어느 리비전이 이 DB 의 모양과 맞는지 **추측하는 것 자체가 틀린 접근**이었다.
지금은 채택 시에도 처음부터 올린다: 0001 은 전부 `IF NOT EXISTS`, 0002·0003 은 컬럼
존재를 직접 확인하므로 기존 데이터에 안전하고 빠진 것만 채운다.

**(2) 인덱스를 베이스라인에 뒀다.** `_CREATE_INDEX` 에 `signal_outcomes(regime)` 처럼
후속 컬럼을 참조하는 인덱스가 있어, 옛 DB 에서 컬럼이 생기기 전에 실행돼
`no such column: regime` 으로 죽었다. 마지막 리비전(0004)으로 분리했다.

##### 운영 DB 채택 결과

적용 전 백업(오프사이트 복제 포함)을 복구 지점으로 잡고 실행했다.

```
mode     : adopt → revision 0004_indexes
scan_log : 71,143행 (변화 없음)
signal_outcomes : 5,525행 (변화 없음)
integrity: ok     view: 존재
```

재실행은 `mode: upgrade` 로 멱등이다. 확인: `make db-revision` / `make db-history`.

#### 13.9l FastAPI sync 핸들러 — 측정 후 범위를 좁혔다 (2026-09-15)

핸들러 86개가 전부 `def` 다. FastAPI 는 sync 핸들러를 anyio 스레드풀(기본 **40**)에서
돌리므로 이벤트 루프는 막히지 않는다. 그래서 먼저 **실제로 무엇이 문제인지 측정**했다.

##### `/health` 는 느리지 않다 — 슬롯을 못 받는다

```
_ollama_runtime_status    3.27 ms   (httpx)
gpu_pause_status          3.67 ms   (내부에서 또 httpx)
get_market_session x2    10.63 ms   (CPU)
나머지(메모리)              ~0 ms
                        ─────────
                        약 18 ms
```

그런데 느린 요청(`/sector` 11초) **45개**를 동시에 던지면:

| | 이전 |
|---|---|
| `/health` 최대 지연 | **7.33초** |
| 컨테이너 헬스체크 timeout | **2초** (compose.yaml) |

자기 일이 느린 게 아니라 **스레드 슬롯 대기**다. `retries: 3`, `interval: 30s` 이므로
90초 이상 부하가 지속되면 컨테이너가 unhealthy 로 떨어진다.

##### 86개를 async 로 바꾸는 것은 해법이 아니다

내부의 blocking 호출(httpx.get, sqlite, pandas)이 그대로면 `async def` 는 **이벤트
루프를 막는다** — sync 로 스레드에서 돌던 것보다 나쁘다. 그래서 두 가지만 했다:

1. **스레드풀 한도 40 → 80** (`API_THREAD_LIMIT`). 핸들러는 I/O 대기가 대부분이라
   스레드 비용이 낮다.
2. **`/health` 만 async 전환.** 슬롯을 아예 안 쓰게 하고 **메모리만 읽는다.**
   - 네트워크·CPU 프로브는 백그라운드 태스크가 `HEALTH_PROBE_INTERVAL_SECONDS`
     (기본 15초)마다 `httpx.AsyncClient` + 워커 스레드로 갱신
   - 스냅샷 **나이**를 `probe.age_sec` / `probe.stale` 로 내보낸다 — 루프가 죽으면
     옛 값이 최신처럼 보이지 않는다 (§13-4)
   - `build_data_health()` 인라인 호출 제거. 스냅샷이 없으면 `not_computed` 로 적는다
   - 실시간 조회가 필요하면 `/health/deep` (sync, 스레드에서 돈다)
   - 부수 효과: `/health` 의 Ollama httpx 호출이 3회 → 0회

##### 결과 (같은 부하 재측정)

| 동시 요청 | `/health` 최대 | slow 전체 |
|---|---|---|
| 45 | 7.33초 → **0.353초** | 14.2초 → 11.3초 |
| 90 | — → **0.114초** | 14.4초 |

한도(80)를 넘는 90 동시에서도 `/health` 가 0.11초다 — 슬롯을 기다리지 않기 때문이다.

##### 남은 것

나머지 85개는 sync 다. 단일 사용자 환경에서 동시 요청이 40을 넘는 일은 거의 없고,
스케줄 잡은 APScheduler 스레드에서 돌아 요청 풀을 쓰지 않는다. 추가 전환은
**측정된 문제가 생길 때** 하는 게 맞다 — 지금 옮기면 blocking 호출이 이벤트 루프로
올라가 더 나빠진다.

#### 13.9n Alembic 이 로깅 설정을 덮었다 (2026-09-15, #72 회귀)

17:30 배치 소요를 조사하려고 로그를 읽는데 종목별 진행 로그가 없었다. 배치 종료 줄이
**`ERROR [alembic]`** 으로 찍혀 있었다.

Alembic 템플릿의 기본 `env.py` 는 `fileConfig(config.config_file_name)` 을 호출한다.
그건 `alembic.ini` 의 `[loggers]`/`[handlers]`/`[formatters]` 로 **루트 로거를 통째로
교체**한다. 서비스는 기동 시 `configure_logging()` 으로 로깅을 구성하는데, 그 직후
`init_db()` → 마이그레이션이 돌아 설정이 덮였다.

```
configure_logging 직후 : root=INFO    formatter=[%(name)s]  filters=[SecretRedactingFilter]
init_db(alembic) 이후  : root=WARNING formatter=[alembic]   filters=[]
```

피해 셋:

1. **`logger.info` 전부 소실** — 배치 진행 로그를 못 봤고, §13.9c 에서 살려낸
   `data_collector` INFO 도 다시 죽었다
2. 모든 모듈 로그가 `[alembic]` 로 표기 (alembic.ini 포맷에 하드코딩돼 있었다)
3. **API 키 마스킹 필터 제거** — §13.9c 에서 막은 유출이 되살아난 상태였다.
   다행히 실제 노출은 0건이었다 (FMP 403 경로가 naver+yfinance 로 충족돼 호출되지
   않았다). 운이 좋았을 뿐이다

**수정**: `env.py` 가 `fileConfig` 를 부르지 않고, `alembic.ini` 에서 로깅 섹션을
제거했다 (CLI 단독 실행에서도 덮지 않게). Alembic 로그는 `alembic.*` 로거로 나가고
루트 설정을 상속한다. 회귀 테스트 3건으로 고정 — 레벨·포맷·필터가 마이그레이션 후에도
동일해야 한다.

실측(수정 후): `[stock_auto.*]` INFO 정상 출력, 잘못된 `[alembic]` 표기 0건,
alembic 자체 로그는 `[alembic.runtime.plugins]` 로 나간다.

##### 교훈

§13.9c 에서 "로깅이 설정된 적이 없다" 를 고쳤는데, 3주도 안 되어 **다른 기능이 그
설정을 조용히 되돌렸다.** 설정을 세우는 것과 세운 설정이 유지되는 것은 다른 문제다.
그래서 이번에는 불변식을 테스트로 박았다.

#### 13.9o 배치 소요의 병목 — 노드 분산을 시도했고 되돌렸다 (2026-09-15)

17:30 배치가 7종목에 1,117초를 쓴다. Mac Studio 가 CPU 폴백(0.5 tok/s)이던 전날과
GPU 복구(9.8 tok/s) 후가 같아서 원인을 측정했다.

##### 측정: 한 종목(PLTR) 에이전트별

| 에이전트 | 노드 | 소요 |
|---|---|---|
| ML Specialist | Mac | **146.7초** |
| Technical Analyst | Mac | **132.3초** |
| Risk Manager | Mac | **91.0초** |
| Quant Analyst | Mac | **46.8초** |
| Geopolitical Analyst | Gemini | 12.3초 |
| Event Analyst | Gemini | 8.7초 |
| Value Investor | Gemini | 6.5초 |

**Ollama 4개 합 417초 / Gemini 3개 합 27.5초**, 총 소요 149.9초 (병렬이므로 가장
느린 에이전트가 정한다). Mac 단독 호출은 7.5초(9.7 tok/s)다 — 4개를 한 노드에 몰아
큐가 쌓인 결과다. 배치는 종목도 직렬(`for ticker in targets`)이라 7 × 약 159초가 된다.

##### 원인 둘

1. **`AGENT_LLM_MAPPING` 의 `node` 필드가 라우터 경로에서 무시됐다.** `_call_llm` 이
   provider 만 넘겨서 Ollama 에이전트 전부가 `agent-llm-secondary`(Mac)를 먼저 쳤다.
   매핑에 `node` 를 적어 둔 것이 장식이었다.
2. 매핑 자체가 Ollama 4개를 모두 mac_studio 로 배정했다.

##### 시도와 결과 — 2.2배 악화

`preferred_node` 를 라우터에 전달하게 고치고(1번 해결), 매핑을 2:2 로 나눴다.

| 에이전트 | Mac 4개 집중 | RTX 2개 분산 후 |
|---|---|---|
| Technical Analyst | 132.3초 | **45.5초** (의도대로) |
| ML Specialist | 146.7초 | **63.2초** (의도대로) |
| Quant Analyst → RTX | 46.8초 | **320.1초** ✗ |
| Risk Manager → RTX | 91.0초 | **279.1초** ✗ |
| **한 종목 총** | **149.9초** | **322.6초** |

Mac 쪽은 3배 빨라졌는데 RTX 로 옮긴 둘이 6배 느려졌다. RTX 5070(12GB)에
`qwen3:14b-q4_K_M`(10.8GB)을 올리면 **여유가 1.4GB 뿐**이라 동시 2요청의 KV 캐시를
감당하지 못한다. `RTX_5070_MAX_INFLIGHT` 기본값이 2 인 것을 고려하지 않았다.

**매핑은 되돌렸다.** 라우팅 기구(`preferred_node`)는 남긴다 — 그 자체는 맞는 수정이고
(매핑의 `node` 가 이제 실제로 동작한다) 재시도 시 매핑만 바꾸면 된다.

##### 곁에서 드러난 것 — RTX 노드도 false-green 이다

측정 직후 RTX 는 **8토큰 요청조차 90초 내에 끝내지 못했다.** 그런데 상태는 전부
정상으로 보인다:

```
/health  ollama=connected  runtime=gpu
         qwen3:14b-q4_K_M  on_gpu=True  vram=10.8GB  gpu_fraction=1.0
nvidia-smi  util 0%  memory 10,134/12,227 MiB
```

§13.9h 에서 Mac Studio 에 넣은 게이트는 `size_vram > 0` 으로 **CPU 폴백**을 잡는다.
지금 RTX 는 CPU 폴백이 아니다 — GPU 에 올라가 있는데도 쓸 수 없다. **적재 위치가
아니라 처리량을 봐야 잡히는 상태**이고, 현재 어떤 게이트도 이를 감지하지 못한다.
원인 미규명 — 별도 과제다.

##### 배치 시간을 줄이려면 (다음 후보)

- `RTX_5070_MAX_INFLIGHT=1` 로 직렬화한 뒤 2:2 재시도. 단 위 RTX 이상을 먼저 규명해야
  측정이 의미를 갖는다
- 종목 병렬화 (현재 완전 직렬). Mac 에 요청이 2배로 몰리므로 노드 처리량이 먼저다
- Mac Studio `OLLAMA_NUM_PARALLEL` 상향 (현재 미설정=1). 32GB 에 19.9GB 모델이라 KV
  캐시 여유 확인 필요 + Ollama 재기동 시 §13.9h 의 GPU 탐지 실패 위험

#### 13.9p 적재 위치가 아니라 생성 경로를 봐야 잡히는 상태 (2026-09-16)

§13.9o 조사 중 RTX 5070 이 **8토큰 요청조차 끝내지 못하는** 상태를 발견했다. 그런데
모든 지표가 정상이었다.

| 지표 | 값 | 판정 |
|---|---|---|
| `/api/tags` | 200, 0.36ms | 정상 |
| `/api/ps` `size_vram` | 10.8GB, `gpu_fraction 1.0` | 정상 |
| `nvidia-smi` | util 0%, 8.8W, 10,134/12,227 MiB | 정상 |
| `/api/generate` | **모델 무관하게 60초+ 아무것도 생성 못 함** | **불가** |
| `/health` | `ollama: connected, runtime: gpu` | **거짓 정상** |

`ollama.service` 는 4일 가동(CPU 11h50m, swap peak 1.4GB), runner 프로세스는 2일
가동 중이었다. 10:32 KST 스캔은 성공했으므로 그 이후에 막혔다 — 진단 중 던진
타임아웃 요청들이 방아쇠로 보인다.

##### §13.9h 게이트가 이걸 못 잡는 이유

Mac Studio 에 넣은 게이트는 `size_vram > 0` 으로 **CPU 폴백**을 판정한다. 지금 RTX 는
CPU 폴백이 **아니다** — GPU 에 100% 올라가 있는데도 쓸 수 없다. 적재 위치는 맞고
생성 경로가 죽은 것이라, 위치만 보는 검사로는 원리적으로 잡히지 않는다.

CLAUDE.md §13-3 이 이 형태를 경고한다: *"응답 코드 200을 성공으로 읽지 말 것 —
Ollama 언로드, 텔레그램 전송 모두 200과 실패가 공존한다."*

##### 수정 — 1토큰 생성 검사

두 노드 모두 프로브에 `num_predict: 1` 생성 호출을 추가했다.

| 상태 | 의미 |
|---|---|
| `ok` | 1토큰을 예산 안에 받았다 (`latency_ms` 동봉) |
| `stalled` | 타임아웃 — **적재는 됐으나 생성 불가**. 이번 사례 |
| `skipped` | 적재 모델 없음(idle) 또는 모델명 불명. **'정상'이 아니다** |
| `error` | 그 외 (HTTP 오류·연결 실패, 사유 포함) |

설계에서 지킨 것:

- **적재된 모델이 있을 때만** 시도한다. 유휴 노드에 보내면 모델 로드(수십 초)를
  유발해 **검사가 스스로 부하를 만든다**
- `stalled`/`error` 면 `runtime` 을 `unusable` 로 내린다. Mac 은
  `is_mac_studio_available()` 이 False 가 되어 **라우팅에서 빠진다**
- CPU 폴백 판정이 우선이다 — 더 구체적인 사유를 `unusable` 로 덮지 않는다
- **RTX 는 라우팅에서 빼지 않는다.** `_node_available_for_model` 의 기존 결정
  (로컬 최후 폴백)을 유지한다 — 여기까지 게이트하면 Mac·Gemini 동시 장애 시 전원
  장애가 된다. `/health` 로 보이게만 한다
- 예산은 `HEALTH_GENERATION_TIMEOUT_SECONDS`(기본 20초). 짧으면 로드 직후 정상
  노드를 오판한다

##### 실측 (교착된 RTX 그대로)

```
ollama          : connected          ← /api/tags 는 여전히 200
runtime         : unusable           ← 종전에는 "gpu"
generation      : stalled, 20,004ms, qwen3:14b-q4_K_M
unusable_reason : 20초 안에 1토큰도 생성하지 못했다 — 적재는 됐으나 생성 불가
```

##### 남은 것

RTX runner 교착의 **근본 원인은 미규명**이다. 재현 조건(버려진 요청 누적?)과
`ollama serve` 재시작 외의 복구 방법이 필요하다. 이 게이트는 **드러내기**까지다.

### 13.10 데이터 품질 위험

- OHLCV 캐시는 TTL 메타(`fetched_at`, `latest_bar_date`, `source`)를 갖지만,
  소스 폴백(한국 pykrx→FDR→yfinance, 미국 yfinance→FDR)이 종목별로 다르게 걸릴 수 있어
  **동일 리포트 안에 서로 다른 소스의 값이 섞일 수 있다.**
- KRX 펀더멘털은 로그인 필수, KDR(9xxxxx)은 KRX 미제공으로 yfinance 폴백.
- 뉴스는 Google News RSS + 네이버 금융 크롤링 — 구조 변경에 취약. 거시는 yfinance(^VIX, ^KS11 등) + FRED.
- 외부 무료 API 의존도가 높아 rate limit·스키마 변경이 조용한 품질 저하로 이어질 수 있다.
- ✅ **`.env`의 `DATA_SOURCE` 이중 선언 정리** (`yfinance` → `toss`, 뒤가 실효값이었다).
  실효 소스는 `toss`(`/data-source` 실측: configured=active=toss, health ok).
  기동 시 `config.find_duplicate_env_keys()`가 중복 키를 **이름만** 경고한다.
- ✅ **평가 가격 조회를 `data_collector` 체인으로 통일** (2026-09-10). 종전에는 사후 평가만
  yfinance를 직접 호출해, 다른 경로는 Toss·pykrx로 받는 종목이 평가에서만 404로 죽었다.
  통일 후 `057050.KS` 프리페치는 성공했지만 53건은 여전히 평가 불가 — yfinance·Toss·pykrx
  **세 소스 모두 2026-07-16 이후 데이터가 없다**(거래 중단). 영구 평가 불가로 확정됐다.
  단, 기존 평가값은 yfinance 가격이고 앞으로는 Toss라 **provenance가 혼재**한다.
- **`/ops/data-health`가 상시 `stale`이다** (실측 24종목 중 17 stale). stale 목록은 전부
  현재 워치리스트에 없는 과거 종목·페이퍼 포지션이라 아무도 데이터를 채우지 않는다.
  현 워치리스트 7종목은 모두 `ok`. 항상 켜져 있는 빨간불이라 §14의 관점에서 정리 대상이다.

---

## 14. 설계 원칙 — 개선 작업 시 반드시 지켜야 할 것

이 프로젝트의 사고 이력은 대부분 **"장애가 정상으로 보고된"** 유형이다. 실제 사례:

| 증상 (화면에 보인 것) | 실제 | 수정 |
|---|---|---|
| `/health` ollama connected | CPU 폴백 중, 추론 156~405초 | `ollama_runtime` 필드 추가 |
| 신호 "관망" | 임계 ±2가 도달 불가 스케일 | 1.3/-0.5 정합 |
| "최근 30일 공시 없음" | 라이브러리 미설치 + 잘못된 호출 | `DartUnavailable` 분리 |
| `alert_sent=1` | 텔레그램 400, 실제 도착 0건 | 전송 결과 반영 |
| R/R 0.20 경고 + 매수 신호 | 경고가 신호를 못 막음 | 하드 게이트 |
| 워치리스트 "삭제됨" | ro 마운트로 파일에 안 써짐 | 되읽기 검증 |
| 리포트 "종합 +5.0" | 부분합과 불일치 | 불변식 + `execution_ready=False` |

**작업 규칙** (CLAUDE.md §13과 동일):

1. `except`에서 사유를 버리지 말 것. 최소한 로그에 남긴다.
2. **'조건 충족'과 '결과 성공'을 같은 필드에 쓰지 말 것.** 전송·저장은 결과를 확인하고 기록한다.
3. HTTP 200을 성공으로 읽지 말 것 — Ollama 언로드·텔레그램 전송 모두 200과 실패가 공존한다.
4. 미검증 상태를 성공으로 덮지 말 것 (`untested` ≠ `ok`).
5. 화면 변경은 브라우저로 확인할 것 — Streamlit은 스크립트가 죽어도 HTTP 200이다.
6. 소비자 없는 출력 필드를 만들지 말 것 — 기능 착시를 만든다.

**의사결정 우선순위**: 데이터 무결성 > 기능 추가 / 측정 가능성 > 최적화 /
명시적 가정 > 암묵적 가정 / 단순 fallback > 정교 합의 / 로컬 운영비용 > 클라우드 정교함 /
paper 60일 검증 > 즉시 live 전환.

**금지 사항**: `.env` 커밋, 키 노출, `paper_trading_state.json` 직접 편집,
백테스트 Sharpe 무보정 신뢰, LLM SDK 직접 호출(LiteLLM Router 우회), `from X import *`,
DB 직접 SQL 변경, `webui.py` 일괄 분해.

---

## 15. 개선 의뢰 시 우선 검토를 요청하는 항목

시스템 소유자가 판단을 미루고 있거나, 외부 시각이 필요한 지점을 우선순위대로 정리했다.

1. **표본 축적 대기** (종목 확대는 2026-09-12 완료, §13.8) — 스크리너가 하루 10종목씩
   독립 표본을 쌓기 시작했다. 7일 horizon 평가까지 최소 1주, 14일 대표 horizon 까지
   2주가 필요하므로 **2026-09-26 이후**에 첫 유효 비교가 가능하다. 그 전에 규칙
   (국면별 손절, IC 가중)을 정하면 또 과적합이다.
   부수 검토: 30분 스캔을 `signal_outcomes`에 전량(하루 48 × 7종목) 적립할 필요가
   있는지 — 읽는 쪽에서 어차피 하루 1건으로 접는다.
2. **국면별 손절 규칙** (역행폭 측정은 2026-09-12 완료, §13.7) — payoff 0.66,
   tail_ratio 1.56 으로 손익 비대칭이 확인됐지만, **고정 손절폭은 답이 아니다**:
   급락장에서는 +4.5%p 개선이고 최근 구간에서는 −0.6~−1.8%p 손해다(§11.2e).
   국면 판정(`regime/detector.py`)과 손절폭을 연결하는 규칙이 필요하고, 그걸 정하려면
   표본이 더 필요하다 — 신 로직 독립 블록 79개로는 국면별 규칙을 세울 수 없다.
3. **IC 앙상블을 살릴 것인가, 지울 것인가** — 계산은 되지만 `apply_ic_weights()` 호출부가
   없어 판정에 반영되지 않는다(§13.3). 소비자 없는 출력은 기능이 있다는 착시만 만든다(§14).
4. **24 도구 + 8 에이전트 구성의 정당성** — 도구별·에이전트별 기여도가 측정되지 않은 상태에서
   구성 요소가 계속 늘어났다. 어떤 것을 줄여야 하는가. (IC 앙상블은 60일 표본 요건 미충족으로 균등가중 폴백 중)
5. **정성(LLM) 기여의 역할** — 현재는 정량 기여를 넘지 못하도록 상한이 걸려 있다.
   LLM 서술이 신호 품질에 실제로 기여하는지, 아니면 비용·지연만 추가하는지.
6. **live 전환 게이트 설계** — 무엇을 만족하면 paper→approval→live로 올릴 수 있는가.
   측정은 복구됐지만 게이트 기준("60일 hit-rate")이 어떤 표본·어떤 지표·어떤 하한을
   뜻하는지가 정의돼 있지 않다.
7. **아키텍처 정리 순서** — `webui.py` 분해 / 이중 호출 경로 단일화 / async 전환 /
   구조화 로깅 중 무엇을 먼저 해야 운영 리스크가 가장 빨리 줄어드는가.
8. **단일 노드 SPOF와 백업** — 현재 복구 절차·데이터 백업 정책이 없다. 개인 운영 규모에서
   합리적인 최소 대비는 무엇인가.

---

## 부록 A. API 엔드포인트 (83개, prefix별)

| prefix | 수 | 대표 |
|---|---:|---|
| `/trading/*` | 14 | mode, kill-switch, broker-health, account, positions, orders, approval |
| `/paper/*` | 9 | order, virtual-buy, partial-close, quote, update-prices, corporate-actions, auto, reset |
| `/watchlist/*` | 4 | get, add, remove, set |
| `/signal-accuracy/*` | 4 | stats, evaluate, validation-status, calibrator |
| `/screener/*` | 4 | run, latest, history, pipeline |
| `/scan-log/*` | 4 | list, latest, range, by-ticker |
| `/gpu/*` | 4 | status, pause, extend, resume |
| `/ops/*` | 3 | jobs, data-health, jobs/{id}/run |
| `/telegram/*` | 3 | rich-signal, daily-digest, process-callbacks |
| `/quant/*`, `/user-action/*` | 3+3 | |
| 단일 | — | `/health`, `/scan`, `/multi-agent/{t}`, `/backtest/{t}`, `/ml/{t}`, `/risk/{t}`, `/macro`, `/regime`, `/news/{t}`, `/sector/{t}`, `/chart/{t}`, `/chart-pattern/{t}`, `/ranking`, `/portfolio/*`, `/calibration/*`, `/ic-weights`, `/weekly/*`, `/system-monitor`, `/restart` |

## 부록 B. 핵심 환경변수 (63키 중)

```
OLLAMA_BASE_URL / OLLAMA_MODEL / OLLAMA_NUM_CTX=8192 / OLLAMA_KEEP_ALIVE=1h
MAC_STUDIO_URL=http://hsptest-macstudio:8080 (+헬스 TTL/threshold/inflight)
GEMINI_MODEL=gemini-3.6-flash / GEMINI_FALLBACK_MODEL / DEFAULT_LLM_PROVIDER
SIGNAL_BUY_THRESHOLD=1.3 / SIGNAL_SELL_THRESHOLD=-0.5   ← .env와 config 양쪽 갱신 필요
BUY_THRESHOLD=1.2 / SELL_THRESHOLD=-0.4 / MIN_CONFIDENCE=5.0
TRADING_MODE=paper / BROKER_NAME / DATA_SOURCE=yfinance / APPROVAL_EXEC_MODE
ACCOUNT_SIZE=100000 / ACCOUNT_SIZE_KRW=100000000 / RISK_PER_TRADE_PCT=1.0
SCAN_INTERVAL_MINUTES=30 / MULTI_AGENT_BATCH_HOUR=17:30 / SIGNAL_VALIDATION_HOUR=23:00
DAILY_LOSS_LIMIT_{ALERT,HARD}_PCT=2/3 / VIX_CAP=30 / COOL_DOWN_HOURS=24
```

API 키류(`GEMINI_API_KEY`, `DART_API_KEY`, `TOSS_APP_SECRET`, `TELEGRAM_BOT_TOKEN` 등)는
`.env`에만 존재하며 이 문서·저장소·이미지에 값이 남지 않는다.

## 부록 C. 검증 명령어

```bash
docker compose ps                                    # 컨테이너 상태
curl -s http://localhost:8100/health | jq            # 헬스 + ollama_runtime + 알림 통계
curl -s http://localhost:8100/ops/jobs | jq          # 5개 잡 마지막 성공/실패
curl -s 'http://localhost:8100/signal-accuracy?dedupe=ticker_day' | jq   # 표본 기준 실측
curl -s 'http://localhost:8100/signal-accuracy?dedupe=none' | jq .sampling # 원시와 비교
curl -s http://localhost:8100/signal-accuracy/validation-status | jq .backlog   # 평가 큐 잔량
curl -sX POST 'http://localhost:8100/signal-accuracy/evaluate?limit=2000' | jq  # 수동 평가
curl -s http://localhost:8100/data-source | jq        # 실효 데이터 소스 + 헬스
open http://localhost:8501                           # WebUI (17페이지)

# Mac Studio 폴백 판정
docker exec stock-auto-webui python -c \
  "import sys; sys.path.insert(0,'/app/stock_analyzer'); \
   from dual_node_config import is_mac_studio_available; print(is_mac_studio_available())"
```

## 부록 D. 함께 전달할 문서

| 문서 | 성격 |
|---|---|
| `CLAUDE.md` | 코딩 규약·금지사항·의사결정 우선순위 (**작업 시 최우선 준수**) |
| `docs/BACKTEST_ASSUMPTIONS.md` | 슬리피지·수수료·무위험수익률 가정 |
| `docs/USER_MANUAL.md` | WebUI 사용법 |
| `docs/DESIGN_SYSTEM.md` | 화면 토큰·컴포넌트 규격 v1.0 |
| `docs/CONSULTING_BRIEF.md` / `ARCHITECTURE_BRIEF.md` | 2026-05 작성. **현재와 불일치 있음** — 이력 참고용 |
| `EXECUTION_PLAN.md` | P0~P2 12단계 실행 기록 (완료) |

---

**문서 끝.** 이 문서의 수치는 2026-09-10 실측이며, 워치리스트·DB 행수·hit-rate는 매일 변한다.
재확인은 부록 C의 명령어로 한다.
