# EXECUTION_PLAN.md — Claude CLI 단계별 실행 지시서

> 본 문서는 Claude Code(CLI)에게 직접 던지는 작업 명령서다.
> 각 단계는 **독립 세션에서 진행 가능**하도록 self-contained으로 작성됨.
> 각 단계 = 1 git branch = 1 PR = 1 commit 시퀀스.
>
> **사용 방법** (사용자 → Claude Code):
> ```
> /clear
> 다음 단계를 진행해라: docs/EXECUTION_PLAN.md#step-1
> ```

---

## 0. 전체 진행 현황

| Step | 제목 | 우선순위 | 예상 공수 | 의존성 | 상태 |
|---|---|---|---|---|---|
| 1 | GlobalKillSwitch | P0 | 2일 | – | ✅ |
| 2 | SignalAggregator | P0 | 3일 | – | ✅ |
| 3 | OHLCV 캐시 freshness + retry | P0 | 3일 | – | ✅ |
| 4 | signal_outcomes 활성화 | P0 | 2일 | Step 3 | ✅ |
| 5 | MFI + RSI/MFI 조합 도구 | P1 | 2일 | – | ✅ |
| 6 | MACD + RSI cross-signal | P1 | 1일 | Step 5 | ✅ |
| 7 | Rule-based regime detector | P1 | 2일 | – | ✅ |
| 8 | Agent group 4분할 | P1 | 3일 | Step 7 | ✅ |
| 9 | LiteLLM + Circuit breaker + Structured output | P1 | 2.5일 | – | ✅ |
| 10 | 백테스트 가정 명시 + rf 차감 | P1 | 1.5일 | – | ✅ |
| 11 | pandas_market_calendars 도입 | P1 | 1일 | – | ✅ |
| 12 | Variance-aware aggregation | P1 | 1일 | Step 8 | ✅ |

**총 공수**: 약 24일 (단일 개발자 5–7주).

진행 순서 권고: 1 → 3 → 4 (안전망·측정 기반 먼저) → 9 (LLM 인프라) → 7 → 8 → 5 → 6 → 12 (시그널 품질) → 2 (배분) → 11 → 10 (보조).

---

## 단계 공통 규칙

### 시작 절차
```bash
cd /home/ubuntu/stock_auto
git pull origin main
git checkout -b feature/step-N-<short-name>
```

### 완료 절차
1. `pytest tests/ -x` 통과
2. `ruff check . && ruff format --check .` 통과
3. `mypy --ignore-missing-imports <changed-files>` 통과
4. `docker compose --profile dev up -d --build` 후 `curl -s http://localhost:8100/health` 정상
5. 커밋: `git commit -m "<type>(<scope>): <subject>"`
6. PR 생성: `gh pr create --title "Step N: <subject>" --body "Refs: docs/EXECUTION_PLAN.md#step-N"`
7. main 머지 후 본 문서의 상태 컬럼 ⬜ → ✅

### 작업 중단 시
- WIP 커밋: `git commit -m "wip(step-N): <progress>"`
- 다음 세션 시작 시 `/clear` 후 본 문서 해당 단계만 다시 로드

### 금지사항 (전 단계 공통)
1. 단계 범위 외 파일 임의 수정 금지
2. 신규 외부 의존성 추가 시 본 문서 또는 CLAUDE.md §8에 사전 명시된 것만
3. `.env` 변경 시 `.env.example`도 동시 갱신
4. LLM 호출 코드 신규 작성 시 Step 9 완료 후 LiteLLM Router 경유

---

## STEP 1 — GlobalKillSwitch 구현

### 목표
포트폴리오 일일 손실 한도, VIX 임계값, 데이터 신선도, 연속 손실 카운터를 기반으로 한 자동 거래 정지 메커니즘 도입.

### 변경 파일
**신규 생성**:
- `chart_agent_service/safety/__init__.py`
- `chart_agent_service/safety/kill_switch.py`
- `chart_agent_service/safety/models.py`
- `tests/unit/test_kill_switch.py`

**수정**:
- `chart_agent_service/config.py` — KillSwitchThresholds 필드 추가
- `chart_agent_service/service.py` — middleware 통합
- `chart_agent_service/db.py` — `kill_switch_events` 테이블 추가
- `.env.example` — 신규 환경변수 명시

### 신규 환경변수
```
DAILY_LOSS_LIMIT_ALERT_PCT=2.0
DAILY_LOSS_LIMIT_HARD_PCT=3.0
WEEKLY_DRAWDOWN_LIMIT_PCT=5.0
TRAILING_PEAK_DD_PCT=10.0
CONSECUTIVE_LOSS_COUNT=5
VIX_CAP=30.0
VIX_SPIKE_PCT=20.0
DATA_STALENESS_HALT_HOURS=6.0
COOL_DOWN_HOURS=24
```

### 구현 사양
1. `KillSwitchThresholds(BaseModel)` 정의 (위 env 매핑).
2. `KillSwitchEvent(BaseModel)`: `triggered_at`, `trigger_type`, `trigger_value`, `portfolio_pnl_pct`, `action: Literal["alert","halt","cool_down"]`, `cool_down_until`.
3. `GlobalKillSwitch` 클래스:
   - `evaluate(ctx: DecisionContext) -> list[KillSwitchEvent]`
   - `is_blocked() -> tuple[bool, str | None]`
   - 모든 이벤트는 `kill_switch_events` 테이블에 append-only 기록.
4. FastAPI middleware `kill_switch_middleware`:
   - `/decide`, `/scan`, `/paper/order`, `/execute` 진입 시 `is_blocked()` 평가.
   - 차단 시 HTTP 423 Locked + 차단 사유 JSON 반환.
5. DB 테이블:
```sql
CREATE TABLE IF NOT EXISTS kill_switch_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at TIMESTAMP NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_value REAL NOT NULL,
    portfolio_pnl_pct REAL,
    action TEXT NOT NULL,
    cool_down_until TIMESTAMP,
    metadata TEXT  -- JSON
);
CREATE INDEX idx_kse_triggered_at ON kill_switch_events(triggered_at);
CREATE INDEX idx_kse_action ON kill_switch_events(action);
```

### 테스트 시나리오 (tests/unit/test_kill_switch.py)
- daily_pnl_pct=-3.5 → action=halt
- daily_pnl_pct=-2.2 → action=alert
- vix=32 → action=halt
- 정상 상태 → events=[]
- cool_down_until > now() → is_blocked()=True
- middleware 423 응답 검증 (FastAPI TestClient)

### 완료 기준
- 모든 위 시나리오 pass
- 수동 검증: `curl -X POST http://localhost:8100/scan` 호출 시 강제로 kill_switch 활성화 → 423 응답 확인
- `kill_switch_events` 테이블에 이벤트 기록 확인

### 커밋 메시지
```
feat(kill-switch): GlobalKillSwitch + DAILY_LOSS_LIMIT + VIX cap

- KillSwitchThresholds Pydantic Settings에 9개 신규 필드
- /decide /scan /paper/order /execute 진입 시 is_blocked() 평가
- kill_switch_events 테이블 append-only 기록
- 차단 시 HTTP 423 Locked 반환

Refs: docs/EXECUTION_PLAN.md#step-1
```

---

## STEP 2 — SignalAggregator (종목당 단일 active position)

### 목표
다중 에이전트가 동일 종목에 BUY를 발주할 때 균등 트랜치 누적을 방지. 종목당 단일 active position 규칙 적용.

### 변경 파일
**신규 생성**:
- `chart_agent_service/signal/__init__.py`
- `chart_agent_service/signal/aggregator.py`
- `chart_agent_service/signal/models.py`
- `tests/unit/test_signal_aggregator.py`

