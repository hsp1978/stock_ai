# 🇰🇷 한국 주식 통합 계획서
## Korean Stock Market Integration Plan for Stock AI System

### 📅 작성일: 2026-04-15
### 🎯 목표: 현재 미국 주식 전용 시스템을 한국 주식도 지원하도록 확장

---

## 1. 🔍 현황 분석

### 현재 시스템 구조
- **데이터 소스**: Yahoo Finance (미국 주식 전용)
- **기술적 분석**: TA-Lib 기반 지표들
- **LLM 분석**: ollama (영어 중심)
- **시간대**: EST/EDT (미국 동부 시간)
- **통화**: USD
- **거래 시간**: 09:30-16:00 EST

### 주요 차이점 분석
| 구분 | 미국 주식 | 한국 주식 |
|------|----------|----------|
| 티커 형식 | AAPL, MSFT | 005930.KS (삼성전자) |
| 거래 시간 | 09:30-16:00 EST | 09:00-15:30 KST |
| 시간대 | UTC-5 (EST) | UTC+9 (KST) |
| 통화 | USD | KRW |
| 데이터 소스 | Yahoo Finance | KRX, Naver, Daum |
| 뉴스 소스 | Bloomberg, Reuters | 연합뉴스, 한경 |
| 공시 | SEC (EDGAR) | DART |

---

## 2. 🏗️ 구현 계획

### Phase 1: 데이터 수집 레이어 (2주)

#### 1.1 데이터 소스 통합
```python
# stock_analyzer/data_sources/korean_stocks.py

class KoreanStockDataCollector:
    """한국 주식 데이터 수집기"""

    def __init__(self):
        self.sources = {
            'krx': KRXDataSource(),        # 한국거래소
            'naver': NaverFinance(),        # 네이버 금융
            'daum': DaumFinance(),          # 다음 금융
            'yahoo': YahooFinanceKorea()   # Yahoo Finance KS
        }

    def fetch_ohlcv(self, ticker: str, period: str = '1y'):
        """OHLCV 데이터 수집"""
        # 005930 → 005930.KS 변환
        # KRX API 또는 웹 스크래핑
        pass

    def fetch_fundamentals(self, ticker: str):
        """재무제표 데이터"""
        # DART API 활용
        pass
```

#### 1.2 티커 코드 관리
```python
# stock_analyzer/ticker_manager.py

class TickerManager:
    """통합 티커 관리 시스템"""

    KOREAN_STOCKS = {
        '005930': {'name': '삼성전자', 'yahoo': '005930.KS', 'krx': '005930'},
        '000660': {'name': 'SK하이닉스', 'yahoo': '000660.KS', 'krx': '000660'},
        '035420': {'name': 'NAVER', 'yahoo': '035420.KS', 'krx': '035420'},
        # ... 주요 종목들
    }

    def normalize_ticker(self, ticker: str, market: str = 'auto'):
        """티커 정규화: 005930 → 005930.KS"""
        if market == 'auto':
            market = self.detect_market(ticker)

        if market == 'KR':
            return self.to_yahoo_format(ticker)
        return ticker
```

### Phase 2: 분석 엔진 확장 (2주)

#### 2.1 Multi-Agent 한국어 지원
```python
# stock_analyzer/multi_agent_korean.py

class KoreanStockAgent:
    """한국 주식 전용 에이전트"""

    def __init__(self):
        self.agents = {
            'technical': KoreanTechnicalAnalyst(),
            'fundamental': KoreanFundamentalAnalyst(),
            'news': KoreanNewsAnalyst(),
            'foreign': ForeignInvestorAnalyst(),  # 외인/기관 동향
            'theme': ThemeAnalyst()  # 테마주 분석
        }

    def analyze(self, ticker: str):
        # 한국 시장 특성 반영
        # - 외인/기관 매매 동향
        # - 프로그램 매매
        # - 테마/섹터 동향
        pass
```

#### 2.2 한국 시장 특화 지표
```python
# chart_agent_service/korean_indicators.py

class KoreanMarketIndicators:
    """한국 시장 특화 지표"""

    def foreign_institution_flow(self, ticker: str):
        """외인/기관 순매수 추이"""
        pass

    def program_trading_volume(self, ticker: str):
        """프로그램 매매 동향"""
        pass

    def kospi_kosdaq_correlation(self, ticker: str):
        """KOSPI/KOSDAQ 상관관계"""
        pass

    def theme_momentum(self, ticker: str):
        """테마 모멘텀 지수"""
        pass
```

### Phase 3: WebUI 통합 (1주)

