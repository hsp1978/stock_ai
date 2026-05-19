# CLAUDE.md — Stock AI Analysis System V2

> 이 파일은 Claude Code가 본 프로젝트에서 작업할 때 매 세션 자동 로드되는 영구 컨텍스트다.
> 변경 시 commit 메시지에 `[claude-md]` prefix 사용. 컨텍스트 토큰 비용을 고려해 간결하게 유지한다.

---

## 1. 프로젝트 개요

**시스템명**: Stock AI Analysis System V2
**목적**: 한국·미국 주식 워치리스트(현재 7종목)에 대한 매수/매도/관망 신호 + 진입가·손절·익절·수량 산출. 1일 1회 EOD 분석.
**사용자**: 운영자 1명 (개인 투자자, paper trading 단계).
**거래 모드**: `TRADING_MODE: Literal["paper", "dry_run", "approval", "live"]`, 기본 `paper`.

**핵심 구조**:
- 8 LLM 에이전트 (Gemini 4 + Ollama 4)
- 16 분석 도구 (`chart_agent_service/analysis_tools.py`)
- 5 ML 앙상블 (RandomForest / GradientBoosting / LightGBM / XGBoost / LSTM)
- EnhancedDecisionMaker (충돌 해결 + 평활화)

---

## 2. 인프라 토폴로지

```
Tailscale Tailnet (testffa97.ts.net)
├─ testdev (Linux Ubuntu 24, RTX 5070 12GB)
│  ├─ webui (Streamlit:8501, 2.06GB 이미지)
│  ├─ agent-api (FastAPI:8100, 7.76GB 이미지)
│  └─ Ollama native :11434 (qwen3:14b-q4_K_M)
└─ hsptest-macstudio (macOS M1 Max 32GB)
   └─ Ollama Homebrew :8080 (qwen2.5:32b, gpt-oss:20b)
```

- Docker Compose `--profile dev` 사용. `network_mode: host` (단일 사용자 dev 전제).
- Mac Studio 다운 시 RTX 5070 단독 폴백 (`dual_node_config.py` 자동 검출).
- 외부 의존: yfinance, FDR, DART, FRED, Google News, Gemini API, OpenAI API.

---

## 3. 디렉토리 구조 (핵심만)

```
stock_auto/
├ compose.yaml                          # dev/mac 프로파일
├ .env / .env.example                   # 60+ 키 SSOT (Pydantic Settings)
├ Makefile                              # 14 운영 타깃
├ CLAUDE.md                             # 본 파일
├ docs/
│  ├ CONSULTING_BRIEF.md                # 도메인 컨설팅 (분석/리스크/데이터)
│  ├ ARCHITECTURE_BRIEF.md              # 시스템 아키텍처 컨설팅
│  ├ BACKTEST_ASSUMPTIONS.md            # Slippage/수수료/rf 가정
│  └ USER_MANUAL.md                     # WebUI 사용법
├ chart_agent_service/                  # FastAPI agent-api
│  ├ service.py (19 endpoints)
│  ├ config.py  (Pydantic Settings 60+ field)
│  ├ analysis_tools.py (16 tools)
│  ├ ml_predictor.py / backtest_engine.py
│  ├ paper_trader.py / signal_tracker.py
│  ├ risk_management.py / portfolio_optimizer.py
│  ├ data_collector.py / news_analyzer.py / macro_context.py
│  ├ db.py (SQLite WAL)
│  └ data_sources/  brokers/  execution/
├ stock_analyzer/                       # Streamlit webui + scanner
│  ├ webui.py (5,136 lines, 리팩터 대상)
│  ├ multi_agent.py (8 agents Orchestrator)
│  ├ enhanced_decision_maker.py
│  ├ dual_node_config.py (라우팅/폴백)
│  ├ local_engine.py (in-proc / HTTP 분기)
│  └ watchlist.txt
└ tests/                                # unit/ 18 files (P2 정비 완료, CI 미구축)
```

---

## 4. 운영 명령어

```bash
# 기동/종료
docker compose --profile dev up -d
docker compose --profile dev down

# 헬스 확인
curl -s http://localhost:8100/health | jq
open http://localhost:8501

# Mac Studio 폴백 검증
python -c "import sys; sys.path.insert(0,'stock_analyzer'); \
  from dual_node_config import is_mac_studio_available; \
  print(is_mac_studio_available())"

# 이미지 크기
docker images stock-auto/{webui,agent-api}

# 로그 (로테이션 없음, 주의)
tail -f chart_agent_service/service.log

# Makefile 타깃
make help
```

