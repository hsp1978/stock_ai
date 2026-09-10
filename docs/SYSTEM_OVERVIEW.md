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
| 분석 주기 | 30분 간격 자동 스캔 + 매일 17:30 멀티에이전트 배치 + 23:00 신호 사후검증 |
| LLM | 8 에이전트 = Gemini 4 (gemini-2.0-flash) + Ollama 4 (Mac Studio qwen2.5:32b) |
| 분석 도구 | 24개 (방향성 22 + 비방향성 2: `risk_position_sizing`, `entry_plan_analysis`) |
| ML | 5모델 앙상블 (RF/GBM/LightGBM/XGBoost/LSTM) + SHAP + Optuna + Walk-Forward |
| 코드 규모 | 프로덕션 Python 53,834 라인 / 최대 파일 `webui.py` 6,379 라인 |
| API | FastAPI 엔드포인트 83개 (`chart_agent_service/service.py`, 3,192 라인) |
| 테스트 | 53 파일 / 548 test, CI(GitHub Actions) 최근 실행 전부 success |
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
| `stock_analyzer/webui.py` | 6,379 | Streamlit 단일 파일 앱 (17페이지). **최대 부채** |
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
├ webui.py, report_format.py, report_invariants.py, report_schema.py
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
| Value Investor | gemini | gemini-2.0-flash | 재무제표·밸류에이션 |
| Event Analyst | gemini | gemini-2.0-flash | 뉴스·내부자 거래 |
| Geopolitical Analyst | gemini | gemini-2.0-flash | 거시·지정학·FX 노출 |
| Decision Maker | gemini | gemini-2.0-flash | 충돌 해결·최종 판단 |

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

`signed`는 방향 보정 기대값(매수 +수익률 / 매도 −수익률)이다. `/signal-accuracy`의
`avg_return_pct`는 방향 보정이 없어 매도가 맞을수록 내려가므로 성능 지표로 읽으면 안 된다.

| 구간 | n | 독립 블록 | signed 평균(7일) | signed 중앙값 | 양(+) 비율 |
|---|---:|---:|---:|---:|---:|
| 구 로직 (~08-05, KOSPI 급락 국면) | 935 | 261 | **−1.50%** | −0.06% | 46.6% |
| 신 로직 (08-06~) | 288 | 117 | **+0.72%** | +0.71% | 58.3% |
| 신 로직, `scan_agent` 제외 | 214 | 100 | **+0.29%** | +0.22% | 54.2% |
| 신 로직, `scan_agent`만 | 74 | **17** | +1.94% | +1.90% | 70.3% |

**읽는 법**:

1. 원시 집계의 신 로직 +2.31%는 표본 단위를 적용하면 **+0.72%**로 줄어든다.
   그 차이는 대부분 30분 스캔의 반복 기록이 만든 것이다.
2. 그 스캔 표본조차 독립 블록이 **17개**뿐이다 — +1.94%는 통계라기보다 잡음이다.
3. 리포트·주문이 실제로 쓰는 경로(일일 멀티에이전트)는 +0.29%, 블록 100개.
   **아직 시장 대비 우위를 주장할 수 없다.**
4. win 정의는 7일 수익률이 신호 방향으로 ±2% 이상 움직인 경우다. ±2% 이내는 neutral로
   분리되므로 win_rate는 승률이 아니다.
5. 53건(`057050.KS`)은 거래 중단으로 평가 불가 — 종결 처리돼 통계에서 빠진다.

### 11.3 데이터 규모

| 항목 | 값 |
|---|---|
| `signal_outcomes` | 5,018행 — 평가 완료 4,272 / 종결 53 / 대기 0 |
| 평가된 발행 기간 | 2026-07-06 ~ 09-03 |
| 14일 / 30일 평가 | 3,468건 / 1,581건 (수리 전 237 / 0) |
| 칼리브레이터 표본 | 812 → 4,272 (원시 기준. 학습은 `ticker_day` 표본으로 한다) |

## 12. 품질 인프라

- **테스트**: `tests/unit/` 53 파일 / 548 test. LLM·외부 API는 mock(`respx`), 실호출 금지.
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