#### 3.1 UI/UX 개선
```python
# stock_analyzer/webui.py 수정사항

def render_home():
    # 시장 선택 옵션 추가
    market = st.selectbox(
        "시장 선택",
        ["🇺🇸 미국 (US)", "🇰🇷 한국 (KR)", "🌍 글로벌"],
        key="market_select"
    )

    if market == "🇰🇷 한국 (KR)":
        # 한국 주식 전용 UI
        render_korean_stocks()
    else:
        # 기존 미국 주식 UI
        render_us_stocks()

def render_korean_stocks():
    """한국 주식 전용 대시보드"""
    # KOSPI/KOSDAQ 지수
    # 업종별 히트맵
    # 외인/기관 동향
    # 프로그램 매매 현황
    pass
```

#### 3.2 통화 및 시간대 처리
```python
# stock_analyzer/utils/localization.py

class MarketLocalization:
    """시장별 현지화 처리"""

    def format_price(self, price: float, market: str):
        if market == 'KR':
            return f"₩{price:,.0f}"
        elif market == 'US':
            return f"${price:,.2f}"

    def convert_timezone(self, dt: datetime, market: str):
        if market == 'KR':
            return dt.astimezone(pytz.timezone('Asia/Seoul'))
        return dt.astimezone(pytz.timezone('US/Eastern'))
```

### Phase 4: 데이터베이스 스키마 확장 (1주)

#### 4.1 DB 스키마 수정
```sql
-- 한국 주식 테이블 추가
CREATE TABLE korean_stocks (
    ticker VARCHAR(10) PRIMARY KEY,
    name VARCHAR(100),
    market VARCHAR(10),  -- KOSPI/KOSDAQ
    sector VARCHAR(50),
    industry VARCHAR(50),
    market_cap BIGINT,
    listed_shares BIGINT,
    foreign_ratio FLOAT  -- 외국인 지분율
);

-- 외인/기관 매매 기록
CREATE TABLE institutional_trading (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker VARCHAR(10),
    date DATE,
    foreign_buy BIGINT,
    foreign_sell BIGINT,
    institution_buy BIGINT,
    institution_sell BIGINT,
    individual_buy BIGINT,
    individual_sell BIGINT
);
```

### Phase 5: API 통합 (1주)

#### 5.1 한국 금융 API 연동
```python
# config/korean_api.py

KOREAN_API_CONFIG = {
    'dart': {  # 전자공시시스템
        'api_key': 'YOUR_DART_API_KEY',
        'base_url': 'https://opendart.fss.or.kr/api/'
    },
    'krx': {  # 한국거래소
        'base_url': 'http://data.krx.co.kr/'
    },
    'naver': {  # 네이버 금융
        'base_url': 'https://finance.naver.com/'
    }
}
```

---

## 3. 📊 예상 데이터 소스

### 무료 데이터 소스
1. **Yahoo Finance Korea** (.KS, .KQ 티커)
   - 일봉 OHLCV 데이터
   - 기본 재무제표

2. **네이버 금융 API/스크래핑**
   - 실시간 가격
   - 외인/기관 매매동향
   - 뉴스 및 공시

3. **DART Open API** (무료)
   - 기업 공시 정보
   - 재무제표 상세

4. **KRX 정보데이터시스템**
   - 시장 통계
   - 업종별 지수

### 유료 데이터 소스 (선택사항)
- KRX DataShop
- FnGuide
- WiseF&

---

## 4. 🚀 구현 로드맵

### Week 1-2: 기초 인프라
- [ ] 한국 주식 데이터 수집 모듈 개발
- [ ] Yahoo Finance .KS/.KQ 티커 지원
- [ ] 네이버 금융 스크래핑 구현
- [ ] 티커 코드 변환 시스템

### Week 3-4: 분석 엔진
- [ ] 한국 시장 특화 지표 구현
- [ ] Multi-Agent 한국어 프롬프트 추가
- [ ] 외인/기관 매매 분석 로직

### Week 5: WebUI 통합
- [ ] 시장 선택 UI 구현
- [ ] 한국 주식 대시보드 개발
- [ ] 통화/시간대 현지화

### Week 6: 테스트 및 최적화
- [ ] 통합 테스트
- [ ] 성능 최적화
- [ ] 사용자 피드백 반영

---

## 5. 🎯 주요 기능 목록

### 핵심 기능
1. **종목 검색**: 한글명/영문명/코드 통합 검색
2. **실시간 시세**: KRW 표시, 전일 대비
3. **기술적 분석**: 한국 시장 거래시간 반영
4. **재무 분석**: DART 공시 연동
5. **뉴스 분석**: 한국어 뉴스 감성분석

