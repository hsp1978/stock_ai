# DART API Key 설정 가이드
## DART (전자공시시스템) API Key Setup Guide

---

## 📋 DART API Key 발급 방법

### Step 1: DART 웹사이트 회원가입
1. https://opendart.fss.or.kr/ 접속
2. 우측 상단 "회원가입" 클릭
3. 이용약관 동의 및 회원정보 입력
4. 이메일 인증 완료

### Step 2: API Key 신청
1. 로그인 후 "오픈API" 메뉴 클릭
2. "인증키 신청/관리" 선택
3. 신청 사유 입력 (예: "개인 주식 분석 프로젝트")
4. 즉시 발급됨! (보통 1분 이내)

### Step 3: API Key 확인
```
발급받은 API Key 예시:
xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx (40자리)
```

---

## 🔧 .env 파일 설정

### 위치
```
/home/ubuntu/stock_auto/stock_analyzer/.env
```

### 추가할 내용
```bash
# ══════════════════════════════════════════════════════════
# DART (전자공시시스템) API Key
# ══════════════════════════════════════════════════════════
# 발급: https://opendart.fss.or.kr/
# 무료, 회원가입 후 즉시 발급
# 용도: 한국 주식 공시 정보 조회
# ══════════════════════════════════════════════════════════

DART_API_KEY=여기에_발급받은_API_Key를_붙여넣으세요

# 예시:
# DART_API_KEY=abcd1234efgh5678ijkl9012mnop3456qrst7890
```

### 전체 .env 파일 예시
```bash
# ── 기존 API Keys ──
OPENAI_API_KEY=sk-proj-...
GOOGLE_API_KEY=AIza...
FRED_API_KEY=...
FMP_API_KEY=...

# ── 한국 주식 API Keys ──
DART_API_KEY=여기에_발급받은_API_Key를_붙여넣으세요

# ── Agent API 설정 ──
AGENT_API_HOST=localhost
AGENT_API_PORT=8100
```

---

## ✅ 설정 확인

### 방법 1: Python 스크립트로 확인
```bash
python3 -c "
import os
from dotenv import load_dotenv

load_dotenv('/home/ubuntu/stock_auto/stock_analyzer/.env')

dart_key = os.getenv('DART_API_KEY', '')

if dart_key and dart_key != '':
    print('✅ DART_API_KEY 설정 완료!')
    print(f'   Key 길이: {len(dart_key)}자')
    print(f'   앞 10자: {dart_key[:10]}...')
else:
    print('❌ DART_API_KEY가 설정되지 않았습니다.')
    print('   stock_analyzer/.env 파일을 확인하세요.')
"
```

### 방법 2: dart_api.py 테스트 스크립트
```bash
cd /home/ubuntu/stock_auto
python3 stock_analyzer/dart_api.py
```

**예상 출력 (API Key 설정 전):**
```
=== DART API 테스트 ===
⚠️ DART_API_KEY가 설정되지 않았습니다.

설정 방법:
1. https://opendart.fss.or.kr/ 에서 API Key 발급 (무료)
2. stock_analyzer/.env 파일에 추가:
   DART_API_KEY=your_api_key_here
```

**예상 출력 (API Key 설정 후):**
```
=== DART API 테스트 ===
✅ DART_API_KEY 설정됨

[Test 1] 삼성전자 최근 공시 (30일)
✅ 15개 공시 조회됨:
  - 20260415: 매출액 또는 손익구조 30%(대규모법인 15%)이상 변경
  - 20260410: 주요사항보고서
  - ...
```

---

## 🎯 DART API 사용 예시

### Python 코드에서
```python
from stock_analyzer.dart_api import DARTClient, get_recent_disclosures

# 클라이언트 생성
client = DARTClient()

# API Key 설정 확인
if client.is_configured():
    # 삼성전자 최근 공시
    disclosures = client.fetch_recent_disclosures("005930", days=30)

    for d in disclosures[:5]:
        print(f"{d['date']}: {d['title']}")

    # 재무제표 조회
    fs = client.fetch_financial_statement("005930", year=2025, quarter=1)
    print(fs)
else:
    print("DART API Key가 설정되지 않았습니다.")
```

### WebUI에서 (자동)
```
1. DART_API_KEY가 설정되어 있으면
2. 한국 주식 Detail 페이지에서
3. 자동으로 최근 공시 표시됨
```

---

## 📊 DART API로 조회 가능한 데이터

### 무료 제공 데이터
- ✅ 정기 공시: 사업보고서, 분기/반기보고서
- ✅ 주요사항보고서: 합병, 분할, 자산 양수도 등
- ✅ 재무제표: 손익계산서, 재무상태표, 현금흐름표
- ✅ 배당 정보
- ✅ 감사보고서
- ✅ 지분 공시

### API 제한사항
- 일일 호출 제한: 10,000건
- 분당 호출 제한: 1,000건
- 일반적 사용: 충분함

---

## ⚠️ 주의사항

### 1. API Key 보안
- .env 파일은 git에 커밋하지 마세요!
- .gitignore에 .env 추가 확인
- API Key 노출 시 재발급 가능

### 2. API 호출 최적화
- 캐싱 활용 (동일 공시 반복 조회 방지)
- 필요한 데이터만 조회
- Rate limiting 준수

### 3. 오류 처리
- API Key 미설정 시: 기능 비활성화 (오류 아님)
- 네트워크 오류: 재시도 로직
- 데이터 없음: 빈 배열 반환

---

## 🔄 시스템 재시작 (설정 적용)

### .env 파일 수정 후
```bash
# WebUI 재시작 (자동 재로드)
# 브라우저에서 새로고침하면 적용됨

# 또는 수동 재시작
pkill -f streamlit
streamlit run stock_analyzer/webui.py --server.port 8501

# Agent Service는 재시작 불필요 (동적 로드)
```

---

## 📝 빠른 시작 체크리스트

- [ ] DART 웹사이트 회원가입
- [ ] API Key 발급 (1분)
- [ ] API Key 복사
- [ ] `/home/ubuntu/stock_auto/stock_analyzer/.env` 파일 열기
- [ ] `DART_API_KEY=발급받은키` 추가
- [ ] 파일 저장
- [ ] `python3 stock_analyzer/dart_api.py` 실행하여 확인
- [ ] WebUI 새로고침

---

*설정 완료 후 한국 주식 Detail 페이지에서 최근 공시를 자동으로 볼 수 있습니다!*