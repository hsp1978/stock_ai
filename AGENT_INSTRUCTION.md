# 에이전트 종합 지시문 (Agent Instruction Document)

## 1. 시스템 아키텍처 개요

```
[Ubuntu 서버 — WebUI + 로컬 엔진]          [Mac Studio — 에이전트 서비스]
stock_analyzer/                            chart_agent_service/
  webui.py (Streamlit :8501)                 service.py (FastAPI :8100)
  local_engine.py ──직접 import──→           analysis_tools.py (16개 분석 도구)
                   ──HTTP GET───→            data_collector.py (yfinance)
                                             backtest_engine.py
                                             ml_predictor.py
                                             portfolio_optimizer.py
                                             paper_trader.py
                                             config.py
                                             Ollama (llama3.1:8b :11434)
```

**연결 방식 2가지:**
- **직접 import**: `local_engine.py`가 `chart_agent_service/` 모듈을 `sys.path`로 추가하여 Python 함수 직접 호출 (분석 16개 도구, 백테스트, ML, 포트폴리오, 페이퍼트레이딩)
- **HTTP API**: Mac Studio의 FastAPI(`http://100.108.11.20:8100`)를 호출하여 뉴스/차트패턴/섹터비교/매크로 데이터 수집

---

## 2. 에이전트가 실행하여 가져오는 결과 값 총정리

### 2-1. 핵심 분석 (16개 분석 도구) — `analysis_tools.py`

모든 도구는 동일한 기본 구조의 dict를 반환합니다:

```json
{
  "tool": "도구_함수명",
  "name": "한글 도구명",
  "signal": "buy | sell | neutral",
  "score": -10.0 ~ +10.0,
  "detail": "요약 텍스트",
  "...도구별 상세 필드..."
}
```

| # | 도구 함수명 | 한글명 | 반환하는 주요 필드 |
|---|------------|--------|-------------------|
| 1 | `trend_ma_analysis` | 이동평균선 배열 분석 | `sma_values`, `price_vs_sma`, `alignment`(bullish/bearish/mixed), `cross_signal`(golden_cross/dead_cross/none) |
| 2 | `rsi_divergence_analysis` | RSI 다이버전스 분석 | `current_rsi`, `rsi_zone`(overbought/oversold/neutral), `divergence`(bullish_regular/bearish_regular/bullish_hidden/bearish_hidden/none) |
| 3 | `bollinger_squeeze_analysis` | 볼린저밴드 스퀴즈 분석 | `bb_upper`, `bb_lower`, `bb_width_pct`, `pct_b`, `squeeze`(bool), `expanding`(bool) |
| 4 | `macd_momentum_analysis` | MACD 모멘텀 분석 | `macd`, `signal_line`, `histogram`, `cross`(bullish_cross/bearish_cross/none), `histogram_acceleration`, `zero_position` |
| 5 | `adx_trend_strength_analysis` | ADX 추세 강도 분석 | `adx`, `plus_di`, `minus_di`, `trend_strength`(very_strong/strong/weak/no_trend), `trend_direction`, `di_cross` |
| 6 | `volume_profile_analysis` | 거래량 프로파일 분석 | `current_volume`, `volume_ratio`, `obv_trend`(rising/falling/flat), `accumulation_distribution`(accumulation/distribution/neutral) |
| 7 | `fibonacci_retracement_analysis` | 피보나치 되돌림 분석 | `levels`(0.0~1.0 피보나치 가격), `current_retracement`, `nearest_level`, `nearest_support`, `nearest_resistance` |
| 8 | `volatility_regime_analysis` | 변동성 체제 분석 | `current_atr`, `atr_pct`, `percentile`, `regime`(high/above_average/normal/below_average/low), `vol_trend`, `annualized_volatility` |
| 9 | `mean_reversion_analysis` | 평균 회귀 분석 | `z_scores`(z_20, z_50), `avg_z_score`, `reversion_probability` |
| 10 | `momentum_rank_analysis` | 모멘텀 순위 분석 | `returns`(1w, 1m, 3m 수익률%), `weighted_return`, `acceleration`(accelerating/decelerating/neutral) |
| 11 | `support_resistance_analysis` | 지지/저항선 분석 | `pivot`, `resistance`(R1,R2,swing), `support`(S1,S2,swing), `upside_pct`, `downside_pct`, `risk_reward_ratio` |
| 12 | `correlation_regime_analysis` | 수익률 자기상관 분석 | `autocorrelations`(lag_1~5), `hurst_exponent`, `regime`(trending/mean_reverting/random_walk) |
| 13 | `risk_position_sizing` | 포지션 사이징/리스크 | `entry_price`, `stop_loss`, `take_profit`, `stop_distance`, `recommended_qty`, `position_value`, `position_pct`, `split_entry`(3단계 분할), `warnings` |
| 14 | `kelly_criterion_analysis` | 켈리 기준 배팅 | `win_rate`, `avg_win_pct`, `avg_loss_pct`, `win_loss_ratio`, `kelly_full_pct`, `kelly_half_pct`, `optimal_position_pct`, `sharpe_ratio` |
| 15 | `beta_correlation_analysis` | 베타/상관관계 분석 | `beta`, `beta_60d`, `alpha_annual_pct`, `correlation`, `r_squared`, `tracking_error_pct`, `information_ratio`, `benchmark`("SPY") |
| 16 | `event_driven_analysis` | 이벤트 드리븐 분석 | `events`(list), `earnings_dates`, `52w_high`, `52w_low`, `analyst_recommendation` |

