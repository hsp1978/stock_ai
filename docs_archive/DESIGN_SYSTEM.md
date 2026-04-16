# Stock AI Agent — Vivid Spectrum Design System

WebUI(Streamlit) 전체에 적용된 디자인 토큰, 컴포넌트 스타일, 레이아웃 규칙을 정리한 문서.

---

## 1. Foundations

### 1.1 Color Palette

#### Surface Layers

| Token | Hex | 용도 |
|---|---|---|
| `--L0` | `#080a12` | 앱 전체 배경 |
| `--L1` | `#121520` | 카드·입력·패널 배경 |
| `--L2` | `#1e2235` | 카드 hover 상태 |
| `--surface-low` | `#151826` | 입력 필드 배경 |
| `--surface-bright` | `#282d42` | 밝은 서피스 |
| `--outline` | `#7c80a0` | 범용 테두리·레이블 |
| `--outline-variant` | `#3a3f58` | 약한 테두리(카드, 배지) |
| `--ghost` | `rgba(90,96,140,0.15)` | 고스트 배경 |

#### Primary Colors (Purple → Blue Gradient)

| Token | Hex | 용도 |
|---|---|---|
| `--primary` | `#b794f6` | 밝은 프라이머리 (텍스트, 라벨) |
| `--primary-ctr` | `#7c5cfc` | 메인 프라이머리 (버튼, 액센트) |
| `--primary-dim` | `#5a3ec8` | 어두운 프라이머리 (스크롤바) |
| `--primary-glow` | `rgba(124,92,252,0.25)` | 글로우 이펙트 |
| `--grad-primary` | `linear-gradient(135deg, #7c5cfc, #5b8def)` | 버튼·배지 그라디언트 |
| `--grad-nav` | `linear-gradient(90deg, #1a1040, #141832, #121a30)` | 네비게이션 바 배경 |

#### Accent Colors

| Token | Hex | 용도 |
|---|---|---|
| `--accent-cyan` | `#22d3ee` | 보조 강조색 |
| `--accent-pink` | `#f472b6` | 보조 강조색 |
| `--accent-amber` | `#fbbf24` | 보조 강조색 |

#### Semantic Colors

| Token | Hex | 용도 |
|---|---|---|
| `--buy` / `--color-up` | `#10b981` | BUY 시그널, 상승 |
| `--buy-bright` | `#34d399` | BUY 밝은 변형 |
| `--sell` / `--color-down` | `#f43f5e` | SELL 시그널, 하락 |
| `--sell-bright` | `#fb7185` | SELL 밝은 변형 |
| `--hold` | `#f59e0b` | HOLD 시그널 |

#### Text Colors

| Token | Hex | 용도 |
|---|---|---|
| `--on-bg` | `#e4e5f1` | 페이지 본문 |
| `--on-surface` | `#ecedf8` | 카드 값, 가격, 타이틀 |
| `--on-surface-variant` | `#b4b8d4` | 보조 텍스트, 라벨 |

### 1.2 Typography

| 요소 | Font Family | Weight | Size | Tracking |
|---|---|---|---|---|
| **UI 전체 (본문)** | Inter, -apple-system, BlinkMacSystemFont, sans-serif | 400 | — | — |
| **제목 (h1–h3)** | Inter | 700–900 | — | -0.02em |
| **페이지 타이틀** `.page-title` | Inter | 800 | 2rem | -0.03em |
| **페이지 부제** `.page-subtitle` | Inter | 400 | 0.8rem | — |
| **섹션 타이틀** `.section-title` | Inter | 700 | 1.1rem | -0.01em |
| **라벨** | Inter | 700 | 0.625rem | 1.2px |
| **숫자·가격** | JetBrains Mono | 700 | 0.9–2.5rem | -0.03em |
| **등락률** | JetBrains Mono | 600 | 0.7rem | — |
| **타임스탬프** | JetBrains Mono | 400 | 0.625rem | 0.3px |

**Web Fonts:**
```
https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap
```

### 1.3 Spacing & Radius

