"""Kinetic Terminal 디자인 시스템 — CSS 토큰과 컴포넌트 스타일.

`webui.py`(6,482 라인)에서 분리한 첫 조각이다. CLAUDE.md §6-10 에 따라 한 번에
쪼개지 않고 **의존성이 없는 덩어리부터** 뗀다. CSS 는 순수 문자열이라 가장 안전하다.

토큰 규격은 `docs/DESIGN_SYSTEM.md` v1.0 이고, `tests/unit/test_design_system.py` 가
이 파일과의 정합을 고정한다.
"""

from __future__ import annotations

import streamlit as st

# 원칙: 숫자가 주인공 / 색은 신호일 때만 / 면 대신 선 / 4px 배수 밀도
THEME_CSS = """
<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap');

    /* ── Stock AI 디자인 시스템 v1.0 토큰 ──
       원칙: 숫자가 주인공 / 색은 신호일 때만 / 면 대신 선 / 4px 배수 밀도 */
    :root {
        /* surface */
        --bg-canvas: #0A0C11;
        --bg-surface: #11151C;
        --bg-raised: #171D26;
        --bg-inset: #06080C;
        /* text */
        --text-hi: #EDF1F7;
        --text-mid: #9BA6B5;
        --text-low: #6A7482;
        /* border */
        --border-subtle: #1F2733;
        --border-strong: #2C3745;
        /* semantic — 상승/하락/액션 3가지 의미에만 색을 쓴다 */
        --accent: #6D7CFF;
        --accent-soft: rgba(109,124,255,.16);
        --up: #2BD98A;
        --down: #FF6B6B;
        --warn: #F5B14C;
        --info: #4CB8F5;
        /* type */
        --font-ui: 'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont, sans-serif;
        --font-num: 'JetBrains Mono', monospace;
        /* space (4px base) */
        --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
        --sp-5: 24px; --sp-6: 40px; --sp-7: 64px;
        /* radius */
        --r-tag: 4px; --r-ctl: 6px; --r-card: 10px; --r-pill: 999px;
        /* control height */
        --h-sm: 32px; --h-md: 36px; --h-lg: 40px;
        /* motion */
        --dur: 120ms; --ease: cubic-bezier(.2,.6,.2,1);

        /* ── 레거시 별칭 ──
           webui.py는 5,100 라인 단일 파일이라 CSS를 한 번에 치환하지 않는다
           (CLAUDE.md #10). 기존 규칙이 그대로 동작하도록 새 토큰에 매핑만 한다. */
        --L0: var(--bg-canvas);
        --L1: var(--bg-surface);
        --L2: var(--border-strong);
        --surface-low: var(--bg-inset);
        --surface-bright: var(--bg-raised);
        --outline: var(--text-low);
        --outline-variant: var(--border-subtle);
        --ghost: rgba(31,39,51,0.35);
        --on-bg: var(--text-hi);
        --on-surface: var(--text-hi);
        --on-surface-variant: var(--text-mid);
        --primary: var(--accent);
        --primary-ctr: var(--accent);
        --buy: var(--up);
        --buy-bright: var(--up);
        --sell: var(--down);
        --sell-bright: var(--down);
        --hold: var(--warn);
    }

    /* ── Base ── */
    .stApp {
        background: var(--L0) !important;
        font-family: var(--font-ui);
        color: var(--on-bg);
    }
    ::-webkit-scrollbar { width: 4px; height: 4px; }
    ::-webkit-scrollbar-track { background: var(--L0); }
    ::-webkit-scrollbar-thumb { background: var(--L2); border-radius: 10px; }
    h1, h2, h3 { font-family: var(--font-ui) !important; letter-spacing: -0.02em; color: var(--on-surface) !important; }

    /* ── Sidebar — No-Line: tonal shift only ── */
    div[data-testid="stSidebar"] {
        background: var(--L0) !important;
        border-right: none !important;
    }
    div[data-testid="stSidebar"] .stMarkdown p,
    div[data-testid="stSidebar"] .stMarkdown li { font-size: 13px; color: var(--on-surface-variant); }

    /* ── Page header ── */
    .page-header { margin-bottom: 28px; }
    .page-title {
        font-size: 2rem; font-weight: 800; color: var(--on-surface);
        letter-spacing: -0.03em; line-height: 1.2;
    }
    .page-subtitle {
        font-size: 0.8rem; color: var(--on-surface-variant);
        opacity: 0.7; margin-top: 4px;
    }

    /* ── Ticker bar — No-Line: L1 card on L0, no border ── */
    /* ── IndexTile (DS §05) — h76 · pad 14/16 · r10 · gap 12 · 좌측 정렬
       라벨 12 / 가격 19 / 등락 12 3단 구조. 클릭 가능해야 하므로 st.button을
       타일 형태로 스타일링한다 (Streamlit은 HTML에 콜백을 붙일 수 없다). */
    [class*="st-key-idx_btn_"] button {
        height: 76px;
        width: 100%;
        padding: 14px 16px;
        border-radius: var(--r-card);
        background: var(--bg-surface);
        border: 1px solid var(--border-subtle);
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        justify-content: center;
        gap: 2px;
        transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
    }
    [class*="st-key-idx_btn_"] button:hover {
        background: var(--bg-raised);
        border-color: var(--border-strong);
    }
    [class*="st-key-idx_btn_"] button[kind="primary"] {
        background: var(--accent-soft);
        border-color: var(--accent);
    }
    [class*="st-key-idx_btn_"] button p {
        text-align: left;
        line-height: 1.25;
        margin: 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        font-family: var(--font-num);
        font-size: 19px;
        font-weight: 600;
        color: var(--text-hi);
        font-variant-numeric: tabular-nums;
    }
    /* 첫 줄 = 지수명 라벨 (11/600 · 대문자 · text-low) */
    [class*="st-key-idx_btn_"] button p::first-line {
        font-family: var(--font-ui);
        font-size: 11px;
        font-weight: 600;
        color: var(--text-low);
        letter-spacing: .1em;
    }
    /* 마지막 줄 = 등락률 (12px). 방향은 색만이 아니라 ▲/▼ 기호로도 전달한다. */
    [class*="st-key-idx_btn_"] button p em {
        font-size: 12px;
        font-style: normal;
        font-weight: 600;
    }
    [class*="st-key-idx_btn_"] button p em.up { color: var(--up); }
    [class*="st-key-idx_btn_"] button p em.down { color: var(--down); }
    [class*="st-key-idx_btn_"] button p em.flat { color: var(--text-low); }

    /* ── SidebarNav (DS §05) — 이동 전용. 항목 h36 · 라벨 13/500
       선택 = accent-soft 배경 + 좌측 2px accent 바 (색만으로 표현하지 않음) */
    section[data-testid="stSidebar"] { width: 264px !important; }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
        height: var(--h-md);
        justify-content: flex-start;
        text-align: left;
        padding: 0 var(--sp-3);
        border: none;
        border-left: 2px solid transparent;
        border-radius: var(--r-ctl);
        background: transparent;
        color: var(--text-mid);
        font-family: var(--font-ui);
        font-size: 13px;
        font-weight: 500;
        transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
    }
    /* Streamlit이 버튼 라벨(<p>)을 가운데 정렬하므로 내부까지 좌측으로 돌린다.
       버튼 자체의 justify-content만으로는 라벨이 가운데에 남는다. */
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button p {
        width: 100%;
        margin: 0;
        text-align: left;
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
        background: var(--bg-raised);
        color: var(--text-hi);
    }
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button[kind="primary"] {
        background: var(--accent-soft);
        border-left-color: var(--accent);
        color: var(--text-hi);
        font-weight: 600;
    }
    /* 그룹 헤더 — 11px mono 대문자 */
    section[data-testid="stSidebar"] div[class*="st-key-navgrp_"] > button {
        height: 28px;
        margin-top: var(--sp-3);
        color: var(--text-low) !important;
        font-family: var(--font-num) !important;
        font-size: 11px !important;
        font-weight: 600 !important;
        letter-spacing: .1em;
        background: transparent !important;
        border-left-color: transparent !important;
    }

    /* ── CommandBar (DS §06) — 사이드바에서 분리한 조작 패널 ── */
    .status-badge {
        display: inline-flex; align-items: center; gap: var(--sp-2);
        height: 24px; padding: 0 var(--sp-3); border-radius: var(--r-pill);
        font-family: var(--font-num); font-size: 11px; font-weight: 600;
        letter-spacing: .08em; background: var(--bg-raised); color: var(--text-mid);
    }
    .status-badge .sb-dot {
        width: 6px; height: 6px; border-radius: var(--r-pill); background: var(--text-low);
    }
    .status-badge.ok { color: var(--up); }
    .status-badge.ok .sb-dot { background: var(--up); }
    .status-badge.err { color: var(--down); }
    .status-badge.err .sb-dot { background: var(--down); }

    /* Streamlit은 버튼 라벨을 중간 flex 컨테이너로 감싸 가운데 정렬한다.
       버튼의 justify-content만으로는 라벨 박스가 가운데에 남으므로 내부까지 편다. */
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button > div,
    section[data-testid="stSidebar"] div[data-testid="stButton"] > button > div > span,
    [class*="st-key-idx_btn_"] button > div,
    [class*="st-key-idx_btn_"] button > div > span,
    [class*="st-key-idx_btn_"] button [data-testid="stMarkdownContainer"],
    [class*="st-key-idx_btn_"] button p {
        justify-content: flex-start !important;
        width: 100% !important;
    }

    /* ── StatCell (DS §05) — 카드 대신 1px 분할 행 ── */
    .statcell-row {
        display: grid;
        grid-template-columns: repeat(6, 1fr);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-card);
        background: var(--bg-surface);
        margin-bottom: var(--sp-5);
        overflow: hidden;
    }
    .statcell {
        padding: var(--sp-3) var(--sp-4);
        border-left: 1px solid var(--border-subtle);
    }
    .statcell:first-child { border-left: none; }
    .statcell .sc-label {
        font-family: var(--font-num); font-size: 11px; font-weight: 600;
        letter-spacing: .1em; text-transform: uppercase; color: var(--text-low);
        margin-bottom: var(--sp-1);
    }
    .statcell .sc-value {
        font-family: var(--font-num); font-size: 26px; font-weight: 600;
        color: var(--text-hi); font-variant-numeric: tabular-nums; line-height: 1.1;
    }
    .statcell .sc-value.empty { color: var(--text-low); font-size: 15px; }
    @media (max-width: 1280px) {
        .statcell-row { grid-template-columns: repeat(3, 1fr); }
        .statcell:nth-child(4) { border-left: none; }
    }

    .ts-up { color: var(--up); }
    .ts-down { color: var(--down); }
    .ts-flat { color: var(--text-low); }

    /* ── Summary Cards — No-Line: L1 on L0, progress bar ── */
    .summary-grid {
        display: grid; grid-template-columns: repeat(4, 1fr);
        gap: 16px; margin-bottom: 24px;
    }
    .summary-card {
        background: var(--L1); border-radius: 12px;
        padding: 24px; position: relative; overflow: hidden;
        transition: background 0.3s;
    }
    .summary-card:hover { background: var(--surface-bright); }
    .summary-card .sc-icon {
        position: absolute; top: 16px; right: 20px;
        font-size: 32px; opacity: 0.06;
    }
    .summary-card .sc-label {
        font-family: var(--font-ui); font-size: 0.625rem; font-weight: 700;
        color: var(--on-surface-variant); text-transform: uppercase;
        letter-spacing: 1.2px; margin-bottom: 12px;
    }
    .summary-card .sc-value {
        font-family: 'JetBrains Mono'; font-size: 2.5rem; font-weight: 700;
        line-height: 1;
    }
    .summary-card .sc-sub {
        font-family: var(--font-ui); font-size: 0.7rem;
        color: var(--on-surface-variant); margin-top: 4px;
    }
    .summary-card .sc-bar {
        margin-top: 16px; height: 3px; border-radius: 2px;
        background: var(--L0);
    }
    .summary-card .sc-bar-fill {
        height: 100%; border-radius: 2px; transition: width 0.6s ease;
    }

    /* ── Section headers ── */
    .section-header {
        display: flex; justify-content: space-between; align-items: center;
        margin: 28px 0 14px 0;
    }
    .section-title {
        font-family: var(--font-ui); font-size: 1.1rem; font-weight: 700;
        color: var(--on-surface); letter-spacing: -0.01em;
    }
    .section-subtitle {
        font-family: 'JetBrains Mono'; font-size: 0.7rem;
        color: var(--outline);
    }

    /* ── Signal pills & badges ── */
    .signal-pill {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 3px 10px; border-radius: 4px;
        font-family: 'JetBrains Mono'; font-size: 0.625rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.5px;
    }
    .signal-pill .sp-dot { width: 5px; height: 5px; border-radius: 50%; }
    .signal-pill.buy { background: rgba(2,212,161,0.10); color: var(--buy-bright); }
    .signal-pill.buy .sp-dot { background: var(--buy); }
    .signal-pill.sell { background: rgba(253,82,111,0.10); color: var(--sell-bright); }
    .signal-pill.sell .sp-dot { background: var(--sell); }
    .signal-pill.hold { background: rgba(255,179,71,0.10); color: var(--hold); }
    .signal-pill.hold .sp-dot { background: var(--hold); }

    .signal-badge-lg {
        display: inline-flex; align-items: center; gap: 8px;
        padding: 8px 28px; border-radius: 8px;
        font-family: 'JetBrains Mono'; font-size: 1.1rem; font-weight: 800;
        letter-spacing: 2px; text-transform: uppercase;
    }
    .signal-badge-lg.buy { background: var(--buy); color: #003828; }
    .signal-badge-lg.sell { background: var(--sell); color: #40000f; }
    .signal-badge-lg.hold { background: var(--L2); color: var(--on-surface); }

    /* ── Metric cards (Streamlit stMetric) — L1 on L0 ── */
    div[data-testid="stMetric"] {
        background: var(--L1) !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 16px 18px !important;
    }
    div[data-testid="stMetric"] label {
        font-family: var(--font-ui) !important;
        font-size: 0.625rem !important;
        font-weight: 700 !important;
        color: var(--on-surface-variant) !important;
        text-transform: uppercase !important;
        letter-spacing: 0.8px !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 1.25rem !important;
        font-weight: 700 !important;
        color: var(--on-surface) !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
        font-family: 'JetBrains Mono' !important;
        font-size: 0.75rem !important;
    }

    /* ── Timestamp meta ── */
    .ts-meta {
        font-family: 'JetBrains Mono'; font-size: 0.625rem;
        color: var(--outline); text-align: right;
        margin-bottom: 8px; letter-spacing: 0.3px;
    }

    /* ── Empty state ── */
    .empty-state { text-align: center; padding: 80px 20px; }
    .empty-state .es-icon { font-size: 48px; margin-bottom: 16px; opacity: 0.2; }
    .empty-state .es-text { font-size: 0.875rem; color: var(--on-surface-variant); opacity: 0.5; }

    /* ── Streamlit widget overrides ── */
    .stDivider { opacity: 0.06; }
    .stDataFrame { border-radius: 10px; overflow: hidden; }
    .stSelectbox > div > div {
        background: var(--L1) !important;
        border-color: var(--ghost) !important;
        color: var(--on-surface) !important;
    }
    .stSelectbox [data-testid="stMarkdownContainer"] p { color: var(--on-surface) !important; }
    .stTextInput > div > div > input {
        background: var(--surface-low) !important;
        border-color: var(--ghost) !important;
        color: var(--on-surface) !important;
        caret-color: var(--primary) !important;
        border-radius: 10px !important;
    }
    .stTextInput > div > div > input:focus {
        border-color: var(--primary-ctr) !important;
        box-shadow: 0 0 0 1px rgba(93,142,241,0.25) !important;
    }
    .stTextInput > div > div > input::placeholder { color: var(--outline) !important; }

    /* ── Sidebar components ── */
    div[data-testid="stSidebar"] .stButton > button {
        background: var(--L1); border: none;
        color: var(--on-surface-variant); font-weight: 600; font-size: 13px;
        border-radius: 10px; transition: all 0.2s;
    }
    div[data-testid="stSidebar"] .stButton > button:hover {
        background: var(--surface-bright); color: var(--on-surface);
    }
    .sidebar-brand {
        font-size: 1.15rem; font-weight: 900;
        color: var(--primary-ctr); letter-spacing: -0.04em; margin-bottom: 2px;
    }
    .sidebar-label {
        font-family: 'JetBrains Mono'; font-size: 0.6rem; font-weight: 700;
        color: var(--primary-ctr); text-transform: uppercase;
        letter-spacing: 1.5px; opacity: 0.7;
    }
    .sidebar-section-label {
        font-family: var(--font-ui); font-size: 0.625rem; font-weight: 700;
        color: var(--on-surface-variant); text-transform: uppercase;
        letter-spacing: 1px; margin-bottom: 8px;
    }
    .sidebar-status-grid { display: flex; gap: 6px; margin: 12px 0; }
    .sidebar-status-item {
        flex: 1; background: var(--L1); border-radius: 10px;
        padding: 10px 6px; text-align: center;
    }
    .sidebar-status-item .ssi-label {
        font-family: var(--font-ui); font-size: 0.55rem; font-weight: 700;
        color: var(--outline); text-transform: uppercase; letter-spacing: 0.5px;
    }
    .sidebar-status-item .ssi-value {
        font-family: 'JetBrains Mono'; font-size: 0.85rem; font-weight: 700;
        color: var(--on-surface); margin-top: 3px;
    }
    .sidebar-info {
        background: var(--L1); border-radius: 10px;
        padding: 12px 14px; margin: 8px 0 16px 0;
        font-size: 0.75rem; color: var(--outline); line-height: 1.9;
    }
    .sidebar-info span { color: var(--on-surface-variant); }
    /* ── TickerChip (DS §05) — h28 · r4 · 티커 우선, 시장 코드는 색 배지로 분리.
       회사 정식 명칭을 넣으면 칩 폭이 들쭉날쭉해져 스캔이 느려진다 (명칭은 툴팁). */
    .wl-chip {
        display: inline-flex; align-items: center; gap: var(--sp-2);
        height: 28px; padding: 0 var(--sp-2) 0 var(--sp-1);
        margin: 2px; border-radius: var(--r-tag);
        background: var(--bg-raised); border: 1px solid var(--border-subtle);
        font-family: var(--font-num); font-size: 12px; font-weight: 500;
        color: var(--text-hi); font-variant-numeric: tabular-nums;
        cursor: default;
    }
    .wl-chip .tc-badge {
        display: inline-flex; align-items: center;
        height: 18px; padding: 0 5px; border-radius: var(--r-tag);
        font-size: 10px; font-weight: 600; letter-spacing: .06em;
    }
    .wl-chip .tc-badge.kr { background: rgba(76,184,245,.16); color: var(--info); }
    .wl-chip .tc-badge.us { background: var(--accent-soft); color: var(--accent); }

    /* ── Expander — No-Line: L1 on L0 ── */
    .stExpander {
        border: none !important;
        background: var(--L1) !important;
        border-radius: 10px !important;
    }
    .stExpander [data-testid="stExpanderDetails"] {
        background: var(--L1) !important;
    }

    /* ── Markdown body inside LLM conclusion ── */
    .llm-body {
        background: var(--L1); border-radius: 10px;
        padding: 24px 28px; line-height: 1.8;
        color: var(--on-surface-variant); font-size: 0.875rem;
    }
    .llm-body h2, .llm-body h3 {
        color: var(--on-surface) !important;
        font-size: 1rem !important; margin-top: 20px !important;
    }
    .llm-body strong { color: var(--on-surface); }
    .llm-body ul, .llm-body ol { padding-left: 20px; }
    .llm-body li { margin-bottom: 4px; }
</style>
"""


def inject_theme() -> None:
    """페이지 렌더 전에 1회 호출한다 (Streamlit 은 rerun 마다 다시 주입한다)."""
    st.markdown(THEME_CSS, unsafe_allow_html=True)