### 2-2. 종합 결과 (composite) — `ChartAnalysisAgent.compute_composite_score()`

16개 도구 결과를 합산한 최종 판단:

```json
{
  "ticker": "NVDA",
  "analysis_date": "2026-04-10T14:08:00",
  "final_signal": "BUY | SELL | HOLD",
  "composite_score": "-10.0 ~ +10.0 (16개 도구 점수 평균)",
  "confidence": "0 ~ 10 (의견 일치도 기반)",
  "signal_distribution": {"buy": 6, "sell": 3, "neutral": 7},
  "tool_count": 16,
  "tool_summaries": [
    {"tool": "함수명", "name": "한글명", "signal": "buy|sell|neutral", "score": 0, "detail": "요약"}
  ],
  "tool_details": ["도구별 전체 dict 16개"],
  "llm_conclusion": "LLM 종합 판단 텍스트 (마크다운)",
  "agent_mode": "ollama | gpt4o",
  "fundamentals": {"pe_ratio": null, "forward_pe": null, "peg_ratio": null, "...": "..."},
  "options_pcr": {"put_call_ratio_oi": null, "put_call_ratio_vol": null, "...": "..."},
  "insider_trades": [{"date": "", "insider": "", "transaction": "", "shares": 0, "value": 0}],
  "chart_path": "/path/to/chart.png",
  "json_path": "/path/to/output.json",
  "analyzed_at": "ISO datetime"
}
```

### 2-3. Mac Studio API 응답 (HTTP 경유)

| 엔드포인트 | 반환 구조 | 주요 필드 |
|-----------|----------|----------|
| `GET /news/{ticker}` | 뉴스 감성 분석 | `news_count`, `overall_sentiment`(bullish/bearish/neutral), `overall_score`(-10~+10), `articles`[{title, source, published, summary, sentiment, score, keywords}] |
| `GET /chart-pattern/{ticker}` | 차트 패턴 인식 | `patterns`[{name, name_kr, confidence(0~1), direction(bullish/bearish), description, target_price, invalidation_price}] |
| `GET /sector/{ticker}` | 섹터 비교 | `sector`, `industry`, `peers`, `comparison`{pe_ratio, momentum_1m, beta: {value, sector_avg, percentile}}, `sector_trend`, `relative_strength` |
| `GET /macro` | 매크로 환경 | `vix`{value, trend, signal}, `us10y`{...}, `dxy`{...}, `oil_wti`{...}, `sp500_trend`, `market_regime`, `summary` |
| `GET /watchlist` | watchlist 조회 | `count`, `tickers`[str] |
| `POST /watchlist/add?ticker=X` | 종목 추가 | `ok`(bool), `msg`, `tickers`[str] |
| `POST /watchlist/remove?ticker=X` | 종목 제거 | `ok`(bool), `msg`, `tickers`[str] |
| `POST /watchlist/set?tickers=A,B,C` | 전체 교체 | `ok`(bool), `msg`, `tickers`[str] |

