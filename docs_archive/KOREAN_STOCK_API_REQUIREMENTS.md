# 🇰🇷 한국 주식 API 및 Key 요구사항
## Korean Stock API Requirements & Keys

---

## ✅ 현재 상태 (Phase 1) - API Key 불필요

### 사용 중인 데이터 소스

#### 1. Yahoo Finance (무료, Key 불필요)
```python
# yfinance 라이브러리 사용
import yfinance as yf

# 한국 주식 조회
ticker = yf.Ticker("005930.KS")  # 삼성전자
data = ticker.history(period="1y")

# API Key 필요 없음!
# 제한사항: 15-20분 지연 데이터
```

**제공 데이터:**
- ✅ OHLCV (일봉, 주봉, 월봉)
- ✅ 거래량
- ✅ 기본 재무 정보 (PER, PBR 등)
- ✅ KOSPI/KOSDAQ 지수 (^KS11, ^KQ11)

**장점:**
- 무료, 무제한
- API Key 불필요
- 안정적인 데이터 품질
- 전 세계 주식 지원

**단점:**
- 15-20분 지연
- 외국인/기관 매매 데이터 없음
- 실시간 호가 없음

---

## 🔨 향후 확장 시 필요한 API (Phase 2+)

### 1. DART (전자공시시스템) - 무료, Key 필요

#### API Key 발급 방법
```
1. DART 웹사이트 접속: https://opendart.fss.or.kr/
2. 회원가입 (무료)
3. 인증 API 신청
4. API Key 발급 (즉시)
```

#### 사용 예시
```python
import requests

DART_API_KEY = "YOUR_API_KEY_HERE"

# 삼성전자 재무제표 조회
url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
params = {
    'crtfc_key': DART_API_KEY,
    'corp_code': '00126380',  # 삼성전자 고유번호
    'bsns_year': '2025',
    'reprt_code': '11011'  # 1분기
}

response = requests.get(url, params=params)
```

**제공 데이터:**
- 재무제표 (손익계산서, 재무상태표, 현금흐름표)
- 기업 개황
- 주요 공시 사항
- 배당 정보
- 대주주 변동

**비용:** 무료
**제한:** API 호출 횟수 제한 있음 (일일 10,000건)

---

### 2. 네이버/다음 금융 - 무료, Key 불필요 (웹 스크래핑)

#### 현재 구현 상태
```python
# korean_stocks.py 내부 (준비만 됨)
def fetch_naver_info(self, ticker: str):
    """네이버 금융 스크래핑 - 구현 예정"""
    pass

def fetch_institutional_trading(self, ticker: str):
    """외국인/기관 매매 - 구현 예정"""
    pass
```

#### 구현 시 필요사항
```python
# 웹 스크래핑 라이브러리
pip install beautifulsoup4 requests lxml

# 사용 예시
import requests
from bs4 import BeautifulSoup

url = f"https://finance.naver.com/item/frgn.naver?code=005930"
response = requests.get(url)
soup = BeautifulSoup(response.text, 'html.parser')

# 외국인/기관 매매 데이터 파싱
```

**제공 데이터:**
- 외국인/기관/개인 순매수/순매도
- 프로그램 매매
- 실시간 시세 (15분 지연)
- 뉴스
- 토론방 (감성 분석 가능)

**비용:** 무료
**제한:**
- 과도한 요청 시 IP 차단 가능
- robots.txt 준수 필요
- User-Agent 설정 필수

**법적 고려사항:**
- 개인 사용 목적 OK
- 상업적 재배포 시 약관 확인 필요
- 데이터 저작권 존재

---

### 3. KRX (한국거래소) - 무료/유료 옵션

#### Option A: pykrx 라이브러리 (무료, Key 불필요)
```python
# 설치
pip install pykrx

# 사용 예시
from pykrx import stock

# 외국인/기관 매매 동향
df = stock.get_market_trading_volume_by_date(
    "20260101", "20260415", "005930"
)
print(df[['외국인매수', '외국인매도', '외국인순매수']])

# 시가총액
cap = stock.get_market_cap_by_ticker("20260415")
```

**제공 데이터:**
- 일별 외국인/기관/개인 매매
- 시가총액, 상장주식수
- 거래대금
- 투자자별 거래량

**비용:** 무료
**제한:** KRX 웹사이트 크롤링이므로 과도한 요청 자제

#### Option B: KRX DataShop (유료)
- 실시간 데이터
- API 형태 제공
- 월 수만원 ~ 수십만원

