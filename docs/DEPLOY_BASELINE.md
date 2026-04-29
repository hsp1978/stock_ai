# Deploy Baseline (Phase 0)

배포 리팩토링 시작 직전 스냅샷. 롤백 기준점.

- **Git tag**: `pre-deploy-refactor` @ `4b0d8ae`
- **작성일**: 2026-04-28

## 진입점

| 컴포넌트 | 시작 명령 | 포트 |
|---|---|---|
| Streamlit WebUI | `streamlit run stock_analyzer/webui.py` | 8501 |
| Chart Agent API | `python chart_agent_service/service.py` | 8000 |
| Setup 스크립트 | `bash setup_v2.sh` | — |

## .env 파일 3곳 (현 상태)

| 경로 | 키 |
|---|---|
| `chart_agent_service/.env` | `AGENT_API_URL`, `API_HOST`, `API_PORT`, `BUY_THRESHOLD`, `MIN_CONFIDENCE`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_NUM_PARALLEL`, `OPENAI_API_KEY`, `SCAN_INTERVAL_MINUTES`, `SCAN_PARALLEL_WORKERS`, `SELL_THRESHOLD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TRADING_STYLE`, `WATCHLIST` |
| `stock_analyzer/.env` | `DART_API_KEY`, `FMP_API_KEY`, `FRED_API_KEY`, `GOOGLE_API_KEY`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `dual_node.env` | `LLM_TIMEOUT_FAST`, `LLM_TIMEOUT_SLOW`, `MAC_STUDIO_IP`, `MAC_STUDIO_URL`, `OLLAMA_MAX_LOADED_MODELS`, `OLLAMA_NUM_PARALLEL` |

중복: `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (5개) — Phase 2에서 통합 대상.

## Tailscale 노드 매핑

| 호스트네임 | Tailnet IP | OS | 역할 | 상태 |
|---|---|---|---|---|
| `testdev` | 100.106.163.2 | linux | 메인 dev/agent | active (현 머신) |
| `hsptest-macstudio` | 100.108.11.20 | macOS | LLM heavy node | active, direct |

MagicDNS FQDN: `hsptest-macstudio.tailffa97.ts.net`

## 알려진 문제 (Phase 1 수정 대상)

1. **Mac Studio Ollama 11434 미응답** — Tailscale 네트워크는 살아있으나 Ollama가 Tailscale 인터페이스에 바인드되어 있지 않음 (기본값 127.0.0.1)
2. **`dual_node.env.example`이 port 8080 사용** — 구 SSH 터널 잔재 (`ssh -L 8080:localhost:11434`). Tailscale 직결 시 11434로 통일 가능
3. **localhost:11434 하드코딩 3곳** (Phase 2 코드 수정 대상):
   - `stock_analyzer/multi_agent.py:1434`
   - `chart_agent_service/service.py:597`
   - `setup_v2.sh:84`
4. **`stock_analyzer/dual_node_config.py:29` 폴백 버그** — `MAC_STUDIO_URL` 미설정 시 `localhost:8080`로 폴백, 실존하지 않는 포트

## 폴백 동작 검증 시나리오 (Phase별 게이트 통과 기준)

각 Phase 종료 시점에 다음을 확인:
1. webui 기동 성공 (config 검증 통과)
2. agent-api 기동 성공
3. 임의 종목 1건 분석 성공 (RTX 5070 단독)
4. Mac Studio 켠 상태에서 heavy 모델 라우팅 성공 (Phase 1 이후)
5. Mac Studio 끈 상태에서 자동 폴백 + 경고 로그 1줄

## 폐기/보존 정책

- **폐기 금지** (새 경로 검증 전): `setup_v2.sh`, `mac_studio_setup.sh`, `dual_node.env.legacy`, `*/.env.legacy`
- **Phase 4에서 정리**: 위 + 루트의 `*_FIX_REPORT.md`, `test_*.py`, `debug_*.py`

---

## Phase 1 결과 (2026-04-28)

| 항목 | 변경 |
|---|---|
| Tailscale | 이미 설치/활성 (양쪽 노드) — 작업 불필요 |
| Mac Studio Ollama | `0.0.0.0:8080` 바인드 (LaunchAgent 영구) |
| `dual_node.env*` | IP → `hsptest-macstudio` hostname |
| `dual_node_config.py:29` 폴백 | `localhost:8080` (부재) → `hsptest-macstudio:8080` |
| `dual_node_config.py:143` health check | `/health` (404) → `/api/tags` (200) |

**핵심 발견**: V1의 "Mac Studio 오프라인" 진짜 원인은 네트워크가 아니라 **`/health` endpoint가 Ollama에 없어서 health check가 항상 False 반환**하던 잠복 버그였음.

## Phase 2 결과 (2026-04-28)

| 항목 | 변경 |
|---|---|
| .env 통합 | 3곳 → 루트 `.env` (50개 키). 기존 3개는 `*.env.legacy`로 보존 |
| .env.example 보강 | `MAC_STUDIO_URL/IP`, `AGENT_API_URL`, `DEFAULT_LLM_PROVIDER`, `MULTI_AGENT_MAX_WORKERS` 추가 |
| Pydantic Settings | `chart_agent_service/config.py` 재작성. 60개 필드 + Literal/범위 검증 |
| 호환성 | 기존 `from config import X` 모두 그대로 동작 (module-level 상수 유지) |
| 기동 시점 검증 | 잘못된 `TRADING_STYLE`/`TRADING_MODE`/`ALPACA_DATA_FEED`/타입/범위는 즉시 ValidationError |
| 하드코딩 제거 | `multi_agent.py:1434`, `service.py:597`, `setup_v2.sh:84` 모두 `OLLAMA_BASE_URL` 환경변수 사용 |
| Dead key 정리 | `RTX_5070_URL`, `RTX_5070_MODEL`, `LLM_TIMEOUT_*`, `OLLAMA_MAX_LOADED_MODELS` (test_*.py만 사용) → root .env 제외, legacy에만 보존 |
| 의존성 | `pydantic-settings>=2.0` 양쪽 `requirements.txt` 추가 |