### 2-4. 확장 분석 모듈 결과

| 모듈 | 엔진 함수 | 반환 구조 |
|------|----------|----------|
| 백테스트 | `engine_backtest(ticker)` | `{ticker, strategies:{sma_cross, rsi_reversion, composite_signal}, best_strategy, best_sharpe}` — 각 전략: total_return_pct, sharpe_ratio, max_drawdown_pct, win_rate_pct, profit_factor |
| ML 예측 | `engine_ml_predict(ticker)` | `{ticker, models:{rf_5d, gb_5d}, best_model, best_prediction("UP"/"DOWN"), best_up_probability, best_accuracy}` |
| 포트폴리오 최적화 | `engine_portfolio_optimize(method)` | `{method, portfolio_return_pct, portfolio_volatility_pct, sharpe_ratio, allocation:{ticker:{weight_pct, amount}}}` |
| 상관/베타 | `engine_correlation_beta()` | `{individual:{ticker:{beta, alpha, correlation}}, pair_correlations, portfolio_beta, hedge_ratios}` |
| 팩터 랭킹 | `engine_factor_ranking()` | `{ranking:[{ticker, rank, weighted_factor_score, factor_momentum, factor_value, ...}]}` |
| 페이퍼 트레이딩 | `engine_paper_status()` | `{total_equity, cash, position_value, total_pnl, unrealized_pnl, win_rate_pct, positions:{}}` |

---

## 3. 데이터 흐름 (End-to-End)

```
1. watchlist.txt 에서 종목 동적 로드 (WebUI에서 실시간 관리, 하드코딩 없음)
   - WebUI 사이드바: Add/Remove 버튼으로 종목 추가/삭제
   - engine_load_watchlist() -> 매 호출 시 watchlist.txt 파일 읽기
   - service.py: GET/POST /watchlist API로 원격 관리 가능
   - 양쪽 파일 자동 동기화 (stock_analyzer/watchlist.txt <-> chart_agent_service/watchlist.txt)
   |
   v
2. fetch_ohlcv(ticker) -> yfinance OHLCV 2년치
   |
   v
3. calculate_indicators(df) -> SMA/EMA/RSI/BB/ATR/ADX/MACD/OBV 계산
   |
   v
4. ChartAnalysisAgent(ticker, df).run(mode="ollama")
   4a. 16개 AnalysisTools 메서드 실행 -> tool_results[]
   4b. compute_composite_score() -> final_signal, composite_score, confidence
   4c. Ollama/GPT-4o에 결과 전달 -> llm_conclusion
   |
   v
5. 부가 데이터 수집
   5a. fetch_fundamentals(ticker) -> P/E, PEG, Beta 등
   5b. fetch_options_pcr(ticker) -> Put/Call Ratio
   5c. fetch_insider_trades(ticker) -> 내부자 거래
   |
   v
6. 결과 저장: JSON 파일 + latest_results 캐시 + 차트 PNG
   |
   v
7. 알림 판단
   - composite_score >= BUY_THRESHOLD(5.0) & confidence >= MIN_CONFIDENCE(5.0) -> 매수 알림
   - composite_score <= SELL_THRESHOLD(-5.0) -> 매도 알림
   - 중복 억제: 동일 종목+신호 1시간 내 1회
   - 냉각기: SELL 후 COOLING_OFF_DAYS(3일) 동안 BUY 억제
   |
   v
8. WebUI에서 표시
   - Dashboard: 전체 종목 카드 (신호/점수/신뢰도)
   - Detail: 16개 도구 상세 + AI 해석 + 차트
   - Report: 뉴스/차트패턴/섹터/매크로 + AI 종합 리포트
   - Quant: 백테스트/ML/포트폴리오/페이퍼트레이딩
```

---

## 4. 연결 인터페이스 규격

### 4-1. local_engine.py가 노출하는 함수 (WebUI -> Engine)

