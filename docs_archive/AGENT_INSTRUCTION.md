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

**V1.0 핵심 함수 (26개)**

| 함수 | 인자 | 반환 | 용도 |
|------|------|------|------|
| `engine_health()` | 없음 | dict | 시스템 상태 |
| `engine_info()` | 없음 | dict | 설정 정보 |
| `engine_scan_ticker(ticker, ai_mode)` | str, str | dict | 단일 종목 분석 (16개 도구) |
| `engine_scan_all(tickers)` | list[str] | dict | 전체 스캔 |
| `engine_get_all_results()` | 없음 | dict | 캐시된 전체 결과 요약 |
| `engine_get_ticker_result(ticker)` | str | dict\|None | 종목별 상세 결과 |
| `engine_get_history(limit)` | int | dict | 스캔 히스토리 |
| `engine_get_chart_path(ticker)` | str | str\|None | 차트 PNG 경로 |
| `engine_backtest(ticker)` | str | dict | 백테스트 결과 |
| `engine_ml_predict(ticker, ensemble)` | str, bool | dict | ML 예측 (앙상블 옵션) ⭐ |
| `engine_backtest_optimize(...)` ⭐ | ticker, strategy, n_trials | dict | HyperOpt 최적화 |
| `engine_backtest_walk_forward(...)` ⭐ | ticker, strategy, train_window, test_window, n_splits | dict | Walk-Forward 검증 |
| `engine_portfolio_optimize(method)` | str | dict | 포트폴리오 최적화 |
| `engine_correlation_beta()` | 없음 | dict | 상관/베타 |
| `engine_factor_ranking()` | 없음 | dict | 팩터 랭킹 |
| `engine_paper_status()` | 없음 | dict | 모의매매 현황 |
| `engine_paper_order(...)` ⭐ | ticker, action, qty, price, reason, trailing_stop_pct, time_stop_days, stop_loss_price, take_profit_price | dict | 수동 주문 (Trailing Stop 지원) |
| `engine_paper_auto()` | 없음 | dict | 자동 모의매매 |
| `engine_paper_reset()` | 없음 | dict | 초기화 |
| `engine_interpret_tool(ticker, tool_key, provider)` | str, str, str | str(마크다운) | 개별 도구 AI 해석 |
| `engine_interpret_full_report(ticker, provider)` | str, str | str(마크다운) | 종합 AI 리포트 |
| `engine_fetch_news(ticker)` | str | dict | 뉴스 감성 |
| `engine_chart_pattern(ticker)` | str | dict | 차트 패턴 |
| `engine_sector_compare(ticker)` | str | dict | 섹터 비교 |
| `engine_macro_context()` | 없음 | dict | 매크로 환경 |
| `engine_available_llm()` | 없음 | dict | 사용 가능 LLM |

**V2.0 신규 함수 (1개)**

| 함수 | 인자 | 반환 | 용도 |
|------|------|------|------|
| `engine_multi_agent_analyze(ticker)` ⭐ | str | dict | 멀티에이전트 분석 (6개 에이전트 협업) |

**watchlist 관리 함수 (5개)**

| 함수 | 인자 | 반환 | 용도 |
|------|------|------|------|
| `engine_load_watchlist()` | 없음 | list[str] | watchlist 동적 로드 |
| `engine_save_watchlist(tickers)` | list[str] | None | watchlist 저장 |
| `engine_add_ticker(ticker)` | str | dict | 종목 추가 |
| `engine_remove_ticker(ticker)` | str | dict | 종목 제거 |
| `engine_set_watchlist(tickers)` | list[str] | dict | watchlist 전체 교체 |

**총 32개 함수**

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

## 9. V2.0 신규 시스템 (2026-04-14)

### 9-1. 멀티에이전트 시스템 — `multi_agent.py`

**아키텍처:**
```
사용자 요청 -> MultiAgentOrchestrator
    -> 5개 에이전트 병렬 실행 (ThreadPoolExecutor)
       - TechnicalAnalyst (Gemini): 기술 지표 6개
       - QuantAnalyst (Gemini): 퀀트 분석 6개
       - RiskManager (Ollama): 리스크 관리 3개
       - MLSpecialist (Ollama): ML 앙상블 예측
       - EventAnalyst (Gemini): 뉴스/이벤트 1개
    -> DecisionMaker (OpenAI GPT-4o): 의견 종합 및 충돌 해결
    -> 최종 리포트 반환
```

