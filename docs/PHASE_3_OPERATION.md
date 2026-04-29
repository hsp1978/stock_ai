# Phase 3 — Compose 운영 가이드

> testdev 측 빌드/기동 + Mac Studio Ollama 처리 결정.

## 1. testdev 측 (이 머신) — `dev` 프로파일

### 빌드
```bash
cd /home/ubuntu/stock_auto
docker compose --profile dev build
# tensorflow / lightgbm / xgboost 등 무거워 첫 빌드는 10~20분 가능
```

### 기동
```bash
docker compose --profile dev up -d
docker compose ps                 # 두 컨테이너 healthy 확인
docker compose logs -f agent-api  # 로그
```

### 검증 게이트
1. `curl http://localhost:8100/health` → `{"status":"healthy","ollama":"connected", ...}`
2. `curl http://localhost:8100/api/tags` 동일 (호스트 Ollama 호출 통과)
3. `http://localhost:8501` 브라우저로 webui 접근
4. 임의 종목 분석 1건 → 8개 에이전트 응답
5. Mac Studio 끈 상태(Ollama 종료) → 자동으로 RTX 5070 폴백

### 종료/롤백
```bash
docker compose --profile dev down       # 컨테이너 정리, 볼륨 보존
docker compose --profile dev down -v    # 볼륨까지 정리 (모델 캐시 손실 — 신중)
```

기존 native 실행 경로 (`python service.py`, `streamlit run webui.py`)는 그대로 작동. 컨테이너로 옮기는 건 선택.

## 2. Mac Studio 측 — 두 옵션 중 택1

### 옵션 A — **현재 Homebrew 그대로 유지** (권장)

이미 LaunchAgent (`com.ollama.setenv`) + Homebrew `homebrew.mxcl.ollama`가 :8080에서 안정 운영 중. 굳이 Docker로 갈아탈 이유가 없으면 그대로 둠. compose의 `mac` 프로파일은 무시.

### 옵션 B — **Docker로 전환**

Docker Desktop 설치 후:

```bash
# 1) Homebrew Ollama 종료 (포트 8080 충돌 방지)
brew services stop ollama
launchctl unload ~/Library/LaunchAgents/com.ollama.setenv.plist
launchctl unload ~/Library/LaunchAgents/homebrew.mxcl.ollama.plist 2>/dev/null

# 2) compose 기동 (compose.yaml 만 Mac Studio에 복사하거나 Tailscale로 마운트)
docker compose --profile mac up -d

# 3) 모델 적재 — 볼륨 ollama-heavy-models 에 새로 받음 (~50GB)
docker exec stock-auto-ollama-heavy ollama pull qwen2.5:32b
docker exec stock-auto-ollama-heavy ollama pull llama3:70b
docker exec stock-auto-ollama-heavy ollama pull gpt-oss:20b
```

**옵션 B의 단점**: ~50GB 재다운로드, Apple Silicon Metal GPU는 Docker에서 제한적 (CPU/Metal partial). 현재 운영을 깨뜨려가며 갈아탈 가치는 낮음.

**기본 권장: 옵션 A 유지.**

## 3. 알려진 제약 (운영 시 인지)

- **`network_mode: host`** 사용 → 컨테이너 격리 약함. 단일 사용자 dev 머신이라 OK. 멀티테넌트 환경이면 bridge + extra_hosts 로 전환 필요.
- **호스트 Ollama 의존** → testdev 호스트의 native Ollama가 죽으면 RTX 5070 라우팅 실패. systemd unit 으로 ollama 자동 기동 권장 (`systemctl status ollama` 확인).
- **컨테이너의 `_ROOT_ENV`** = `/app/.env` — 파일 마운트 안 함. compose의 `env_file: .env`로 환경변수 주입. Pydantic Settings는 환경변수 우선이라 작동.
- **시크릿** → `.env` 는 build 컨텍스트 제외 (`.dockerignore`), 런타임에만 env_file로 주입. 이미지에 시크릿 베이크되지 않음.

## 4. 빌드 결과 검증 (사용자 실행 후 보고 항목)

- [ ] `docker compose --profile dev build` 성공
- [ ] `docker compose --profile dev up -d` 두 컨테이너 healthy
- [ ] `curl http://localhost:8100/health` → ollama: connected
- [ ] webui 8501 응답
- [ ] Mac Studio 라우팅 한 건 성공 (Decision Maker → llama3:70b)
- [ ] Mac Studio 끈 상태 폴백 (Ollama 종료 후 분석 1건 → RTX 5070)