**수정**:
- `chart_agent_service/service.py` — `/scan` 핸들러에 통합
- `chart_agent_service/paper_trader.py` — aggregator 결과 수신 후 발주
- `chart_agent_service/db.py` — `active_positions` 뷰

### 구현 사양

1. `SignalAggregator` 클래스:
```python
class SignalAggregator:
    def __init__(self, weights: dict[str, float],
                 conflict_window_days: int = 3,
                 conviction_threshold: float = 0.5):
        self.weights = weights  # {"agent_ensemble": 0.4, "ml_ensemble": 0.4, "tool_score": 0.2}
        self.window = conflict_window_days
        self.threshold = conviction_threshold

    def aggregate(self,
                  ticker: str,
                  agent_signals: list[AgentResult],
                  ml_signals: list[MLPrediction],
                  tool_outputs: dict[str, ToolResult],
                  active_positions: dict[str, Position]
                  ) -> Decision:
        # 1. 종목당 단일 active rule 검사
        # 2. conviction 합성
        # 3. 임계값 체크
        # 4. position size 결정 (ATR 기반)
        ...
```

2. 종목당 단일 active position rule:
   - `ticker in active_positions` 이고 `opened_at`이 `now() - conflict_window_days` 이내 → 신규 발주 차단
   - 단, 신규 conviction이 기존보다 +0.2 이상 강한 경우 → resize 허용

3. Conviction 합성:
   - `agent_conf = weighted_mean(agent_signals.confidence)`
   - `ml_conf = mean(ml_signals.score)`
   - `tool_score = normalize(sum(tool_outputs.score))`
   - `conviction = w_a × agent_conf + w_m × ml_conf + w_t × tool_score`

4. Position size:
```python
def _size_position(conviction: float, atr: float, nav: float) -> int:
    risk_per_trade_pct = settings.RISK_PER_TRADE_PCT  # 1.0%
    risk_amount = nav * risk_per_trade_pct / 100
    if conviction < 0.5:
        return 0
    scale = min((conviction - 0.5) / 0.5, 1.0)  # 0.5~1.0 → 0~1
    return int(risk_amount * scale / (atr * settings.ATR_STOP_MULTIPLIER))
```

5. Exposure 한도 검증 (Step 2 범위 내):
   - per_ticker ≤ 10% NAV
   - per_sector ≤ 25% NAV
   - per_currency ≤ 60% NAV
   - 위반 시 size 자동 축소

### 테스트 시나리오
- 신규 BUY → position 생성
- 동일 ticker 3일 내 재BUY (conviction 동일) → 차단
- 동일 ticker 3일 내 재BUY (conviction +0.3) → resize 허용
- 4 에이전트 mixed signal → conviction 가중 합산 정확성
- per_ticker 10% 초과 사이즈 → 자동 축소
- conviction < threshold → action="wait"

### 완료 기준
- 모든 테스트 pass
- 수동 검증: paper trading 시뮬레이션에서 동일 종목 2회 BUY 시 1회만 실행 확인

### 커밋 메시지
```
feat(signal-agg): SignalAggregator + 종목당 단일 active position rule

- conviction 가중 합성 (agent 0.4 + ml 0.4 + tool 0.2)
- 3일 conflict window 내 동일 ticker BUY 차단 (단, conviction +0.2 시 resize)
- per_ticker/sector/currency 노출 한도 검증
- ATR 기반 position sizing

Refs: docs/EXECUTION_PLAN.md#step-2
```

---

## STEP 3 — OHLCV 캐시 freshness + retry + 다중 소스 fallback

### 목표
`yf.download` 실패 시 silent corruption 방지. TTL 메타·재시도·다중 소스 fallback 도입.

### 변경 파일
**수정**:
- `chart_agent_service/data_collector.py`
- `chart_agent_service/config.py` — TTL 필드 추가
- `chart_agent_service/data_sources/base.py` — Protocol 확장
- `chart_agent_service/data_sources/yfinance_source.py`
- `chart_agent_service/data_sources/fdr_source.py`

**신규 생성**:
- `chart_agent_service/data_sources/pykrx_source.py` (Step 3 범위 내 baseline만)
- `chart_agent_service/data_collector_models.py`
- `tests/unit/test_data_collector.py`

### 신규 의존성
```toml
[project.dependencies]
tenacity = ">=8.2,<9.0"
```

### 구현 사양

1. `CacheEntry(BaseModel)`:
```python
class CacheEntry(BaseModel):
    ticker: str
    data: pd.DataFrame  # arbitrary_types_allowed=True
    fetched_at: datetime
    source: Literal["yfinance", "fdr", "pykrx"]
    auto_adjust: bool
    row_count: int
    latest_bar_date: date
    data_hash: str  # SHA256 of (date, OHLCV) tuples
    retry_count: int = 0
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
```

2. TTL 정책:
   - EOD 일봉: 시장 마감 후 첫 fetch 24h, 영업일 중 fetch 5분
   - 주간/월간: 24h
   - 펀더멘털: 12h
   - 시장 시간 검출: `pandas_market_calendars` (Step 11에서 본격 도입 예정, Step 3에서는 단순 시간 기반 검출 baseline)

3. Tenacity 재시도:
```python
@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_exception_type((requests.RequestException, ConnectionError)),
       reraise=True)
def _fetch_with_retry(source: DataSource, ticker: str, **kwargs):
    return source.fetch_ohlcv(ticker, **kwargs)
```

4. 다중 소스 fallback:
```python
def fetch_ohlcv(ticker: str, period: str) -> CacheEntry:
    is_korean = _is_korean_ticker(ticker)
    sources = (
        [PykrxSource(), FdrSource(), YFinanceSource()]
        if is_korean else
        [YFinanceSource(), FdrSource()]
    )
    last_exc = None
    for source in sources:
        try:
            df = _fetch_with_retry(source, ticker, period=period)
            return _build_cache_entry(ticker, df, source.name)
        except Exception as e:
            last_exc = e
            logger.warning(f"{source.name} failed for {ticker}: {e}")
    raise DataStaleError(f"All sources exhausted for {ticker}", last_exc)
```

5. `DataStaleError` 발생 시 GlobalKillSwitch에 전파 (Step 1 의존성):
```python
# kill_switch.py에서
if isinstance(exc, DataStaleError):
    self.record_event(trigger_type="data_stale", ...)
```

### 테스트 시나리오
- yfinance 정상 → CacheEntry 정상 생성
- yfinance 3회 실패 → FDR fallback
- 모든 소스 실패 → DataStaleError raise
- 한국 ticker `005930.KS` → pykrx 우선 호출 (mock)
- 캐시 TTL 만료 후 재호출 → 새 fetch
- 캐시 TTL 미만료 → 캐시 반환 (호출 안 함)

### 완료 기준
- 모든 테스트 pass
- 수동: 인터넷 차단 시뮬레이션 후 `/scan` 호출 → DataStaleError → kill_switch 발동 확인

### 커밋 메시지
```
feat(cache): OHLCV freshness 메타 + tenacity retry + 다중 소스 fallback

- CacheEntry 모델: fetched_at, source, data_hash, latest_bar_date
- TTL 정책: EOD 24h, intraday 5min, fundamental 12h
- 한국 pykrx > FDR > yfinance, 미국 yfinance > FDR fallback
- 3회 retry exponential backoff, 실패 시 DataStaleError
- kill_switch 연동

Refs: docs/EXECUTION_PLAN.md#step-3
```

---

## STEP 4 — signal_outcomes 배치 활성화

### 목표
`signal_outcomes` 테이블이 정의만 되고 미사용. 주1회 cron으로 7/14/30일 outcome 평가 → hit-rate, expectancy 측정 가능.

### 의존성
- Step 3 완료 필수 (가격 데이터 신뢰성 확보 후 outcome 평가)