**반환 구조:**
```json
{
  "ticker": "NVDA",
  "multi_agent_mode": true,
  "agent_results": [
    {
      "agent": "Technical Analyst",
      "signal": "buy",
      "confidence": 7.5,
      "reasoning": "판단 근거 (한국어)",
      "llm_provider": "gemini",
      "execution_time": 1.2,
      "error": null
    }
  ],
  "final_decision": {
    "final_signal": "buy",
    "final_confidence": 7.8,
    "consensus": "4명 매수, 1명 중립",
    "conflicts": "Risk Manager는 변동성 과다로 중립, 하지만 기술/퀀트 분석 강력하여 매수",
    "reasoning": "종합 판단 근거",
    "key_risks": ["변동성 스파이크", "실적 발표 임박"],
    "agent_count": 5,
    "signal_distribution": {"buy": 4, "sell": 0, "neutral": 1}
  },
  "total_execution_time": 8.5,
  "analyzed_at": "2026-04-14T22:48:02"
}
```

**엔진 함수:**
- `engine_multi_agent_analyze(ticker)` → 멀티에이전트 분석 실행
- API 경로: `GET /multi-agent/{ticker}`

**규칙:**
1. 각 에이전트는 독립적으로 판단 (타임아웃 60초)
2. 실패한 에이전트는 neutral/0점으로 처리, 전체 실행은 계속
3. Decision Maker는 모든 의견을 종합하고 소수 의견도 리스크로 반영
4. 전체 실행 시간 목표: 120초 이내

### 9-2. MCP 서버 — `mcp_server.py`, `mcp_server_extended.py`

**Model Context Protocol**: Claude Desktop, ChatGPT 등 외부 AI에서 직접 도구 호출 가능

**21개 노출 도구:**
- **핵심 5개**: analyze_stock, predict_ml, optimize_strategy, walk_forward_test, optimize_portfolio
- **개별 16개**: analyze_trend_ma, analyze_rsi_divergence, ... (16개 분석 도구 각각)
- **시스템 1개**: get_system_info

**설정 예시 (Claude Desktop):**
```json
{
  "mcpServers": {
    "stock-ai": {
      "command": "python",
      "args": ["/home/ubuntu/stock_auto/mcp_server_extended.py"]
    }
  }
}
```

**규칙:**
1. 모든 도구는 JSON 형태로 결과 반환
2. 에러 발생 시에도 {"error": "..."} 구조 유지
3. 각 도구는 독립 실행 가능 (상태 없음)

### 9-3. ML 앙상블 강화 — `ml_predictor.py`

**V2.0 추가 사항:**
- **LightGBM, XGBoost 추가**: 기존 RF, GB에 2개 모델 추가 (총 5개)
- **LSTM 시계열 모델**: 시계열 패턴 학습
- **SHAP 설명력**: 각 feature의 예측 기여도 계산

**반환 구조 (ensemble=True):**
```json
{
  "ticker": "NVDA",
  "ensemble": {
    "prediction": "UP",
    "up_probability": 0.73,
    "model_count": 5,
    "agreement_rate": 0.8
  },
  "models": {
    "lgb_5d": {
      "prediction": "UP",
      "up_probability": 0.75,
      "accuracy": 0.58,
      "shap": {
        "shap_available": true,
        "feature_importance_shap": {
          "RSI": 0.234,
          "MACD": 0.187,
          "Volume": 0.156
        }
      }
    }
  }
}
```

**규칙:**
1. SHAP는 tree 기반 모델(LightGBM, XGBoost)에서만 가능
2. 앙상블은 가중 평균 + 다수결 조합
3. `shap` 패키지 미설치 시 `shap_available: false`로 처리

### 9-4. HyperOpt 백테스트 최적화 — `backtest_engine.py`

**Optuna 기반 파라미터 탐색:**
```python
# 함수: optimize_strategy_params(ticker, df, strategy, n_trials)
# 전략: rsi_reversion, sma_cross, bollinger_reversion
```

**반환 구조:**
```json
{
  "ticker": "NVDA",
  "strategy": "rsi_reversion",
  "best_params": {"rsi_threshold": 32, "hold_days": 5},
  "best_sharpe": 2.34,
  "optimization_trials": 50,
  "result": {
    "total_return_pct": 28.5,
    "annualized_return_pct": 32.1,
    "sharpe_ratio": 2.34,
    "max_drawdown_pct": -12.3,
    "total_trades": 42,
    "win_rate_pct": 57.1
  }
}
```

