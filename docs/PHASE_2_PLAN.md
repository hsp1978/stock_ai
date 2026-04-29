# Phase 2 작업 계획서

**프로젝트**: Stock AI Analysis System — 자동화 매매 확장
**대상 항목**: #7 증권사 API 연동 · #8 실시간 데이터 소스 통합
**작성일**: 2026-04-19
**상태**: 계획 — 착수 전
**예상 공수**: 6~10주 (1인 기준)

---

## 0. Executive Summary

현재 시스템(Sprint 1~3 완료 기준)은 **분석/판단/알림까지 자동화**되어 있으나, 매매 실행은 사용자가 증권 앱에 수동 입력해야 합니다. Phase 2는 이 마지막 갭을 메워 **분석 → 주문 실행**까지 단일 파이프라인으로 만드는 작업입니다.

핵심 가치:
- **분석 신호의 사실상 수익률 회복**: 분석 완료 ↔ 실제 주문 사이 15분~수시간 지연 제거 → 신호 신뢰도 30~40% 복원 추정
- **24시간 무인 운영**: 장 중 발생하는 기회·위험에 즉각 대응
- **실시간 리스크 관리**: 15분 지연 데이터 기반 trailing stop의 체결 불확실성 해소

위험: 실제 자금이 움직이므로 **단계적 dry-run 검증**, **승인 게이트**, **금액 상한** 필수.

---

## 1. 현재 상태 (As-Is)

### 1.1 완료된 역량 (Sprint 1~3)
| 영역 | 상태 |
|------|-----|
| 16개 분석 도구 + 6개 멀티에이전트 | ✅ |
| 백테스트 거래비용/호가단위 반영 | ✅ |
| 매매 시점·분할·손절익절 계획 출력 | ✅ |
| 신호 적중률 추적 + 신뢰도 칼리브레이션 | ✅ |
| Telegram 풍부한 알림 + 인라인 버튼 | ✅ |
| 일일/주간 자동 스케줄 (scanner) | ✅ |

### 1.2 핵심 제약
1. `paper_trader.py:7` — "실제 주문 집행 없음 (시뮬레이션 전용)"
2. `data_collector.py` — yfinance 15분 지연 데이터
3. 증권사 어댑터 코드 부재 (grep으로 `broker`, `order_execution`, `한투` 등 검색 시 0건)
4. 실시간 스트리밍 인프라 부재 — WebSocket 구현 없음

### 1.3 아키텍처 종속성
```
[scanner] → [service/analyze] → [multi_agent] → [entry_plan]
                                                     ↓
                                               [Telegram 알림]
                                                     ↓
                                          ❌ 사용자 수동 개입
                                                     ↓
                                              [증권사 앱]
```

Phase 2 완료 후:
```
[scanner] → [service/analyze] → [multi_agent] → [entry_plan]
                                                     ↓
                                          [broker_adapter]
                                                     ↓
                                          [dry-run 검증]
                                                     ↓
                                          [승인 게이트]
                                                     ↓
                                           [실제 주문 제출]
                                                     ↓
                                          [포지션 추적 + 텔레그램]
```

---

## 2. 범위 & 목표

### 2.1 포함
- ✅ 증권사 API 어댑터 인터페이스 (`BrokerInterface`)
- ✅ 최소 1개 미국 증권사 연동 (**Alpaca 권장**)
- ✅ 최소 1개 한국 증권사 연동 (**한국투자증권 KIS 권장**)
- ✅ 실시간 가격 데이터 통합 (**Polygon.io** 또는 KIS WebSocket)
- ✅ Dry-run / Approval / Live 3단계 실행 모드
- ✅ 주문 실행 로그 + 대시보드
- ✅ 일일 주문 금액 상한 + 긴급 중지 스위치

### 2.2 제외 (추후 과제로 분리)
- ❌ 키움증권 OpenAPI+ (Windows 32-bit COM 종속 → 별도 VM 필요)
- ❌ Interactive Brokers (유료 계좌 필요)
- ❌ 옵션·선물·암호화폐 거래
- ❌ 마진 거래
- ❌ 공매도 (short selling)
- ❌ 알고리즘 트레이딩 고빈도화 (<1초)