### 변경 파일
**수정**:
- `chart_agent_service/db.py` — `signal_outcomes` 스키마 확장
- `chart_agent_service/signal_tracker.py` — outcome 평가 로직

**신규 생성**:
- `chart_agent_service/jobs/__init__.py`
- `chart_agent_service/jobs/evaluate_signal_outcomes.py`
- `chart_agent_service/jobs/calibration_metrics.py`
- `scripts/cron/weekly_signal_outcomes.sh`
- `tests/unit/test_signal_outcomes.py`

### 구현 사양

1. DB 스키마 (현재 정의 보강):
```sql
CREATE TABLE IF NOT EXISTS signal_outcomes (
    signal_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_source TEXT NOT NULL,  -- agent_name or "ensemble"
    issued_at TIMESTAMP NOT NULL,
    conviction REAL NOT NULL,
    price_at_signal REAL NOT NULL,
    price_7d REAL,
    price_14d REAL,
    price_30d REAL,
    return_7d REAL,
    return_14d REAL,
    return_30d REAL,
    max_drawdown_30d REAL,
    evaluated_at TIMESTAMP,
    market_context TEXT,  -- JSON
    regime TEXT
);
CREATE INDEX idx_so_ticker_issued ON signal_outcomes(ticker, issued_at);
CREATE INDEX idx_so_source_issued ON signal_outcomes(signal_source, issued_at);
CREATE INDEX idx_so_regime ON signal_outcomes(regime);
```

2. 시그널 발주 시점에 row 생성 (insert):
   - `/scan` 또는 `/decide` 핸들러에서 최종 시그널 산출 후 signal_outcomes에 insert
   - signal_id = UUID4

3. 평가 작업 (주1회 cron):
```python
def evaluate_pending_outcomes():
    pending = db.query("""
        SELECT signal_id, ticker, issued_at, price_at_signal
        FROM signal_outcomes
        WHERE evaluated_at IS NULL
          AND datetime(issued_at, '+30 days') < datetime('now')
    """)
    for row in pending:
        price_7d = _fetch_price_at(row.ticker, row.issued_at + timedelta(days=7))
        price_14d = _fetch_price_at(row.ticker, row.issued_at + timedelta(days=14))
        price_30d = _fetch_price_at(row.ticker, row.issued_at + timedelta(days=30))
        ret_7d = (price_7d - row.price_at_signal) / row.price_at_signal
        ret_14d = ...
        ret_30d = ...
        max_dd = _compute_max_dd(row.ticker, row.issued_at, days=30)
        db.update("""UPDATE signal_outcomes SET ... WHERE signal_id=?""", ...)
```

4. 집계 view (매일 갱신):
```sql
CREATE VIEW IF NOT EXISTS signal_performance_summary AS
SELECT
    signal_source,
    signal_type,
    regime,
    COUNT(*) as n,
    AVG(CASE WHEN return_7d > 0 THEN 1.0 ELSE 0.0 END) as hit_rate_7d,
    AVG(return_7d) as expectancy_7d,
    AVG(return_30d) as expectancy_30d,
    AVG(max_drawdown_30d) as avg_max_dd
FROM signal_outcomes
WHERE evaluated_at IS NOT NULL
  AND issued_at >= datetime('now', '-90 days')
GROUP BY signal_source, signal_type, regime;
```

5. Calibration 지표 산출:
```python
def compute_ece(df, n_bins=10):
    """Expected Calibration Error."""
    bins = pd.cut(df.conviction, n_bins)
    grouped = df.groupby(bins)
    ece = 0
    n_total = len(df)
    for bin_name, group in grouped:
        if len(group) == 0:
            continue
        avg_conf = group.conviction.mean()
        accuracy = (group.return_7d > 0).mean()
        ece += len(group) / n_total * abs(avg_conf - accuracy)
    return ece
```

6. Cron 스크립트 (`scripts/cron/weekly_signal_outcomes.sh`):
```bash
#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/stock_auto
docker compose --profile dev exec -T agent-api \
    python -m chart_agent_service.jobs.evaluate_signal_outcomes
```

7. Crontab 등록 가이드 (README에 추가):
```
# 매주 일요일 22:00 KST
0 22 * * 0 /home/ubuntu/stock_auto/scripts/cron/weekly_signal_outcomes.sh \
    >> /var/log/stock_auto/signal_outcomes.log 2>&1
```

### 테스트 시나리오
- 시그널 insert → signal_outcomes row 생성
- 30일 경과 시뮬레이션 → evaluate 호출 → return_7/14/30d 산출
- ECE 계산 정확성 (sample fixture)
- signal_performance_summary view 조회

### 완료 기준
- 모든 테스트 pass
- 수동: `python -m chart_agent_service.jobs.evaluate_signal_outcomes` 실행 → DB 갱신 확인
- Streamlit 페이지 또는 Markdown 리포트로 hit_rate_7d, expectancy_7d 가시화

### 커밋 메시지
```
feat(signal-outcomes): 활성화 + 주1회 cron + ECE calibration

- signal_outcomes 스키마: regime 컬럼 추가, 인덱스 보강
- /scan 핸들러에서 시그널 발주 시 row insert
- evaluate_signal_outcomes job: 7/14/30d 수익률·MaxDD 계산
- signal_performance_summary view: agent×regime hit rate
- ECE (Expected Calibration Error) 산출 함수

Refs: docs/EXECUTION_PLAN.md#step-4
```

---

## STEP 5 — MFI 도구 + RSI/MFI 조합 신호

### 목표
가격만 사용하는 RSI의 약점(저유동성 거짓 돌파)을 거래량 가중 MFI로 보완.

### 변경 파일
**수정**:
- `chart_agent_service/analysis_tools.py` — `money_flow_index_tool` 추가, `rsi_mfi_combined_tool` 추가

**신규 생성**:
- `tests/unit/test_mfi.py`

### 구현 사양

1. MFI 계산:
```python
def _compute_mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tp = (df.High + df.Low + df.Close) / 3
    rmf = tp * df.Volume
    direction = np.where(tp > tp.shift(1), 1, np.where(tp < tp.shift(1), -1, 0))
    positive_mf = pd.Series(rmf.where(direction > 0, 0)).rolling(period).sum()
    negative_mf = pd.Series(rmf.where(direction < 0, 0)).rolling(period).sum()
    mfr = positive_mf / negative_mf.replace(0, np.nan)
    mfi = 100 - 100 / (1 + mfr)
    return mfi
```

2. MFI 도구 (단독):
```python
def money_flow_index_tool(df: pd.DataFrame, period: int = 14) -> ToolResult:
    mfi = _compute_mfi(df, period)
    last = mfi.iloc[-1]
    score = 0
    flags = []
    if last > 80:
        score = -3
        flags.append("MFI_OVERBOUGHT")
    elif last < 20:
        score = +3
        flags.append("MFI_OVERSOLD")
    return ToolResult(name="mfi", score=score, last_value=last, flags=flags)
```

