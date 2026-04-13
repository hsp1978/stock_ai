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