### 2.3 성공 기준
| 지표 | 목표 |
|------|------|
| Dry-run 주문 생성 → 성공률 | 100% (2주 운영) |
| 라이브 주문 제출 → 체결 확인 | 99% (N=50 이상) |
| 분석 완료 ↔ 주문 제출 지연 | < 3초 |
| 실시간 가격 업데이트 주기 | < 1초 |
| 일일 최대 주문 금액 위반 | 0건 |
| 긴급 중지 반응 시간 | < 5초 |
| 실전 적중률 추적 (Sprint 2 연계) | +10%p 상승 (수동 대비) |

---

## 3. 아키텍처 설계

### 3.1 신규 모듈 구조

```
chart_agent_service/
├── brokers/                    # 증권사 어댑터 패키지 (신규)
│   ├── __init__.py
│   ├── base.py                 # BrokerInterface, OrderRequest, OrderResult
│   ├── paper_broker.py         # 기존 paper_trader 래핑
│   ├── dry_run_broker.py       # 로그만 남기고 실제 제출 안 함
│   ├── alpaca_broker.py        # 미국 주식
│   ├── kis_broker.py           # 한국투자증권
│   └── safety.py               # 일일 상한/긴급 중지/승인 큐
│
├── data_sources/               # 데이터 소스 어댑터 (신규)
│   ├── __init__.py
│   ├── base.py                 # DataSource protocol
│   ├── yfinance_source.py      # 기존 (15분 지연)
│   ├── polygon_source.py       # Polygon.io REST + WebSocket
│   ├── alpaca_data_source.py   # Alpaca Market Data (Free tier)
│   └── kis_data_source.py      # KIS WebSocket (실시간 한국)
│
├── execution/                  # 주문 실행 오케스트레이션 (신규)
│   ├── order_router.py         # entry_plan → broker 주문 변환
│   ├── position_manager.py     # 보유 포지션 추적 + trailing stop
│   ├── approval_queue.py       # 사용자 승인 대기 큐 (텔레그램 연동)
│   └── audit_log.py            # 모든 주문 시도/결과 감사 로그
│
└── [기존 모듈 수정]
    ├── service.py               # /orders, /positions, /approval 엔드포인트
    ├── paper_trader.py          # BrokerInterface 준수하도록 리팩토링
    └── data_collector.py        # DataSource 추상화 위에 구축
```

### 3.2 핵심 인터페이스

```python
# brokers/base.py
from typing import Protocol, Literal
from dataclasses import dataclass

@dataclass
class OrderRequest:
    ticker: str
    qty: int
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop", "stop_limit"]
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: Literal["day", "gtc", "ioc"] = "day"
    client_order_id: str | None = None  # 중복 방지 idempotency key

@dataclass
class OrderResult:
    success: bool
    broker_order_id: str | None
    status: Literal["accepted", "rejected", "filled", "partial", "cancelled", "error"]
    filled_qty: int = 0
    avg_fill_price: float | None = None
    error_message: str | None = None
    raw_response: dict | None = None  # 디버깅용

class BrokerInterface(Protocol):
    def place_order(self, req: OrderRequest) -> OrderResult: ...
    def cancel_order(self, broker_order_id: str) -> bool: ...
    def get_order_status(self, broker_order_id: str) -> OrderResult: ...
    def get_positions(self) -> list[dict]: ...
    def get_account(self) -> dict: ...
    def is_market_open(self) -> bool: ...
```

### 3.3 실행 모드 (단계적 안전)

| 모드 | 동작 | 용도 |
|------|-----|------|
| `PAPER` | 페이퍼 트레이더만 | 현재 기본값, 항상 사용 가능 |
| `DRY_RUN` | 주문을 API 호출 직전까지 생성 + 로그 | 1주 운영 검증 |
| `APPROVAL` | 주문 생성 → 텔레그램 승인 대기 → 제출 | 초기 라이브 2주 |
| `LIVE` | 자동 제출 | 충분 검증 후 |

`TRADING_MODE` 환경변수로 제어 + 런타임에서 웹UI/텔레그램 토글 가능.

### 3.4 데이터 소스 스위칭