---

## 5. 코딩 컨벤션

### 5.1 Python
- **버전**: Python 3.12 고정. 3.13 호환성 미확인.
- **타입 힌트**: 신규 코드는 반드시 타입 힌트.
- **포매팅**: `ruff format`. 라인 길이 100자.
- **린트**: `ruff check`. 무시 규칙은 `pyproject.toml`에 명시.
- **import 순서**: stdlib → 외부 → 내부. `isort` 호환.
- **주석 언어**: 한국어 OK. 단 함수 docstring은 영어 권장 (LLM 호출 시 토큰 비용).

### 5.2 FastAPI
- 핸들러: 현재 모두 `def` (sync). blocking I/O 직접 호출.
- 향후 async 전환은 `httpx.AsyncClient`로 단계적 진행.
- 응답 모델: Pydantic `BaseModel` 필수.

### 5.3 Pydantic
- Settings: `pydantic-settings ≥ 2.0`. `Literal`, `Field(ge=..., le=...)` 적극 사용.
- DTO: `BaseModel` + 가능하면 `frozen=True`.

### 5.4 LLM 호출
- **신규 호출**: 반드시 LiteLLM Router 사용 (직접 SDK 호출 금지).
- **응답 형식**: Pydantic schema enforce. 자유 텍스트 응답 금지.
- **타임아웃**: 개별 호출 30s, 에이전트 전체 90s.
- **재시도**: `tenacity` + `circuitbreaker`.

### 5.5 데이터
- **OHLCV 캐시**: TTL 메타 필수. `fetched_at`, `latest_bar_date`, `source` 기록.
- **재시도**: 외부 API 호출은 `tenacity.retry(stop_after_attempt(3), wait_exponential)`.
- **다중 소스**: 한국 `pykrx → FDR → yfinance`, 미국 `yfinance → FDR`.
- **휴장일**: `pandas_market_calendars` 사용. XKRX, NYSE 코드.
- **timezone**: 내부 저장은 UTC aware. 시장 코드 명시.

### 5.6 테스트
- **위치**: `tests/{unit,integration,e2e}/`.
- **명령**: `pytest -x --cov=. --cov-report=term-missing`.
- **LLM mock**: `respx` 또는 `pytest-mock`. 실제 API 호출 금지.
- **fixture**: OHLCV 샘플은 `tests/fixtures/ohlcv/`.