**엔진 함수:**
- `engine_backtest_optimize(ticker, strategy, n_trials)` → HyperOpt 실행
- API 경로: `GET /backtest/optimize/{ticker}?strategy=rsi_reversion&n_trials=50`

### 9-5. Walk-Forward 백테스트 — `backtest_engine.py`

**과적합 방지 검증:**
```python
# 함수: backtest_walk_forward(ticker, df, strategy, train_window, test_window, n_splits)
# 학습 구간 → 테스트 구간을 Rolling하며 실행
```

**반환 구조:**
```json
{
  "ticker": "NVDA",
  "strategy": "rsi_reversion",
  "walk_forward_splits": 5,
  "avg_train_sharpe": 2.1,
  "avg_test_sharpe": 1.8,
  "avg_test_return_pct": 15.3,
  "overfitting_ratio": 1.17,
  "splits": [
    {
      "split": 1,
      "train_start": "2024-01-01",
      "train_end": "2024-08-31",
      "test_start": "2024-09-01",
      "test_end": "2024-10-31",
      "best_params": {"rsi_threshold": 30},
      "train_sharpe": 2.0,
      "test_sharpe": 1.9,
      "test_return_pct": 12.5,
      "test_trades": 8
    }
  ]
}
```

**규칙:**
1. 과적합 비율 = avg_train_sharpe / avg_test_sharpe
2. 1.0~1.5 양호, 2.0 이상 과적합 의심
3. 각 split마다 독립적으로 파라미터 최적화

### 9-6. Trailing Stop & 시간 기반 청산 — `paper_trader.py`

**V2.0 추가 파라미터:**
```python
execute_paper_order(
    ticker, action, qty, price, reason,
    trailing_stop_pct=0.0,      # 고점 대비 % 하락 시 청산
    time_stop_days=0,           # N일 경과 시 청산
    stop_loss_price=0.0,        # 고정 손절가
    take_profit_price=0.0       # 고정 익절가
)
```

**Trailing Stop 작동:**
```python
# 매수가 $100, trailing_stop_pct=5%
# 고점 $108 도달 → trailing stop = $102.6 (108 * 0.95)
# 가격 $102 하락 → 자동 청산 (trailing stop 발동)
```

**규칙:**
1. Trailing Stop은 고점 갱신 시마다 업데이트
2. 시간 기반 청산은 진입일 + N일 경과 시 강제 청산
3. 고정 손절/익절과 병행 사용 가능 (먼저 도달하는 조건 우선)

### 9-7. 주간 트렌드 DB 분석 — `db.py`

**SQLite 기반 스캔 이력 저장:**
```python
# 테이블: scan_log (ticker, scanned_at, signal, score, confidence, ...)
# 함수: get_weekly_ticker(ticker, weeks_ago)
```

**반환 구조:**
```json
{
  "ticker": "NVDA",
  "week": "2026-W15",
  "stats": {
    "scan_count": 5,
    "avg_score": 3.2,
    "buy_cnt": 3,
    "sell_cnt": 0,
    "hold_cnt": 2
  },
  "latest_scan": {
    "scanned_at": "2026-04-14T10:00:00",
    "signal": "BUY",
    "score": 4.5,
    "confidence": 7
  }
}
```

**LLM 활용:**
- `_gather_extra_context()`에서 주간 트렌드 수집
- LLM 프롬프트에 "주간 추세 분석" 섹션 포함
- WoW 변화를 해석하여 추세 반전/지속 판단

**규칙 (절대 제거 금지):**
1. `_gather_extra_context()` 내 주간 트렌드 블록 유지 (섹션 6-2)
2. `_build_full_report_prompt()` 내 "주간 추세 분석" 섹션 유지 (섹션 6-3)
3. DB 없이 LLM은 단일 스캔만 보므로 추세 판단 불가

---

## 10. 파일 구조 참조 (V2.0)