---

### 4. 추가 유용한 API (선택사항)

#### FinanceDataReader (무료, Key 불필요)
```python
pip install finance-datareader

import FinanceDataReader as fdr

# 삼성전자 주가
df = fdr.DataReader('005930', '2025-01-01', '2026-04-15')

# KOSPI 지수
kospi = fdr.DataReader('KS11', '2025-01-01')
```

#### 한국은행 API (무료, Key 필요)
- 경제 통계 (금리, 환율, GDP)
- API Key 발급: https://ecos.bok.or.kr/
- 통화정책, 금융안정 지표

---

## 📊 Phase별 API 요구사항 정리

### Phase 1 (현재 구현) - ✅ API Key 불필요
```
데이터 소스: Yahoo Finance (yfinance)
필요 라이브러리: yfinance, pandas, numpy
API Key: 불필요
비용: 무료

지원 기능:
✅ OHLCV 데이터
✅ KOSPI/KOSDAQ 지수
✅ 기술적 지표
✅ Multi-Agent 분석
✅ 백테스팅, ML 예측
```

### Phase 2 (외국인/기관 매매) - 🔨 API Key 불필요 (웹 스크래핑)
```
데이터 소스: 네이버 금융 또는 pykrx
필요 라이브러리: beautifulsoup4, requests, pykrx
API Key: 불필요
비용: 무료

추가 기능:
- 외국인/기관/개인 순매수
- 프로그램 매매
- 투자자별 거래 동향
```

### Phase 3 (공시/뉴스) - 📝 API Key 필요
```
데이터 소스: DART API
필요 라이브러리: dart-fss
API Key: DART API Key (무료 발급)
비용: 무료

추가 기능:
- 기업 공시
- 재무제표 상세
- 배당 정보
- IR 자료
```

### Phase 4 (실시간 데이터) - 💰 유료
```
데이터 소스: KRX DataShop, 증권사 API
API Key: 필요
비용: 유료 (월 수만원~)

추가 기능:
- 실시간 시세
- 실시간 호가
- 체결 내역
- Tick 데이터
```

---

## 🔑 API Key 관리 (향후 Phase 2+ 구현 시)

### .env 파일에 추가할 내용
```bash
# ── 한국 주식 API Keys ──

# DART (전자공시) - Phase 3
DART_API_KEY=your_dart_api_key_here

# 한국은행 (경제 통계) - Optional
BOK_API_KEY=your_bok_api_key_here

# FnGuide (금융 데이터) - Optional, 유료
FNGUIDE_API_KEY=your_fnguide_key_here
```

### config.py에 추가할 설정
```python
# chart_agent_service/config.py

import os
from dotenv import load_dotenv

load_dotenv()

# ── 한국 주식 API 설정 ──
DART_API_KEY = os.getenv("DART_API_KEY", "")
BOK_API_KEY = os.getenv("BOK_API_KEY", "")

# 네이버 금융 스크래핑 설정
NAVER_REQUEST_DELAY = 1.0  # 초 (과도한 요청 방지)
NAVER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
```

---

## ✅ 현재 구현 (Phase 1) 요약

### API Key 불필요! 즉시 사용 가능!

**필요한 것:**
1. Python 패키지: `yfinance` (이미 설치됨)
2. 인터넷 연결
3. 그게 전부입니다!

**사용 예시:**
```python
# 별도 설정 없이 바로 사용 가능
from stock_analyzer.korean_stocks import KoreanStockData

collector = KoreanStockData()
df = collector.fetch_ohlcv("005930")  # 삼성전자

# Multi-Agent 분석도 바로 가능
curl http://localhost:8100/multi-agent/005930.KS
```

---

## 📈 향후 Phase별 추가 요구사항

### Phase 2 실행 시
```bash
# 웹 스크래핑 라이브러리만 추가
pip install beautifulsoup4 lxml

# 또는 pykrx 사용
pip install pykrx

# API Key 여전히 불필요!
```

### Phase 3 실행 시 (DART 공시)
```bash
# 1. DART API Key 발급 (무료)
#    https://opendart.fss.or.kr/ 회원가입 후 발급

# 2. .env 파일에 추가
echo "DART_API_KEY=your_key_here" >> .env

# 3. dart-fss 라이브러리 설치
pip install dart-fss
```

---

## ❓ FAQ

