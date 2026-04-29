# Stock AI Analysis System · 사용자 매뉴얼

**버전**: 2026-04-21 기준  
**시스템**: 한국/미국 주식 통합 AI 분석 플랫폼  
**대상**: 개인 투자자 (연구·보조 도구)

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [설치 및 초기 설정](#2-설치-및-초기-설정)
3. [WebUI 네비게이션](#3-webui-네비게이션)
4. [페이지별 상세 사용법](#4-페이지별-상세-사용법)
5. [핵심 워크플로](#5-핵심-워크플로)
6. [환경 설정](#6-환경-설정)
7. [Telegram 알림](#7-telegram-알림)
8. [일일 운영 루틴](#8-일일-운영-루틴)
9. [속도 최적화](#9-속도-최적화)
10. [자주 묻는 질문](#10-자주-묻는-질문)
11. [법적 주의사항](#11-법적-주의사항)
12. [부록](#12-부록)

---

## 1. 시스템 개요

### 1.1 이 시스템으로 할 수 있는 것

- **분석**: 개별 종목의 16개 기술 지표 + 7개 전문 AI 에이전트 종합 분석
- **발굴**: 한국 시장 2,500개 중 매수 후보 상위 20개 자동 발굴 (매일 장 마감 후)
- **가상 매매**: 사용자가 정한 시점/가격으로 가상 포지션 추적, 손익 자동 계산
- **신호 추적**: 모든 분석 신호의 7/14/30일 후 실제 수익률 자동 평가 + 신뢰도 칼리브레이션
- **알림**: 매수/매도 시그널 + 풍부한 카드 포맷 Telegram 푸시

### 1.2 이 시스템이 하지 않는 것

- ❌ **실제 자금 매매 실행** (Phase 2 계획, 현재는 페이퍼 트레이딩만)
- ❌ **투자 자문** (법적으로 허가되지 않음 — 연구·보조 도구)
- ❌ **실시간 데이터** (yfinance 기준 15분 지연)
- ❌ **100% 수익 보장** (모든 AI 분석 동일)

### 1.3 시스템 구성

```
Stock AI System
├── chart_agent_service/  ← 분석 엔진 (FastAPI)
│   ├── 16개 기술 지표
│   ├── Multi-Agent 7 에이전트
│   ├── 한국 주식 스크리너
│   └── ML 예측 + 백테스트
│
├── stock_analyzer/       ← WebUI (Streamlit)
│   ├── 15개 페이지
│   ├── Watchlist 관리
│   └── Scanner (스케줄러)
│
└── 공용
    ├── watchlist.txt     ← 관심 종목 (SSOT)
    ├── scan_log.db       ← 분석 기록
    └── Telegram Bot
```

### 1.4 실제 효용성

현재 버전 (2026-04-21 기준):

| 영역 | 점수 | 비고 |
|------|-----|-----|
| 분석 품질 | 8.5/10 | 7 에이전트 협업, 모순 검증 완료 |
| 실행 가능성 | 2/10 | Paper Trading만, 실거래 Phase 2 |
| 속도 | 9/10 | 7종목 48초 (기존 7분 30초에서 개선) |
| 사용 편의성 | 8/10 | 한국/미국 통합, 수동 가상 매매 |
| 운영 비용 | 9/10 | 월 약 ₩1,000 (전기세만) |

**권장 사용**: 투자 리서치 2차 의견, 매매 후보 발굴, 전략 백테스트  
**비권장 사용**: 자동 매매, 고빈도 트레이딩, 독립적 투자 결정

---

## 2. 설치 및 초기 설정

### 2.1 시스템 요구사항

- **OS**: Linux / Mac / Windows (WSL)
- **Python**: 3.10 이상
- **GPU**: NVIDIA (Ollama용) 12GB+ 권장 (RTX 5070/4070 이상)
- **RAM**: 16GB 이상
- **인터넷**: 안정적 연결

### 2.2 자동 설치 (권장)

```bash
# 프로젝트 루트에서
bash setup_v2.sh
```

자동으로 수행:
- Python 3.10+ 확인
- venv 생성 및 활성화
- 의존성 설치 (stock_analyzer/requirements.txt + chart_agent_service/requirements.txt)
- `.env` 파일 생성 (`.env.example` 기반)
- Ollama 설치 및 상태 확인

`--minimal` 옵션으로 Ollama 단계 스킵 가능.

### 2.3 수동 설치

```bash
# 1. 가상환경
python3 -m venv venv
source venv/bin/activate

# 2. 의존성
pip install -r stock_analyzer/requirements.txt
pip install -r chart_agent_service/requirements.txt

# 3. 환경 설정
cp .env.example .env
# .env 파일 열어 편집 (아래 2.4 참조)

# 4. Ollama 설치 (https://ollama.com)
ollama pull qwen3:14b-q4_K_M  # 약 9GB
ollama serve  # 백그라운드 실행
```

### 2.4 필수 환경 변수

`.env` 파일에서:

```bash
# ─── 필수 ────────────────────────────────
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:14b-q4_K_M

# ─── 선택 (API 키는 발급 후 입력) ─────────
OPENAI_API_KEY=          # OpenAI GPT 사용 시
GEMINI_API_KEY=          # Google Gemini 사용 시
DART_API_KEY=            # 한국 공시 (무료, opendart.fss.or.kr)

# ─── Telegram 알림 (선택) ───────────────
TELEGRAM_BOT_TOKEN=      # @BotFather에서 발급
TELEGRAM_CHAT_ID=        # 본인 chat_id

# ─── 병렬 처리 ──────────────────────────
SCAN_PARALLEL_WORKERS=2  # 병렬 분석 종목 수
OLLAMA_NUM_PARALLEL=1    # Ollama 동시 처리 (VRAM 기반)
```

발급처:
- OpenAI: https://platform.openai.com/api-keys
- Gemini: https://aistudio.google.com/apikey
- DART: https://opendart.fss.or.kr (즉시 발급)
- Telegram: @BotFather → /newbot

### 2.5 서비스 실행

```bash
# 터미널 1 — 분석 엔진
cd chart_agent_service
python service.py

# 터미널 2 — WebUI
cd stock_analyzer
streamlit run webui.py --server.port 8501

# 터미널 3 — 스케줄러 (선택, 자동 스캔 필요 시)
cd stock_analyzer
python scanner.py
```

브라우저에서 `http://localhost:8501` 접속.

---

## 3. WebUI 네비게이션

좌측 사이드바에서 15개 페이지 선택 가능:

| # | 페이지 | 용도 |
|---|-------|-----|
| 1 | **Home** | 통합 홈 (시장 지수, Watchlist, 최신 신호) |
| 2 | **Dashboard** | 분석 결과 요약 대시보드 |
| 3 | **Detail** | 개별 종목 상세 분석 |
| 4 | **Multi-Agent** | 7 에이전트 심층 분석 |
| 5 | **Scan Log** | 과거 스캔 이력 DB 조회 |
| 6 | **Signal Accuracy** | 신호 적중률 + 칼리브레이터 상태 |
| 7 | **Screener** | 한국 주식 기술적 스크리너 (신규) |
| 8 | **Trading** | 주문 모드 + Kill Switch (Phase 2.1) |
| 9 | **Virtual Trade** | 수동 가상 매매 (내가 정한 시점) |
| 10 | **Backtest** | 전략 백테스트 (거래비용 반영) |
| 11 | **ML Predict** | ML 앙상블 예측 |
| 12 | **Portfolio** | 포트폴리오 최적화 |
| 13 | **Ranking** | 팩터 랭킹 |
| 14 | **Paper Trade** | 자동 신호 기반 페이퍼 트레이딩 |
| 15 | **History** | 스캔 히스토리 |

---

## 4. 페이지별 상세 사용법

### 4.1 Home (통합 홈)

**핵심**: 미국/한국 구분 없이 한 화면에서 전체 관리

**상단**:
- 시장 지수 바 (S&P 500, NASDAQ, DOW, KOSPI, KOSDAQ, USD/KRW, Gold 등)
- 분석 요약 6개 지표 (Total / Buy / Sell / Hold / 🇺🇸 US / 🇰🇷 KR)
- System Status (Agent/Ollama 연결 상태)

**Watchlist 섹션**:
- 시장 플래그 표시: 🇰🇷 하림 / 🇺🇸 AAPL
- 필터 라디오: 전체 / 🇺🇸 US / 🇰🇷 KR
- 빠른 추가 입력창 (영문/한글/6자리 코드 모두 인식)

**Latest Signals 테이블**:
- 시장 필터: 전체 / US / KR / BUY만 / SELL만
- Market / Name / Ticker / Signal / Score / Confidence / Time 컬럼

**한국 심화 도구** (접이식):
- 🇰🇷 Watchlist 한국 종목 현재가 카드
- 투자자별 매매 동향 (외국인/기관/개인)
- DART 공시 최근 30일

### 4.2 Multi-Agent 분석

**7 에이전트 구성**:
1. Technical Analyst — 차트 지표
2. Quant Analyst — 통계·수학
3. Risk Manager — 리스크·포지션 사이징
4. ML Specialist — 머신러닝 예측
5. Event Analyst — 뉴스·이벤트
6. Geopolitical Analyst — 지정학·환율 (V2.0 신규)
7. Value Investor — 밸류에이션 (V2.0 신규)
+ Decision Maker (종합 판단)

**사용 방법**:
1. 상단 종목 입력 (또는 Watchlist 선택)
2. **🤖 Multi-Agent 분석** 버튼 클릭
3. 약 1분 대기 (병렬 처리)

**결과 화면**:
- **Single LLM vs Multi-Agent 비교 카드**: 두 시스템 결과 나란히
- **신뢰도 갭 경고**: 차이 ≥ 2.0일 때 자동 표시 (원인 해설 포함)
- **에이전트 의견**: 7명 각자 BUY/SELL/NEUTRAL + 판단 근거
- **Decision Maker 최종 판단**: 신호 + 관망 확신도 (HOLD 시 라벨 변경)
- **실전 진입 계획** (신호가 BUY일 때):
  - 주문 유형 (시장가/지정가)
  - 진입가 / 손절가 / 익절가
  - 분할 진입 표 (25/50/75%)
  - 예상 보유 기간
- **📝 이 계획대로 가상 매수** 버튼 → Virtual Trade로 프리필

### 4.3 Screener (한국 주식 스크리너)

**목적**: 시총 2,000억+ 한국 종목 중 매수 후보 상위 20개 자동 발굴

**매일 자동 실행**: 평일 15:35 KST (장 마감 직후)  
**수동 실행**: 페이지 상단 버튼

**컨트롤**:
- 최소 시총 (억원): 기본 2,000억
- 상위 N개: 기본 20개
- 자동 심층: 0~20 (0이면 스크리너만, 5+ 이면 Multi-Agent 자동 병렬)

**2가지 실행 모드**:

| 모드 | 소요 | 출력 |
|-----|-----|-----|
| 스크리너만 (`자동 심층=0`) | 약 2분 | 상위 20개 점수/등급 |
| **🚀 파이프라인 모드** (`자동 심층=5`) | 약 5~7분 | + Multi-Agent 심층 분석 |

**점수 체계 (100점 만점)**:

| 득점 항목 | 최대 |
|---------|-----|
| MACD 골든크로스 (최근 10봉) | +30 |
| MA5>MA20>MA60 정배열 | +20 |
| RSI > 50 + 상승 기울기 | +20 |
| 거래량+양봉 동반 (3일 중 2일+) | +20 |
| MA20 지지 확인 | +10 |

| 감점 항목 | 최대 |
|---------|-----|
| MACD 데드크로스 | -20 |
| RSI > 78 과매수 | -15 |
| 5일 연속 거래량↓ | -10 |
| 종가 < MA120 | -10 |

**등급**:
- **S**: 85점 이상 (⭐⭐ 즉시 관심)
- **A**: 75~84 (⭐ 강한 후보)
- **B**: 65~74 (보통 후보)
- **C**: 50~64 (약한 후보)
- **D**: 50 미만 (제외)

**합의도 분석** (파이프라인 모드):

스크리너 × Multi-Agent 신호 일치 수준을 5단계로 분류:

| 합의 | 조건 | 설명 |
|-----|------|-----|
| 🟢🟢 **강한 일치** | 스크리너 S/A + MA buy + 신뢰도≥6 | 1순위 후보 |
| 🟢 **부분 일치** | 스크리너 S/A + MA 보수적 | 추가 관찰 |
| ⚠️ **신호 충돌** | 스크리너 S/A + MA sell | 재검토 필요 |
| 🟡 **이례적 매수** | 스크리너 C/D + MA buy | MA 근거 확인 |
| ⚪ **동반 약세** | 스크리너 C/D + MA neutral/sell | 관망 |

**최우선 관심 종목**: 🟢🟢 강한 일치 종목만 별도 하이라이트로 진입 계획 표시

**다음 단계 버튼**:
- 📋 **Watchlist 추가** — 명시적 선택 시에만 (SSOT 보장)
- 🤖 **Multi-Agent 개별** — 상세 분석
- 📝 **Virtual Trade 프리필** — 가상 매수 폼 자동 입력

### 4.4 Virtual Trade (수동 가상 매매)

**핵심**: 사용자가 "지금 사고 싶다"고 판단한 시점/가격/수량으로 가상 포지션 생성 → 자동 추적

**진입 흐름**:

1. **종목 입력** (영문/한글/한국 6자리)
2. **📡 현재가 조회** 버튼
   - 현재가, 당일 고가/저가, 호가단위 즉시 표시
3. **파라미터 입력**:
   - 수량, 진입가 (직접 수정 가능)
   - 총 투자금 자동 계산
4. **🛡️ 손절·익절·자동 청산 설정** (접이식):
   - 손절가 (도달 시 자동 매도)
   - 익절가 (도달 시 자동 매도)
   - Trailing Stop % (고점 대비 하락 시)
   - 시간 청산 (N일 경과 시)
   - **R/R 비율 자동 계산** 표시
5. **진입 근거 메모**
6. **🛒 가상 매수 실행** — 즉시 체결

**포지션 모니터링**:

- **🔄 현재가 갱신** 버튼 — 전체 포지션 일괄 업데이트 + 자동 청산 감지
- 각 포지션 카드:
  - 수량/진입가/현재가/손익 (색상)
  - 진입일 + 경과일
  - **청산 버튼**: 25% / 50% / 75% / 100% / **지정가**
  - **자동 청산 조건 시각화**:
    - 🛑 손절가 + 현재가 대비 거리 %
    - 🎯 익절가 + 현재가 대비 거리 %
    - 📉 Trailing: 고점 + 트리거 가격
    - ⏱ 시간 청산 남은 일수

**최근 청산 이력**:
- 종목명/티커/수량/진입가/청산가/손익/수익률/🟢WIN or 🔴LOSS/사유/청산일

**연계 기능**:
- Multi-Agent 분석 페이지의 "📝 이 계획대로 가상 매수" 버튼 → 진입가/손절/익절 자동 프리필
- Screener 결과의 "📝 Virtual Trade 프리필" 버튼 → 동일

### 4.5 Signal Accuracy

**목적**: 시스템이 낸 신호가 실제로 얼마나 맞았는지 추적

**매일 자동 실행**: 03:00 KST (scan_log 순회 + yfinance로 실제 가격 비교)

**지표**:
- 평가 건수 (7/14/30일 Horizon 선택)
- 적중률 (win/loss/neutral 비율)
- 평균 수익률
- 랜덤(33%) 대비 엣지

**신호별 분포**: BUY/SELL/NEUTRAL 각각 적중률

**신뢰도 구간별 적중률** (Plotly 차트):
- 0~2 / 2~4 / 4~6 / 6~8 / 8~10 구간별 건수·적중률
- 색상: 빨강(<50%) / 노랑(50~60%) / 초록(≥60%)
- 랜덤 기준선(50%) 자동 표시

**🎯 칼리브레이터 상태**:
- 활성화 여부 (최소 50건 이상 누적 시 활성)
- 누적 표본, 마지막 학습 시각
- 보정 적용 신호 (buy/sell/neutral별)

**활용**:
- 칼리브레이터가 활성화되면 이후 Multi-Agent 결과의 신뢰도가 자동 보정됨
- Multi-Agent 결과에 "보정 전 8.5 → 7.2" 같이 표시

### 4.6 Trading (주문 모드 관리)

**핵심**: 4단계 실행 모드로 실거래 위험 관리

| 모드 | 동작 | 용도 |
|-----|-----|-----|
| 🟢 **PAPER** | 내부 페이퍼 트레이더 | 기본, 안전 |
| 🟡 **DRY_RUN** | 주문 생성·로그만 | 검증 단계 |
| 🟠 **APPROVAL** | 텔레그램 승인 후 실행 | 안전장치 |
| 🔴 **LIVE** | 실제 증권사 API | 자금 이동 (Phase 2.2+) |

**안전 장치**:
- 🚨 **Kill Switch** 즉시 활성화 버튼
- 일일 주문 한도 (US: $1,000 / KR: ₩1,000,000)
- 단일 주문 한도
- 중복 주문 10초 방지

**표시 정보**:
- 현재 모드 + Kill Switch 상태
- 일일 한도 사용량 (프로그레스 바)
- 계좌 요약 (총 자산 / 현금 / 수익률 / 포지션)
- 보유 포지션 테이블
- 🔔 승인 대기 주문 (APPROVAL 모드)
- 📝 최근 주문 감사 로그 (7일 통계)

### 4.7 Backtest (전략 백테스트)

**지원 전략**:
- SMA Cross
- RSI Reversion
- Bollinger Reversion
- Composite Signal

**Sprint 1 개선**: 거래비용 자동 반영
- 한국: 수수료 0.015% + 슬리피지 0.05% + 거래세 0.18% (매도)
- 미국: 수수료 0 + 슬리피지 0.05%
- 호가단위 정규화 (52,347원 → 52,300원)

**HyperOpt 최적화**: Optuna 50회 시뮬레이션으로 최적 파라미터 탐색

**Walk-Forward 검증**: 과적합 방지

**출력 지표**:
- 총 수익률 / 연환산 수익률
- Sharpe Ratio (무위험 수익률 옵션)
- Max Drawdown
- 승률 / Profit Factor
- 평균 보유일

### 4.8 Scan Log

**목적**: 과거 모든 분석 기록 조회

**상단 통계**:
- 총 스캔 횟수
- BUY / SELL / HOLD 카운트

**필터**: 종목별, 날짜 범위, 신호별

**주간 트렌드**: 일별 점수 변화 차트

### 4.9 기타 페이지

- **Dashboard**: 현재 분석 결과 요약 대시보드 + 시장 필터
- **Detail**: 개별 종목 차트 + 16개 도구 결과
- **ML Predict**: LightGBM/XGBoost/LSTM 앙상블 예측 + SHAP
- **Portfolio**: Markowitz / Risk Parity 최적화
- **Ranking**: 멀티팩터 종목 순위
- **Paper Trade**: 자동 신호 기반 페이퍼 트레이딩 (Virtual Trade는 수동)
- **History**: 스캔 실행 히스토리

---

## 5. 핵심 워크플로

### 5.1 일일 루틴 (권장)

**아침 9:00 (장 시작 전)**
- Home 페이지에서 전일 한국 스크리너 결과 확인
- Multi-Agent 합의도 🟢🟢 강한 일치 종목 검토

**장 중**
- 시스템은 30분 주기로 자동 스캔 (Scanner)
- Telegram 알림 확인 (매수/매도 시그널)

**장 마감 직후 15:35**
- 스크리너 자동 실행 (설정되어 있다면)
- 결과 확인

**밤 17:00**
- 일일 다이제스트 Telegram 알림 수신
- Signal Accuracy 페이지에서 어제 신호 검증

**취침 전**
- 관심 종목 Virtual Trade 포지션 확인
- 다음 날 매수 후보 추가

### 5.2 시나리오 1: 한국 매수 후보 발굴

```
1. Screener 페이지
   → 시총 2,000억 / 상위 20 / 자동 심층 5
   → 🚀 파이프라인 실행 (약 5~7분)

2. 결과 확인
   → 합의도 🟢🟢 강한 일치 섹션 먼저 검토
   → 예: 하림 (스크리너 A + MA buy 7.5)

3. 🎯 최우선 관심 종목 카드
   → 진입가/손절/익절 확인

4. 📝 Virtual Trade 프리필
   → Virtual Trade 페이지로 이동
   → 수량 입력 후 "🛒 가상 매수 실행"

5. 자동 추적 시작
   → 손절/익절 도달 시 자동 청산
   → Signal Accuracy에서 30일 후 검증
```

### 5.3 시나리오 2: 보유 종목 주간 점검

```
1. Virtual Trade 페이지
   → "🔄 현재가 갱신" 버튼
   → 전체 포지션 손익 + 자동 청산 체크

2. 각 포지션 카드 확인
   → 목표까지 %, 경과일
   → 자동 청산 조건 현황

3. 필요 시 조정
   → 일부 수익 실현: 25%/50% 청산
   → 트레일링 상향: 재매수 후 손절가 상향

4. Multi-Agent 재분석 (선택)
   → "🤖 Multi-Agent" 버튼으로 심층 재검증
```

### 5.4 시나리오 3: 특정 종목 심층 분석

```
1. Multi-Agent 페이지
   → 종목 입력 (한글 OK)
   → "🤖 Multi-Agent 분석" 버튼
   → 약 1분 대기

2. 7 에이전트 의견 검토
   → 각자의 BUY/SELL/NEUTRAL 확인
   → 판단 근거 펼쳐보기

3. Decision Maker 최종 판단
   → 합의 vs 충돌 해설
   → 신뢰도 갭 경고 있으면 설명 읽기

4. 실전 진입 계획
   → 진입가/손절/익절
   → 분할 진입 표 검토

5. 실행 선택:
   - 보류: 정보만 수집
   - 가상 매수: Virtual Trade 프리필
   - Watchlist 추가: 정기 모니터링
```

### 5.5 시나리오 4: 전략 백테스트

```
1. Backtest 페이지
   → 종목 선택
   → 전략 선택 (RSI Reversion 등)
   → HyperOpt 최적화 실행

2. 결과 해석
   → 거래비용 반영된 실제 수익률
   → Sharpe / Max DD 확인
   → Walk-Forward 과적합 체크

3. 실전 적용 여부 판단
   → Sharpe > 1.0 + DD < 20% 권장
   → overfitting_ratio < 1.3
```

---

## 6. 환경 설정

### 6.1 주요 환경변수

`.env` 파일:

```bash
# ── Ollama ──
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:14b-q4_K_M
OLLAMA_NUM_PARALLEL=1           # VRAM 기반 (12GB에서 qwen3:14b는 1)

# ── 스캔 병렬 ──
SCAN_PARALLEL_WORKERS=2         # 동시 분석 종목 수
SCAN_INTERVAL_MINUTES=30        # Scheduler 주기

# ── 주문 모드 (Phase 2) ──
TRADING_MODE=paper              # paper | dry_run | approval | live
DAILY_ORDER_LIMIT_USD=1000
DAILY_ORDER_LIMIT_KRW=1000000
SINGLE_ORDER_LIMIT_USD=200
SINGLE_ORDER_LIMIT_KRW=200000
KILL_SWITCH=false

# ── 거래비용 ──
TRADING_COMMISSION_PCT_KR=0.015
TRADING_COMMISSION_PCT_US=0.0
TRADING_SLIPPAGE_PCT=0.05
TRADING_SELL_TAX_PCT_KR=0.18

# ── Screener ──
SCREENER_MIN_MARKET_CAP_KRW=200000000000  # 2천억
SCREENER_TOP_N=20

# ── 알림 임계값 ──
BUY_THRESHOLD=5.0
SELL_THRESHOLD=-5.0
MIN_CONFIDENCE=5.0

# ── 무위험 수익률 (Sharpe 계산용) ──
ANNUAL_RISK_FREE_RATE=0.0       # 또는 0.035 (3.5%)
```

### 6.2 투자 스타일 프리셋

```bash
TRADING_STYLE=swing   # scalping | swing | longterm
```

| 스타일 | SMA 기간 | ATR 배수 | 기간 | 타임프레임 |
|------|--------|--------|-----|---------|
| scalping | [5, 20] | 1.2 | 60d | intraday |
| **swing (기본)** | [20, 50, 200] | 2.0 | 2y | daily |
| longterm | [50, 120, 200] | 3.0 | 5y | weekly |

### 6.3 Watchlist 관리

**위치**: `stock_analyzer/watchlist.txt` (SSOT)

**추가 방법** (3가지):
1. WebUI 사이드바 → "Watchlist · 통합" → 입력창 → Add
2. WebUI Home 페이지 → "빠른 종목 추가"
3. 파일 직접 편집 (WebUI 재시작 필요)

**입력 예시** (모두 인식):
- `AAPL` → Apple Inc.
- `005930.KS` → 삼성전자
- `005930` → 삼성전자 (자동 .KS 추가)
- `삼성전자` → 005930.KS (한글 검색, FDR 설치 필요)
- `하림` → 136480.KS

**삭제**: 사이드바 → Remove 버튼

**SSOT 원칙**: Watchlist에서 지운 종목은 모든 페이지에서 자동으로 사라짐 (한국 심화 도구, 드롭다운 등)

---

## 7. Telegram 알림

### 7.1 설정 (5분 소요)

1. Telegram에서 **@BotFather** 검색 → 대화 시작
2. `/newbot` 입력 → 봇 이름 지정 → **Token 복사**
3. Telegram에서 **@userinfobot** 검색 → `/start` → **Chat ID 복사**
4. `.env` 파일에 추가:
   ```
   TELEGRAM_BOT_TOKEN=123456789:ABCdef...
   TELEGRAM_CHAT_ID=123456789
   ```
5. 서비스 재시작

### 7.2 알림 종류

**풍부한 신호 알림** (매수/매도 시그널):
```
🟢 005930.KS (삼성전자)
━━━━━━━━━━━━━━━━━━━━
📊 신호: 매수 (신뢰도 7.5/10)
📋 주문: 지정가 · 즉시
💰 진입가: ₩52,400
🛑 손절: ₩50,500
🎯 익절: ₩56,200
⏱ 예상 보유: 10일
📊 분할: 60% @ ₩52,400 → 40% @ ₩51,000

👥 합의: 4 매수 / 1 매도
💡 강한 상승 추세 확인됨
⚠️ 리스크: 실적 발표 임박
📈 과거 적중률: 62% (n=50)

[📊 상세 보기] [✅ 워치리스트] [🚫 무시]
```

**인라인 버튼**:
- ✅ 워치리스트 → 원클릭으로 watchlist.txt 추가
- 🚫 무시 → 쿨다운 상태로 표시

**일일 다이제스트** (매일 17:00 평일):
- 오늘 스캔 요약
- BUY/SELL 상위 5개

**승인 대기 주문** (APPROVAL 모드):
- ✅ 승인 / ❌ 거절 버튼

**에러 알림**: LLM 장애, API 오류 등

### 7.3 콜백 처리

- Scanner가 5분마다 폴링하여 버튼 클릭 자동 처리
- 또는 API로 수동: `POST /telegram/process-callbacks`

---

## 8. 일일 운영 루틴

### 8.1 Scanner 자동 스케줄

`python scanner.py` 실행 시 자동 등록:

| 시각 | 작업 | 소요 |
|-----|-----|-----|
| 30분 주기 | Watchlist 전체 스캔 | 약 1분 (7종목) |
| 월요일 09:30 | 포트폴리오 리밸런싱 체크 | 1-2분 |
| 매일 03:00 | 신호 정확도 평가 + 칼리브레이터 재학습 | 1-5분 |
| 평일 15:35 | 한국 주식 스크리너 | 약 2분 |
| 5분 주기 | Telegram 콜백 폴링 | 즉시 |
| 평일 17:00 | 일일 다이제스트 Telegram 발송 | 즉시 |

### 8.2 수동 작업

**아침**: Scanner 시작 확인
```bash
ps aux | grep scanner.py
```

**저녁**: 오늘 분석 결과 확인
- WebUI Home → Latest Signals
- Signal Accuracy → 최근 적중률

**주말**: 
- Virtual Trade 포지션 정리
- 백테스트 재검토

### 8.3 모니터링

**서비스 상태**:
- `GET /health` — chart_agent_service 응답 확인
- Ollama: `curl http://localhost:11434/api/tags`

**로그**:
- FastAPI 콘솔 출력
- Scanner 콘솔 출력

---

## 9. 속도 최적화

### 9.1 현재 성능

| 작업 | 소요 |
|-----|-----|
| 7종목 스캔 (Watchlist) | 48초 |
| 단일 Multi-Agent 분석 | 약 1분 |
| 한국 스크리너 (280개) | 약 2분 |
| 스크리너 + MA 5개 파이프라인 | 약 5~7분 |

### 9.2 VRAM 기반 병렬 설정

| GPU | 모델 크기 | 권장 `OLLAMA_NUM_PARALLEL` | `SCAN_PARALLEL_WORKERS` |
|-----|---------|------------------------|-----------------------|
| RTX 5070 12GB | qwen3:14b (8GB) | 1 | 2 |
| RTX 4080 16GB | qwen3:14b (8GB) | 2 | 3 |
| Mac Studio M1 Max 32GB | qwen3:14b (8GB) | 3 | 3 |
| 듀얼 노드 | - | - | 4 |

**VRAM 초과 증상**:
- Ollama 응답 지연
- "out of memory" 에러
- → `OLLAMA_NUM_PARALLEL=1`로 낮춤

### 9.3 스캐너 개선

- 배치 OHLCV 다운로드: 7종목 → 1.5초 (기존 49초)
- 종목 간 병렬 처리: `ThreadPoolExecutor(max_workers=WORKERS)`
- 캐시 재사용: `data_collector._ohlcv_cache`

---

## 10. 자주 묻는 질문

### Q1. Ollama 모델을 바꾸고 싶어요

`.env`:
```bash
OLLAMA_MODEL=qwen2.5:32b  # 더 큰 모델 (VRAM 충분 시)
# 또는
OLLAMA_MODEL=llama3.1:8b  # 작은 모델 (속도 빠름)
```

`ollama pull` 로 모델 다운로드 후 서비스 재시작.

### Q2. 한국 주식 종목명이 "코드"로 나와요

1. pykrx 설치 확인: `pip install pykrx finance-datareader`
2. 내장 주요 종목 맵에 없으면 티커 그대로 표시
3. 해결: `stock_analyzer/webui.py`의 `_KR_TICKER_NAME_FALLBACK` 딕셔너리에 직접 추가

### Q3. 분석이 너무 느려요

1. `.env`의 `SCAN_PARALLEL_WORKERS` 값 확인 (기본 2)
2. Ollama 모델 크기 확인 (qwen3:14b → qwen3:8b로 전환 시 2배 빠름)
3. yfinance 대신 Alpaca 전환 (`DATA_SOURCE=alpaca`, 유료)

### Q4. Multi-Agent 결과가 "LLM 서비스 일시 장애"

- Ollama 연결 확인: `curl http://localhost:11434/api/tags`
- 모델 다운로드 확인: `ollama list`
- OpenAI API 키 (Decision Maker용) 설정 확인

### Q5. Virtual Trade의 자동 청산이 안 돼요

- "🔄 현재가 갱신" 버튼을 눌러야 체크됨
- 또는 Scanner가 30분 주기로 자동 업데이트

### Q6. 실제 자금으로 매매 가능한가요?

**현재는 불가능**. Phase 2.2+에서 증권사 API 연동 예정:
- 미국: Alpaca (무료)
- 한국: KIS (한국투자증권)
- 계획서: `docs/PHASE_2_PLAN.md`

### Q7. 스크리너 결과와 Multi-Agent 결과가 다를 때?

**합의도 5단계**로 자동 분류:
- 🟢🟢 **강한 일치**: 둘 다 매수 → 1순위
- ⚠️ **신호 충돌**: 스크리너 A/S + MA sell → 재검토
- 🟡 **이례적 매수**: MA만 매수 → 근거 확인

스크리너 페이지의 "🔗 합의도 분석" 섹션에서 확인.

### Q8. 신호 정확도는 어떻게 확인하나요?

**Signal Accuracy** 페이지:
- 7/14/30일 Horizon 선택
- 신호별 적중률 카드
- 신뢰도 구간별 차트

**초기 상태**: 신호 50건 이상 누적 후 칼리브레이터 활성화

### Q9. 백테스트 수익률이 실제와 차이나요

Sprint 1 개선으로 거래비용 자동 반영:
- 수수료 + 슬리피지 + 세금 차감됨
- 이전 버전보다 현실적 수치

단, **과적합 주의**:
- Walk-Forward 검증 결과의 overfitting_ratio 확인
- In-sample 수익률이 Out-of-sample보다 1.5배 이상 높으면 의심

### Q10. Watchlist에서 지운 종목이 다른 곳에 남아있어요

최신 버전에서 **SSOT 원칙** 준수:
- 사이드바 + 홈 + 한국 심화 도구 + Multi-Agent 드롭다운 + Virtual Trade 모두 `watchlist.txt` 하나를 참조
- 지우면 모든 곳에서 사라짐 (페이지 새로고침)

이전 버전 잔재가 있다면 브라우저 캐시 초기화 + 서비스 재시작.

---

## 11. 법적 주의사항

### 11.1 본 시스템의 성격

**이 시스템은 투자 자문 도구가 아닙니다.**

- ✅ 개인 투자자의 연구·보조 도구
- ✅ 시장 데이터 분석·시각화
- ✅ 페이퍼 트레이딩 교육용
- ❌ 타인 대상 투자 자문 (불법)
- ❌ 투자 권유
- ❌ 수익 보장

### 11.2 한국 자본시장법

- **무인가 투자자문업**: 5년 이하 징역 또는 2억원 이하 벌금
- **타인 명의 매매**: 본인 확인 필수
- **자금 운용 위탁**: 별도 금융감독원 등록 필요

**본 시스템 사용 범위**: **본인 계좌 본인 사용 한정**

### 11.3 손실 면책

모든 AI 분석에는 오류가 있을 수 있습니다:
- 데이터 지연 (yfinance 15분)
- 모델 편향
- 시장 급변 대응 불가

**최종 투자 결정은 사용자 본인 판단**이며, 시스템 제작자·기여자는 어떠한 금전적 손실에 대해서도 **책임지지 않습니다**.

### 11.4 권장 사용 원칙

1. **소액 시작** — 총 자산의 1~5%
2. **3~6개월 페이퍼 검증** — 실제 자금 투입 전
3. **시스템 신호 맹신 금지** — 본인 판단 우선
4. **기록 유지** — 모든 매매에 대한 자체 기록
5. **다양화** — 단일 종목/전략 집중 금지

---

## 12. 부록

### 12.1 주요 파일 구조

```
stock_auto/
├── .env                          ← 환경 변수
├── watchlist.txt                 ← 관심 종목 (SSOT)
│
├── chart_agent_service/          ← 분석 엔진
│   ├── service.py                ← FastAPI 서버
│   ├── analysis_tools.py         ← 16개 분석 도구
│   ├── data_collector.py         ← yfinance + 지표 계산
│   ├── screener.py               ← 한국 주식 스크리너 ⭐
│   ├── entry_plan.py             ← 진입 계획 생성
│   ├── trading_costs.py          ← 거래비용 모델
│   ├── tick_size.py              ← 호가단위 정규화
│   ├── paper_trader.py           ← 페이퍼 트레이딩
│   ├── ml_predictor.py           ← ML 앙상블
│   ├── backtest_engine.py        ← 백테스트
│   ├── news_analyzer.py          ← 뉴스 감성
│   ├── signal_tracker.py         ← 신호 정확도 추적
│   ├── telegram_bot.py           ← Telegram 알림
│   ├── db.py                     ← SQLite DB
│   │
│   ├── brokers/                  ← Phase 2 브로커 어댑터
│   │   ├── base.py               ← BrokerInterface
│   │   ├── paper_broker.py       ← 페이퍼 브로커
│   │   ├── dry_run_broker.py     ← DryRun 브로커
│   │   ├── alpaca_broker.py      ← Alpaca (미국)
│   │   ├── safety.py             ← Kill Switch + 한도
│   │   └── factory.py            ← 모드별 디스패치
│   │
│   ├── execution/                ← 주문 실행
│   │   ├── order_router.py       ← 주문 라우팅
│   │   ├── approval_queue.py     ← 승인 큐
│   │   └── audit_log.py          ← 감사 로그
│   │
│   └── data_sources/             ← 데이터 소스 어댑터
│       ├── yfinance_source.py
│       └── alpaca_data_source.py
│
├── stock_analyzer/               ← WebUI
│   ├── webui.py                  ← Streamlit 메인 (15 페이지)
│   ├── multi_agent.py            ← 7 에이전트 시스템
│   ├── enhanced_decision_maker.py ← Decision Maker
│   ├── scanner.py                ← 스케줄러
│   ├── local_engine.py           ← 엔진 브릿지
│   ├── ticker_validator.py       ← 티커 검증
│   ├── dart_api.py               ← 한국 공시
│   └── watchlist.txt             ← SSOT 종목 목록
│
└── docs/
    ├── USER_MANUAL.md            ← 본 문서
    └── PHASE_2_PLAN.md           ← Phase 2 계획서
```

### 12.2 API 엔드포인트 전체 목록

**분석**:
- `GET /` — 서비스 정보
- `GET /health` — 헬스체크
- `GET /results` — 전체 분석 결과
- `GET /results/{ticker}` — 종목 결과 조회
- `POST /scan/{ticker}` — 단일 종목 스캔
- `POST /scan` — 복수 스캔
- `GET /multi-agent/{ticker}` — Multi-Agent 분석

**Screener** (신규):
- `POST /screener/run` — 스크리너 실행
- `POST /screener/pipeline` — 스크리너 + Multi-Agent 파이프라인
- `GET /screener/latest` — 최근 결과
- `GET /screener/history` — 실행 이력

**Virtual Trade**:
- `POST /paper/virtual-buy` — 수동 가상 매수
- `POST /paper/partial-close` — 부분/전량 청산
- `GET /paper/quote/{ticker}` — 현재가 + 호가단위
- `POST /paper/update-prices` — 포지션 현재가 갱신

**Signal Accuracy**:
- `GET /signal-accuracy` — 정확도 통계
- `POST /signal-accuracy/evaluate` — 수동 평가 실행
- `GET /signal-accuracy/calibrator` — 칼리브레이터 상태

**Telegram**:
- `POST /telegram/rich-signal/{ticker}` — 풍부한 알림
- `POST /telegram/daily-digest` — 일일 다이제스트
- `POST /telegram/process-callbacks` — 버튼 콜백 처리

**Trading (Phase 2)**:
- `GET /trading/mode` — 현재 모드
- `POST /trading/mode` — 모드 변경
- `POST /trading/kill-switch/activate` — 긴급 중지
- `GET /trading/broker-health` — 브로커 상태
- `GET /trading/positions` — 포지션 조회
- `POST /trading/orders` — 주문 제출
- `GET /trading/orders/recent` — 최근 주문
- `POST /trading/approval/{id}/approve` — 주문 승인

**기타**:
- `GET /paper` — 페이퍼 트레이딩 상태
- `GET /backtest/{ticker}` — 백테스트
- `GET /ml/{ticker}` — ML 예측
- `GET /portfolio/optimize` — 포트폴리오 최적화
- `GET /weekly` — 주간 요약
- `GET /scan-log` — 스캔 로그

### 12.3 분석 도구 16개 (analysis_tools.py)

기술적 분석 (6):
1. trend_ma_analysis — 이동평균 배열
2. rsi_divergence_analysis — RSI 다이버전스
3. bollinger_squeeze_analysis — 볼린저 스퀴즈
4. macd_momentum_analysis — MACD
5. adx_trend_strength_analysis — ADX 추세 강도
6. volume_profile_analysis — 거래량 프로파일

퀀트 분석 (6):
7. fibonacci_retracement_analysis — 피보나치
8. volatility_regime_analysis — 변동성 체제
9. mean_reversion_analysis — 평균 회귀
10. momentum_rank_analysis — 모멘텀 순위
11. support_resistance_analysis — 지지/저항
12. correlation_regime_analysis — Hurst 체제

리스크 관리 (4):
13. risk_position_sizing — 포지션 사이징
14. kelly_criterion_analysis — 켈리 기준
15. beta_correlation_analysis — 베타
16. event_driven_analysis — 이벤트
+ insider_trading_analysis — 내부자 거래
+ entry_plan_analysis — 진입 계획

### 12.4 7 에이전트 (Multi-Agent)

| 에이전트 | 역할 | 할당 도구 |
|--------|-----|---------|
| Technical Analyst | 차트 패턴 | trend_ma, rsi, bollinger, macd, adx, volume |
| Quant Analyst | 통계 모델 | fibonacci, volatility, mean_reversion, momentum_rank, S/R, correlation |
| Risk Manager | 리스크 | risk_position_sizing, kelly, beta |
| ML Specialist | ML 예측 | event_driven, insider_trading |
| Event Analyst | 뉴스·이벤트 | event_driven, 공시 |
| Geopolitical Analyst | 지정학 (V2.0) | 거시경제, 환율 |
| Value Investor | 밸류에이션 (V2.0) | PE/PB, 재무제표 |
| **Decision Maker** | **종합 판단** | 7명 의견 종합 |

### 12.5 공식 지원 문의

- GitHub Issues: (프로젝트 저장소)
- 환경 설정 문제: `setup_v2.sh` 실행 후 로그 공유
- 분석 결과 이상: scan_log.db 백업 + 재현 단계 기록

---

## 버전 히스토리

- **v1.0 (2026-04-21)**: 최초 작성
  - Sprint 1~3 기능 포함
  - Phase 2.1~2.2 페이퍼 브로커
  - 한국 주식 스크리너 V1 + 파이프라인
  - 미국/한국 통합 홈
  - Virtual Trade 수동 매매
  - Signal Accuracy 칼리브레이션