```
stock_auto/
  # ── 프로젝트 문서 ──
  README.md                      # V2.0 프로젝트 소개
  AGENT_INSTRUCTION.md           # 이 파일 — 에이전트 코딩 규칙
  DESIGN_SYSTEM.md               # 디자인 시스템 가이드
  ROADMAP_V2_REVISED.md          # V2.0 로드맵
  V2_PREREQUISITES.md            # V2.0 사전 준비
  V2_IMPLEMENTATION_CHECKLIST.md # 구현 체크리스트
  V2_EXECUTIVE_SUMMARY.md        # 경영진 요약

  # ── V2.0 신규 파일 ⭐ ──
  mcp_server.py                  # MCP 서버 기본 (6개 도구)
  mcp_server_extended.py         # MCP 서버 확장 (21개 도구)
  test_mcp_server.py             # MCP 테스트
  test_multi_agent.py            # 멀티에이전트 테스트
  test_v2_prerequisites.py       # V2.0 준비 상태 테스트
  claude_desktop_config.json     # Claude Desktop MCP 설정
  setup_v2.sh                    # V2.0 자동 설정 스크립트

  # ── V1.0 테스트 ──
  test_new_features.py           # ML 앙상블, Trailing Stop, HyperOpt, Walk-Forward 테스트

  chart_agent_service/           # 에이전트 코어 (Mac Studio 배포 단위)
    config.py                    # 전역 설정 + 스타일 프리셋
    db.py                        # SQLite 스캔 로그 DB (단일 테이블 scan_log)
    data_collector.py            # yfinance OHLCV + 지표 계산 + 펀더멘털/옵션/내부자
    analysis_tools.py            # 16개 분석 도구 + LLM 에이전트 오케스트레이션
    backtest_engine.py           # 백테스트 + HyperOpt + Walk-Forward ⭐
    ml_predictor.py              # ML 앙상블 (5개 모델) + SHAP ⭐
    portfolio_optimizer.py       # 마코위츠/리스크패리티/팩터랭킹/상관베타
    paper_trader.py              # 모의매매 + Trailing Stop + 시간 기반 청산 ⭐
    news_analyzer.py             # 뉴스 감성 분석
    chart_pattern.py             # 차트 패턴 인식 (알고리즘 기반)
    sector_compare.py            # 섹터/산업 비교
    macro_context.py             # 매크로 경제 지표
    service.py                   # FastAPI 서버 (Mac Studio 독립 실행용)
    watchlist.txt                # 안내 파일 (종목 추가 금지 — stock_analyzer/ 참조)
    requirements.txt             # V2.0 의존성 (shap, lightgbm, xgboost, tensorflow, optuna)
    output/                      # 분석 결과 JSON + 차트 PNG + scan_log.db

  stock_analyzer/                # WebUI + 로컬 엔진 (Ubuntu 서버)
    webui.py                     # Streamlit 대시보드 (7페이지 + Multi-Agent 추가 예정)
    local_engine.py              # 브릿지 엔진 (직접 import + Multi-LLM) ⭐
    multi_agent.py               # V2.0 멀티에이전트 시스템 (672줄) ⭐
    scanner.py                   # 백그라운드 스케줄러
    watchlist.txt                # 관심 종목 목록 (Single Source of Truth)
    requirements.txt             # 통합 의존성 목록
    .streamlit/config.toml       # Streamlit 서버 설정
    .env                         # API Keys (OPENAI, GOOGLE, FRED, FMP)
    v2/                          # V2.0 개발 디렉토리

  docs/v2/                       # V2.0 문서
    MCP_GUIDE.md                 # MCP 서버 사용 가이드
    WEEK1_COMPLETION_REPORT.md   # Week 1 완료 보고서

  backups/                       # 프로젝트 백업
    v1_backup_*.tar.gz           # V1.0 백업
```

**⭐ 표시: V2.0에서 추가/강화된 파일**

---

## 11. 🇰🇷 한국 주식 시장 지원 (V2.1 - 2026-04-15)

### 11-1. 개요

**V2.1부터 한국 주식(KOSPI/KOSDAQ) 분석을 지원합니다.**

- **티커 형식**: Yahoo Finance `.KS` (KOSPI), `.KQ` (KOSDAQ)
- **데이터 소스**: Yahoo Finance, 네이버 금융 (준비 중)
- **지원 종목**: 주요 20개 + 모든 .KS/.KQ 티커
- **UI**: 🇺🇸 US Market / 🇰🇷 Korean Market 탭 분리

### 11-2. 티커 형식 및 자동 감지

#### 자동 시장 감지 규칙