```python
# config.py
DATA_SOURCE = os.getenv("DATA_SOURCE", "yfinance")  # yfinance | polygon | alpaca | kis

# data_sources/__init__.py
def get_data_source() -> DataSource:
    name = os.getenv("DATA_SOURCE", "yfinance")
    return {
        "yfinance": YFinanceSource,
        "polygon": PolygonSource,
        "alpaca": AlpacaDataSource,
        "kis": KISDataSource,
    }[name]()
```

---

## 4. Phase 2 단계별 계획

### Phase 2.1 — 기반 인프라 (2주)

**목표**: 증권사/데이터 소스 추상화 + Paper/DryRun 브로커

| Week | 작업 | 산출물 |
|------|-----|-------|
| 1 | BrokerInterface / OrderRequest / OrderResult 설계 | `brokers/base.py` |
| 1 | 기존 `paper_trader.py`를 `PaperBroker` 클래스로 리팩토링 | `brokers/paper_broker.py` |
| 1 | `DryRunBroker` — 주문 로깅만 | `brokers/dry_run_broker.py` |
| 2 | `safety.py` — 일일 상한, kill switch | `brokers/safety.py` |
| 2 | `order_router.py` — entry_plan → OrderRequest 변환 | `execution/order_router.py` |
| 2 | `approval_queue.py` — 텔레그램 승인 연동 | `execution/approval_queue.py` |
| 2 | `audit_log.py` — SQLite 기반 모든 주문 시도 기록 | `execution/audit_log.py` |
| 2 | 단위 테스트 + 통합 테스트 (Paper/DryRun) | `tests/phase2/` |

**완료 기준**:
- [ ] Paper → DryRun 전환이 환경변수 1개로 가능
- [ ] DryRun 로그에서 OrderRequest 전부 확인
- [ ] 텔레그램 승인 버튼 → 큐 반영 → 승인 후 실행

---

### Phase 2.2 — 미국 증권사 (Alpaca) (1~1.5주)

**왜 Alpaca 먼저?**
- 무료, REST + WebSocket, 한국어 이슈 없음
- Paper 계좌 자동 제공 (실계좌 없이 테스트 가능)
- 공식 Python SDK (`alpaca-py`)

**작업**:
| Day | 작업 |
|-----|-----|
| 1 | Alpaca 계정 생성 (Paper), API 키 발급 |
| 1-2 | `alpaca_broker.py` 구현 — BrokerInterface 준수 |
| 2-3 | `alpaca_data_source.py` — REST 과거데이터 + WebSocket 실시간 |
| 4 | 기존 `AAPL`, `NVDA` 등 watchlist로 Paper 계좌에서 주문 테스트 |
| 5-7 | 통합 테스트: 분석 → 주문 → 체결 확인 → 포지션 추적 |

**체크리스트**:
- [ ] market order, limit order, stop-loss, take-profit 각각 제출 확인
- [ ] 부분 체결(partial fill) 핸들링
- [ ] 주문 취소 정상 동작
- [ ] 시장 휴장일 처리
- [ ] fractional share 지원 여부 확인

---

### Phase 2.3 — 한국 증권사 (KIS) (2~3주)

**왜 KIS?**
- 개인 무료 (계좌 보유자)
- 공식 REST API + WebSocket (최근 Python 샘플 공식 제공)
- 실시간 시세 포함

**난이도 포인트**:
- OAuth 2.0 토큰 갱신 (24시간 만료)
- 종목 코드 포맷 (`.KS`/`.KQ` ↔ 순수 6자리)
- 가격 호가단위 (Sprint 1에서 구현한 `tick_size.py` 재활용)
- 거래 가능 시간 (09:00~15:30 KST)
- 한국 특유 주문 유형 (IOC/FOK, 시간외단일가 등)

**작업**:
| Day | 작업 |
|-----|-----|
| 1-2 | KIS 개발자 계정 + 앱 등록 + 모의투자 계좌 |
| 3-5 | `kis_broker.py` — 토큰 발급 + 현금 매수/매도 |
| 6-8 | `kis_data_source.py` — REST 분봉 + WebSocket 체결 스트림 |
| 9-11 | 모의투자 계좌로 watchlist 전체 자동 매매 시뮬레이션 |
| 12-14 | 실계좌 연동 — 소액(50만원) 테스트 |
| 15 | 통합 테스트 + 장애 복구 시나리오 |

