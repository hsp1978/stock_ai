# testdev 서버 배포 가이드 (2026-04-13)

## 문서 구성

| 파일 | 내용 |
|------|------|
| `DEPLOY_01_summary.md` | 변경 요약 + 적용 순서 (이 파일) |
| `DEPLOY_02_local_engine.md` | local_engine.py 전체 코드 |
| `DEPLOY_03_webui.md` | webui.py 수정 3곳 |
| `DEPLOY_04_config_env.md` | config.py + .env + watchlist |

---

## 변경 요약

| # | 파일 | 작업 | 설명 |
|---|------|------|------|
| 1 | `stock_analyzer/local_engine.py` | **신규 생성** | WebUI <-> chart_agent_service 브릿지 모듈 (24개 엔진 함수 + Multi-LLM) |
| 2 | `stock_analyzer/webui.py` | **수정** | local_engine 연동 (3곳 변경) |
| 3 | `stock_analyzer/watchlist.txt` | **수정** | 7종목 활성화 (WebUI에서 관리하는 단일 소스) |
| 4 | `chart_agent_service/config.py` | **수정** | Gemini 설정 2줄 추가 |
| 5 | `chart_agent_service/.env` | **신규 생성** | 환경변수 파일 |
| 6 | `chart_agent_service/watchlist.txt` | **수정** | 비움 (WebUI 단일 관리로 전환) |

추가 패키지: `pip install google-generativeai`

---

## 적용 순서

```bash
# 1) 파일 배포 (scp 또는 git)
# 2) 패키지 설치
cd ~/stock_auto/stock_ai
source venv/bin/activate   # 또는 해당 환경
pip install google-generativeai

# 3) .env 파일 API 키 설정 (필요 시)
vi chart_agent_service/.env

# 4) Streamlit 재시작
# (systemctl restart 또는 프로세스 재시작)

# 5) 검증
python -c "from local_engine import engine_health; print(engine_health())"
```

---

## 아키텍처 변경 전/후

**변경 전:**
```
WebUI (Streamlit)  --HTTP-->  Mac Studio FastAPI (:8100)
```

**변경 후:**
```
WebUI (Streamlit)
  +- local_engine.py (직접 import)
       +- chart_agent_service 모듈 직접 호출
       +- 뉴스/차트패턴/섹터/매크로 (직접 import + HTTP fallback)
       +- Multi-LLM: Gemini -> Ollama -> OpenAI
```

local_engine.py가 없으면 자동으로 기존 HTTP 모드로 fallback됨.

---

## watchlist 관리 정책

- **단일 소스:** `stock_analyzer/watchlist.txt`
- **관리 방법:** WebUI 사이드바에서 추가/삭제
- `.env`의 `WATCHLIST=` 비워둠
- `chart_agent_service/watchlist.txt` 비워둠
