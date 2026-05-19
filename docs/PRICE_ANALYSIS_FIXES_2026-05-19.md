# 주가 분석 모듈 수정 내역 (2026-05-19)

이번 수정은 분석 결과의 방향성 왜곡, 미래 데이터 누수, 데이터 소스 우선순위 우회, 백테스트 look-ahead bias를 제거하는 데 초점을 맞췄다.

## 수정 범위

- `chart_agent_service/ml_predictor.py`
  - 5일 후 수익률 라벨 생성 시 미래 종가가 없는 마지막 `horizon`개 행을 `DOWN`이 아니라 `NaN`으로 남기도록 수정했다.
  - 피처 생성 결과의 `inf/-inf`를 `NaN`으로 치환해 학습기 입력 오류를 줄였다.
  - LSTM 스케일러를 전체 데이터가 아니라 학습 구간에만 `fit`하도록 변경해 테스트 구간 누수를 제거했다.
  - `/ml/{ticker}` 경로의 앙상블을 단순 평균에서 `test_accuracy` 기반 가중 평균으로 변경했다.

- `stock_analyzer/ml_pipeline_fix.py`
  - 개선 ML 파이프라인에서도 마지막 5개 미래 미확정 행이 하락 라벨로 들어가던 문제를 수정했다.
  - 학습 행 수(`rows_used`)를 기록해 confidence shrinkage가 실제 표본 수 기준으로 동작하도록 했다.

- `stock_analyzer/multi_agent.py`, `chart_agent_service/analysis_tools.py`
  - 멀티에이전트 evidence wrapper(`{"tool": ..., "result": ...}`)를 진입계획에 넘길 때 원본 tool result로 정규화하도록 수정했다.
  - `risk_position_sizing`, `entry_plan_analysis`는 방향 판단 도구가 아니라 실행 계획 도구로 분리해 최종 composite 방향 점수에서 제외했다.

- `chart_agent_service/signal_agg/aggregator.py`
  - conviction을 상승 확률처럼 계산하던 구조를 방향(-1~1)과 확신도(0~1)로 분리했다.
  - 강한 SELL 합의가 낮은 conviction으로 처리되어 `wait`가 되던 문제를 수정했다.

- `chart_agent_service/data_collector.py`
  - 한국 종목은 yfinance 배치 캐시를 사용하지 않고 `pykrx -> FDR -> yfinance` 우선순위를 유지하도록 수정했다.
  - `DATA_SOURCE`가 yfinance가 아닐 때 yfinance 배치 프리페치를 생략하고, 설정된 데이터 소스를 우선 시도하도록 정리했다.

- `chart_agent_service/entry_plan.py`, `chart_agent_service/analysis_tools.py`
  - 볼린저밴드 결과 키를 `squeeze/is_squeeze`, `bb_upper/upper_band` 양쪽에서 호환되도록 수정했다.
  - 모멘텀 가속 판단을 1주 수익률과 3개월 주간 환산 수익률의 같은 단위 비교로 변경했다.
  - long 포지션 손절가는 현재가 아래 후보 중 더 가까운 가격을 선택하도록 수정했다.

- `chart_agent_service/backtest_engine.py`
  - 현재 시점 tool result를 과거 60봉에 재사용하던 복합 시그널 백테스트를 중단하고, look-ahead bias 방지 note를 남기도록 변경했다.
  - walk-forward SMA 테스트 구간은 학습 구간 이전 데이터로 계산된 SMA 값을 유지해 긴 slow window 때문에 테스트가 비는 문제를 줄였다.

- `stock_analyzer/enhanced_technical_analyzer.py`
  - 기본 분석 기간을 `3mo`에서 `1y`로 변경해 MA200 등 장기 지표가 기본 경로에서 계산될 수 있게 했다.
  - 볼린저 squeeze 평균 bandwidth가 짧은 데이터에서 `NaN`으로 남지 않도록 fallback을 추가했다.
  - 지지/저항 리스크 평가는 현재가 아래 지지선, 현재가 위 저항선만 사용하도록 수정했다.

- `chart_agent_service/safety/kill_switch.py`, `chart_agent_service/service.py`
  - 전체 단위 테스트를 멈추게 하던 kill-switch 미들웨어 테스트 경로를 정리하기 위해 미들웨어를 재사용 가능한 ASGI 미들웨어로 분리했다.
  - `/scan` 등 보호 대상 POST 요청은 halt 상태에서 423을 반환하고, `/health` 같은 조회 경로는 통과하는 동작을 직접 검증한다.

- `chart_agent_service/screener.py`, `chart_agent_service/service.py`, `stock_analyzer/webui.py`, `stock_analyzer/scanner.py`, `stock_analyzer/local_engine.py`
  - MA 정배열 점수가 과거 rolling 초기 `NaN` 때문에 항상 0점이 되던 문제를 최신 행 기준 검증으로 수정했다.
  - 손실이 없는 강한 상승 구간의 RSI를 `NaN`이 아니라 100으로 계산하고, 무변동 구간은 50으로 처리했다.
  - MACD 골든크로스 신선도 점수를 문서 의도대로 1봉 전 30점에서 10봉 전 20점까지 선형 감점하도록 수정했다.
  - 스크리너 실행 ID를 분 단위에서 마이크로초 단위로 바꿔 같은 분 안의 실행 결과가 DB에서 섞이지 않게 했다.
  - 한국 종목 스크리너는 yfinance 배치 캐시를 우회하고 `pykrx -> FDR -> yfinance` 개별 조회 우선순위를 유지하도록 정리했다.
  - 최소 시총 API 파라미터를 실제 단위에 맞게 `min_market_cap_100m`으로 추가하고, 기존 `min_market_cap_bn`은 호환 alias로 남겼다.
  - 로컬 WebUI screener 프록시는 하드코딩된 `localhost:8100` 대신 `AGENT_API_URL`을 사용한다.

## 회귀 테스트

- `tests/unit/test_signal_aggregator.py`
  - 강한 SELL 합의가 `sell` decision을 생성하는 테스트를 추가했다.

- `tests/unit/test_data_collector.py`
  - 한국 종목이 yfinance 배치 캐시를 무시하고 pykrx 경로를 사용하는 테스트를 추가했다.

- `tests/unit/test_price_analysis_fixes.py`
  - ML 타깃 마지막 구간 `NaN` 처리
  - 볼린저 키 alias 기반 진입계획
  - 현재 tool result 기반 복합 백테스트 replay 차단

- `tests/unit/test_kill_switch.py`
  - `TestClient` 기반 hang을 제거하고 ASGI 미들웨어를 직접 호출해 423 차단 응답을 검증한다.

- `tests/unit/test_screener.py`
  - MA 정배열 최신 행 판정, 강한 상승 RSI=100, MACD 10봉 전 최소 점수, run_id 충돌 방지, 한국 종목 yfinance 배치 우회 동작을 검증한다.

## 남은 주의 사항

- 복합 시그널을 진짜 과거 백테스트하려면 각 과거 시점에서 tool set을 다시 계산한 시계열 점수가 필요하다.
- `DATA_SOURCE=polygon`, `DATA_SOURCE=kis`는 팩토리 슬롯이 있으나 실제 소스 클래스가 없으면 기존 yfinance fallback을 사용한다.
