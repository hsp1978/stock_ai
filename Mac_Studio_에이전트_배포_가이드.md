# Mac Studio 차트 분석 에이전트 배포 가이드

## 환경 정보

| 항목 | testdev (Ubuntu) | Mac Studio (M1 Max) |
|------|-----------------|---------------------|
| 역할 | 기존 분석 시스템, API 클라이언트 | 에이전트 서비스, LLM 분석 |
| IP | - | 100.108.11.20 (Tailscale) |
| 포트 | - | 8100 |
| 프로젝트 경로 | `~/stock_auto/stock_analyzer/` | `~/stock_auto/chart_agent_service/` |
| LLM | Ollama (llama3.1:8b) | Ollama 설치됨 + GPT API 가능 |

---

## 아키텍처

```
[Mac Studio (M1 Max)]                        [testdev 서버 (Ubuntu)]
  100.108.11.20:8100                            Tailscale 연결
┌───────────────────────────┐            ┌───────────────────────────┐
│ chart_agent_service/      │            │ stock_analyzer/            │
│  ├ service.py (FastAPI)   │◄─── API ───│  ├ agent_client.py        │
│  ├ analysis_tools.py      │            │  ├ main.py                │
│  ├ data_collector.py      │            │  └ ...                    │
│  ├ config.py              │            └───────────────────────────┘
│  └ .env                   │
│                           │
│ 30분마다 자동 스캔        │
│ 12개 기법 분석            │
│ Ollama/GPT LLM 종합 판단 │
│ 기준치 도달 시 ──────────────→ 텔레그램 알림
└───────────────────────────┘
```

### 동작 흐름

1. Mac Studio에서 30분마다 watchlist 전체를 12개 기법으로 분석
2. Ollama(또는 GPT)가 분석 결과를 종합하여 매수/매도/관망 판단
3. 종합 점수가 임계값을 넘으면 텔레그램으로 즉시 알림
4. testdev에서 `agent_client.py`로 언제든 결과 조회 가능

---

## 1단계: testdev에서 Mac Studio로 파일 전송

```bash
# testdev에서 실행
scp -r ~/stock_auto/chart_agent_service/ 사용자명@100.108.11.20:~/stock_auto/

# 또는 rsync (이후 동기화 시 유용)
rsync -avz ~/stock_auto/chart_agent_service/ 사용자명@100.108.11.20:~/stock_auto/chart_agent_service/
```

전송 확인:
```bash
ssh 사용자명@100.108.11.20 "ls ~/stock_auto/chart_agent_service/"
# service.py, analysis_tools.py, data_collector.py, config.py 등이 보이면 정상
```

---

## 2단계: Mac Studio에서 설치

Mac Studio 터미널에서 진행:

### 2-1. Python 환경 구성

```bash
cd ~/stock_auto/chart_agent_service

# 가상환경 생성
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

### 2-2. Ollama 모델 확인

```bash
# 설치된 모델 확인
ollama list

# llama3.1:8b 없으면 설치
ollama pull llama3.1:8b

# 동작 테스트
curl -s http://localhost:11434/api/tags | python3 -m json.tool
```

M1 Max는 GPU 메모리가 충분하므로 더 큰 모델도 가능:
```bash
# 더 정확한 분석을 원하면 (16GB+ 메모리 필요)
ollama pull llama3.1:70b-instruct-q4_0
# .env에서 OLLAMA_MODEL=llama3.1:70b-instruct-q4_0 으로 변경
```

### 2-3. 환경 설정

```bash
cp .env.example .env
nano .env   # 또는 vim .env
```

`.env` 파일 내용:

```env
# ═══ Ollama ═══
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

# ═══ OpenAI (선택 - GPT 분석 시) ═══
OPENAI_API_KEY=sk-xxxxx

# ═══ 텔레그램 (testdev와 동일한 봇) ═══
TELEGRAM_BOT_TOKEN=8568095277:AAEGOAjtILyk-wR5n0GsBulam-PoDbu0Ctc
TELEGRAM_CHAT_ID=여기에_chat_id_입력

# ═══ 서비스 ═══
API_HOST=0.0.0.0
API_PORT=8100

# ═══ 스캔 주기 (분) ═══
SCAN_INTERVAL_MINUTES=30

# ═══ 관심 종목 ═══
WATCHLIST=AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA

# ═══ 알림 임계값 ═══
BUY_THRESHOLD=3.0
SELL_THRESHOLD=-3.0
MIN_CONFIDENCE=5.0
```

---

## 3단계: Mac Studio 서비스 실행

### 포그라운드 실행 (테스트용)

```bash
cd ~/stock_auto/chart_agent_service
source venv/bin/activate
python service.py
```

정상 시 출력:
```
============================================================
  차트 분석 에이전트 서비스 시작
  API: http://0.0.0.0:8100
  모델: llama3.1:8b
  스캔 주기: 30분
  종목: AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA
  매수 임계: ≥3.0, 매도 임계: ≤-3.0
============================================================

