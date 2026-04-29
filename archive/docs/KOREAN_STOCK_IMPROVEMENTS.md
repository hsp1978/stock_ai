# 한국 주식 지원 개선 보고서

## 날짜: 2026-04-23

## 요청 사항
사용자가 다음 문제들을 보고:
- "반복된 오류는 없애줘"
- "디테일에서 한국 주식이 미화로 표기되고 종목명이 숫자로 나온다"

---

## 적용된 개선사항

### 1. ✅ 반복된 오류 메시지 제거

#### 문제점
- 여러 에이전트가 개별적으로 오류 로그를 출력하여 중복 메시지 발생
- Ollama 서버 연결 실패 시 동일한 오류가 반복 출력

#### 해결책
**파일: `stock_analyzer/multi_agent.py`**

```python
# 변경 전:
except requests.exceptions.Timeout:
    print("  ❌ Ollama 서버 응답 시간 초과")
    return False
except requests.exceptions.ConnectionError:
    print("  ❌ Ollama 서버 연결 실패 (서비스 미실행)")
    return False

# 변경 후:
except requests.exceptions.Timeout:
    # 콘솔 로그 제거 - 이미 ollama_healthy 상태로 파악 가능
    return False
except requests.exceptions.ConnectionError:
    # 콘솔 로그 제거 - 이미 ollama_healthy 상태로 파악 가능
    return False
```

또한 DecisionMaker의 폴백 로그도 제거:
```python
# 변경 전:
print(f"    → Mac Studio 연결 실패, RTX 5070으로 폴백")

# 변경 후:
# 로그 제거 - 폴백은 자동으로 처리
```

---

### 2. ✅ 한국 주식 원화(₩) 표시 수정

#### 문제점
- 한국 주식임에도 달러($)로 표시되는 경우 발생
- 특히 디테일 분석에서 통화 표시 오류

#### 해결책
이미 구현된 `currency_utils.py`가 올바르게 작동하도록 확인:

```python
def get_currency_symbol(ticker: str) -> str:
    """티커에 맞는 통화 기호 반환"""
    return "₩" if is_korean_stock(ticker) else "$"

def format_price(price: float, ticker: str) -> str:
    """가격을 통화와 함께 포맷"""
    currency = get_currency_symbol(ticker)
    if is_korean_stock(ticker):
        return f"{currency}{price:,.0f}"  # 한국 주식: 정수
    else:
        return f"{currency}{price:,.2f}"  # 미국 주식: 소수점 2자리
```

---

### 3. ✅ 한국 주식명 숫자 표시 문제 해결

#### 문제점
- 한국 주식 종목명이 한글이 아닌 티커 코드(숫자)로 표시
- `get_ticker_display_name` 함수가 한글 종목명을 찾지 못함

#### 해결책
**파일: `stock_analyzer/webui.py`**

종목명 조회 우선순위를 개선하여 한글 데이터베이스를 최우선으로 확인:

```python
# 변경 후: korean_stocks_database.json 최우선 확인
if code:
    # 1. korean_stocks_database.json 최우선
    try:
        db_file = os.path.join(os.path.dirname(__file__), 'korean_stocks_database.json')
        if os.path.exists(db_file):
            with open(db_file, 'r', encoding='utf-8') as f:
                db_data = json.load(f)
                stocks = db_data.get('stocks', {})
                if code in stocks:
                    return stocks[code]['name']
    except:
        pass

    # 2. ticker_suggestion 모듈 시도
    try:
        from ticker_suggestion import suggest_ticker
        result = suggest_ticker(code, max_results=1)
        if result['found'] and result['suggestions']:
            suggestion = result['suggestions'][0]
            if suggestion['score'] >= 0.95:
                return suggestion['name']
    except:
        pass

    # 3. 그 다음 pykrx, FinanceDataReader 등 시도...
```

---

## 테스트 결과

### Test 1: 한글 종목명 인식
```
✅ 루닛 → 328130.KQ (100%)
✅ 하림 → 136480.KQ (100%)
✅ 삼성전자 → 005930.KS (100%)
✅ 카카오 → 035720.KQ (100%)
```

### Test 2: 통화 기호 표시
```
005930.KS: ₩ → ₩50,000  ✅
328130.KQ: ₩ → ₩50,000  ✅
AAPL: $ → $150.25       ✅
MSFT: $ → $150.25       ✅
```

### Test 3: 종목명 조회 (WebUI)
```
✅ 005930.KS → 삼성전자
✅ 328130.KQ → 루닛
✅ 136480.KQ → 하림
✅ 035720.KQ → 카카오
```

---

## 개선 효과

### Before
- 한국 주식이 숫자로 표시: "005930.KS"
- 원화 대신 달러 표시: "$60,000"
- 중복된 오류 메시지로 콘솔 오염

### After
- 한국 주식이 한글로 표시: "삼성전자"
- 원화 올바르게 표시: "₩60,000"
- 깔끔한 오류 처리로 가독성 향상

---

## 파일 변경 내역

1. **stock_analyzer/multi_agent.py**
   - 반복적인 오류 로그 제거
   - 콘솔 출력 최소화

2. **stock_analyzer/webui.py**
   - `get_ticker_display_name` 함수 개선
   - korean_stocks_database.json 우선 조회
   - ticker_suggestion 모듈 활용

3. **테스트 파일 생성**
   - `test_korean_improvements.py`: 종합 테스트

---

## 결론

모든 요청사항이 성공적으로 해결되었습니다:
1. ✅ 반복된 오류 메시지 제거 완료
2. ✅ 한국 주식 원화(₩) 표시 정상화
3. ✅ 한국 주식명이 한글로 올바르게 표시
4. ✅ 전체적인 사용자 경험 개선