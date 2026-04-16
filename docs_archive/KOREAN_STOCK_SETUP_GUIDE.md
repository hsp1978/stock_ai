# 🇰🇷 한국 주식 통합 설정 가이드
## Korean Stock Integration - Setup Guide

### ✅ 구현 완료 현황

현재 Stock AI 시스템에 한국 주식 지원이 성공적으로 통합되었습니다!

---

## 📦 구현된 파일 목록

### 1. 핵심 모듈
```
stock_analyzer/
├── korean_stocks.py        # 한국 주식 데이터 수집기
├── ticker_manager.py        # 통합 티커 관리자
└── webui.py                # WebUI (한국/미국 탭 추가)
```

### 2. 문서
```
/
├── KOREAN_STOCK_INTEGRATION_PLAN.md      # 통합 계획서
├── KOREAN_STOCK_AGENT_INSTRUCTIONS.md    # 에이전트 지시문
├── KOREAN_STOCK_SETUP_GUIDE.md          # 설정 가이드 (본 문서)
└── test_korean_stocks.py                 # 통합 테스트 스크립트
```

---

## 🚀 사용 방법

### 1. WebUI에서 한국 주식 사용하기

#### Step 1: WebUI 접속
```bash
# WebUI가 이미 실행 중이라면 자동으로 재로드됩니다
# 또는 다시 시작:
streamlit run stock_analyzer/webui.py --server.port 8501
```

#### Step 2: 한국 주식 탭 선택
1. Home 페이지 접속
2. **🇰🇷 Korean Market** 탭 클릭
3. KOSPI/KOSDAQ 지수 확인
4. 주요 종목 현황 확인

#### Step 3: 종목 분석
```
Sidebar에서:
1. 한국 주식 코드 입력
   예시:
   - 005930 (삼성전자)
   - 000660 (SK하이닉스)
   - 035420 (NAVER)

2. 또는 Yahoo Finance 형식
   - 005930.KS
   - 000660.KS

3. 또는 한글 종목명
   - 삼성전자
   - SK하이닉스
```

---

## 🎯 주요 기능

### 현재 지원 기능 ✅

#### 1. 데이터 수집
- [x] Yahoo Finance .KS/.KQ 티커 지원
- [x] KOSPI/KOSDAQ 지수 조회
- [x] OHLCV 데이터 (일봉, 주봉, 월봉)
- [x] 주요 20개 종목 사전 등록

#### 2. UI/UX
- [x] 한국/미국 탭 분리
- [x] KRW 가격 표시 (₩)
- [x] KOSPI/KOSDAQ 지수 실시간 표시
- [x] 주요 종목 현황 대시보드
- [x] 종목 검색 기능

#### 3. 티커 관리
- [x] 자동 시장 감지 (KR/US)
- [x] 티커 정규화 (005930 → 005930.KS)
- [x] 종목명 변환 (삼성전자 → 005930.KS)
- [x] 시장별 통화/시간대 처리

#### 4. 분석 지원
- [x] 기술적 지표 (RSI, MACD, MA 등)
- [x] 한국 시장 특성 반영된 에이전트 지시문
- [x] Multi-Agent 분석 지원 (.KS 티커로 분석 가능)

### 개발 예정 기능 🔨

#### Phase 2 기능
- [ ] 외국인/기관/개인 매매 동향 분석
- [ ] 프로그램 매매 데이터 수집
- [ ] 테마주 연동 분석
- [ ] DART 전자공시 연동
- [ ] 한국어 뉴스 감성 분석

---

## 📊 사용 예시

### 예시 1: 삼성전자 분석

```python
# 1. 데이터 수집
from korean_stocks import KoreanStockData

collector = KoreanStockData()
df = collector.fetch_ohlcv("005930", period="1y")

# 2. 시장 정보
from ticker_manager import get_stock_info

info = get_stock_info("005930")
print(info)
# {
#   'ticker': '005930.KS',
#   'name': '삼성전자',
#   'market': 'KR',
#   'currency': 'KRW',
#   ...
# }

# 3. Multi-Agent 분석 (API 사용)
import requests

response = requests.get("http://localhost:8100/multi-agent/005930.KS")
result = response.json()
```

### 예시 2: WebUI에서 사용

1. **Home 페이지**
   - 🇰🇷 Korean Market 탭 클릭
   - KOSPI: 2,500.00 (+2.07%)
   - KOSDAQ: 850.00 (+1.50%)
   - 주요 종목 6개 현황 확인

2. **종목 검색**
   - "삼성" 입력
   - 삼성전자, 삼성SDI, 삼성바이오로직스 등 결과 표시

3. **분석 실행**
   - Sidebar에서 "005930" 입력
   - Multi-Agent 또는 Detail 페이지에서 분석 결과 확인

---

## 🧪 테스트

### 통합 테스트 실행
```bash
python3 test_korean_stocks.py
```

### 테스트 항목
1. ✅ 한국 주식 데이터 수집
2. ✅ KOSPI/KOSDAQ 지수 조회
3. ✅ 종목 검색
4. ✅ 티커 관리자 (시장 감지, 정규화)
5. ✅ WebUI 통합 (탭, import)
6. ✅ 데이터 품질 (OHLCV, NULL 체크)

### 예상 결과
```
======================================================================
✅ 전체 테스트 완료!
======================================================================

다음 단계:
  1. WebUI 실행: streamlit run stock_analyzer/webui.py
  2. Home 페이지에서 🇰🇷 Korean Market 탭 확인
  3. Sidebar에서 한국 주식 코드 입력 (예: 005930)
```