### 한국 시장 특화 기능
1. **외인/기관 동향**: 순매수/순매도 추적
2. **프로그램 매매**: 차익거래 동향
3. **테마 분석**: 관련 테마주 연동
4. **공시 알림**: DART 주요 공시 알림
5. **업종 비교**: KOSPI/KOSDAQ 업종별 분석

---

## 6. 💻 예제 코드

### 통합 사용 예시
```python
# 미국 주식 분석
result_us = analyze_stock("AAPL", market="US")

# 한국 주식 분석
result_kr = analyze_stock("005930", market="KR")  # 삼성전자

# 자동 판별
result = analyze_stock("005930")  # 자동으로 한국 주식 인식
```

### WebUI에서 사용
```python
# Sidebar
market = st.sidebar.radio(
    "시장 선택",
    ["🇺🇸 미국", "🇰🇷 한국", "🌍 전체"]
)

if market == "🇰🇷 한국":
    ticker = st.selectbox(
        "종목 선택",
        ["005930 삼성전자", "000660 SK하이닉스", "035420 NAVER"]
    )

    # 한국 시장 특화 정보 표시
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("외국인 순매수", "₩2,350억")
    with col2:
        st.metric("기관 순매수", "₩-1,200억")
    with col3:
        st.metric("개인 순매수", "₩-1,150억")
```

---

## 7. 🔧 기술 스택

### 신규 추가 필요
```python
# requirements.txt 추가
pykrx==1.0.0          # 한국거래소 데이터
finance-datareader    # 한국 금융 데이터
dart-fss             # DART 공시 API
korean-lunar-calendar # 한국 공휴일 처리
konlpy               # 한국어 자연어 처리
```

### API 키 필요
- DART API Key (무료, 신청 필요)
- 네이버 API (선택사항)
- KRX API (선택사항)

---

## 8. 🚨 주의사항 및 리스크

### 기술적 도전과제
1. **데이터 수집**: 한국 시장 데이터는 미국보다 제한적
2. **실시간 데이터**: 무료 실시간 데이터 소스 제한
3. **언어 처리**: 한국어 뉴스/공시 분석 정확도

### 법적/규제 고려사항
1. **데이터 저작권**: 웹 스크래핑 시 약관 확인
2. **개인정보보호**: 사용자 데이터 처리
3. **투자 조언**: 투자 권유 금지 명시

### 성능 고려사항
1. **API 제한**: Rate limiting 처리
2. **데이터 저장**: KRW 큰 숫자 처리
3. **시간대 처리**: KST/EST 변환

---

## 9. 📈 예상 효과

### 사용자 확대
- 한국 개인투자자 유입
- 글로벌 투자자 한국 시장 분석 지원

### 기능 확장성
- 아시아 시장 확대 기반 마련
- 다국가 포트폴리오 분석 가능

### 차별화 요소
- 한/미 시장 통합 분석
- 외인/기관 동향 기반 AI 분석
- 한국어/영어 이중 언어 지원

---

## 10. 🏁 완료 체크리스트

### Phase 1 ✓
- [ ] 한국 주식 티커 데이터베이스 구축
- [ ] Yahoo Finance .KS/.KQ 연동
- [ ] 기본 OHLCV 데이터 수집 테스트

### Phase 2 ✓
- [ ] 외인/기관 매매 데이터 수집
- [ ] 한국어 뉴스 감성 분석
- [ ] DART 공시 연동

### Phase 3 ✓
- [ ] WebUI 한국 주식 페이지
- [ ] 통화/시간대 자동 변환
- [ ] 한국 시장 전용 차트

### Phase 4 ✓
- [ ] 통합 테스트 완료
- [ ] 문서화 완료
- [ ] 배포 준비 완료

---

## 📝 참고 자료

### 유용한 라이브러리
- [pykrx](https://github.com/sharebook-kr/pykrx): 한국거래소 주식 정보
- [FinanceDataReader](https://github.com/financedata-org/FinanceDataReader): 한국 금융 데이터
- [dart-fss](https://github.com/josw123/dart-fss): DART OpenAPI Python 라이브러리

### API 문서
- [DART Open API](https://opendart.fss.or.kr/): 전자공시 API
- [KRX 정보데이터시스템](http://data.krx.co.kr/): 한국거래소 데이터
- [네이버 증권](https://finance.naver.com/): 웹 스크래핑 대상

### 참고 프로젝트
- [korea-stock-analysis](https://github.com/example/korea-stock)
- [krx-trading-bot](https://github.com/example/krx-bot)

---

*작성자: Stock AI Development Team*
*최종 수정: 2026-04-15*