| 함수 | 인자 | 반환 | 용도 |
|------|------|------|------|
| `engine_health()` | 없음 | dict | 시스템 상태 |
| `engine_info()` | 없음 | dict | 설정 정보 |
| `engine_scan_ticker(ticker, ai_mode)` | str, str | dict | 단일 종목 분석 |
| `engine_scan_all(tickers)` | list[str] | dict | 전체 스캔 |
| `engine_get_all_results()` | 없음 | dict | 캐시된 전체 결과 요약 |
| `engine_get_ticker_result(ticker)` | str | dict\|None | 종목별 상세 결과 |
| `engine_get_history(limit)` | int | dict | 스캔 히스토리 |
| `engine_get_chart_path(ticker)` | str | str\|None | 차트 PNG 경로 |
| `engine_backtest(ticker)` | str | dict | 백테스트 결과 |
| `engine_ml_predict(ticker)` | str | dict | ML 예측 |
| `engine_portfolio_optimize(method)` | str | dict | 포트폴리오 최적화 |
| `engine_correlation_beta()` | 없음 | dict | 상관/베타 |
| `engine_factor_ranking()` | 없음 | dict | 팩터 랭킹 |
| `engine_paper_status()` | 없음 | dict | 모의매매 현황 |
| `engine_paper_order(...)` | ticker, action, qty, price, reason | dict | 수동 주문 |
| `engine_paper_auto()` | 없음 | dict | 자동 모의매매 |
| `engine_paper_reset()` | 없음 | dict | 초기화 |
| `engine_interpret_tool(ticker, tool_key, provider)` | str, str, str | str(마크다운) | 개별 도구 AI 해석 |
| `engine_interpret_full_report(ticker, provider)` | str, str | str(마크다운) | 종합 AI 리포트 |
| `engine_fetch_news(ticker)` | str | dict | 뉴스 감성 |
| `engine_chart_pattern(ticker)` | str | dict | 차트 패턴 |
| `engine_sector_compare(ticker)` | str | dict | 섹터 비교 |
| `engine_macro_context()` | 없음 | dict | 매크로 환경 |
| `engine_load_watchlist()` | 없음 | list[str] | watchlist 동적 로드 |
| `engine_save_watchlist(tickers)` | list[str] | None | watchlist 저장 |
| `engine_add_ticker(ticker)` | str | dict | 종목 추가 |
| `engine_remove_ticker(ticker)` | str | dict | 종목 제거 |
| `engine_set_watchlist(tickers)` | list[str] | dict | watchlist 전체 교체 |
| `engine_available_llm()` | 없음 | dict | 사용 가능 LLM |

### 4-2. Multi-LLM 해석 파이프라인

```
engine_interpret_full_report(ticker, provider="auto")
  |
  v
1. engine_get_ticker_result(ticker) -> 16개 도구 결과 수집
2. _build_full_report_prompt() -> 리포트 프롬프트 조립
3. _gather_extra_context(ticker) -> 뉴스+매크로+차트패턴+섹터 수집 (HTTP)
4. prompt에 EXTRA_CONTEXT 삽입
5. _call_llm(prompt, provider)
   - 우선순위: Gemini -> Ollama -> OpenAI (auto 모드)
   - fallback: 실패 시 다음 provider로 자동 전환
6. 응답 상단에 사용된 LLM 모델명 메타데이터 삽입
   "<!-- llm_meta:Gemini 2.0 Flash-->"
```

---

## 5. 설정 파라미터 (config.py)

| 파라미터 | 기본값 | 설명 |
|---------|-------|------|
| `OLLAMA_BASE_URL` | http://localhost:11434 | Ollama 서버 |
| `OLLAMA_MODEL` | llama3.1:8b | 사용 모델 |
| `TRADING_STYLE` | swing | scalping / swing / longterm |
| `SCAN_INTERVAL_MINUTES` | 30 | 자동 스캔 주기 (분) |
| `BUY_THRESHOLD` | 5.0 | 매수 알림 기준 점수 |
| `SELL_THRESHOLD` | -5.0 | 매도 알림 기준 점수 |
| `MIN_CONFIDENCE` | 5.0 | 최소 신뢰도 |
| `ACCOUNT_SIZE` | 100,000 | 가상 계좌 크기 ($) |
| `RISK_PER_TRADE_PCT` | 1.0 | 1거래당 리스크 (%) |
| `MAX_POSITION_PCT` | 20.0 | 최대 포지션 비중 (%) |
| `TAKE_PROFIT_RR_RATIO` | 2.0 | 손익비 목표 |
| `COOLING_OFF_DAYS` | 3 | SELL 후 매수 냉각기 (일) |