**체크리스트**:
- [ ] 삼성전자 매수/매도 왕복 성공 (모의)
- [ ] WebSocket 재연결 자동 복구
- [ ] 장 시작/마감 전환 자동 처리
- [ ] 호가단위 오류 → 자동 보정 (Sprint 1 `round_to_tick` 활용)
- [ ] 예수금 부족 → 수량 자동 조정 또는 거절
- [ ] 실계좌 소액 테스트 10건 완료

---

### Phase 2.4 — 실시간 데이터 통합 (1주)

**선택지**:
| 소스 | 가격 | 지연 | 시장 | 권장 |
|-----|------|------|------|------|
| Polygon.io Starter | $29/월 | 실시간 | 미국 전체 | ⭐ 미국 |
| Alpaca Data Free | $0 | 15분 | 미국 | 보조 |
| Alpaca Unlimited | $99/월 | 실시간 | 미국 | 대안 |
| KIS WebSocket | $0 | 실시간 | 한국 | ⭐ 한국 |
| 키움 OpenAPI+ | $0 | 실시간 | 한국 | 제외 (Windows) |

**작업**:
- Polygon WebSocket client (채널 구독: trades, quotes, aggregates)
- KIS WebSocket client (이미 Phase 2.3에서 기본 구현)
- 가격 피드 버퍼 + 종목별 최신가 캐시
- 1초 단위 trailing stop 재평가

**주의**:
- WebSocket 끊김 처리 (지수 백오프)
- 메시지 드롭 탐지 (시퀀스 번호 확인)
- 시간 동기화 (NTP, 장중 clock drift)

---

### Phase 2.5 — 통합 & 운영 준비 (1.5주)

**작업**:
- **WebUI 새 페이지**:
  - `📦 Orders` — 현재 주문 큐, 체결 이력
  - `📍 Positions` — 실시간 포지션 + 손익
  - `🛡️ Approval` — 대기 중 승인 요청
  - `⚙️ Trading Settings` — 모드 전환, 한도 설정, Kill Switch
- **Telegram 확장**:
  - 주문 제출 확인 알림
  - 체결 알림 (부분/전체)
  - 손절/익절 발동 알림
  - Kill Switch 발동 알림
- **모니터링**:
  - Prometheus/Grafana 연동 (선택) 또는 자체 대시보드
  - 주요 지표: 일일 주문수, 체결률, 평균 슬리피지, API 에러율
- **장애 복구 시나리오**:
  - 증권사 API 다운 → 주문 큐에 쌓고 재시도
  - WebSocket 끊김 → REST 폴링으로 폴백
  - 예상치 못한 포지션 (reconciliation) 감지

**운영 안정화**:
| 기간 | 모드 | 검증 |
|-----|------|------|
| 1주 | DRY_RUN | 모든 주문 로그만 |
| 2주 | APPROVAL (소액) | 승인 후 제출, 텔레그램 확인 |
| 1개월 | APPROVAL (일반) | 일일 한도 50만원 |
| ∞ | LIVE (점진적) | 한도 단계적 상향 |

---

## 5. 기술 스펙

### 5.1 신규 Python 의존성

```
alpaca-py>=0.21       # Alpaca Broker API
polygon-api-client>=1.13  # Polygon.io
websocket-client>=1.6     # WebSocket (KIS용)
```

KIS는 공식 SDK가 없어 httpx 직접 호출로 구현 (이미 의존성 있음).

### 5.2 환경변수 추가

```bash
# Phase 2 — 매매 실행
TRADING_MODE=paper  # paper | dry_run | approval | live
DAILY_ORDER_LIMIT_USD=1000
DAILY_ORDER_LIMIT_KRW=1000000
KILL_SWITCH=false

# Alpaca
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
ALPACA_BASE_URL=https://paper-api.alpaca.markets  # paper → live

# KIS
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ACCOUNT_NO=
KIS_ACCOUNT_PROD_CD=01
KIS_BASE_URL=https://openapivts.koreainvestment.com:29443  # mock → prod

# Phase 2 — 실시간 데이터
DATA_SOURCE=yfinance  # yfinance | polygon | alpaca | kis
POLYGON_API_KEY=
```