| Token | Value | 사용처 |
|---|---|---|
| Card border-radius | `14px` | summary-card, ticker-expanded |
| Navigation border-radius | `14px` | top-nav |
| Nav item border-radius | `10px` | top-nav-item |
| Badge border-radius | `6px–10px` | signal-pill, signal-badge-lg |
| Chip border-radius | `6px` | watchlist chip |
| Grid gap | `16px` | summary-grid |
| Section margin-top | `28px` | section-header |
| Card padding | `24px` | summary-card |

---

## 2. Components

### 2.1 Top Navigation Bar (`.top-nav`)

상단 고정 가로 네비게이션 바. **보라→남색 그라디언트 배경**으로 light 테마에서도 확실한 대비.

```
┌─ grad-nav ─────────────────────────────────────────────────────┐
│ Stock AI │ Home │ Dashboard │ Report │ Detail │ ... │ Status   │
│ (gradient│      │ (active=  │        │        │     │ (glow)   │
│  text)   │      │  grad-    │        │        │     │          │
│          │      │  primary) │        │        │     │          │
└────────────────────────────────────────────────────────────────┘
```

- 배경: `--grad-nav` (보라→남색 그라디언트)
- 보더: `1px solid rgba(124,92,252,0.20)`
- 박스 섀도: `0 4px 24px rgba(124,92,252,0.08)`
- 브랜드: 그라디언트 텍스트 (`--grad-primary`)
- 비활성 아이템: `--on-surface-variant`, hover 시 `rgba(124,92,252,0.12)` 배경
- 활성 아이템: `--grad-primary` 배경, 흰색 텍스트, 보라 글로우 섀도
- `position: sticky; top: 0; z-index: 999`

### 2.2 Summary Card (`.summary-card`)

4열 그리드로 Total / Buy / Sell / Hold 카운트 표시.

- 배경: `--L1`, 보더: `1px solid --outline-variant`
- Hover: `--L2` 배경, `--primary-ctr` 보더, 보라 글로우, `translateY(-2px)`
- 하단 프로그레스 바: `4px` 높이
- `border-radius: 14px`

### 2.3 Signal Pill (`.signal-pill`)

인라인 시그널 표시 (테이블 내 등).

| Class | Background | Text | Border | Dot Glow |
|---|---|---|---|---|
| `.signal-pill.buy` | `rgba(16,185,129,0.12)` | `#34d399` | `rgba(16,185,129,0.20)` | `0 0 6px --buy` |
| `.signal-pill.sell` | `rgba(244,63,94,0.12)` | `#fb7185` | `rgba(244,63,94,0.20)` | `0 0 6px --sell` |
| `.signal-pill.hold` | `rgba(245,158,11,0.12)` | `#f59e0b` | `rgba(245,158,11,0.20)` | `0 0 6px --hold` |

### 2.4 Signal Badge Large (`.signal-badge-lg`)

Detail 페이지 상단 시그널 표시.

| Class | Background | Text |
|---|---|---|
| `.buy` | `linear-gradient(135deg, #10b981, #059669)` | `#ffffff` |
| `.sell` | `linear-gradient(135deg, #f43f5e, #e11d48)` | `#ffffff` |
| `.hold` | `linear-gradient(135deg, #f59e0b, #d97706)` | `#1a1000` |

- `box-shadow: 0 4px 16px rgba(0,0,0,0.2)`

### 2.5 Section Title (`.section-title`)

섹션 구분용 타이틀. **좌측 보라 보더 액센트**.

- `1.1rem`, `700`, `--on-surface`
- 좌측: `3px solid --primary-ctr` border
- `padding-left: 12px`

### 2.6 Ticker Bar (`.ticker-expanded`)

시장 지수를 그리드로 표시.

- 배경: `--L1`, 보더: `1px solid --outline-variant`
- Hover: `rgba(124,92,252,0.08)` 배경, `translateY(-1px)`
- `border-radius: 14px`

### 2.7 Watchlist Chip (`.wl-chip`)