---

## 📝 주요 종목 코드 참고

### KOSPI 대형주
| 코드 | 종목명 | 섹터 |
|------|--------|------|
| 005930 | 삼성전자 | 반도체 |
| 000660 | SK하이닉스 | 반도체 |
| 035420 | NAVER | 인터넷 |
| 005380 | 현대차 | 자동차 |
| 051910 | LG화학 | 화학 |
| 006400 | 삼성SDI | 2차전지 |
| 035720 | 카카오 | 인터넷 |
| 207940 | 삼성바이오로직스 | 바이오 |
| 068270 | 셀트리온 | 바이오 |
| 028260 | 삼성물산 | 종합상사 |

### 금융주
| 코드 | 종목명 |
|------|--------|
| 105560 | KB금융 |
| 055550 | 신한지주 |
| 032830 | 삼성생명 |

### 통신/IT
| 코드 | 종목명 |
|------|--------|
| 017670 | SK텔레콤 |
| 018260 | 삼성SDS |
| 009150 | 삼성전기 |

---

## ⚙️ 설정 옵션

### 1. Yahoo Finance 티커 형식
한국 주식은 Yahoo Finance에서 다음 형식을 사용합니다:
- **KOSPI**: {종목코드}.KS (예: 005930.KS)
- **KOSDAQ**: {종목코드}.KQ (예: 900140.KQ)

시스템이 자동으로 변환하므로 사용자는:
- `005930` ← 이렇게 입력하면
- `005930.KS` ← 자동으로 변환됩니다

### 2. 시간대 설정
- 한국: Asia/Seoul (KST, UTC+9)
- 미국: US/Eastern (EST, UTC-5)

`TickerManager`가 자동으로 시간대를 처리합니다.

### 3. 통화 표시
- 한국: ₩ (KRW)
- 미국: $ (USD)

`format_price()` 함수가 시장별로 자동 포맷팅합니다.

---

## 🔧 트러블슈팅

### 문제 1: "한국 주식 모듈을 사용할 수 없습니다"
**원인**: korean_stocks.py 또는 ticker_manager.py import 실패

**해결**:
```bash
# 파일 존재 확인
ls -la stock_analyzer/korean_stocks.py
ls -la stock_analyzer/ticker_manager.py

# Python 경로 확인
python3 -c "import sys; print(sys.path)"

# 직접 import 테스트
python3 -c "from stock_analyzer.korean_stocks import KoreanStockData"
```

### 문제 2: Yahoo Finance 데이터 없음
**원인**: .KS/.KQ 티커가 Yahoo에 없거나 네트워크 문제

**해결**:
```bash
# yfinance 버전 확인
pip show yfinance

# 직접 테스트
python3 -c "import yfinance as yf; print(yf.Ticker('005930.KS').history(period='5d'))"

# 필요시 업데이트
pip install --upgrade yfinance
```

### 문제 3: KOSPI/KOSDAQ 지수 로드 실패
**원인**: Yahoo Finance에서 ^KS11, ^KQ11 티커 조회 실패

**해결**:
- 인터넷 연결 확인
- Yahoo Finance API 상태 확인
- 일시적 문제면 잠시 후 재시도

---

## 📈 향후 개선 계획

### Short-term (1-2주)
- [ ] 네이버 금융 스크래핑 구현
- [ ] 외국인/기관 매매 데이터 수집
- [ ] 한국 주식 전용 Watchlist 분리

### Mid-term (1개월)
- [ ] DART API 연동
- [ ] 한국어 뉴스 감성 분석
- [ ] 테마주 자동 연동

### Long-term (3개월)
- [ ] 한국 주식 백테스팅 특화
- [ ] 한국 시장 전용 ML 모델
- [ ] 프로그램 매매 분석

---

## 💡 참고 자료

### API 문서
- [Yahoo Finance (yfinance)](https://github.com/ranaroussi/yfinance)
- [DART Open API](https://opendart.fss.or.kr/)
- [KRX 정보데이터시스템](http://data.krx.co.kr/)

### 한국 주식 라이브러리
- [pykrx](https://github.com/sharebook-kr/pykrx)
- [FinanceDataReader](https://github.com/financedata-org/FinanceDataReader)
- [dart-fss](https://github.com/josw123/dart-fss)

---

## ❓ FAQ

### Q1: 한국 주식 실시간 데이터를 지원하나요?
A: 현재는 일봉 데이터만 지원합니다. Yahoo Finance는 15-20분 지연 데이터를 제공합니다.

### Q2: 모든 한국 주식을 지원하나요?
A: 현재는 주요 20개 종목이 사전 등록되어 있습니다. 다른 종목도 6자리 코드(.KS 형식)로 조회 가능하지만, 종목명 검색은 지원되지 않을 수 있습니다.

### Q3: Multi-Agent 분석이 한국 주식에도 작동하나요?
A: 네! .KS 티커로 `/multi-agent/005930.KS` 엔드포인트를 호출하면 됩니다. 다만 에이전트가 한국 시장 특성을 100% 이해하진 못할 수 있으므로, `KOREAN_STOCK_AGENT_INSTRUCTIONS.md`를 참고하여 프롬프트를 개선하세요.

### Q4: 외국인/기관 매매 데이터는 언제 추가되나요?
A: 네이버 금융 스크래핑 구현이 완료되면 추가될 예정입니다 (Phase 2).

---

*최종 업데이트: 2026-04-15*
*작성자: Stock AI Development Team*