| 입력 | 감지 결과 | 정규화 | 시장 |
|------|----------|--------|------|
| `005930` | 한국 (6자리 숫자) | `005930.KS` | KR |
| `삼성전자` | 한국 (한글 포함) | `005930.KS` | KR |
| `005930.KS` | 한국 (.KS 접미사) | `005930.KS` | KR |
| `000660.KQ` | 한국 (.KQ 접미사) | `000660.KQ` | KR |
| `AAPL` | 미국 | `AAPL` | US |
| `MSFT` | 미국 | `MSFT` | US |

#### 주요 한국 종목 코드

```python
KOREAN_STOCKS = {
    '005930': '삼성전자',      # Samsung Electronics
    '000660': 'SK하이닉스',    # SK Hynix
    '035420': 'NAVER',         # NAVER
    '005380': '현대차',        # Hyundai Motor
    '051910': 'LG화학',        # LG Chem
    '006400': '삼성SDI',       # Samsung SDI
    '035720': '카카오',        # Kakao
    '207940': '삼성바이오로직스', # Samsung Biologics
    '068270': '셀트리온',      # Celltrion
    '028260': '삼성물산',      # Samsung C&T
    '105560': 'KB금융',        # KB Financial
    '055550': '신한지주',      # Shinhan Financial
    '017670': 'SK텔레콤',      # SK Telecom
    '096770': 'SK이노베이션',  # SK Innovation
    '034730': 'SK',            # SK Inc.
    '003550': 'LG',            # LG Corp.
    '051900': 'LG생활건강',    # LG H&H
    '018260': '삼성SDS',       # Samsung SDS
    '009150': '삼성전기',      # Samsung Electro-Mechanics
    '032830': '삼성생명',      # Samsung Life
}
```

### 11-3. 한국 시장 특성 (분석 시 필수 고려사항)

#### 시장 구조
- **KOSPI**: 대형주 중심, 시가총액 기준
- **KOSDAQ**: 중소형 성장주, 기술주 중심
- **거래시간**: 09:00 - 15:30 KST (점심시간 없음, 미국과 다름)
- **통화**: KRW (원화) → 가격 포맷: `₩75,000` (소수점 없음)
- **시간대**: Asia/Seoul (UTC+9)

#### 가격 제한폭
- **상한가/하한가**: 전일 종가 대비 **±30%**
- **서킷 브레이커**: KOSPI/KOSDAQ 지수 8%, 15%, 20% 하락 시 발동
- **호가 단위**: 주가에 따라 상이 (1원, 5원, 10원, 50원, 100원)

#### 투자자 구조 (한국 시장 특수성)
```
외국인: 지수 주도, 큰 손 매매
기관: 증권사, 보험, 연기금
개인: 변동성 높음, 감정 매매 빈번
프로그램: 차익거래, 알고리즘 매매
```

### 11-4. Multi-Agent 분석 가이드 (한국 주식)

#### Technical Analyst (기술적 분석가)
```yaml
한국 주식 추가 고려사항:
1. 거래량 분석
   - 외국인/기관 순매수 + 거래량 증가 = 강한 신호
   - 개인 거래량 1위이지만 외국인이 방향성 결정

2. 차트 패턴
   - 상한가/하한가 (±30%) 근접 여부
   - 갭 상승/하락 빈도 (미국보다 갭 크게 발생)

3. 이동평균선
   - 5일선, 20일선, 60일선, 120일선 (한국 선호 기준선)

4. 매물대
   - 심리적 저항선 (10,000원, 50,000원, 100,000원 단위)
```

#### Quant Analyst (퀀트 분석가)
```yaml
한국 주식 퀀트 지표:
1. 상대적 모멘텀
   - KOSPI/KOSDAQ 지수 대비 강도
   - 동일 섹터 내 상대 수익률

2. 외국인 지분율
   - 30% 이상: 외국인 선호주 (안정적)
   - 증가/감소 추세 분석

3. 재무 배수 (한국 평균치)
   - PER: 10~15배
   - PBR: 0.8~1.2배
   - ROE, 부채비율
```