3. RSI/MFI 조합 도구:
```python
def rsi_mfi_combined_tool(df: pd.DataFrame, period: int = 14) -> ToolResult:
    rsi = _compute_rsi(df, period)
    mfi = _compute_mfi(df, period)
    last_rsi, last_mfi = rsi.iloc[-1], mfi.iloc[-1]
    score = 0
    flags = []

    # 합치 과매수/과매도
    if last_rsi > 70 and last_mfi > 80:
        score = -5
        flags.append("CONFIRMED_OVERBOUGHT")
    elif last_rsi < 30 and last_mfi < 20:
        score = +5
        flags.append("CONFIRMED_OVERSOLD")

    # 다이버전스
    price_div = _detect_divergence(df.Close, rsi, lookback=30)
    volume_div = _detect_divergence(df.Close, mfi, lookback=30)
    if price_div == "bearish" and volume_div == "bearish":
        score -= 6
        flags.append("DOUBLE_BEARISH_DIVERGENCE")
    elif price_div == "bullish" and volume_div == "bullish":
        score += 6
        flags.append("DOUBLE_BULLISH_DIVERGENCE")

    # 가격은 강세지만 자금 유입 약함 (거짓 돌파)
    if last_rsi > 70 and last_mfi < 60:
        score -= 4
        flags.append("VOLUME_DIVERGENCE_BEARISH")
    elif last_rsi < 30 and last_mfi > 40:
        score += 4
        flags.append("VOLUME_DIVERGENCE_BULLISH")

    return ToolResult(
        name="rsi_mfi_combined",
        score=score,
        last_value={"rsi": last_rsi, "mfi": last_mfi},
        flags=flags,
    )
```

4. 16 → 18 도구로 확장. `analysis_tools.py` 내 도구 레지스트리에 등록.

### 테스트 시나리오
- 평탄 OHLCV → MFI 50 근처
- 강세 fixture (가격↑, 거래량↑) → MFI > 70, score < 0
- 약세 fixture (가격↓, 거래량↑) → MFI < 30, score > 0
- 다이버전스 fixture (가격↑, 거래량 평탄) → bearish divergence flag
- NaN 처리: 첫 period bars → NaN

### 완료 기준
- 모든 테스트 pass
- 수동: 워치리스트 1개 종목 분석 결과에 `rsi_mfi_combined` 도구 출력 확인

### 커밋 메시지
```
feat(mfi): MFI 도구 + RSI/MFI 조합 도구 추가

- _compute_mfi 14-period 표준 공식
- money_flow_index_tool 단독 도구 (score ±3)
- rsi_mfi_combined_tool: 합치 과매수/매도, 이중 다이버전스, 거짓 돌파 감지 (score ±6)
- 도구 수 16 → 18

Refs: docs/EXECUTION_PLAN.md#step-5
```

---

## STEP 6 — MACD + RSI cross-signal

### 목표
MACD bearish/bullish crossover와 RSI 과매수/매도가 동시 발생 시 강한 신호로 가중. 추가 컨설팅 문서 §4.1 핵심 권고 직접 반영.

### 의존성
- Step 5 완료 권장 (RSI 계산 함수 재사용)

### 변경 파일
**수정**:
- `chart_agent_service/analysis_tools.py` — `macd_rsi_cross_signal` 추가
- `stock_analyzer/enhanced_decision_maker.py` — evidence 합성 시 cross-signal 가중

**신규 생성**:
- `tests/unit/test_macd_rsi_cross.py`

### 구현 사양

```python
def macd_rsi_cross_signal_tool(df: pd.DataFrame) -> ToolResult:
    macd_line = _ema(df.Close, 12) - _ema(df.Close, 26)
    signal_line = _ema(macd_line, 9)
    rsi = _compute_rsi(df, 14)

    bearish_cross = (macd_line.iloc[-2] > signal_line.iloc[-2]
                     and macd_line.iloc[-1] < signal_line.iloc[-1])
    bullish_cross = (macd_line.iloc[-2] < signal_line.iloc[-2]
                     and macd_line.iloc[-1] > signal_line.iloc[-1])

    score = 0
    flags = []
    last_rsi = rsi.iloc[-1]

    if bearish_cross:
        flags.append("MACD_BEARISH_CROSS")
        if last_rsi > 70:
            score = -7
            flags.append("STRONG_BEARISH_CONFIRMATION")
        else:
            score = -3
    elif bullish_cross:
        flags.append("MACD_BULLISH_CROSS")
        if last_rsi < 30:
            score = +7
            flags.append("STRONG_BULLISH_CONFIRMATION")
        else:
            score = +3

    return ToolResult(
        name="macd_rsi_cross",
        score=score,
        last_value={"macd": macd_line.iloc[-1],
                    "signal": signal_line.iloc[-1],
                    "rsi": last_rsi},
        flags=flags,
    )
```

EnhancedDecisionMaker에서 `STRONG_*_CONFIRMATION` flag 보유 시 conviction에 +0.1 가중.

### 테스트 시나리오
- bearish cross + RSI 75 → score=-7, STRONG_BEARISH_CONFIRMATION flag
- bullish cross + RSI 25 → score=+7, STRONG_BULLISH_CONFIRMATION flag
- bearish cross + RSI 50 → score=-3 (단순 cross)
- no cross → score=0

### 완료 기준
- 모든 테스트 pass
- 도구 수 18 → 19

### 커밋 메시지
```
feat(macd-rsi): MACD + RSI cross-signal 도구 + STRONG confirmation flag

- bearish cross ∧ RSI>70 → score=-7
- bullish cross ∧ RSI<30 → score=+7
- EnhancedDecisionMaker conviction +0.1 가중

Refs: docs/EXECUTION_PLAN.md#step-6
```

---

## STEP 7 — Rule-based regime detector + regime-aware weighting

### 목표
VIX, KOSPI/SPX 모멘텀, ATR%, ADX 기반 시장 체제 감지. regime별 momentum/mean_reversion/fundamental 가중치 분기.

### 변경 파일
**신규 생성**:
- `chart_agent_service/regime/__init__.py`
- `chart_agent_service/regime/detector.py`
- `chart_agent_service/regime/models.py`
- `tests/unit/test_regime_detector.py`

**수정**:
- `chart_agent_service/macro_context.py` — VHF 계산 추가
- `chart_agent_service/service.py` — `/regime` 엔드포인트 추가
- `stock_analyzer/enhanced_decision_maker.py` — regime-aware 가중치 적용

### 구현 사양

1. Regime enum:
```python
class Regime(str, Enum):
    STRONG_UPTREND = "strong_uptrend"
    STRONG_DOWNTREND = "strong_downtrend"
    RANGING = "ranging"
    VOLATILE = "volatile"
    NORMAL = "normal"
```

2. Detector:
```python
def detect_market_regime(ctx: MacroContext, mkt: MarketFeatures) -> Regime:
    if ctx.vix > 30 or mkt.atr_pct > 3.5:
        return Regime.VOLATILE
    if mkt.vhf > 0.4 and mkt.adx > 25:
        if mkt.kospi_momentum_20d > 0.05 and mkt.spx_momentum_20d > 0.05:
            return Regime.STRONG_UPTREND
        elif mkt.kospi_momentum_20d < -0.05 and mkt.spx_momentum_20d < -0.05:
            return Regime.STRONG_DOWNTREND
    if mkt.vhf < 0.3 and abs(mkt.kospi_momentum_20d) < 0.03:
        return Regime.RANGING
    return Regime.NORMAL
```

3. VHF 계산 (macro_context.py에 추가):
```python
def compute_vhf(close: pd.Series, period: int = 28) -> float:
    rolling_max = close.rolling(period).max()
    rolling_min = close.rolling(period).min()
    abs_changes = close.diff().abs().rolling(period).sum()
    vhf = (rolling_max - rolling_min).iloc[-1] / abs_changes.iloc[-1]
    return float(vhf)
```

4. Regime weights:
```python
REGIME_WEIGHTS = {
    Regime.STRONG_UPTREND:   {"momentum": 1.5, "mean_reversion": 0.3, "fundamental": 1.0},
    Regime.STRONG_DOWNTREND: {"momentum": 1.2, "mean_reversion": 0.5, "fundamental": 1.0},
    Regime.RANGING:          {"momentum": 0.4, "mean_reversion": 1.5, "fundamental": 1.2},
    Regime.VOLATILE:         {"momentum": 0.3, "mean_reversion": 0.3, "fundamental": 1.8},
    Regime.NORMAL:           {"momentum": 1.0, "mean_reversion": 1.0, "fundamental": 1.0},
}
```