**스타일별 프리셋:**

| 스타일 | SMA 기간 | EMA 기간 | ATR 배수 | 데이터 기간 | 타임프레임 |
|--------|---------|---------|---------|-----------|-----------|
| scalping | [5, 20] | [9, 21] | 1.2x | 60일 | intraday |
| swing | [20, 50, 200] | [12, 26] | 2.0x | 2년 | daily |
| longterm | [50, 120, 200] | [50, 100] | 3.0x | 5년 | weekly |

---

## 6. 절대 제거 금지 항목 (DO NOT REMOVE / SIMPLIFY)

> **경고:** 아래 항목들은 런타임 안정성의 핵심입니다. 축소/제거 시 JSON 직렬화 오류, LLM 컨텍스트 누락 등이 발생합니다.

### 6-1. `_sanitize()` 함수 — `local_engine.py`

분석 결과를 JSON으로 변환할 때 **모든 비표준 타입**을 처리합니다. **절대 축소하지 마세요.**

| 타입 | 변환 | 제거 시 증상 |
|------|------|-------------|
| `datetime` | `.isoformat()` | `TypeError: Object of type datetime is not JSON serializable` |
| `pd.Timestamp` | `.isoformat()` | 동일 — pandas 시각 데이터에서 발생 |
| `np.bool_` | `bool()` | `TypeError: Object of type bool_ is not JSON serializable` |
| `np.integer` | `int()` | 정수 직렬화 오류 |
| `np.floating` | `float()` + NaN/Inf 체크 | NaN이 JSON에 포함되면 프론트엔드 크래시 |
| `np.ndarray` | `.tolist()` 재귀 | 배열 직렬화 오류 |
| dict key `str(k)` | 키를 문자열로 강제 변환 | Timestamp/int가 dict key인 경우 직렬화 오류 |

### 6-2. `_gather_extra_context()` 주간 트렌드 DB 블록

LLM이 종합 리포트 작성 시 **과거 스캔 이력(DB)**을 참조하여 WoW(Week-over-Week) 변화를 해석합니다.
이 블록이 없으면 LLM은 현재 단일 스캔만 보고 판단하므로 **추세 반전/지속 판단이 불가능**합니다.

```python
# ⚠ 제거 금지 — _gather_extra_context() 내부
try:
    weekly = get_weekly_ticker(ticker, weeks_ago=0)
    if weekly and weekly.get("stats", {}).get("scan_count", 0) > 0:
        stats = weekly["stats"]
        parts.append(f"**주간 트렌드 (DB 기반)**\n...")
except Exception as e:
    print(f"  [{ticker}] 주간 트렌드 수집 실패: {e}")
```

### 6-3. `_build_full_report_prompt()` 주간 추세 분석 섹션

LLM 프롬프트에 아래 2가지가 반드시 포함되어야 합니다:

1. **헤더:** `"## 추가 컨텍스트 (주간트렌드/뉴스/매크로/섹터/차트패턴)"` — "주간트렌드" 포함 필수
2. **분석 섹션:** `"### 주간 추세 분석\n[DB 누적 데이터 기반 WoW 변화 해석 — 점수/신호 추이, 반전/지속 판단]"`

### 6-4. 코드 수정 전 체크리스트

- [ ] `git pull origin main` 으로 최신 코드 확인
- [ ] `_sanitize()` 전체 타입 처리(datetime, pd.Timestamp, np.bool_ 포함)가 유지되는지 확인
- [ ] `_gather_extra_context()` 주간 트렌드 블록이 있는지 확인
- [ ] `_build_full_report_prompt()` 주간 추세 분석 섹션이 있는지 확인
- [ ] 컴파일 검증: `python -c "import py_compile; py_compile.compile('파일', doraise=True)"`
- [ ] 커밋 전 `git diff` 로 의도하지 않은 삭제가 없는지 확인

---

## 7. 에이전트 작업 시 준수 규칙