**검증 통과**: syntax (config/service/multi_agent/dual_node/setup_v2.sh), `multi_agent.py` import OK, Mac Studio 라우팅 정상 + 폴백 정상, Pydantic Literal/타입/범위 위반 시 즉시 fail.

**남은 운영 검증** (사용자 손):
- webui+agent-api 실제 기동 (uvicorn/streamlit 의존성 설치 후)
- 임의 종목 분석 1건
- Mac Studio 끈 상태 폴백 동작 (실 시나리오)

## Phase 3 결과 (2026-04-29)

### 코드 정리 (Phase 4 부분 선행)
- 루트 `.py` 38개 → 2개 (mcp_server, mcp_server_extended)
- 루트 `.md` 23개 → 1개 (README.md)
- `archive/scripts/` 36개, `archive/docs/` 22개, `archive/setup/` 2개

### Compose 인프라

| 파일 | 역할 |
|---|---|
| `compose.yaml` | dev (webui+agent-api) / mac (ollama-heavy 옵션) 두 프로파일 |
| `chart_agent_service/Dockerfile` | python:3.12-slim + uvicorn, 비루트 사용자 |
| `stock_analyzer/Dockerfile` | python:3.12-slim + streamlit, chart_agent_service 코드 포함 |
| `.dockerignore` | archive/ docs/ .env *.legacy 제외 — 시크릿/잡파일 빌드 컨텍스트 차단 |
| `docs/PHASE_3_OPERATION.md` | 빌드/기동/롤백 + Mac Studio 두 옵션 |

### 핵심 결정
- **호스트 Ollama 그대로 사용** (compose에 ollama-light 미포함). RTX 5070 native ollama 가 이미 운영 중이라 컨테이너로 갈아끼울 이득 없음.
- **`network_mode: host`** — Linux dev 머신이고 호스트 Ollama 호출이 빈번. bridge + extra_hosts 보다 단순.
- **Mac Studio**: 기본은 Homebrew 유지, Docker 전환은 옵션. 50GB 모델 재다운로드 부담 + Metal GPU 제약 때문에 권장 안 함.

### 검증 통과
- `docker compose --profile dev config --services` → agent-api, webui
- `docker compose --profile mac config --services` → ollama-heavy
- 시크릿은 `.dockerignore`로 빌드 컨텍스트에서 제외, env_file로만 런타임 주입

### 사고 보고
검증 중 `docker compose config` 출력이 `.env` 시크릿을 평문으로 chat에 펼침. 사용자가 OPENAI 등 키 회전 필요. 메모리에 마스킹 규칙 저장 (`feedback_secret_masking.md`).

---

## Phase 4 결과 (2026-04-29)

### 운영 검증 통과
- agent-api 컨테이너 healthy + `/health`: `{"ollama":"connected", ...}`
- webui 컨테이너 HTTP 200 (8501)
- 컨테이너 내부에서도 Tailscale MagicDNS 해석 + Mac Studio 라우팅 정상
- `is_mac_studio_available() = True` (Phase 1 health check fix가 컨테이너에서도 효과)

### 최종 정리
| 작업 | 상세 |
|---|---|
| systemd unit 비활성화 | `stock-webui.service`, `stock-bot.service` `disable --now` |
| OpenAI/Google 키 회전 | 사용자 진행 완료 (DART/FMP/FRED는 보류 — 기존 키 유지) |
| `*.env.legacy` 삭제 | 3개 (chart_agent_service, stock_analyzer, dual_node) |
| 중복 .env.example 삭제 | 3개 (각 디렉토리 + dual_node.env.example) — 루트 단일 source |
| ZeroDivisionError fix | `service.py:438` watchlist 빈 케이스 가드 |
| `setup_v2.sh` archive | native 운영 도구 → `archive/setup/` (compose가 대체) |

### 최종 루트 구성
```
.env, .env.example          # single source of truth
README.md                   # 메인 (압축은 다음 작업)
compose.yaml                # dev / mac 프로파일
.dockerignore               # 시크릿/잡파일 차단
mcp_server.py, mcp_server_extended.py    # active MCP
chart_agent_service/, stock_analyzer/    # 두 코어 패키지
archive/scripts·docs·setup/ # 60+ 파일 보존
docs/                       # DEPLOY_BASELINE.md, PHASE_1_MAC_STUDIO.md, PHASE_3_OPERATION.md, ...
```

### 남은 선택 (요청 시 진행)
- README 압축 — 큰 작업, 사용자 동의 필요
- `archive/scripts/` 안의 dead test 추가 분류
- 이미지 크기 최적화 (현재 ~4GB · multi-stage build, slim 의존성)
- Makefile 한 줄 명령 (`make up/down/logs/ps`)
- compose 기반 systemd unit (재부팅 시 자동 기동)