5. Tool 분류 (어떤 도구가 어떤 카테고리에 속하는지):
```python
TOOL_CATEGORY = {
    "trend_ma": "momentum",
    "macd_momentum": "momentum",
    "macd_rsi_cross": "momentum",
    "adx_trend_strength": "momentum",
    "momentum_rank": "momentum",
    "rsi_divergence": "mean_reversion",
    "rsi_mfi_combined": "mean_reversion",
    "bollinger_squeeze": "mean_reversion",
    "mean_reversion": "mean_reversion",
    "stochastic": "mean_reversion",
    # ...
}
```

6. EnhancedDecisionMaker 통합:
```python
def aggregate_tools_regime_aware(tool_outputs, regime: Regime):
    weights = REGIME_WEIGHTS[regime]
    total_score = 0
    for tool_name, result in tool_outputs.items():
        category = TOOL_CATEGORY.get(tool_name, "fundamental")
        total_score += result.score * weights[category]
    return total_score
```

7. signal_outcomes에 regime 컬럼 기록 (Step 4 의존성):
```python
# 시그널 발주 시
db.insert_signal_outcome(
    signal_id=...,
    ...,
    regime=current_regime.value,
)
```

### 테스트 시나리오
- VIX=35 → VOLATILE
- VHF=0.5, ADX=30, kospi_mom=0.08 → STRONG_UPTREND
- VHF=0.25, kospi_mom=0.01 → RANGING
- regime-aware 합산: STRONG_UPTREND에서 momentum 도구 score 1.5× 가중

### 완료 기준
- 모든 테스트 pass
- `/regime` 엔드포인트 호출 → 현재 regime + 입력 메트릭 반환
- Streamlit 사이드바에 현재 regime 표시

### 커밋 메시지
```
feat(regime): rule-based regime detector + regime-aware tool weighting

- 5 regime: STRONG_UPTREND/DOWNTREND, RANGING, VOLATILE, NORMAL
- VIX + ATR% + VHF + ADX + 20d momentum 기반 판정
- REGIME_WEIGHTS: momentum/mean_reversion/fundamental 카테고리별
- TOOL_CATEGORY 매핑으로 도구별 가중치 자동 적용
- /regime 엔드포인트 + signal_outcomes.regime 기록

Refs: docs/EXECUTION_PLAN.md#step-7
```

---

## STEP 8 — Agent group 4분할 (DEPART 단순화)

### 목표
8 에이전트를 4 도메인 그룹(Technical/Fundamental/Macro/Risk)으로 분할. 그룹 내 weighted vote 후 그룹 대표 신호 생성. 한 도메인 에이전트 실패에도 그룹 신호 유지.

### 의존성
- Step 7 완료 권장 (regime 정보 활용)

### 변경 파일
**수정**:
- `stock_analyzer/multi_agent.py` — AgentGroup enum, aggregate_by_group 추가
- `stock_analyzer/enhanced_decision_maker.py` — 그룹 신호 합성

**신규 생성**:
- `stock_analyzer/agent_groups.py`
- `tests/unit/test_agent_groups.py`

### 구현 사양

1. Group enum:
```python
class AgentGroup(str, Enum):
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    MACRO = "macro"
    RISK = "risk"

AGENT_TO_GROUP = {
    "Technical": AgentGroup.TECHNICAL,
    "Quant": AgentGroup.TECHNICAL,
    "Value": AgentGroup.FUNDAMENTAL,
    "Insider": AgentGroup.FUNDAMENTAL,
    "Event": AgentGroup.MACRO,
    "Geopolitical": AgentGroup.MACRO,
    "RiskManager": AgentGroup.RISK,
    "MLSpecialist": AgentGroup.RISK,
}
```

2. Group result model:
```python
class GroupResult(BaseModel):
    group: AgentGroup
    signal: Literal["buy", "sell", "neutral"]
    confidence: float = Field(ge=0.0, le=10.0)
    member_count: int
    member_results: list[str]  # agent names
    error_count: int
```

3. Group aggregation:
```python
def aggregate_by_group(agent_results: list[AgentResult]) -> dict[AgentGroup, GroupResult]:
    groups: dict[AgentGroup, list[AgentResult]] = defaultdict(list)
    for r in agent_results:
        grp = AGENT_TO_GROUP.get(r.agent_name)
        if grp:
            groups[grp].append(r)

    out = {}
    for grp, members in groups.items():
        out[grp] = _weighted_vote(grp, members)
    return out

def _weighted_vote(group: AgentGroup, members: list[AgentResult]) -> GroupResult:
    valid = [r for r in members if not r.error and r.confidence > 0]
    if not valid:
        return GroupResult(group=group, signal="neutral", confidence=0,
                          member_count=len(members), member_results=[],
                          error_count=len(members))
    score = sum(_signal_score(r.signal) * r.confidence for r in valid)
    norm = sum(r.confidence for r in valid)
    avg_score = score / norm
    avg_conf = sum(r.confidence for r in valid) / len(valid)
    signal = "buy" if avg_score > 0.3 else "sell" if avg_score < -0.3 else "neutral"
    return GroupResult(
        group=group,
        signal=signal,
        confidence=avg_conf,
        member_count=len(members),
        member_results=[r.agent_name for r in valid],
        error_count=len(members) - len(valid),
    )

def _signal_score(s: str) -> float:
    return {"buy": 1.0, "sell": -1.0, "neutral": 0.0}[s]
```

4. EnhancedDecisionMaker 통합:
```python
def decide(agent_results, regime, ...):
    group_results = aggregate_by_group(agent_results)
    regime_weights = REGIME_WEIGHTS[regime]
    GROUP_TO_CATEGORY = {
        AgentGroup.TECHNICAL: "momentum",  # 또는 mean_reversion (도구 mix에 따라)
        AgentGroup.FUNDAMENTAL: "fundamental",
        AgentGroup.MACRO: "fundamental",
        AgentGroup.RISK: "fundamental",
    }
    final_score = 0
    for grp, result in group_results.items():
        cat = GROUP_TO_CATEGORY[grp]
        weight = regime_weights[cat]
        final_score += _signal_score(result.signal) * result.confidence * weight
    # ...
```

5. Reflect 단계 (sanity check):
```python
def reflect(group_results, final_signal):
    sell_count = sum(1 for r in group_results.values() if r.signal == "sell")
    buy_count = sum(1 for r in group_results.values() if r.signal == "buy")
    flags = []
    if sell_count >= 3 and final_signal == "buy":
        flags.append("REFLECT_INCONSISTENT_3_SELL_VS_FINAL_BUY")
    if buy_count >= 3 and final_signal == "sell":
        flags.append("REFLECT_INCONSISTENT_3_BUY_VS_FINAL_SELL")
    return flags
```

### 테스트 시나리오
- 8 에이전트 mixed → 4 group 결과
- Technical 그룹 2명 모두 실패 → group neutral, error_count=2
- 3 그룹 SELL + 1 그룹 BUY → final SELL 또는 inconsistent flag
- 그룹 내 confidence-weighted vote 정확성

### 완료 기준
- 모든 테스트 pass
- 시그널 발주 시 evidence에 그룹별 결과 포함
- signal_outcomes에 그룹별 시그널도 별도 row로 기록 (signal_source 컬럼에 group name)

### 커밋 메시지
```
feat(agent-group): 4 그룹 분할 (Technical/Fundamental/Macro/Risk)

- AgentGroup enum, AGENT_TO_GROUP 매핑
- _weighted_vote: 그룹 내 confidence 가중 다수결
- EnhancedDecisionMaker regime-aware 그룹 합성
- reflect() sanity check: 3 그룹 일치 ↔ final 불일치 감지
- signal_outcomes에 그룹별 시그널 별도 기록

Refs: docs/EXECUTION_PLAN.md#step-8
```