### 13.3 구조적 부채 (기존 인식)

| # | 항목 | 현재 상태 |
|---|---|---|
| 1 | `webui.py` 6,379 라인 God file | 포맷 로직만 `report_format.py`로 분리 시작. 페이지 단위 점진 분리 예정 |
| 2 | 이중 호출 경로 (직접 import + HTTP) | `/paper`·`/trading`·`/gpu`만 HTTP 강제. 나머지는 여전히 이중 |
| 3 | `print()` 기반 로깅 | 미해결 |
| 4 | 양방향 `sys.path` 주입 | 미해결 (webui↔agent 상호 import) |
| 5 | 분석 결과 JSON 69,421개 / 1.6GB | 정리 cron 없음 (`crontab` 비어 있음) |
| 6 | DB 마이그레이션 도구 부재 | Alembic 미도입 |
| 7 | FastAPI 전 핸들러 sync + blocking I/O | `httpx.AsyncClient` 단계 전환 미착수 |
| 8 | 모델 버전 태그 핀 | `qwen3:14b-q4_K_M` 등 태그 고정이나 digest 핀은 아님 |
| 9 | 백테스트 Composite 전략의 과거 replay 제외 | look-ahead 회피 목적. 도구 신호의 역사적 성능은 미측정 |
| 10 | 단일 노드 SPOF | testdev가 죽으면 전부 정지. 백업/복구 절차 문서화 없음 |

### 13.4 데이터 품질 위험

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

1. **표본 수 자체** (측정 루프 §13.1, 표본 단위 §13.2는 2026-09-10 완료) — 이제 지표는
   정직하지만 **양이 부족하다**. 일일 멀티에이전트 경로는 독립 블록 100개, 30분 스캔은 17개다.
   승률 ±5%p 신뢰구간에는 수백 건이 필요하다. 종목 수를 늘릴지, 기간을 기다릴지,
   평가 horizon을 바꿀지가 선택지다. 부수적으로: 30분 스캔 신호를 `signal_outcomes`에
   전량(하루 48 × 7종목) 적립할 필요가 있는지 — 읽는 쪽에서 어차피 하루 1건으로 접는다.
2. **성과 평가 프레임 자체** — win 정의(±2% 밴드), horizon(7/14/30일), 벤치마크 부재.
   `/signal-accuracy`의 `avg_return_pct`는 방향 보정이 없어 매도 신호가 맞을수록 내려간다 —
   지표 자체가 오해를 부른다. 현재 지표로는 "시장 대비 알파"를 말할 수 없다.
   7종목·표본 수백 건 규모에서 통계적으로 방어 가능한 평가 설계는 무엇인가.
3. **24 도구 + 8 에이전트 구성의 정당성** — 도구별·에이전트별 기여도가 측정되지 않은 상태에서
   구성 요소가 계속 늘어났다. 어떤 것을 줄여야 하는가. (IC 앙상블은 60일 표본 요건 미충족으로 균등가중 폴백 중)
4. **정성(LLM) 기여의 역할** — 현재는 정량 기여를 넘지 못하도록 상한이 걸려 있다.
   LLM 서술이 신호 품질에 실제로 기여하는지, 아니면 비용·지연만 추가하는지.
5. **live 전환 게이트 설계** — 무엇을 만족하면 paper→approval→live로 올릴 수 있는가.
   측정은 복구됐지만 게이트 기준("60일 hit-rate")이 어떤 표본·어떤 지표·어떤 하한을
   뜻하는지가 정의돼 있지 않다.
6. **아키텍처 정리 순서** — `webui.py` 분해 / 이중 호출 경로 단일화 / async 전환 /
   구조화 로깅 중 무엇을 먼저 해야 운영 리스크가 가장 빨리 줄어드는가.
7. **단일 노드 SPOF와 백업** — 현재 복구 절차·데이터 백업 정책이 없다. 개인 운영 규모에서
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
GEMINI_MODEL=gemini-2.0-flash / DEFAULT_LLM_PROVIDER
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
