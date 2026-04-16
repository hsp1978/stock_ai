# config.py + .env + watchlist 수정

---

## 1. chart_agent_service/config.py (수정)

**추가 위치:** `OPENAI_API_KEY` 아래에 3줄 추가

```python
# ═══ OpenAI 설정 (선택) ═══
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ═══ Gemini 설정 ═══
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
```

---

## 2. chart_agent_service/.env (신규)

**전체 내용:**
```
# ═══ Ollama ═══
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

# ═══ OpenAI (선택) ═══
OPENAI_API_KEY=

# ═══ Gemini ═══
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash

# ═══ 텔레그램 ═══
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ═══ 서비스 ═══
API_HOST=0.0.0.0
API_PORT=8100

# ═══ 스케줄러 ═══
SCAN_INTERVAL_MINUTES=30

# ═══ 관심 종목 ═══
# WebUI(stock_analyzer/watchlist.txt)에서 관리. 여기에 적지 않음.
WATCHLIST=

# ═══ 알림 임계값 ═══
BUY_THRESHOLD=5.0
SELL_THRESHOLD=-5.0
MIN_CONFIDENCE=5.0

# ═══ Mac Studio API (WebUI용) ═══
AGENT_API_URL=http://100.108.11.20:8100
```

---

## 3. stock_analyzer/watchlist.txt (수정)

**전체 내용:**
```
# 관심 종목 리스트 (한 줄에 하나, #은 주석)
# 빈 줄과 주석은 무시됨

NVDA
TSLA
NTLA
PLTR
MSFT
IBM
BAC
```

WebUI 사이드바에서 추가/삭제 관리됨. 유일한 watchlist 소스.

---

## 4. chart_agent_service/watchlist.txt (수정)

**전체 내용:**
```
# 관심 종목 리스트
# WebUI(stock_analyzer/watchlist.txt)에서 통합 관리됨.
# 이 파일에 직접 추가하지 마세요.
```

---

## 5. 패키지 설치

```bash
pip install google-generativeai
```