---

## STEP 9 — LiteLLM Router + Circuit breaker + Structured output

### 목표
LLM provider 통합 인터페이스. Gemini/Ollama Mac/Ollama RTX fallback chain 명시화. 회로 차단기로 자동 차단·복구. Pydantic schema로 환각 위험 제거.

### 변경 파일
**신규 생성**:
- `chart_agent_service/llm/__init__.py`
- `chart_agent_service/llm/router.py`
- `chart_agent_service/llm/schemas.py`
- `chart_agent_service/llm/circuit_breakers.py`
- `tests/unit/test_llm_router.py`

**수정 (모든 에이전트가 신규 Router 경유하도록)**:
- `stock_analyzer/multi_agent.py` — 각 에이전트의 `_call_llm()`
- `stock_analyzer/dual_node_config.py` — Router 설정으로 통합
- `chart_agent_service/news_analyzer.py` — Ollama 직접 호출 → Router

### 신규 의존성
```toml
[project.dependencies]
litellm = ">=1.50,<2.0"
circuitbreaker = ">=2.0,<3.0"
```

### 구현 사양

1. Pydantic 응답 스키마:
```python
class AgentLLMResponse(BaseModel):
    signal: Literal["buy", "sell", "neutral"]
    confidence: float = Field(ge=0.0, le=10.0)
    reasoning: str = Field(max_length=500)
    key_evidence: list[str] = Field(max_items=5)
    risk_flags: list[str] = Field(default_factory=list)

    @field_validator("reasoning")
    def strip_reasoning(cls, v):
        return v.strip()
```

2. LiteLLM Router 설정:
```python
from litellm import Router

def build_router() -> Router:
    return Router(
        model_list=[
            {
                "model_name": "agent-llm-primary",
                "litellm_params": {
                    "model": "gemini/gemini-2.5-pro",
                    "api_key": os.environ["GEMINI_API_KEY"],
                    "timeout": 30,
                },
            },
            {
                "model_name": "agent-llm-secondary",
                "litellm_params": {
                    "model": "ollama/qwen2.5:32b-instruct-q4_K_M",
                    "api_base": os.environ["MAC_STUDIO_URL"],
                    "timeout": 60,
                },
            },
            {
                "model_name": "agent-llm-tertiary",
                "litellm_params": {
                    "model": "ollama/qwen3:14b-q4_K_M",
                    "api_base": os.environ["OLLAMA_BASE_URL"],
                    "timeout": 90,
                },
            },
        ],
        fallbacks=[
            {"agent-llm-primary": ["agent-llm-secondary", "agent-llm-tertiary"]},
        ],
        num_retries=2,
        retry_after=5,
        routing_strategy="usage-based-routing",
        set_verbose=False,
    )
```

3. Circuit breaker 데코레이터:
```python
from circuitbreaker import circuit

@circuit(failure_threshold=3, recovery_timeout=300,
         expected_exception=(litellm.exceptions.Timeout,
                             litellm.exceptions.RateLimitError,
                             ConnectionError))
def _call_with_breaker(router: Router, model_name: str, messages: list[dict], **kwargs):
    return router.completion(model=model_name, messages=messages, **kwargs)
```

4. Structured output 호출 헬퍼:
```python
def call_agent_llm(
    router: Router,
    agent_role: str,
    prompt: str,
    response_model: type[BaseModel] = AgentLLMResponse,
) -> BaseModel:
    schema = response_model.model_json_schema()
    messages = [
        {"role": "system",
         "content": f"You are {agent_role}. Respond ONLY in JSON matching this schema: {schema}"},
        {"role": "user", "content": prompt},
    ]
    response = _call_with_breaker(
        router,
        model_name="agent-llm-primary",
        messages=messages,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    try:
        return response_model.model_validate_json(raw)
    except ValidationError as e:
        logger.warning(f"LLM response parse fail: {e}")
        # 파싱 실패 시 neutral 안전 응답
        return response_model(
            signal="neutral", confidence=0.0,
            reasoning=f"parse_error: {e}", key_evidence=[],
            risk_flags=["LLM_PARSE_ERROR"],
        )
```

5. 모든 기존 에이전트의 `_call_llm()` 호출을 위 헬퍼로 교체:
```python
# Before
response = ollama.chat(model="qwen2.5:32b", messages=[...])
parsed = self._parse_response(response["message"]["content"])

# After
parsed = call_agent_llm(self.router, self.agent_role, prompt)
```

### 테스트 시나리오
- 정상 호출 → AgentLLMResponse 객체
- Primary timeout → secondary fallback
- 3회 연속 실패 → 회로 차단, 5분 후 자동 복구
- LLM 응답이 JSON 아님 → ValidationError → neutral 안전 응답
- LLM 응답 confidence=15 (범위 초과) → ValidationError

### 완료 기준
- 모든 테스트 pass
- 수동: Mac Studio Ollama 중단 시 → RTX 자동 fallback 확인
- Streamlit에서 에이전트 응답 시 `risk_flags` 표시

### 커밋 메시지
```
feat(llm-router): LiteLLM Router + circuit breaker + Pydantic structured output

- 3-tier fallback: Gemini > Mac qwen32b > RTX qwen14b
- circuitbreaker: 3회 실패 시 5분 자동 차단
- AgentLLMResponse Pydantic 스키마 enforce
- 모든 에이전트 _call_llm()을 call_agent_llm() 헬퍼로 통합
- 환각 위험 schema validation으로 차단

Refs: docs/EXECUTION_PLAN.md#step-9
```

---

## STEP 10 — 백테스트 가정 명시 + rf 차감

### 목표
naive Sharpe(rf=0) → KOFR/T-Bill 차감. 슬리피지·수수료·look-ahead bias 명시. `BACKTEST_ASSUMPTIONS.md` 문서 분리.

### 변경 파일
**수정**:
- `chart_agent_service/backtest_engine.py` — Sharpe 계산 rf 차감
- `chart_agent_service/config.py` — `ANNUAL_RISK_FREE_RATE_KR`, `ANNUAL_RISK_FREE_RATE_US` 분리
- `chart_agent_service/trading_costs.py` — 2026 거래세 0.20% 반영

**신규 생성**:
- `docs/BACKTEST_ASSUMPTIONS.md`
- `chart_agent_service/backtest_metrics.py` — 추가 메트릭 (Sortino, Calmar, Omega)
- `tests/unit/test_backtest_metrics.py`

### 신규 환경변수
```
ANNUAL_RISK_FREE_RATE_KR=3.5  # KOFR 기준
ANNUAL_RISK_FREE_RATE_US=4.5  # 3M T-Bill 기준
KRX_TRADING_TAX_PCT=0.18      # 2025년 기준, 2026 0.20으로 변경 예정
```

### 구현 사양

1. Sharpe rf 차감:
```python
def compute_sharpe(daily_returns: pd.Series, is_korean: bool) -> float:
    rf_annual = (settings.ANNUAL_RISK_FREE_RATE_KR if is_korean
                 else settings.ANNUAL_RISK_FREE_RATE_US)
    rf_daily = rf_annual / 252 / 100  # 백분율 → 소수
    excess = daily_returns - rf_daily
    return excess.mean() / excess.std() * np.sqrt(252)
```

2. Sortino:
```python
def compute_sortino(daily_returns: pd.Series, is_korean: bool) -> float:
    rf_daily = ...
    excess = daily_returns - rf_daily
    downside = excess[excess < 0]
    if len(downside) == 0:
        return float("inf")
    return excess.mean() / downside.std() * np.sqrt(252)
```