[스케줄러] 30분 간격 스캔 등록 완료
INFO:     Uvicorn running on http://0.0.0.0:8100
```

### 백그라운드 실행 (운영용)

방법 A - nohup (간편):
```bash
cd ~/stock_auto/chart_agent_service
source venv/bin/activate
nohup python service.py > output/service.log 2>&1 &
echo $! > service.pid

# 로그 확인
tail -f output/service.log

# 종료
kill $(cat service.pid)
```

방법 B - launchd (macOS 서비스 등록, 재부팅 시 자동 시작):
```bash
sudo tee /Library/LaunchDaemons/com.stockagent.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.stockagent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/사용자명/stock_auto/chart_agent_service/venv/bin/python</string>
        <string>/Users/사용자명/stock_auto/chart_agent_service/service.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/사용자명/stock_auto/chart_agent_service</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/사용자명/stock_auto/chart_agent_service/output/service.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/사용자명/stock_auto/chart_agent_service/output/service_error.log</string>
</dict>
</plist>
EOF

# 서비스 시작
sudo launchctl load /Library/LaunchDaemons/com.stockagent.plist

# 상태 확인
sudo launchctl list | grep stockagent

# 서비스 중지
sudo launchctl unload /Library/LaunchDaemons/com.stockagent.plist
```

---

## 4단계: testdev에서 연동 확인

### 4-1. .env 설정 (이미 완료)

```bash
# testdev의 stock_analyzer/.env에 추가 (이미 설정됨)
AGENT_API_URL=http://100.108.11.20:8100
```

### 4-2. 연결 테스트

```bash
cd ~/stock_auto/stock_analyzer
source ../venv/bin/activate

# 1. 서비스 상태 확인
python agent_client.py --health

# 2. 전체 결과 조회
python agent_client.py

# 3. 특정 종목 상세
python agent_client.py AAPL

# 4. 즉시 분석 요청 (1~3분 소요)
python agent_client.py --scan NVDA

# 5. 전체 watchlist 스캔 요청
python agent_client.py --scan-all

# 6. URL 직접 지정 (테스트용)
python agent_client.py --url http://100.108.11.20:8100 --health
```

### 4-3. curl로 직접 API 호출

```bash
# 상태 확인
curl -s http://100.108.11.20:8100/health | python3 -m json.tool

# 전체 결과
curl -s http://100.108.11.20:8100/results | python3 -m json.tool

# 특정 종목
curl -s http://100.108.11.20:8100/results/AAPL | python3 -m json.tool

# 즉시 분석 (POST)
curl -s -X POST http://100.108.11.20:8100/scan/TSLA | python3 -m json.tool

# 차트 이미지 다운로드
curl -o AAPL_chart.png http://100.108.11.20:8100/chart/AAPL
```

---

## API 엔드포인트

| 메서드 | 경로 | 설명 | 예시 |
|--------|------|------|------|
| GET | `/` | 서비스 상태 요약 | 모델, 종목, 임계값 등 |
| GET | `/health` | 헬스 체크 | Ollama 연결 상태 포함 |
| GET | `/results` | 전체 최신 결과 | 모든 종목 신호/점수 |
| GET | `/results/{ticker}` | 특정 종목 상세 | 12개 기법별 결과 포함 |
| POST | `/scan/{ticker}` | 단일 종목 즉시 분석 | 1~3분 소요 |
| POST | `/scan` | 전체 watchlist 스캔 | 종목 수 × 1~3분 |
| GET | `/chart/{ticker}` | 차트 이미지 (PNG) | 가격 + 12개 기법 스코어 |
| GET | `/history` | 스캔 히스토리 | 최근 100회 |

---

## 알림 임계값 설정

`.env`에서 조정 (서비스 재시작 필요):

### 프리셋

```env
# 보수적 (알림 적음, 강한 신호만)
BUY_THRESHOLD=5.0
SELL_THRESHOLD=-5.0
MIN_CONFIDENCE=7.0

# 기본값 (균형)
BUY_THRESHOLD=3.0
SELL_THRESHOLD=-3.0
MIN_CONFIDENCE=5.0

# 공격적 (알림 많음, 약한 신호도)
BUY_THRESHOLD=2.0
SELL_THRESHOLD=-2.0
MIN_CONFIDENCE=3.0
```

### 각 값의 의미

| 설정 | 범위 | 설명 |
|------|------|------|
| `BUY_THRESHOLD` | 0 ~ +10 | 12개 기법 평균 점수가 이 값 이상이면 매수 알림 |
| `SELL_THRESHOLD` | -10 ~ 0 | 이 값 이하이면 매도 알림 |
| `MIN_CONFIDENCE` | 0 ~ 10 | 12개 기법 중 동일 방향 의견 비율 (10=만장일치) |

### 중복 알림 방지

동일 종목 + 동일 신호는 1시간 내 중복 전송하지 않는다. 30분 스캔 2회 연속 같은 결과가 나와도 알림은 1번만 발송.

---

## 종목 관리

### 방법 1: .env의 WATCHLIST 변수

```env
WATCHLIST=AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA
```

### 방법 2: watchlist.txt 파일 (두 소스가 자동 병합됨)

`chart_agent_service/watchlist.txt`:
```
# 성장주
AAPL
MSFT
NVDA