#### Risk Manager (리스크 관리자)
```yaml
한국 주식 리스크 요인:
1. 시장 리스크
   - 코리아 디스카운트 (저평가 현상)
   - 북한 리스크 (지정학적)
   - 중국 경기 의존도

2. 환율 영향
   - 수출주: 원화 약세 = 실적 개선
   - 수입주: 원화 강세 = 비용 절감
   - USD/KRW 환율 모니터링 필수

3. 외국인 수급
   - 외국인 순매도 지속 = 추가 하락 압력
```

#### Event Analyst (이벤트 분석가)
```yaml
한국 시장 이벤트:
1. 공시
   - DART (전자공시시스템) 체크
   - 실적 발표: 분기(1,4,7,10월)

2. 뉴스
   - 한국어 뉴스 감성 분석
   - 정부 정책 발표 (반도체, 배터리 지원)

3. 시즌성
   - 배당락: 12월 말 (결산월)
   - 주주총회: 3월

4. 글로벌 연동
   - 미국 증시 전날 동향 (나스닥, S&P500)
   - 중국 증시 영향 (상해종합)
```

#### Decision Maker (최종 의사결정자)
```yaml
한국 주식 종합 판단 가중치:

외국인/기관 동향: 30%  ← 가장 중요!
기술적 지표: 25%
재무/밸류에이션: 20%
테마/섹터 강도: 15%
뉴스/이벤트: 10%

최종 신호:
- BUY: 외국인/기관 순매수 + 기술적 상승 + 테마 강세
- SELL: 외국인/기관 순매도 + 기술적 하락 + 악재
- NEUTRAL: 혼조, 방향성 불명확
```

### 11-5. 한국어 분석 프롬프트 예시

#### 요청 프롬프트
```
삼성전자(005930.KS) 주식을 분석해주세요.

다음 항목을 포함해주세요:
1. 현재 주가 및 기술적 지표 (RSI, MACD, 이동평균선)
2. 외국인/기관/개인 매매 동향 (최근 5일) ← Phase 2에서 구현 예정
3. 반도체 섹터 전반 동향
4. 최근 뉴스 및 공시 사항
5. 종합 의견 (매수/매도/중립)

참고: 삼성전자는 한국 대표 반도체 기업으로, 외국인 보유 비중이 높고
KOSPI 시가총액 1위입니다. 글로벌 반도체 업황과 밀접한 연관이 있습니다.
```

#### 응답 형식
```markdown
# 삼성전자 (005930.KS) 분석

## 📊 현재 시세
- 현재가: ₩75,000
- 전일 대비: +1,000원 (+1.35%)
- 거래량: 15,234,567주

## 🔍 기술적 분석
- RSI(14): 58.2 (중립)
- MACD: 긍정적 크로스오버
- 20일 이동평균: ₩73,500 (현재가 상회)

## 🏭 섹터 분석
- 반도체 업종: KOSPI 섹터 지수 +2.1%
- 글로벌 반도체: 필라델피아 반도체 지수 +1.5%

## 🎯 종합 의견
**신호: 매수 (BUY)**
**신뢰도: 7/10**

**목표가: ₩80,000**
**손절가: ₩72,000**
```

### 11-6. 파일 구조 (한국 주식 관련)

```
stock_auto/
  # ── 한국 주식 통합 ⭐ ──
  KOREAN_STOCK_INTEGRATION_PLAN.md        # 통합 계획서
  KOREAN_STOCK_AGENT_INSTRUCTIONS.md     # 에이전트 지시문
  KOREAN_STOCK_SETUP_GUIDE.md            # 사용 가이드
  KOREAN_STOCK_IMPLEMENTATION_SUMMARY.md # 구현 보고서
  test_korean_stocks.py                   # 통합 테스트

  stock_analyzer/
    korean_stocks.py         # 한국 주식 데이터 수집기 ⭐
    ticker_manager.py        # 통합 티커 관리자 ⭐
    webui.py                 # 한국/미국 탭 추가 ⭐
```

### 11-7. 한국 주식 분석 규칙

#### 데이터 수집 시
1. **티커 정규화**: 입력 티커를 항상 정규화
   ```python
   from ticker_manager import normalize_ticker
   ticker, market = normalize_ticker("005930")  # → ("005930.KS", "KR")
   ```

2. **통화 처리**: KRW는 소수점 없이 표시
   ```python
   from ticker_manager import format_price
   format_price(75000, "KR")  # → "₩75,000"
   format_price(175.50, "US")  # → "$175.50"
   ```