- 배경: `rgba(124,92,252,0.10)` (보라 틴트)
- 보더: `1px solid rgba(124,92,252,0.20)`
- 텍스트: `--primary` (#b794f6)
- Hover: 더 진한 보라 배경

### 2.8 LLM Body (`.llm-body`)

AI 분석 결과 표시.

- 배경: `--L1`, 좌측 보더: `3px solid --primary-ctr`
- 서브 헤딩: `--primary` 색상
- `border-radius: 12px`

### 2.9 Empty State (`.empty-state`)

데이터 없을 때 중앙 정렬 메시지. opacity `0.3–0.6`.

---

## 3. Streamlit Overrides

### Widget Overrides

| 위젯 | 속성 | 값 |
|---|---|---|
| `stMetric` | background | `--L1` |
| `stMetric` | border | `1px solid --outline-variant`, hover → `--primary-ctr` |
| `stMetric` | hover glow | `0 2px 12px --primary-glow` |
| `stMetric` value | font | JetBrains Mono `1.25rem` |
| `stSelectbox` | background | `--L1`, border `--outline-variant` |
| `stTextInput` | background | `--surface-low`, focus glow `--primary-glow` |
| `stExpander` | border | `1px solid --outline-variant` |
| `stTabs` active | background | `--primary-ctr`, color `#ffffff` |
| `stDataFrame` | border-radius | `12px` |

### Button Overrides

| Type | Background | Color | Shadow |
|---|---|---|---|
| `primary` | `--grad-primary` | `#ffffff` | `0 2px 8px --primary-glow` |
| `secondary` | `--L1` | `--on-surface-variant` | none |
| `secondary:hover` | `rgba(124,92,252,0.10)` | `--primary` | border → `--primary-ctr` |

### Streamlit Theme Config (`.streamlit/config.toml`)

```toml
[theme]
base = "dark"
primaryColor = "#7c5cfc"
backgroundColor = "#0b0e14"
secondaryBackgroundColor = "#161b28"
textColor = "#e1e2eb"
```

---

## 4. Charts (Plotly)

### 공통 레이아웃 (`_plotly_base_layout`)

```python
template      = "plotly_dark"
paper_bgcolor = "rgba(0,0,0,0)"
plot_bgcolor  = "#080a12"
font          = Inter, #b4b8d4, 12px
gridcolor     = "rgba(90,96,140,0.12)"
zerolinecolor = "rgba(90,96,140,0.18)"
```

### Score Bar Chart

- 바 색상: score > 0 → `#10b981`, < 0 → `#f43f5e`, == 0 → `#1e2235`
- 텍스트: JetBrains Mono 11px `#b4b8d4`

### Pie Chart Colors

```python
["#b794f6", "#10b981", "#f43f5e", "#f59e0b", "#b4b8d4", "#7c5cfc"]
```

### DataTable Signal Styling

- BUY → `#10b981`, SELL → `#f43f5e`, HOLD → `#f59e0b`

---

## 5. Layout Structure

```
┌───────────────────────────────────────────────────────────────────┐
│ ┌─ Top Navigation Bar (grad-nav) ──────────────────────────────┐ │
│ │ Stock AI │ Home │ Dashboard │ Report │ ... │ Status          │ │
│ └──────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ ┌─ Main Content ────────────────────────────────────────────────┐ │
│ │ Page Title (gradient text)                                    │ │
│ │ Page Subtitle                                                 │ │
│ │                                                               │ │
│ │ ┌─ Market Ticker Bar (grid, L1) ──────────────────────────┐  │ │
│ │ │ S&P 500  │ NASDAQ  │ DOW  │ KOSPI  │ KOSDAQ │ ...      │  │ │
│ │ └─────────────────────────────────────────────────────────┘  │ │
│ │                                                               │ │
│ │ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │ │
│ │ │  TOTAL   │ │   BUY    │ │   SELL   │ │   HOLD   │         │ │
│ │ │  (hover→ │ │  (green  │ │  (red    │ │ (amber   │         │ │
│ │ │  purple  │ │   glow)  │ │   glow)  │ │   glow)  │         │ │
│ │ │  glow)   │ │          │ │          │ │          │         │ │
│ │ └──────────┘ └──────────┘ └──────────┘ └──────────┘         │ │
│ │                                                               │ │
│ │ Score Overview (bar chart)                                    │ │
│ │ Analysis Results (dataframe)                                  │ │
│ └───────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ ┌─ Sidebar (collapsed) ─┐                                        │
│ │ Stock AI (gradient)    │                                        │
│ │ Status Grid            │                                        │
│ │ Manual Scan            │                                        │
│ │ Watchlist (purple chips│                                        │
│ └────────────────────────┘                                        │
└───────────────────────────────────────────────────────────────────┘
```

### 페이지별 구성

| 페이지 | 컴포넌트 |
|---|---|
| **Home** | Ticker Bar → Metric Grid (4-col) → System Status → Score Chart → Analysis DataFrame |
| **Dashboard** | Ticker Bar → Summary Grid → Score Bar Chart → Analysis DataFrame |
| **Report** | Ticker Selector → Tool Results → AI Interpretation → Deep Analysis |
| **Detail** | Ticker Selector → Signal Badge + Detail Metrics → Tool Results (chart + table) → Chart Image → LLM Conclusion |
| **Backtest** | Strategy Config → Backtest Results → Performance Charts |
| **ML Predict** | Model Selection → Prediction Results |
| **Portfolio** | Allocation Pie → Holdings Table → Risk Metrics |
| **Ranking** | Ranking Table → Score Distribution |
| **Paper Trade** | Trade Journal → P&L Summary |
| **History** | Expander list → per-scan DataFrame |

---

## 6. Design Tokens Quick Reference

```css
/* Surface Layers */
--L0:              #080a12;
--L1:              #121520;
--L2:              #1e2235;
--surface-low:     #151826;
--surface-bright:  #282d42;

/* Borders */
--outline:         #7c80a0;
--outline-variant: #3a3f58;
--ghost:           rgba(90,96,140,0.15);

/* Primary (Purple → Blue) */
--primary:         #b794f6;
--primary-ctr:     #7c5cfc;
--primary-dim:     #5a3ec8;
--primary-glow:    rgba(124,92,252,0.25);
--grad-primary:    linear-gradient(135deg, #7c5cfc, #5b8def);
--grad-nav:        linear-gradient(90deg, #1a1040, #141832, #121a30);

/* Accent */
--accent-cyan:     #22d3ee;
--accent-pink:     #f472b6;
--accent-amber:    #fbbf24;

/* Semantic */
--buy:             #10b981;
--buy-bright:      #34d399;
--sell:            #f43f5e;
--sell-bright:     #fb7185;
--hold:            #f59e0b;

/* Text */
--on-bg:           #e4e5f1;
--on-surface:      #ecedf8;
--on-surface-variant: #b4b8d4;

/* Typography */
--font-ui:         'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
--font-mono:       'JetBrains Mono', monospace;
```

---

## 7. 신규 기능 가이드 (2026-04-14 추가)

오픈소스 프로젝트(Freqtrade, Qlib, OpenBB, NautilusTrader, Cluefin 등) 참고하여 추가된 기능들.

### 7.1 ML 앙상블 + SHAP 설명력 (Cluefin 스타일)

**기능:** RandomForest, GradientBoosting 외에 **LightGBM, XGBoost, LSTM** 앙상블 + SHAP 피처 중요도

**API:**
```python
GET /ml/{ticker}?ensemble=true
```

**결과 예시:**
```json
{
  "ensemble": {
    "prediction": "UP",
    "up_probability": 0.6234,
    "signal": "buy",
    "model_count": 5
  },
  "models": {
    "lgb_5d": {
      "up_probability": 0.6150,
      "test_accuracy": 0.5789,
      "shap": {
        "shap_available": true,
        "feature_importance_shap": {
          "rsi": 0.023456,
          "sma_ratio_20": 0.018901,
          "volatility_10d": 0.015234
        },
        "latest_shap_values": {
          "rsi": -0.012345,
          "sma_ratio_20": 0.008901
        }
      }
    }
  }
}
```

**SHAP 해석:**
- `feature_importance_shap`: 평균 절대 SHAP 값 (전역 중요도)
- `latest_shap_values`: 최근 예측의 개별 피처 기여도 (양수 = 상승 기여, 음수 = 하락 기여)

**의존성:**
```
shap>=0.44.0
lightgbm>=4.1.0
xgboost>=2.0.0
tensorflow>=2.15.0
```

### 7.2 Trailing Stop / 시간 기반 청산 (NautilusTrader/Freqtrade 스타일)

**기능:** 고점 대비 X% 이탈 시 자동 청산 + N일 경과 시 자동 청산

**API:**
```python
POST /paper/order?ticker=NVDA&action=BUY&qty=10&price=100.0&trailing_stop_pct=0.05&time_stop_days=30&stop_loss_price=95.0&take_profit_price=110.0
```

**파라미터:**
- `trailing_stop_pct`: Trailing stop 비율 (0.05 = 5%)
- `time_stop_days`: 시간 기반 청산 일수 (30 = 30일 후 자동 청산)
- `stop_loss_price`: 고정 손절가 (선택)
- `take_profit_price`: 고정 익절가 (선택)

**동작:**
1. 매수 후 고점 `peak_price` 추적
2. 현재가 > `peak_price` → `peak_price` 갱신
3. 현재가 <= `peak_price * (1 - trailing_stop_pct)` → 자동 청산
4. `entry_date`로부터 `time_stop_days` 경과 → 자동 청산
5. 고정 SL/TP 도달 → 자동 청산

**자동 청산 확인:**
- `update_position_prices(prices: dict[str, float])` 호출 시 자동 실행
- 반환값: 청산된 주문 리스트

### 7.3 HyperOpt 파라미터 최적화 (Freqtrade 스타일)

**기능:** Optuna를 사용한 전략 파라미터 자동 최적화 (Sharpe Ratio 최대화)

**API:**
```python
GET /backtest/optimize/{ticker}?strategy=rsi_reversion&n_trials=50
```

**지원 전략:**
- `sma_cross`: fast_period (5~30), slow_period (35~100)
- `rsi_reversion`: oversold (20~35), overbought (65~80)
- `bollinger_reversion`: bb_period (10~30), bb_std (1.5~3.0)

**결과 예시:**
```json
{
  "strategy": "rsi_reversion",
  "best_params": {"oversold": 28, "overbought": 72},
  "best_sharpe": 1.234,
  "n_trials": 50,
  "result": {
    "total_return_pct": 45.67,
    "annualized_return_pct": 23.12,
    "max_drawdown_pct": -12.34,
    "total_trades": 25
  }
}
```

**의존성:**
```
optuna>=3.5.0
```

### 7.4 Walk-Forward 백테스트 (vectorbt/Qlib 스타일)

**기능:** Rolling window 방식 out-of-sample 테스트 (과적합 방지)

**API:**
```python
GET /backtest/walk-forward/{ticker}?strategy=rsi_reversion&train_window=252&test_window=63&n_splits=5
```

**파라미터:**
- `train_window`: 학습 윈도우 (거래일 수, 기본 252일 = 1년)
- `test_window`: 테스트 윈도우 (거래일 수, 기본 63일 = 3개월)
- `n_splits`: 총 분할 수 (기본 5)

**프로세스:**
1. 학습 구간에서 HyperOpt로 최적 파라미터 탐색
2. 테스트 구간에서 최적 파라미터로 백테스트 실행
3. n_splits만큼 반복 (시간 순서 유지)

**결과 예시:**
```json
{
  "strategy": "rsi_reversion",
  "walk_forward_splits": 5,
  "avg_train_sharpe": 1.456,
  "avg_test_sharpe": 0.987,
  "avg_test_return_pct": 12.34,
  "overfitting_ratio": 1.48,
  "splits": [
    {
      "split": 1,
      "train_start": "2024-01-01",
      "train_end": "2024-12-31",
      "test_start": "2025-01-01",
      "test_end": "2025-03-31",
      "best_params": {"oversold": 30, "overbought": 70},
      "train_sharpe": 1.567,
      "test_sharpe": 1.123,
      "test_return_pct": 15.67
    }
  ]
}
```

**과적합 판정:**
- `overfitting_ratio = avg_train_sharpe / avg_test_sharpe`
- 1.0 ~ 1.5: 양호
- 1.5 ~ 2.0: 주의
- > 2.0: 과적합 의심

### 7.5 확장성 고려 사항 (MCP 서버 / 멀티에이전트 준비)

모든 신규 함수는 명확한 시그니처 + 독립 모듈 구조로 설계되어, 향후 MCP 서버 노출 및 멀티에이전트 아키텍처로 확장 가능:

**MCP 서버 노출 예시:**
```python
# mcp_server.py (미래 구현 예정)
from ml_predictor import train_predict_lgb, train_predict_xgb, train_predict_lstm
from backtest_engine import optimize_strategy_params, backtest_walk_forward
from paper_trader import execute_paper_order, update_position_prices

@mcp_tool("ml_ensemble")
def mcp_ml_ensemble(ticker: str) -> dict:
    return engine_ml_predict(ticker, ensemble=True)

@mcp_tool("backtest_optimize")
def mcp_backtest_optimize(ticker: str, strategy: str) -> dict:
    return engine_backtest_optimize(ticker, strategy, n_trials=30)
```

**멀티에이전트 분리 예시:**
```python
# multi_agent.py (미래 구현 예정)
class TechnicalAnalysisAgent:
    tools = [trend_ma, rsi_divergence, ...]

class QuantAnalysisAgent:
    tools = [fibonacci, mean_reversion, ...]

class MLPredictionAgent:
    tools = [train_predict_lgb, train_predict_xgb, train_predict_lstm]

class RiskManagerAgent:
    tools = [risk_position_sizing, kelly_criterion, ...]

class DecisionMakerAgent:
    def aggregate(self, agents: list):
        # 각 에이전트 결과 종합 → 최종 판단
        pass
```

### 7.6 사용 예시

**1. 종목 스캔 + ML 앙상블:**
```python
from local_engine import engine_scan_ticker, engine_ml_predict

# 16개 도구 분석
result = engine_scan_ticker("NVDA")
print(f"신호: {result['final_signal']} (점수: {result['composite_score']})")

# ML 앙상블 예측
ml_result = engine_ml_predict("NVDA", ensemble=True)
print(f"ML 예측: {ml_result['ensemble']['prediction']} ({ml_result['ensemble']['up_probability']:.1%})")
```

**2. 백테스트 최적화 + Walk-Forward:**
```python
from local_engine import engine_backtest_optimize, engine_backtest_walk_forward

# HyperOpt로 최적 파라미터 탐색
opt_result = engine_backtest_optimize("NVDA", strategy="rsi_reversion", n_trials=50)
print(f"최적 파라미터: {opt_result['best_params']}")
print(f"최고 Sharpe: {opt_result['best_sharpe']:.3f}")

# Walk-Forward로 과적합 검증
wf_result = engine_backtest_walk_forward("NVDA", strategy="rsi_reversion", n_splits=5)
print(f"평균 테스트 Sharpe: {wf_result['avg_test_sharpe']:.3f}")
print(f"과적합 비율: {wf_result['overfitting_ratio']:.2f}")
```

**3. Trailing Stop 페이퍼 트레이딩:**
```python
from local_engine import engine_paper_order, update_position_prices

# 5% trailing stop + 30일 time stop으로 매수
order = engine_paper_order(
    ticker="NVDA",
    action="BUY",
    qty=10,
    price=100.0,
    trailing_stop_pct=0.05,  # 고점 대비 5% 이탈 시 청산
    time_stop_days=30,       # 30일 후 자동 청산
)

# 가격 업데이트 시 자동 청산 체크
auto_closed = update_position_prices({"NVDA": 105.0})
if auto_closed:
    for c in auto_closed:
        print(f"자동 청산: {c['ticker']} - {c['reason']}")
```

### 7.7 통합 테스트

```bash
# 의존성 설치
pip install -r chart_agent_service/requirements.txt

# 통합 테스트 실행
python test_new_features.py
```

**테스트 항목:**
1. ML 앙상블 + SHAP (LightGBM, XGBoost, LSTM)
2. Trailing Stop 자동 청산
3. HyperOpt 파라미터 최적화
4. Walk-Forward 백테스트

---

## 8. 참고 오픈소스 프로젝트

신규 기능 구현 시 참고한 프로젝트:

| 프로젝트 | Stars | 적용 기능 |
|---|---|---|
| [Freqtrade](https://github.com/freqtrade/freqtrade) | 48K | HyperOpt, Trailing Stop, Time-based Exit |
| [Qlib](https://github.com/microsoft/qlib) | 36K | ML 앙상블, Walk-Forward 백테스트 |
| [OpenBB](https://github.com/OpenBB-finance/OpenBB) | 35K | MCP 서버 확장성 고려 |
| [Cluefin](https://github.com/Cluefin-AI/cluefin) | ? | SHAP 설명력 |
| [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | 2.3K | Trailing Stop, Position Management |
| [vectorbt](https://github.com/polakowo/vectorbt) | 4.5K | 벡터화 백테스트 (Walk-Forward 참고) |

**확장 로드맵 (우선순위별):**
- ✅ 1. SHAP 설명력 (완료)
- ✅ 2. Trailing Stop (완료)
- ✅ 3. HyperOpt (완료)
- ✅ 4. ML 앙상블 (완료)
- ✅ 5. Walk-Forward (완료)
- ✅ 6. MCP 서버 노출 (V2.0 완료) ⭐
- ✅ 7. 멀티에이전트 시스템 (V2.0 완료) ⭐
- 🔲 8. 포트폴리오 리밸런싱 자동화 (Week 4 예정)

---

## 9. V2.0 신규 기능 가이드 (2026-04-14)

### 9.1 멀티에이전트 시스템 — `multi_agent.py`

**개념:** 단일 LLM 판단 → 6개 전문 에이전트 협업 → 의견 충돌 해결

**아키텍처:**
```
MultiAgentOrchestrator
  ├── TechnicalAnalyst (Gemini) - 차트 6개 도구
  ├── QuantAnalyst (Gemini) - 퀀트 6개 도구
  ├── RiskManager (Ollama) - 리스크 3개 도구
  ├── MLSpecialist (Ollama) - ML 앙상블
  ├── EventAnalyst (Gemini) - 뉴스/이벤트
  └── DecisionMaker (GPT-4o) - 의견 종합
```

**API:**
```python
GET /multi-agent/{ticker}

# 또는 직접 호출
from local_engine import engine_multi_agent_analyze
result = engine_multi_agent_analyze("NVDA")
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
      "reasoning": "차트상 강한 상승 추세...",
      "llm_provider": "gemini",
      "execution_time": 1.2
    },
    {
      "agent": "Risk Manager",
      "signal": "neutral",
      "confidence": 5.0,
      "reasoning": "변동성 과다로 주의 필요...",
      "llm_provider": "ollama"
    }
  ],
  "final_decision": {
    "final_signal": "buy",
    "final_confidence": 7.2,
    "consensus": "4명 매수, 1명 중립",
    "conflicts": "Risk Manager는 변동성 과다로 중립 의견이나, Technical/Quant 분석이 강력하여 최종 매수 판단",
    "reasoning": "종합 근거...",
    "key_risks": ["변동성 스파이크", "실적 발표 임박"],
    "signal_distribution": {"buy": 4, "sell": 0, "neutral": 1},
    "agent_count": 5
  },
  "total_execution_time": 8.5
}
```

**특징:**
- 병렬 실행: 5개 에이전트 동시 실행 (ThreadPoolExecutor)
- 타임아웃: 각 60초, 전체 120초
- 에러 핸들링: 개별 에이전트 실패 시에도 계속 진행
- 소수 의견 반영: 리스크 항목에 명시

### 9.2 MCP 서버 — `mcp_server_extended.py`

**개념:** Model Context Protocol 서버로 모든 분석 기능을 외부 AI에 노출

**21개 도구:**
- **핵심 5개**: analyze_stock, predict_ml, optimize_strategy, walk_forward_test, optimize_portfolio
- **개별 16개**: analyze_trend_ma, analyze_rsi_divergence, ... (16개 분석 도구 각각)
- **시스템 1개**: get_system_info

**Claude Desktop 설정:**
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

**사용 예시:**
```
Claude Desktop에서:
"NVDA 주식 분석해줘"
→ analyze_stock tool 자동 호출
→ 16개 도구 실행
→ 결과 반환

"RSI 다이버전스만 확인해줘"
→ analyze_rsi_divergence tool 호출
→ 단일 도구 결과 반환
```

**규칙:**
1. 모든 tool은 JSON 형태로 결과 반환
2. 에러도 `{"error": "..."}` 구조 유지
3. 각 tool은 독립 실행 (상태 없음)

### 9.3 V2.0 WebUI 추가 페이지 (예정)

**Multi-Agent 페이지:**
```
┌─────────────────────────────────────────┐
│ 🤖 Multi-Agent Analysis                 │
├─────────────────────────────────────────┤
│ Ticker: [NVDA ▼]   [Analyze]            │
│                                         │
│ ┌────────────┐  ┌──────────────┐       │
│ │ Single LLM │  │ Multi-Agent  │       │
│ │ HOLD       │  │ BUY          │       │
│ │ Score: +1  │  │ Confidence:7 │       │
│ └────────────┘  └──────────────┘       │
│                                         │
│ Agent Opinions:                         │
│ ├─ Technical Analyst: buy (7.5/10)     │
│ │  └─ "차트상 강한 상승 추세..."         │
│ ├─ Quant Analyst: buy (7.0/10)         │
│ ├─ Risk Manager: neutral (5.0/10) ⚠️   │
│ ├─ ML Specialist: buy (6.5/10)         │
│ └─ Event Analyst: buy (7.2/10)         │
│                                         │
│ Conflict Resolution:                    │
│ "Risk Manager는 변동성 과다로 중립..."   │
│                                         │
│ Key Risks:                              │
│ • 변동성 스파이크                        │
│ • 실적 발표 임박                         │
└─────────────────────────────────────────┘
```

**스타일:**
- 에이전트 카드: `.summary-card` 스타일 재사용
- 합의 아이콘: ✓ (일치), ⚠️ (충돌)
- 의견 분포 차트: Plotly pie chart
- 충돌 해결: `.llm-body` 스타일

---

## 10. V2.0 디자인 토큰 추가

### Agent Status Colors

| Token | Hex | 용도 |
|---|---|---|
| `--agent-active` | `#7c5cfc` | 에이전트 실행 중 |
| `--agent-success` | `#10b981` | 에이전트 성공 |
| `--agent-error` | `#f43f5e` | 에이전트 실패 |
| `--agent-neutral` | `#f59e0b` | 에이전트 중립 |
| `--consensus-high` | `#10b981` | 합의도 높음 (80%+) |
| `--consensus-medium` | `#f59e0b` | 합의도 중간 (50-80%) |
| `--consensus-low` | `#f43f5e` | 합의도 낮음 (<50%) |

### MCP Tool Badge

```css
.mcp-tool-badge {
  background: linear-gradient(135deg, #7c5cfc, #22d3ee);
  color: #ffffff;
  font-size: 0.625rem;
  padding: 4px 10px;
  border-radius: 6px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
```

### Multi-Agent Progress

```css
.agent-progress {
  display: flex;
  gap: 8px;
  margin: 12px 0;
}

.agent-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--outline-variant);
  transition: all 0.3s;
}

.agent-dot.active {
  background: var(--agent-active);
  box-shadow: 0 0 8px var(--primary-glow);
}

.agent-dot.success {
  background: var(--agent-success);
}

.agent-dot.error {
  background: var(--agent-error);
}
```