### 5.3 DB 스키마 추가

```sql
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY,
  client_order_id TEXT UNIQUE,
  broker TEXT,              -- alpaca | kis | paper | dry_run
  ticker TEXT,
  side TEXT,
  qty INTEGER,
  order_type TEXT,
  limit_price REAL,
  stop_price REAL,
  status TEXT,              -- pending | submitted | filled | partial | cancelled | rejected | error
  filled_qty INTEGER DEFAULT 0,
  avg_fill_price REAL,
  broker_order_id TEXT,
  entry_plan_snapshot TEXT, -- JSON: 의사결정 당시 계획
  submitted_at TEXT,
  filled_at TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY,
  broker TEXT,
  ticker TEXT,
  qty INTEGER,
  avg_entry_price REAL,
  current_price REAL,
  unrealized_pnl_pct REAL,
  stop_loss REAL,
  take_profit REAL,
  trailing_high REAL,
  entry_order_id INTEGER,
  opened_at TEXT,
  last_updated_at TEXT,
  FOREIGN KEY (entry_order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS approval_queue (
  id INTEGER PRIMARY KEY,
  order_request TEXT,       -- JSON: OrderRequest
  status TEXT,              -- pending | approved | rejected | expired
  requested_at TEXT,
  responded_at TEXT,
  responder TEXT            -- telegram user / system
);
```

### 5.4 신규 API 엔드포인트

| Method | Path | 용도 |
|--------|------|------|
| POST | `/orders` | 주문 제출 (모드에 따라 실행) |
| GET | `/orders?status=pending` | 주문 조회 |
| POST | `/orders/{id}/cancel` | 주문 취소 |
| GET | `/positions` | 현재 포지션 |
| GET | `/approval/pending` | 승인 대기 목록 |
| POST | `/approval/{id}/approve` | 승인 |
| POST | `/approval/{id}/reject` | 거절 |
| POST | `/kill-switch/activate` | 긴급 중지 (모든 미체결 주문 취소 + 신규 금지) |
| POST | `/kill-switch/deactivate` | 해제 |
| GET | `/trading-mode` | 현재 모드 조회 |
| PUT | `/trading-mode` | 모드 변경 (paper/dry_run/approval/live) |
| GET | `/broker/health` | 각 broker 연결 상태 |

---

## 6. 위험 분석 & 완화

| 위험 | 심각도 | 확률 | 완화 |
|------|--------|------|------|
| **자금 손실** (버그로 잘못된 주문) | 🔴 Critical | 중 | DRY_RUN 2주 필수, APPROVAL 모드 초기 2주, 일일 한도 |
| **중복 주문** (네트워크 재시도 오류) | 🔴 Critical | 중 | `client_order_id` idempotency key |
| **API 키 유출** | 🔴 Critical | 저 | .env 파일 .gitignore 확인 (이미 됨), 환경변수만 사용 |
| **증권사 API 장애** | 🟠 High | 중 | 주문 큐 + 재시도 + 사용자 알림 |
| **시간 동기화 오류** | 🟠 High | 저 | NTP, 주문 timestamp는 broker 응답 사용 |
| **레이스 컨디션** (동시 주문) | 🟠 High | 중 | position_manager에 mutex lock |
| **메모리 누수** (WebSocket long-run) | 🟡 Medium | 중 | 주기적 재연결, 메트릭 모니터 |
| **법적 규제** (무인가 투자자문) | 🟠 High | 저 | 본인 계좌만 사용, disclaimer 추가 |
| **세금 계산 누락** | 🟡 Medium | 중 | 연말 정산 시 수동, 거래 내역 export |
| **일일 한도 우회 버그** | 🔴 Critical | 저 | `safety.py` 단위 테스트 필수 |

### 6.1 필수 안전장치