3. **시간대 처리**: KST (UTC+9)
   ```python
   from ticker_manager import TickerManager
   tz = TickerManager.get_timezone("KR")  # → Asia/Seoul
   ```

#### 분석 시 추가 고려사항
1. **외국인/기관 매매 동향** (Phase 2에서 추가 예정)
   - 순매수/순매도 추이
   - 외국인 지분율 변화

2. **테마/섹터**
   - 동일 테마 내 다른 종목 동향
   - 정부 정책/규제 영향

3. **환율**
   - USD/KRW 환율 (수출주 영향)
   - 원화 강세/약세 트렌드

4. **글로벌 연동**
   - 미국 증시 전날 동향 (나스닥 영향 큼)
   - 중국 증시 (상해종합)

#### LLM 프롬프트 작성 시
1. **한국 주식 판별**: 티커에 `.KS` 또는 `.KQ` 포함 시 한국 주식
2. **통화 표기**: 한국 주식은 `₩` (원화), 미국 주식은 `$` (달러)
3. **시장 특성 반영**: 외국인/기관 동향, 테마주 특성 언급
4. **가격 단위**: 한국은 천 단위 (₩75,000), 미국은 소수점 2자리 ($175.50)

### 11-8. Multi-Agent 한국 주식 분석 예시

#### 입력
```python
# API 호출
GET /multi-agent/005930.KS

# 또는 local_engine
from local_engine import engine_multi_agent_analyze
result = engine_multi_agent_analyze("005930.KS")
```

#### 출력 (예시)
```json
{
  "ticker": "005930.KS",
  "multi_agent_mode": true,
  "agent_results": [
    {
      "agent": "Technical Analyst",
      "signal": "buy",
      "confidence": 7.0,
      "reasoning": "20일 이동평균선을 상향 돌파했으며, RSI는 58로 과매수 구간 전입니다. 외국인 순매수가 지속되고 있어 긍정적입니다.",
      "llm_provider": "ollama"
    },
    {
      "agent": "Quant Analyst",
      "signal": "buy",
      "confidence": 6.5,
      "reasoning": "KOSPI 대비 상대 강도가 높으며, 반도체 섹터 전반의 모멘텀이 양호합니다.",
      "llm_provider": "ollama"
    }
  ],
  "final_decision": {
    "final_signal": "buy",
    "final_confidence": 7,
    "consensus": "매수: 4명, 중립: 1명",
    "reasoning": "기술적 지표와 섹터 모멘텀이 긍정적이며, 외국인 순매수가 지속되어 매수 신호를 제시합니다."
  }
}
```

### 11-9. 한국 주식 분석 체크리스트

#### 분석 전
- [ ] 티커 형식 확인 (.KS 또는 .KQ 포함)
- [ ] 시장 감지 (KR/US)
- [ ] 데이터 수집 가능 여부 (Yahoo Finance)

#### 분석 중
- [ ] 기술적 지표 (RSI, MACD, MA)
- [ ] KOSPI/KOSDAQ 지수 대비 강도
- [ ] 동일 섹터 내 상대 위치
- [ ] 환율 영향 (수출주/수입주)
- [ ] 미국 증시 전날 동향

#### 응답 생성 시
- [ ] 통화 KRW로 표시 (₩)
- [ ] 가격 단위 천 단위 구분 (₩75,000)
- [ ] 시간 KST 표시
- [ ] 한국 시장 특성 언급 (외국인/기관 동향)
- [ ] 목표가/손절가 제시

### 11-10. 주의사항

#### ⚠️ 현재 제한사항 (Phase 1)
1. **외국인/기관 데이터**: 아직 미구현 (Phase 2 예정)
   - 응답에서 언급은 하되, "데이터 수집 예정" 명시
2. **실시간 데이터**: 15-20분 지연 (Yahoo Finance 특성)
3. **종목명 검색**: 주요 20개만 지원 (확장 예정)

#### ✅ 지원되는 기능
1. **OHLCV 데이터**: Yahoo Finance 통해 안정적 수집
2. **기술적 지표**: 모든 TA-Lib 지표 정상 작동
3. **Multi-Agent 분석**: .KS 티커로 전체 에이전트 실행 가능
4. **백테스팅**: 한국 주식도 백테스트 가능
5. **ML 예측**: 한국 주식도 ML 모델 적용 가능

---

**⭐ V2.1 신규 추가: 한국 주식 통합 지원**