### 5.7 커밋 메시지
```
<type>(<scope>): <subject>

<body>

```
- type: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`
- scope: `kill-switch`, `signal-agg`, `cache`, `mfi`, `regime`, `agent-group`, `llm-router`, ...

---

## 6. 절대 하지 말 것 (Critical Don'ts)

1. **`.env` 파일을 절대 git에 커밋하지 말 것.** `.gitignore`, `.dockerignore`에 이미 등록됨.
2. **API 키를 코드·로그·docstring에 노출하지 말 것.** 디버깅 시 `printenv`, `docker config` 출력 시 키 부분 마스킹.
3. **`paper_trading_state.json`을 직접 편집하지 말 것.** API 또는 SQLite 마이그레이션 후 DB로 처리.
4. **백테스트 결과의 Sharpe·수익률을 그대로 신뢰하지 말 것.** DSR + PBO 보정 필수.
5. **새 LLM provider 직접 SDK 호출 추가하지 말 것.** LiteLLM Router 통한 등록만 허용.
6. **`from X import *` 금지.**
7. **차트 PNG 무한 누적 방치 금지.** 30일 이상 파일 자동 정리 cron 유지.
8. **DB 직접 SQL 변경 금지.** Alembic migration 도입 후 마이그레이션 스크립트로만.
9. **README 라우팅 표 수정 시 `dual_node_config.py` 코드와 일치 확인.**
10. **5,136 라인 `webui.py`를 한 번에 분리하지 말 것.** P2 단계에서 페이지 단위 점진 분리.

---

## 7. 통합 로드맵

### P0+P1+P2 — 완료 (2026-05-14)
12 단계 EXECUTION_PLAN + P2 (F-Score/Z-Score, VaR/CVaR, DSR+PBO, LLM calibration, IC ensemble, pykrx 외국인/공매도, DART) 모두 머지. tests/ 18 files.

### P3 — 데이터 누적 후 재검토 (선택)
- HMM regime detector
- Contextual bandit 에이전트 가중치
- Black-Litterman 포트폴리오 비중
- ML 라벨 회귀화
- CPCV 백테스트

현재 단계: paper trading 운영 + signal_outcomes 누적 (60일 hit-rate 검증).

---

## 8. 외부 의존성 정책

| 라이브러리 | 용도 | 도입 단계 |
|---|---|---|
| `litellm` | LLM provider 통합 | Step 9 |
| `tenacity` | 재시도 | Step 3 |
| `circuitbreaker` | 회로 차단 | Step 9 |
| `pandas_market_calendars` | 휴장일 | Step 11 |
| `pykrx` | 한국 KRX 데이터 | P2 |
| `OpenDartReader` | DART 공시 | P2 |
| `hmmlearn` | HMM regime | P3 |
| `PyPortfolioOpt` | Black-Litterman | P3 |
| `prometheus-fastapi-instrumentator` | 메트릭 | 시스템 보고서 P1 |
| `respx` | HTTP mocking | 테스트 도입 시 |

신규 의존성 추가 시:
1. `pyproject.toml` 명시
2. 핀 버전 또는 범위 사용
3. `requirements*.txt` 동기화
4. Docker 이미지 재빌드 영향 평가

---

## 9. 의사결정 가이드

작업 중 다음 trade-off 발생 시 이 우선순위로 결정:

1. **데이터 무결성 > 기능 추가**: stale 데이터 위험 vs 신규 지표 → freshness 먼저.
2. **측정 가능성 > 최적화**: signal_outcomes 없는 상태에서 ML 튜닝 금지.
3. **명시적 가정 > 암묵적 가정**: 백테스트 슬리피지·수수료·rf 명시 후 결과 보고.
4. **단순 fallback > 정교 합의**: 분산 합의 알고리즘 도입보다 단순 weighted majority 우선.
5. **로컬 운영 비용 > 클라우드 정교함**: NATS/Kafka 등 메시지 브로커는 현재 규모(7종목, 1사용자)에서 보류.
6. **paper trading 검증 60일 > 즉시 live 전환**: 새 도구 추가 후 paper 운영 60일 hit-rate 검증 통과 시에만 live 후보.

---

## 10. 작업 시작 절차 (Claude Code 사용 시)

새 세션 시작 시:
1. `git pull origin main`
2. `git checkout -b feature/<scope>` (변경 단위별 브랜치)
3. 변경 → 테스트 → 커밋 → PR

세션이 길어지면 `/compact`로 컨텍스트 축소. 작업 단위 완료 후 `/clear` 권장.

PR 머지 시:
1. `pytest` 통과 확인 (CI 부재 — 수동)
2. `docker compose --profile dev up -d` 재기동 후 `/health` 정상 확인

---

## 11. 알려진 안티패턴

| # | 안티패턴 | 처리 단계 |
|---|---|---|
| 1 | God file (`webui.py` 5,136 라인) | P2 |
| 2 | Dual call path (in-proc + HTTP) | P2 (HTTP 단일화) |
| 3 | `print()` 기반 로깅 | 시스템 P1 |
| 4 | `paper_state.json` 무락 | 시스템 P0 |
| 5 | 양방향 sys.path 주입 | P2 |
| 6 | 모델 버전 미핀 (`qwen3:14b-q4_K_M`) | P2 |
| 7 | 매직 포트 8080 (3곳 흩어짐) | P2 |
| 8 | CI 부재 (tests/ 18 files 존재) | P2 후속 |
| 9 | 차트 PNG 무한 누적 | 시스템 P1 |
| 10 | README ↔ 코드 라우팅 불일치 | P2 |
| 11 | 프롬프트 인젝션 표면 | Step 9 (structured output) |

---

## 12. 참조 문서

- `docs/CONSULTING_BRIEF.md` — 사용자 작성 도메인 브리프
- `docs/ARCHITECTURE_BRIEF.md` — 사용자 작성 시스템 브리프
- `docs/BACKTEST_ASSUMPTIONS.md` — Slippage/수수료/rf 가정 (Step 10)
- `docs/USER_MANUAL.md` — WebUI 사용법
- `docs/PHASE_1_MAC_STUDIO.md` / `PHASE_3_OPERATION.md` — 듀얼 노드 셋업/운영

---

**문서 끝.** 변경 사항은 `git commit -m "[claude-md] ..."`로 기록.