```python
# safety.py 핵심 기능
class TradingSafety:
    def check_daily_limit(self, order: OrderRequest) -> bool:
        """오늘 이미 제출된 금액 + 이번 주문 금액 ≤ 한도"""

    def check_kill_switch(self) -> bool:
        """Kill Switch 활성화 시 모든 주문 거부"""

    def check_market_hours(self, order: OrderRequest) -> bool:
        """장외 주문 방지 (옵션)"""

    def check_max_position_size(self, order: OrderRequest) -> bool:
        """단일 종목 최대 비중 초과 방지 (config의 MAX_POSITION_PCT)"""

    def check_duplicate_order(self, client_order_id: str) -> bool:
        """10초 내 동일 client_order_id 중복 방지"""

    def require_all_checks(self, order: OrderRequest) -> tuple[bool, str]:
        """모든 체크를 통과해야 True. 실패 시 이유 반환."""
```

---

## 7. 의존성 & 선행 조건

### 7.1 외부 의존성
- [ ] Alpaca 계정 (무료) — 발급 https://alpaca.markets
- [ ] Polygon.io 계정 (Starter $29/월) — 선택
- [ ] 한국투자증권 개발자 계정 + 앱 등록
- [ ] 한국투자증권 모의투자 계좌 (무료)
- [ ] 한국투자증권 실계좌 (테스트용 소액, Phase 2.3 후반)

### 7.2 시스템 요구사항
- Python 3.10+ (이미 충족)
- 안정적 인터넷 (증권사 API 연결 유지)
- 시스템 시각 NTP 동기화
- 가상환경 + 프로덕션 서버 분리 권장

### 7.3 Sprint 1~3 산출물 재활용
- ✅ `tick_size.py` — KIS 호가단위 정합
- ✅ `trading_costs.py` — 실제 수수료 모델
- ✅ `entry_plan.py` — OrderRequest 변환 기반
- ✅ `signal_outcomes` 테이블 — 실제 주문 결과도 동일 구조로 추적
- ✅ Telegram 인라인 버튼 — 승인 플로우 재활용

---

## 8. 주요 결정 포인트 (Decision Points)

Phase 2 착수 전 또는 각 단계 전환 시 결정 필요:

| # | 질문 | 권장 |
|---|------|------|
| D1 | Alpaca vs IBKR 중 미국 브로커 선택 | **Alpaca** (무료, 쉬움) |
| D2 | 한국은 KIS vs 키움 | **KIS** (Python 친화) |
| D3 | 실시간 데이터 유료 지불? | **Phase 2.4에서 결정** (Polygon $29 vs Alpaca free) |
| D4 | APPROVAL 모드 건너뛰고 바로 LIVE? | **NO** — 최소 2주 필수 |
| D5 | 일일 한도 초기값 | **$500 / 50만원** |
| D6 | 대상 종목 제한 | 초기 **S&P 500 + KOSPI 200**만 |
| D7 | 주문 크기 상한 | 단일 주문 **$200 / 20만원** |
| D8 | 장외 주문 허용? | **NO** (초기) |
| D9 | 부분 체결 시 재주문? | **NO** (잔여 cancel 후 재평가) |
| D10 | 긴급 중지 트리거 | 시스템 1시간 5% 이상 손실 시 자동 활성화 |

---

## 9. 산출물 (Deliverables)

### 9.1 코드
- [ ] `chart_agent_service/brokers/` 패키지 (5개 파일)
- [ ] `chart_agent_service/data_sources/` 패키지 (4개 파일)
- [ ] `chart_agent_service/execution/` 패키지 (4개 파일)
- [ ] `tests/phase2/` 단위+통합 테스트 (목표 커버리지 80%)
- [ ] WebUI 4개 신규 페이지
- [ ] Telegram 알림 확장

### 9.2 문서
- [ ] `docs/PHASE_2_PLAN.md` (본 문서)
- [ ] `docs/BROKER_SETUP.md` — 각 증권사 계정 설정 가이드
- [ ] `docs/TRADING_MODES.md` — 4단계 모드 운영 가이드
- [ ] `docs/RUNBOOK.md` — 장애 대응 절차
- [ ] `README.md` 업데이트

### 9.3 운영 아티팩트
- [ ] `.env.example` 업데이트 (신규 환경변수 포함)
- [ ] `setup_v2.sh` 확장 (Alpaca/KIS 연결 체크)
- [ ] Grafana 대시보드 (선택)