3. Calmar:
```python
def compute_calmar(daily_returns: pd.Series, max_dd: float) -> float:
    cagr = ((1 + daily_returns).prod() ** (252/len(daily_returns)) - 1)
    return cagr / abs(max_dd) if max_dd != 0 else float("inf")
```

4. `BACKTEST_ASSUMPTIONS.md` 내용:
```markdown
# Backtest Assumptions

## Slippage
- KRX 대형주 (KOSPI200): 5bp
- KRX 중소형주: 15bp
- NYSE 대형주: 2bp
- NYSE ETF: 1bp

## Trading Costs
- 한국 commission: 0.015% (증권사)
- 한국 거래세: 0.18% (2025) → 0.20% (2026 예정, settings.KRX_TRADING_TAX_PCT로 조정)
- 미국 commission: 0% (Charles Schwab 등 free trade 가정)

## Look-ahead Bias 방지
- Bar close 시점 시그널 → next bar open 체결 (1-bar delay)
- Indicator 계산 시 only past bars 사용 (.shift(1) 명시)

## Survivorship Bias
- 워치리스트 13종목은 현재 시점에서 선택됨 → 명시적 한계
- 백테스트 결과는 universe selection bias 포함

## Risk-Free Rate
- 한국: KOFR (Korean Overnight Financing Rate), 2026-05 기준 3.5%
- 미국: 3M T-Bill yield, 2026-05 기준 4.5%
- Sharpe·Sortino 계산 시 차감

## 분배·배당 처리
- yfinance auto_adjust=True 사용 (블랙박스)
- 분기별 split/dividend audit cron 별도 운영 (P2)

## 거래 단위
- 한국: 1주 (소수점 거래 미지원)
- 미국: 1주 (fractional 미지원 가정)

## 공매도
- 2025-03-31 한국 공매도 전면 재개
- 본 시스템은 long-only, short signal은 청산 트리거로만 사용
```

5. 백테스트 리포트에 다음 항목 모두 출력:
   - Sharpe (rf 차감)
   - Sortino
   - Calmar
   - Max Drawdown
   - Win Rate
   - Profit Factor
   - Average Win / Average Loss
   - Total Trades
   - 가정 명시 (rf, slippage, commission 값)

### 테스트 시나리오
- daily_returns sample → Sharpe rf 차감 정확성
- 강세장 fixture → Sortino > Sharpe (downside 작아서)
- 큰 drawdown 시나리오 → Calmar 감소
- 백테스트 결과 출력에 ANNUAL_RISK_FREE_RATE 명시

### 완료 기준
- 모든 테스트 pass
- `BACKTEST_ASSUMPTIONS.md` 생성
- `/backtest/{ticker}` 응답에 가정 메타 포함

### 커밋 메시지
```
feat(backtest): rf 차감 Sharpe + Sortino/Calmar + 가정 문서화

- ANNUAL_RISK_FREE_RATE_KR/US 분리 (KOFR, T-Bill)
- Sharpe·Sortino 계산 시 일별 rf 차감
- Calmar 추가 (CAGR / MaxDD)
- 2026 거래세 0.20% 변수화
- docs/BACKTEST_ASSUMPTIONS.md: slippage, look-ahead, survivorship 명시

Refs: docs/EXECUTION_PLAN.md#step-10
```

---

## STEP 11 — pandas_market_calendars 도입

### 목표
KRX·NYSE 휴장일·timezone 보정. forward-fill 금지 옵션 도입.

### 변경 파일
**수정**:
- `chart_agent_service/data_collector.py` — bar reindex 시 valid_days만 사용
- `chart_agent_service/config.py` — market 코드 enum
- `chart_agent_service/ticker_utils.py` — market detection (신규)

**신규 생성**:
- `chart_agent_service/calendar/__init__.py`
- `chart_agent_service/calendar/market_calendar.py`
- `tests/unit/test_market_calendar.py`

### 신규 의존성
```toml
[project.dependencies]
pandas_market_calendars = ">=4.4,<5.0"
```

### 구현 사양

```python
import pandas_market_calendars as mcal
from functools import lru_cache

@lru_cache(maxsize=2)
def get_calendar(market: Literal["KRX", "NYSE"]):
    code = "XKRX" if market == "KRX" else "NYSE"
    return mcal.get_calendar(code)

def get_valid_trading_days(market: str, start: date, end: date) -> pd.DatetimeIndex:
    cal = get_calendar(market)
    schedule = cal.schedule(start_date=start, end_date=end)
    return mcal.date_range(schedule, frequency="1D").normalize()

def reindex_to_trading_days(df: pd.DataFrame, market: str,
                            forward_fill: bool = False) -> pd.DataFrame:
    if df.empty:
        return df
    start = df.index.min()
    end = df.index.max()
    valid = get_valid_trading_days(market, start.date(), end.date())
    df_reindexed = df.reindex(valid)
    if forward_fill:
        df_reindexed = df_reindexed.ffill()
    return df_reindexed

def is_trading_day(market: str, dt: datetime | None = None) -> bool:
    dt = dt or datetime.now(timezone.utc)
    cal = get_calendar(market)
    schedule = cal.schedule(start_date=dt.date(), end_date=dt.date())
    return not schedule.empty

def get_market_session(market: str, dt: datetime | None = None) -> str:
    """returns 'pre_open', 'regular', 'post_close', 'closed'"""
    # ...
```

DataCollector 통합:
```python
def fetch_ohlcv(ticker: str, period: str) -> pd.DataFrame:
    market = "KRX" if _is_korean(ticker) else "NYSE"
    raw = _fetch_from_source(ticker, period)
    # 휴장일 reindex (forward_fill 금지)
    return reindex_to_trading_days(raw, market, forward_fill=False)
```

### 테스트 시나리오
- 2026-05-05 (어린이날) → KRX is_trading_day=False
- 2026-12-25 → NYSE is_trading_day=False
- 어린이날 포함 7일 fetch → KRX 휴장일 제외 후 6 영업일 반환
- forward_fill=False → 휴장일 row 미포함
- forward_fill=True → 휴장일에 직전 영업일 가격으로 채움

### 완료 기준
- 모든 테스트 pass
- `/health` 응답에 `current_market_session: "KRX_REG"` 등 메타 추가

### 커밋 메시지
```
feat(calendar): pandas_market_calendars 도입 + KRX/NYSE 휴장일 보정

- get_calendar(market) lru_cache 캐싱
- reindex_to_trading_days(forward_fill=False) 표준 옵션
- DataCollector fetch_ohlcv 후 자동 reindex
- is_trading_day, get_market_session 헬퍼
- /health 응답에 market_session 메타 추가

Refs: docs/EXECUTION_PLAN.md#step-11
```

---

## STEP 12 — Variance-aware aggregation

### 목표
단순 점수 합산이 "강한 충돌"을 감지하지 못하는 약점 보완. 그룹·에이전트 신호의 분산을 측정해 high-variance 케이스를 별도 처리.

### 의존성
- Step 8 완료 필수

### 변경 파일
**수정**:
- `stock_analyzer/agent_groups.py` — variance 계산
- `stock_analyzer/enhanced_decision_maker.py` — variance 기반 conviction 조정
- `chart_agent_service/db.py` — signal_outcomes에 variance 컬럼 추가

### 구현 사양

```python
def aggregate_with_variance(group_results: dict[AgentGroup, GroupResult]) -> dict:
    scores = [_signal_score(g.signal) * g.confidence for g in group_results.values()]
    weights = [1.0] * len(scores)  # 또는 regime weight
    mean_score = np.average(scores, weights=weights)
    weighted_var = np.average((np.array(scores) - mean_score) ** 2, weights=weights)
    weighted_std = np.sqrt(weighted_var)

    agreement = ("high" if weighted_std < 1.5 else
                 "medium" if weighted_std < 3.0 else
                 "low")
    return {
        "mean_score": mean_score,
        "std": weighted_std,
        "agreement": agreement,
    }

# Decision Maker에서
agg = aggregate_with_variance(group_results)
if agg["agreement"] == "low":
    # 분산이 큼 → 신뢰도 하향 OR wait 처리
    final_conviction *= 0.7
    if abs(final_score) < 5:
        final_signal = "wait"
        flags.append("HIGH_VARIANCE_WAIT")
```