### Q1: 현재 구현(Phase 1)으로 어디까지 분석 가능한가요?
**A:** Yahoo Finance를 통해 다음이 가능합니다:
- ✅ 모든 기술적 지표 (RSI, MACD, MA, BB, ATR 등)
- ✅ Multi-Agent AI 분석
- ✅ 백테스팅
- ✅ ML 예측
- ✅ 포트폴리오 최적화
- ❌ 외국인/기관 매매 (Phase 2 필요)
- ❌ 실시간 시세 (Phase 4 필요)

### Q2: Yahoo Finance로 한국 주식 데이터가 정확한가요?
**A:** 네, 정확합니다!
- Yahoo Finance는 KRX(한국거래소) 공식 데이터 사용
- OHLCV 데이터는 100% 정확
- 단, 15-20분 지연 데이터 (실시간 아님)

### Q3: 외국인/기관 매매 데이터는 언제 추가되나요?
**A:** Phase 2에서 추가 예정입니다:
- **방법 1**: pykrx 라이브러리 사용 (무료, Key 불필요)
- **방법 2**: 네이버 금융 스크래핑 (무료, Key 불필요)
- 추가 비용 없이 구현 가능!

### Q4: DART API Key는 필수인가요?
**A:** 아니요, 선택사항입니다 (Phase 3):
- Phase 1-2: 불필요 (기술적 분석, 외인/기관 매매)
- Phase 3: DART 공시 연동 시 필요 (무료 발급 가능)
- Phase 4: 실시간 데이터 시 유료 API 필요

### Q5: 현재 비용이 드나요?
**A:** 전혀 들지 않습니다!
- Yahoo Finance: 무료
- yfinance 라이브러리: 오픈소스, 무료
- 추가 API Key: 불필요
- Phase 2 (외국인/기관): 무료 방법 사용 예정

---

## 🚀 권장 구현 순서

### 즉시 사용 가능 (현재)
```
✅ Phase 1: 기술적 분석
   - 비용: $0
   - API Key: 불필요
   - 구현 시간: 완료
```

### 1-2주 후
```
🔨 Phase 2: 외국인/기관 매매
   - 비용: $0
   - API Key: 불필요
   - 방법: pykrx 또는 네이버 스크래핑
```

### 1개월 후
```
📝 Phase 3: DART 공시 연동
   - 비용: $0
   - API Key: DART (무료 발급)
   - 발급 시간: 즉시
```

### 3개월 후 (선택)
```
💰 Phase 4: 실시간 데이터
   - 비용: 월 $50-200
   - API Key: 증권사 API 또는 KRX DataShop
   - 필수 아님 (선택사항)
```

---

## 💡 결론

### 현재 Phase 1 구현은:
- ✅ **완전 무료**
- ✅ **API Key 불필요**
- ✅ **즉시 사용 가능**
- ✅ **기술적 분석 완벽 지원**

### 향후 확장도:
- ✅ **Phase 2: 무료** (pykrx, 네이버 스크래핑)
- ✅ **Phase 3: 무료** (DART API Key 무료 발급)
- ❓ **Phase 4: 선택적 유료** (실시간 필요 시)

**즉, 대부분의 기능을 무료로 사용할 수 있습니다!**

---

## 📝 설정 가이드 (Phase 2+ 준비용)

### Phase 2 준비 (외국인/기관 매매)

#### Option 1: pykrx 사용 (추천)
```bash
# 설치
pip install pykrx

# 사용
from pykrx import stock

# 외국인 매매
df = stock.get_market_trading_volume_by_date(
    "20260401", "20260415", "005930"
)
```

#### Option 2: 네이버 금융 스크래핑
```bash
# 설치
pip install beautifulsoup4 requests lxml

# korean_stocks.py의 fetch_institutional_trading() 구현
```

### Phase 3 준비 (DART 공시)

```bash
# 1. DART API Key 발급
#    https://opendart.fss.or.kr/에서 무료 회원가입

# 2. .env 파일 수정
echo "DART_API_KEY=your_key_here" >> stock_analyzer/.env

# 3. 라이브러리 설치
pip install dart-fss

# 4. 사용
import dart_fss as dart

api_key = os.getenv("DART_API_KEY")
dart.set_api_key(api_key)

# 재무제표 조회
fs = dart.filings.get_corp_code("삼성전자")
```

---

*최종 업데이트: 2026-04-15*
*작성자: Stock AI Development Team*

**요약: 현재 Phase 1은 API Key 없이 완전 무료로 사용 가능합니다!**