---

## 10. 일정 Roll-up

```
Week 1-2   [Phase 2.1] 기반 인프라          ████████████████
Week 3-4   [Phase 2.2] Alpaca 연동          ████████░░░░░░░░
Week 5-7   [Phase 2.3] KIS 연동             ████████████████
Week 8     [Phase 2.4] 실시간 데이터          ████████░░░░░░░░
Week 9-10  [Phase 2.5] 통합 & 운영 준비     ████████████████
Week 11+   [운영 안정화] DryRun→Approval→Live 점진 전환
```

**마일스톤**:
- **M1 (Week 2)**: DRY_RUN 모드로 기존 Paper 결과와 동등
- **M2 (Week 4)**: Alpaca Paper 계좌에서 자동 매매 동작
- **M3 (Week 7)**: KIS 모의투자 자동 매매 동작
- **M4 (Week 8)**: 실시간 데이터 피드 안정화
- **M5 (Week 10)**: WebUI/Telegram 완전 통합, DRY_RUN 운영 개시
- **M6 (Week 12)**: APPROVAL 모드로 실계좌 소액 운영
- **M7 (Week 16)**: LIVE 모드 전환 결정

---

## 11. 성공 후 시스템 모습

```
[scanner 30분 주기]
     ↓
[multi_agent 분석 + entry_plan]
     ↓
[order_router] — entry_plan → OrderRequest
     ↓
[safety.require_all_checks()] — 일일한도/kill switch/중복
     ↓
  ┌─────────────────┐
  │ TRADING_MODE    │
  ├─────────────────┤
  │ PAPER    → paper_broker
  │ DRY_RUN  → audit_log만
  │ APPROVAL → approval_queue + Telegram 알림
  │ LIVE     → alpaca/kis broker 즉시 제출
  └─────────────────┘
     ↓
[broker 체결 확인] ↔ [position_manager]
     ↓
[실시간 WebSocket] — 현재가 업데이트
     ↓
[position_manager.check_exits()] — trailing stop/TP/SL
     ↓ (조건 충족 시)
[자동 청산 주문] → broker
     ↓
[signal_outcomes 업데이트] (Sprint 2와 연계)
     ↓
[Telegram 체결 알림] + WebUI Positions 페이지 업데이트
```

---

## 12. 착수 체크리스트

Phase 2 시작 직전 확인:

- [ ] Sprint 1~3 모든 기능 1주 안정 운영 확인
- [ ] `signal_outcomes` 테이블에 최소 100건 이상 축적
- [ ] Alpaca 계정 + API 키 발급
- [ ] KIS 개발자 계정 + 모의투자 계좌
- [ ] 프로덕션 서버 또는 전용 VM 확보 (24시간 가동)
- [ ] 백업 전략 (DB, .env, 로그)
- [ ] 긴급 연락 체계 (Telegram 관리자 알림 테스트)
- [ ] 초기 투입 자금 한도 결정
- [ ] 법적 검토 (본인 계좌 단독 사용 확인)

---

## 부록 A. 참고 자료

- Alpaca API Docs: https://docs.alpaca.markets
- 한국투자증권 Open API: https://apiportal.koreainvestment.com
- Polygon.io Docs: https://polygon.io/docs
- FINRA/SEC 규정 (미국 일중 규제)
- 자본시장법 시행령 (한국, 개인 투자자)

## 부록 B. 예상 운영 비용 (월)

| 항목 | 비용 |
|------|------|
| Alpaca Paper | $0 |
| Alpaca Live (수수료) | $0 (커미션 free) |
| KIS 모의투자 | $0 |
| KIS 실계좌 수수료 | 0.015% (자동 반영됨 — Sprint 1 `trading_costs.py`) |
| Polygon.io Starter | $29 |
| Ollama (로컬) | $0 |
| LLM 클라우드 (선택) | $0~$50 |
| 서버 (클라우드 VM) | $5~$20 |
| **합계** | **$30~$100/월** |

## 부록 C. 버전 관리

- **v1.0 (2026-04-19)**: 최초 작성
- 향후 업데이트: Phase 진행에 따라 각 섹션 상태 업데이트
