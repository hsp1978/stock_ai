# Backtest Assumptions

> Step 10 — 모든 백테스트 결과는 아래 가정을 기반으로 산출됨.

## Slippage

| 시장 | 종목 유형 | Slippage |
|---|---|---|
| KRX | KOSPI200 대형주 | 5 bp |
| KRX | 중소형주 | 15 bp |
| NYSE | 대형주 | 2 bp |
| NYSE | ETF | 1 bp |

## Trading Costs

| 항목 | 값 | 비고 |
|---|---|---|
| 한국 수수료 | 0.015% | 증권사 기준 |
| 한국 거래세 | 0.20% | 2026 기준 (`settings.KRX_TRADING_TAX_PCT`로 조정) |
| 미국 수수료 | 0% | Charles Schwab 등 free trade 가정 |

## Look-ahead Bias 방지

- Bar close 시점 시그널 → next bar open 체결 (1-bar delay)
- Indicator 계산 시 only past bars 사용 (`.shift(1)` 명시)

## Survivorship Bias

- 워치리스트 13종목은 현재 시점에서 선택됨 → 명시적 한계
- 백테스트 결과는 universe selection bias 포함

## Risk-Free Rate

| 시장 | 지표 | 2026-05 기준 |
|---|---|---|
| 한국 | KOFR (Korean Overnight Financing Rate) | 3.5% |
| 미국 | 3M T-Bill yield | 4.5% |

Sharpe / Sortino 계산 시 일별 rf = `annual_rf / 252 / 100` 으로 차감.

## 분배·배당 처리

- yfinance `auto_adjust=True` 사용 (블랙박스)
- 분기별 split/dividend audit cron 별도 운영 예정 (P2)

## 거래 단위

- 한국: 1주 (소수점 거래 미지원)
- 미국: 1주 (fractional 미지원 가정)

## 공매도

- 2025-03-31 한국 공매도 전면 재개
- 본 시스템은 long-only; short signal은 청산 트리거로만 사용

## 보고 지표

백테스트 결과에 항상 포함해야 할 항목:

- Sharpe (rf 차감)
- Sortino
- Calmar
- Max Drawdown
- Win Rate
- Profit Factor
- Average Win / Average Loss
- Total Trades
- 가정 메타 (rf, slippage, commission 값)