1. **모든 결과는 JSON-serializable**: NaN/Inf -> None, datetime -> ISO string, numpy -> Python native
2. **에러 응답 표준**: `{"error": "메시지"}` 형태로 반환, 에러도 dict로 감싸야 함
3. **타임아웃 준수**: 뉴스 120s, 차트패턴 60s, 섹터 30s, 매크로 15s
4. **output 디렉토리**: 분석 JSON은 `chart_agent_service/output/{TICKER}_agent_{YYYYMMDD_HHMM}.json`
5. **점수 체계**: 모든 score는 `-10 ~ +10` 범위, signal은 `buy/sell/neutral` (소문자)
6. **종합 신호**: composite_score > 2 -> BUY, < -2 -> SELL, 그 외 -> HOLD (대문자)
7. **신뢰도**: 16개 도구 중 가장 많은 일치 비율 x 10
8. **LLM 프롬프트 언어**: 한국어 응답, 마크다운 형식
9. **`_sanitize()` 함수 필수 적용**: numpy/pandas 타입 -> JSON 호환 타입 변환
10. **모니터링 종목은 하드코딩 금지**: 종목 목록은 반드시 `watchlist.txt` 파일에서 동적 로드해야 하며, 코드나 환경변수에 직접 기입하지 않는다. WebUI에서 실시간 추가/삭제가 가능해야 한다.
11. **watchlist 단일 소스**: `stock_analyzer/watchlist.txt`가 정식 소스. `chart_agent_service/watchlist.txt`는 안내 파일(주석만 있음)이므로 종목을 직접 추가하지 않는다.
12. **`_sanitize()` 축소 금지**: 섹션 6-1 참조. pd.Timestamp, np.bool_, datetime 등 전체 타입 처리를 유지해야 한다.
13. **주간 트렌드 DB 연동 제거 금지**: 섹션 6-2, 6-3 참조. `_gather_extra_context()`와 `_build_full_report_prompt()`의 주간 트렌드 관련 코드를 유지해야 한다.

---

## 8. 리포지토리 규칙

- **정식 리포:** `github.com:hsp1978/stock_ai.git` — Mac/Ubuntu 모두 이 리포에 push/pull
- **stock_auto 리포는 사용하지 않음** (이전 착오로 생긴 중복 리포)
- **DB 모듈:** `chart_agent_service/db.py` (단일 테이블 `scan_log`) — `scan_logger.py`는 삭제됨, 복원하지 마세요

---

## 9. 파일 구조 참조

```
stock_auto/
  AGENT_INSTRUCTION.md           # 이 파일 — 에이전트 코딩 규칙
  chart_agent_service/           # 에이전트 코어 (Mac Studio 배포 단위)
    config.py                    # 전역 설정 + 스타일 프리셋
    db.py                        # SQLite 스캔 로그 DB (단일 테이블 scan_log)
    data_collector.py            # yfinance OHLCV + 지표 계산 + 펀더멘털/옵션/내부자
    analysis_tools.py            # 16개 분석 도구 + LLM 에이전트 오케스트레이션
    backtest_engine.py           # SMA크로스/RSI역추세/복합시그널 백테스트
    ml_predictor.py              # RandomForest/GradientBoosting 방향 예측
    portfolio_optimizer.py       # 마코위츠/리스크패리티/팩터랭킹/상관베타
    paper_trader.py              # 모의매매 시뮬레이터
    news_analyzer.py             # 뉴스 감성 분석
    chart_pattern.py             # 차트 패턴 인식 (알고리즘 기반)
    sector_compare.py            # 섹터/산업 비교
    macro_context.py             # 매크로 경제 지표
    service.py                   # FastAPI 서버 (Mac Studio 독립 실행용)
    watchlist.txt                # 안내 파일 (종목 추가 금지 — stock_analyzer/ 참조)
    output/                      # 분석 결과 JSON + 차트 PNG + scan_log.db
  stock_analyzer/                # WebUI + 로컬 엔진 (Ubuntu 서버)
    webui.py                     # Streamlit 대시보드 (watchlist Add/Remove UI 포함)
    local_engine.py              # 로컬 분석 엔진 (chart_agent_service 직접 import + Multi-LLM)
    scanner.py                   # 백그라운드 스케줄러
    watchlist.txt                # 관심 종목 목록 (Single Source of Truth, WebUI에서 관리)
    requirements.txt             # 통합 의존성 목록
    .streamlit/config.toml       # Streamlit 서버 설정
```