# 반도체
AMD
AVGO

# ETF
SPY
QQQ
```

두 방법을 동시에 사용하면 중복 없이 병합된다.

---

## 트러블슈팅

### 연결 실패: `Mac Studio 연결 실패: http://100.108.11.20:8100`

원인별 확인:

```bash
# 1. 네트워크 연결 확인 (testdev에서)
ping 100.108.11.20

# 2. 포트 열림 확인 (testdev에서)
nc -zv 100.108.11.20 8100

# 3. Mac Studio에서 서비스 실행 여부 확인
ssh 사용자명@100.108.11.20 "lsof -i :8100"

# 4. Mac Studio 방화벽 확인
# macOS 시스템 설정 → 네트워크 → 방화벽 → Python 허용 추가
# 또는 터미널에서:
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /Users/사용자명/stock_auto/chart_agent_service/venv/bin/python3
```

### Ollama 500 에러

```bash
# Mac Studio에서 실행
# 1. Ollama 서비스 확인
ollama list

# 2. 모델 존재 여부
ollama show llama3.1:8b

# 3. 메모리 확인 (M1 Max 32GB/64GB에 따라 모델 크기 조절)
sysctl -n hw.memsize | awk '{print $1/1024/1024/1024 " GB"}'

# 4. Ollama 재시작
brew services restart ollama
# 또는
pkill ollama && ollama serve &
```

### 분석 실행은 되지만 텔레그램 알림 안 옴

```bash
# 1. .env의 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 확인
cat .env | grep TELEGRAM

# 2. 텔레그램 연결 테스트
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}&text=테스트"

# 3. 임계값 확인 - 점수가 임계값 미만이면 알림이 안 나옴
# output/ 디렉토리의 최신 JSON 결과에서 composite_score 확인
cat output/*_agent_*.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f'점수: {data.get(\"composite_score\")}, 신뢰도: {data.get(\"confidence\")}')
"
```

### yfinance 데이터 수집 실패

```bash
# Mac Studio에서 인터넷 연결 확인
curl -s https://query1.finance.yahoo.com/v8/finance/chart/AAPL | head -100

# pip 업그레이드
pip install --upgrade yfinance
```

### 서비스 로그 확인

```bash
# nohup 실행 시
tail -100 ~/stock_auto/chart_agent_service/output/service.log

# launchd 실행 시
tail -100 ~/stock_auto/chart_agent_service/output/service_error.log
```

---

## 12개 분석 기법 요약

### 기술적 분석 (6개)

| # | 기법 | 핵심 |
|---|------|------|
| 1 | 이동평균선 배열 | 골든/데드크로스, 정배열/역배열 |
| 2 | RSI 다이버전스 | 과매수/과매도 + 가격-RSI 괴리 |
| 3 | 볼린저밴드 스퀴즈 | 밴드 수축→변동성 폭발 예고 |
| 4 | MACD 모멘텀 | 시그널 크로스, 히스토그램 가속 |
| 5 | ADX 추세 강도 | 추세 유무/방향/DI 크로스 |
| 6 | 거래량 프로파일 | OBV, 매집/분산, 거래량 이상 |

### 퀀트 분석 (6개)

| # | 기법 | 핵심 |
|---|------|------|
| 7 | 피보나치 되돌림 | 0.382/0.5/0.618 레벨 지지/저항 |
| 8 | 변동성 체제 | ATR 퍼센타일, 연환산 변동성 |
| 9 | 평균 회귀 (Z-Score) | 평균 대비 괴리도, 회귀 확률 |
| 10 | 모멘텀 순위 | 1주/1개월/3개월 가중 수익률 |
| 11 | 지지/저항선 | 피봇포인트 + 스윙 고저점, R:R |
| 12 | 수익률 자기상관 | Hurst 지수, 추세/회귀/랜덤 판단 |

각 기법은 -10 ~ +10 점수를 반환하고, 12개의 평균이 종합 점수가 된다.

---

## 파일 구조

### Mac Studio: `chart_agent_service/`

```
chart_agent_service/
├── service.py           # 메인 (FastAPI + 스케줄러 + 텔레그램)
├── analysis_tools.py    # 12개 분석 기법 + LLM 에이전트
├── data_collector.py    # 데이터 수집 + 지표 계산
├── config.py            # 설정
├── requirements.txt     # 의존성
├── .env                 # 환경변수 (직접 생성)
├── .env.example         # 환경변수 템플릿
├── watchlist.txt        # 관심 종목 (선택)
└── output/              # 결과 JSON, 차트 PNG, 로그
```

### testdev: `stock_analyzer/` (추가된 파일)

```
stock_analyzer/
├── agent_client.py      # Mac Studio API 클라이언트
└── .env                 # AGENT_API_URL=http://100.108.11.20:8100 추가
```