DB 스키마:
```sql
ALTER TABLE signal_outcomes ADD COLUMN signal_std REAL;
ALTER TABLE signal_outcomes ADD COLUMN agreement_level TEXT;
```

### 테스트 시나리오
- 4 그룹 모두 BUY conviction 0.7 → low variance, conviction 유지
- 2 그룹 BUY + 2 그룹 SELL → high variance, conviction 30% 감소, wait
- 1 그룹 strong SELL + 3 그룹 weak BUY → medium variance

### 완료 기준
- 모든 테스트 pass
- signal_outcomes에 variance 누적 → 추후 high-variance 케이스의 hit rate 별도 분석 가능

### 커밋 메시지
```
feat(variance): variance-aware aggregation + HIGH_VARIANCE_WAIT 플래그

- aggregate_with_variance: 그룹별 점수 가중 분산 계산
- agreement_level: high/medium/low
- low → conviction *= 0.7, score < 5 시 wait 처리
- signal_outcomes에 signal_std, agreement_level 기록

Refs: docs/EXECUTION_PLAN.md#step-12
```

---

## 부록 A — 단계 진행 후 통합 검증

12 단계 모두 완료 시 다음 통합 검증을 수행한다.

### A.1 End-to-end 시나리오
```bash
# 1. 워치리스트 스캔
curl -X POST http://localhost:8100/scan

# 2. 응답 메타 검증
# - kill_switch_state: not_blocked
# - regime: STRONG_UPTREND (또는 현 시장 상태)
# - groups: 4개 (Technical, Fundamental, Macro, Risk)
# - data_freshness: 모든 ticker is_fresh=true
# - signal_outcomes_recorded: true

# 3. 백테스트
curl http://localhost:8100/backtest/005930.KS
# - Sharpe (rf 차감), Sortino, Calmar 출력
# - 가정 메타 (slippage, commission) 포함

# 4. signal_outcomes 평가
docker compose --profile dev exec agent-api \
    python -m chart_agent_service.jobs.evaluate_signal_outcomes
```

### A.2 KPI 측정
- kill_switch가 시뮬레이션된 silent failure 케이스 100% 차단
- signal_outcomes 자동 갱신 (주1회 cron)
- regime detector 정상 작동 (Streamlit에 표시)
- 모든 LLM 호출이 LiteLLM Router 경유
- 백테스트 보고서에 rf 차감 Sharpe 명시
- Variance-aware aggregation의 low agreement 케이스 식별

---

## 부록 B — 트러블슈팅

### B.1 Step 1 — kill_switch 오작동
- `kill_switch_events` 테이블 조회: `sqlite3 chart_agent.db "SELECT * FROM kill_switch_events ORDER BY triggered_at DESC LIMIT 10"`
- middleware 우회: `unset DAILY_LOSS_LIMIT_HARD_PCT` 후 재기동

### B.2 Step 3 — DataStaleError 빈번
- 인터넷 연결 확인
- yfinance rate limit: `sleep(60)` 후 재시도
- pykrx 의존성 미설치 시 한국 종목은 FDR로만 폴백

### B.3 Step 9 — LLM Router 호출 실패
- 환경변수 확인: `GEMINI_API_KEY`, `MAC_STUDIO_URL`, `OLLAMA_BASE_URL`
- circuit_breaker 상태 reset: `python -c "from circuitbreaker import CircuitBreakerMonitor; CircuitBreakerMonitor.all_closed()"`
- LiteLLM 디버그: `litellm.set_verbose=True` 후 stderr 확인

### B.4 일반
- 컨테이너 로그: `docker compose --profile dev logs -f agent-api | tee /tmp/api.log`
- DB 백업: `sqlite3 chart_agent.db ".backup /tmp/chart_agent_$(date +%Y%m%d).db"`
- 롤백: `git revert <commit-sha>` 또는 `git checkout main && docker compose --profile dev up -d --build`

---

## 부록 C — Claude Code 세션 시작 템플릿

각 단계 시작 시 다음을 Claude Code에 던진다:

```
/clear

다음 단계를 진행한다. 본 디렉토리는 stock_auto이며, CLAUDE.md를 먼저 읽고 시작한다.

목표: docs/EXECUTION_PLAN.md의 STEP N 완료
완료 기준: 해당 단계의 "완료 기준" 섹션 모두 충족

순서:
1. CLAUDE.md 검토 (특히 §6 절대 하지 말 것)
2. docs/EXECUTION_PLAN.md#step-N 섹션 검토
3. git checkout -b feature/step-N-<short-name>
4. 변경 파일 목록의 신규 파일 먼저 생성, 그 후 수정
5. tests/ 작성 후 pytest 통과 확인
6. ruff check + ruff format + mypy 통과 확인
7. docker compose --profile dev up -d --build 후 /health 정상 확인
8. 커밋 메시지 템플릿 그대로 사용
9. PR 생성

질문이 있다면 작업 시작 전에 모두 물어라. 작업 중 추측으로 진행하지 마라.
```

세션이 길어지면 `/compact`. 단계 완료 후 `/clear`.

---

## 부록 D — 진행 추적 표

12 단계 완료 시 본 표를 갱신:

| Step | 시작일 | 완료일 | PR | 비고 |
|---|---|---|---|---|
| 1 | 2026-05-14 | 2026-05-14 | feature/step-1-kill-switch | GlobalKillSwitch + 7 트리거 |
| 2 | 2026-05-14 | 2026-05-14 | feature/step-2-signal-aggregator | signal_agg 패키지 (내장 signal 충돌→rename) |
| 3 | 2026-05-14 | 2026-05-14 | feature/step-3-ohlcv-cache | CacheEntry + tenacity retry + 다중소스 |
| 4 | 2026-05-14 | 2026-05-14 | feature/step-4-signal-outcomes | signal_outcomes V2 + cron job + ECE |
| 5 | 2026-05-14 | 2026-05-14 | feature/step-5-mfi | MFI, RSI/MFI 조합, MACD/RSI cross |
| 6 | 2026-05-14 | 2026-05-14 | feature/step-5-mfi | Step 5와 동일 브랜치 |
| 7 | 2026-05-14 | 2026-05-14 | feature/step-7-regime-detector | 5-state regime + VHF + /regime endpoint |
| 8 | 2026-05-14 | 2026-05-14 | feature/step-8-agent-groups | 4-group + reflect + variance 기반 |
| 9 | 2026-05-14 | 2026-05-14 | feature/step-9-llm-router | LiteLLM 3-tier + circuit breaker |
| 10 | 2026-05-14 | 2026-05-14 | feature/step-11-10-calendar-backtest | rf 차감 Sharpe/Sortino/Calmar |
| 11 | 2026-05-14 | 2026-05-14 | feature/step-11-10-calendar-backtest | pandas_market_calendars KRX/NYSE |
| 12 | 2026-05-14 | 2026-05-14 | feature/step-12-variance | variance-aware aggregation + HIGH_VARIANCE_WAIT |

---

**문서 끝.** 12 단계 모두 ✅ 시 본 시스템은 0–3개월 P0+P1 마일스톤 달성. 다음 단계는 P2 (DSR/PBO 백테스트 검증, F-Score/Z-Score, IC-weighted ensemble, pykrx/DART 통합)으로 진행.

