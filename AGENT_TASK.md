# Mac Studio 에이전트 서버 확장 지시서

## 현재 아키텍처

```
[Ubuntu 서버 (WebUI)]                    [Mac Studio (Agent)]
stock_analyzer/                          chart_agent_service/
  webui.py (Streamlit)                     service.py (FastAPI :8100)
  local_engine.py ──import──→              analysis_tools.py (16개 도구)
                                           data_collector.py (yfinance)
                                           Ollama (llama3.1:8b :11434)
```

- Ubuntu 서버의 `local_engine.py`가 `chart_agent_service/` 모듈을 직접 import하여 분석 실행
- Mac Studio의 `service.py`(FastAPI)는 현재 **독립 실행 가능**하나, WebUI에서는 직접 사용하지 않음
- Ollama는 Mac Studio에서 실행 중 (OLLAMA_BASE_URL=http://100.108.11.20:11434)

---

## 요청 사항: 에이전트 서버에 새 기능 추가

Mac Studio의 `chart_agent_service/service.py`에 아래 API 엔드포인트를 추가하여,
Ubuntu WebUI에서 HTTP로 호출할 수 있게 합니다.

### 1. 뉴스 수집 API

**엔드포인트**: `GET /news/{ticker}`

**기능**:
- 해당 종목 관련 최신 뉴스 수집 (최근 7일)
- 뉴스 소스: Google News RSS, Yahoo Finance, finviz 등 무료 소스 활용
- 각 뉴스에 대해 LLM(Ollama)으로 감성 분석 (bullish/bearish/neutral + 점수)

**응답 형식**:
```json
{
  "ticker": "NVDA",
  "news_count": 10,
  "overall_sentiment": "bullish",
  "overall_score": 3.2,
  "articles": [
    {
      "title": "NVIDIA Announces New AI Chip",
      "source": "Reuters",
      "published": "2025-04-09T14:30:00",
      "url": "https://...",
      "summary": "뉴스 요약 (한국어, 2~3문장)",
      "sentiment": "bullish",
      "score": 7.0,
      "keywords": ["AI", "GPU", "신제품"]
    }
  ],
  "analyzed_at": "2025-04-10T10:00:00"
}
```

**구현 참고**:
```python
# Google News RSS 예시
import feedparser
feed = feedparser.parse(f"https://news.google.com/rss/search?q={ticker}+stock&hl=en&gl=US&ceid=US:en")

# Yahoo Finance 뉴스
import yfinance as yf
t = yf.Ticker(ticker)
news = t.news  # 최근 뉴스 리스트

# LLM 감성 분석 (기존 Ollama 연동 활용)
prompt = f"""다음 뉴스 제목과 내용을 분석하여 JSON으로 응답하라:
- sentiment: bullish / bearish / neutral
- score: -10 ~ +10
- summary: 한국어 2~3문장 요약
- keywords: 핵심 키워드 3개

뉴스: {article_text}"""
```

**필요 패키지**: `feedparser` (pip install feedparser)

---

### 2. 차트 패턴 인식 API

**엔드포인트**: `GET /chart-pattern/{ticker}`

**기능**:
- 기존 `generate_agent_chart()`로 차트 이미지 생성
- 차트 이미지를 Ollama Vision 또는 별도 패턴 인식 로직으로 분석
- 감지할 패턴: 헤드앤숄더, 더블탑/바텀, 삼각수렴, 채널, 깃발, 쐐기, 컵위드핸들

**응답 형식**:
```json
{
  "ticker": "NVDA",
  "patterns": [
    {
      "name": "ascending_triangle",
      "name_kr": "상승 삼각형",
      "confidence": 0.75,
      "direction": "bullish",
      "description": "저점이 높아지며 수평 저항선에 수렴 중. 상방 돌파 시 강한 상승 기대.",
      "target_price": 145.00,
      "invalidation_price": 128.50
    }
  ],
  "chart_path": "/path/to/chart.png",
  "analyzed_at": "2025-04-10T10:00:00"
}
```

**구현 방법** (2가지 중 택 1 또는 병행):

방법 A — **알고리즘 기반** (권장, Ollama 불필요):
```python
# scipy.signal로 로컬 극값 탐지 → 패턴 매칭
from scipy.signal import argrelextrema

def detect_patterns(df):
    highs = argrelextrema(df['High'].values, np.greater, order=5)[0]
    lows = argrelextrema(df['Low'].values, np.less, order=5)[0]
    # 더블탑: 최근 2개 고점이 유사 가격 + 사이에 저점
    # 헤드앤숄더: 3개 고점 중 가운데가 최고
    # 삼각수렴: 고점 하락 + 저점 상승 추세선
    ...
```

방법 B — **LLM Vision 기반** (Ollama multimodal 모델 필요):
```python
# llava 등 Vision 모델 사용
import base64
with open(chart_path, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

resp = httpx.post(f"{OLLAMA_BASE_URL}/api/generate", json={
    "model": "llava",  # Vision 지원 모델
    "prompt": "이 차트에서 기술적 패턴을 식별하라...",
    "images": [img_b64],
    "stream": False,
})
```

---

### 3. 섹터/산업 비교 API

**엔드포인트**: `GET /sector/{ticker}`

**기능**:
- 종목의 섹터/산업 내 상대 위치 분석
- 동종 업계 대비 밸류에이션, 모멘텀, 변동성 비교

**응답 형식**:
```json
{
  "ticker": "NVDA",
  "sector": "Technology",
  "industry": "Semiconductors",
  "peers": ["AMD", "INTC", "AVGO", "QCOM"],
  "comparison": {
    "pe_ratio": {"NVDA": 45.2, "sector_avg": 28.1, "percentile": 85},
    "momentum_1m": {"NVDA": 12.3, "sector_avg": 5.1, "percentile": 78},
    "beta": {"NVDA": 1.65, "sector_avg": 1.2, "percentile": 72}
  },
  "sector_trend": "outperforming",
  "relative_strength": 1.35
}
```

---

### 4. 매크로 경제 컨텍스트 API

**엔드포인트**: `GET /macro`

**기능**:
- 주요 매크로 지표 수집 (VIX, 국채 수익률, DXY, 유가 등)
- 시장 전반 분위기 판단

**응답 형식**:
```json
{
  "vix": {"value": 18.5, "trend": "falling", "signal": "risk_on"},
  "us10y": {"value": 4.32, "trend": "rising", "signal": "headwind"},
  "dxy": {"value": 104.2, "trend": "stable", "signal": "neutral"},
  "oil_wti": {"value": 78.5, "trend": "rising", "signal": "inflationary"},
  "sp500_trend": "bullish",
  "market_regime": "risk_on",
  "summary": "VIX 하락, 국채 수익률 상승 속 주식 시장 강세 유지. 기술주 유리 환경.",
  "updated_at": "2025-04-10T10:00:00"
}
```

**구현 참고**:
```python
# yfinance로 매크로 지표 수집
vix = yf.Ticker("^VIX").history(period="1mo")
us10y = yf.Ticker("^TNX").history(period="1mo")
dxy = yf.Ticker("DX-Y.NYB").history(period="1mo")
oil = yf.Ticker("CL=F").history(period="1mo")
```

---

## Ubuntu WebUI 연동 계획

에이전트 서버에 위 API가 추가되면, Ubuntu 측에서:

### local_engine.py에 추가할 함수
```python
def engine_fetch_news(ticker: str) -> dict:
    """에이전트 서버에서 뉴스 수집"""
    resp = httpx.get(f"{AGENT_API_URL}/news/{ticker}", timeout=60)
    return resp.json()

def engine_chart_pattern(ticker: str) -> dict:
    resp = httpx.get(f"{AGENT_API_URL}/chart-pattern/{ticker}", timeout=60)
    return resp.json()

def engine_sector_compare(ticker: str) -> dict:
    resp = httpx.get(f"{AGENT_API_URL}/sector/{ticker}", timeout=60)
    return resp.json()

def engine_macro_context() -> dict:
    resp = httpx.get(f"{AGENT_API_URL}/macro", timeout=30)
    return resp.json()
```

### webui.py Report 페이지에 추가할 탭
- **News Sentiment** 탭: 뉴스 목록 + 감성 차트
- **Chart Patterns** 탭: 감지된 패턴 + 차트 이미지
- **Sector Compare** 탭: 동종업계 비교 레이더 차트
- **Macro Context** 탭: 매크로 환경 대시보드

### AI 종합 리포트에 통합
`engine_interpret_full_report()`의 프롬프트에 뉴스 감성, 차트 패턴, 섹터 비교, 매크로 데이터를 추가하여 더 정확한 AI 분석 생성.

---

## 에이전트 서버 설정 사항

### 1. Ollama 외부 접근 허용 (아직 미완료 시)
```bash
launchctl setenv OLLAMA_HOST 0.0.0.0
brew services restart ollama
```

### 2. 추가 패키지 설치
```bash
pip install feedparser
```

### 3. 환경 변수 (.env)
```
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
```

### 4. API 서버 실행
```bash
cd chart_agent_service
python service.py  # 또는 uvicorn service:app --host 0.0.0.0 --port 8100
```

---

## 통신 규격

| 항목 | 값 |
|------|-----|
| 에이전트 서버 주소 | `http://100.108.11.20:8100` |
| 프로토콜 | HTTP REST (JSON) |
| 인증 | 없음 (내부 네트워크) |
| 타임아웃 | 뉴스 60s, 차트패턴 60s, 섹터 30s, 매크로 15s |
| 에러 응답 | `{"error": "메시지"}` + HTTP 4xx/5xx |

## 구현 우선순위

1. **뉴스 수집 + 감성 분석** — 매매 판단에 가장 직접적 영향
2. **매크로 경제 컨텍스트** — 시장 전반 분위기 파악
3. **차트 패턴 인식** — 알고리즘 방식 우선, Vision은 선택
4. **섹터 비교** — 상대 밸류에이션 참고
