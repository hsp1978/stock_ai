#!/usr/bin/env python3
"""
주식 분석 시스템 WebUI (Streamlit)
로컬 분석 엔진 직접 호출 + 전체 리포트 대시보드

실행:
    streamlit run webui.py --server.port 8501
"""
import json
import os
from datetime import datetime

import yfinance as yf
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import load_dotenv

load_dotenv()

WATCHLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.txt")

from local_engine import (
    engine_health, engine_info, engine_get_all_results,
    engine_get_ticker_result, engine_scan_ticker, engine_scan_all,
    engine_get_history, engine_get_chart_path,
    engine_backtest, engine_ml_predict,
    engine_portfolio_optimize, engine_correlation_beta,
    engine_factor_ranking,
    engine_paper_status, engine_paper_order, engine_paper_auto, engine_paper_reset,
    engine_available_llm, engine_interpret_tool, engine_interpret_full_report,
    OLLAMA_MODEL,
)

st.set_page_config(
    page_title="Stock AI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Kinetic Terminal Design System CSS ──────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap');

    :root {
        --L0: #0b0e14;
        --L1: #1d2026;
        --L2: #32353c;
        --surface-low: #191c22;
        --surface-bright: #363940;
        --outline: #8d909e;
        --outline-variant: #424752;
        --ghost: rgba(66,71,82,0.20);
        --on-bg: #e1e2eb;
        --on-surface: #e1e2eb;
        --on-surface-variant: #c3c6d4;
        --primary: #aec6ff;
        --primary-ctr: #5d8ef1;
        --buy: #02d4a1;
        --buy-bright: #46f1bc;
        --sell: #fd526f;
        --sell-bright: #ffb2b8;
        --hold: #ffb347;
    }

    /* ── Base ── */
    .stApp {
        background: var(--L0) !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: var(--on-bg);
    }
    ::-webkit-scrollbar { width: 4px; height: 4px; }
    ::-webkit-scrollbar-track { background: var(--L0); }
    ::-webkit-scrollbar-thumb { background: var(--L2); border-radius: 10px; }
    h1, h2, h3 { font-family: 'Inter', sans-serif !important; letter-spacing: -0.02em; color: var(--on-surface) !important; }

    /* ── Sidebar — No-Line: tonal shift only ── */
    div[data-testid="stSidebar"] {
        background: var(--L0) !important;
        border-right: none !important;
    }
    div[data-testid="stSidebar"] .stMarkdown p,
    div[data-testid="stSidebar"] .stMarkdown li { font-size: 13px; color: var(--on-surface-variant); }

    /* ── Top Navigation Bar ── */
    .top-nav {
        display: flex;
        align-items: center;
        gap: 0;
        background: var(--L1);
        border-radius: 12px;
        padding: 4px;
        margin-bottom: 20px;
        position: sticky;
        top: 0;
        z-index: 999;
    }
    .top-nav-brand {
        font-size: 1rem; font-weight: 900;
        color: var(--primary-ctr); letter-spacing: -0.04em;
        padding: 8px 18px 8px 14px;
        white-space: nowrap;
        border-right: 1px solid var(--outline-variant);
        margin-right: 4px;
    }
    .top-nav-item {
        padding: 8px 16px;
        border-radius: 8px;
        font-family: 'Inter', sans-serif;
        font-size: 0.78rem;
        font-weight: 600;
        color: var(--on-surface-variant);
        cursor: pointer;
        transition: all 0.2s;
        text-decoration: none;
        white-space: nowrap;
    }
    .top-nav-item:hover {
        background: var(--surface-bright);
        color: var(--on-surface);
    }
    .top-nav-item.active {
        background: var(--primary-ctr);
        color: #0b0e14;
        font-weight: 700;
    }
    .top-nav-right {
        margin-left: auto;
        display: flex;
        align-items: center;
        gap: 8px;
        padding-right: 8px;
    }
    .top-nav-status {
        font-family: 'JetBrains Mono';
        font-size: 0.65rem;
        font-weight: 600;
        padding: 4px 10px;
        border-radius: 6px;
        background: var(--L0);
    }

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
    .ticker-expanded {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
        gap: 2px;
        background: var(--L1);
        border-radius: 12px;
        padding: 4px;
        margin-bottom: 24px;
    }
    .ticker-cell {
        padding: 12px 8px; text-align: center;
        border-radius: 10px; transition: background 0.2s;
    }
    .ticker-cell:hover { background: var(--surface-bright); }
    .ticker-cell .tc-name {
        font-family: 'Inter'; font-size: 0.625rem; font-weight: 700;
        color: var(--on-surface-variant); text-transform: uppercase;
        letter-spacing: 0.5px; margin-bottom: 4px;
    }
    .ticker-cell .tc-price {
        font-family: 'JetBrains Mono'; font-size: 0.9rem; font-weight: 700;
        color: var(--on-surface); letter-spacing: -0.03em;
    }
    .ticker-cell .tc-change {
        font-family: 'JetBrains Mono'; font-size: 0.7rem; font-weight: 600; margin-top: 2px;
    }
    .ts-up { color: var(--buy); }
    .ts-down { color: var(--sell); }
    .ts-flat { color: var(--outline); }

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
        font-family: 'Inter'; font-size: 0.625rem; font-weight: 700;
        color: var(--on-surface-variant); text-transform: uppercase;
        letter-spacing: 1.2px; margin-bottom: 12px;
    }
    .summary-card .sc-value {
        font-family: 'JetBrains Mono'; font-size: 2.5rem; font-weight: 700;
        line-height: 1;
    }
    .summary-card .sc-sub {
        font-family: 'Inter'; font-size: 0.7rem;
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
        font-family: 'Inter'; font-size: 1.1rem; font-weight: 700;
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
        font-family: 'Inter' !important;
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
        font-family: 'Inter'; font-size: 0.625rem; font-weight: 700;
        color: var(--on-surface-variant); text-transform: uppercase;
        letter-spacing: 1px; margin-bottom: 8px;
    }
    .sidebar-status-grid { display: flex; gap: 6px; margin: 12px 0; }
    .sidebar-status-item {
        flex: 1; background: var(--L1); border-radius: 10px;
        padding: 10px 6px; text-align: center;
    }
    .sidebar-status-item .ssi-label {
        font-family: 'Inter'; font-size: 0.55rem; font-weight: 700;
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
    .wl-chip {
        display: inline-block; background: var(--L2); border-radius: 6px;
        padding: 3px 10px; margin: 2px;
        font-family: 'JetBrains Mono'; font-size: 0.7rem; font-weight: 500;
        color: var(--on-surface-variant);
    }

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
""", unsafe_allow_html=True)


MARKET_INDICES = {
    "us_market": {
        "title": "US",
        "items": [
            ("^GSPC", "S&P 500", 2),
            ("^IXIC", "NASDAQ", 2),
            ("^DJI", "DOW", 2),
        ],
    },
    "kr_market": {
        "title": "KR",
        "items": [
            ("^KS11", "KOSPI", 2),
            ("^KQ11", "KOSDAQ", 2),
            ("USDKRW=X", "USD/KRW", 2),
        ],
    },
    "commodities": {
        "title": "CMDTY",
        "items": [
            ("GC=F", "Gold", 2),
            ("SI=F", "Silver", 2),
            ("HG=F", "Copper", 3),
            ("NG=F", "Nat Gas", 2),
        ],
    },
}


@st.cache_data(ttl=300)
def fetch_market_indices() -> tuple[dict, str]:
    results = {}
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_tickers = []
    for group in MARKET_INDICES.values():
        for sym, name, decimals in group["items"]:
            all_tickers.append(sym)

    try:
        data = yf.download(
            all_tickers, period="5d", auto_adjust=True,
            progress=False, threads=True,
        )
    except Exception:
        return results, fetched_at

    for group_key, group in MARKET_INDICES.items():
        for sym, name, decimals in group["items"]:
            try:
                close_series = data['Close'] if len(all_tickers) == 1 else data['Close'][sym]
                close_series = close_series.dropna()
                if len(close_series) < 2:
                    continue
                price = float(close_series.iloc[-1])
                prev = float(close_series.iloc[-2])
                change = price - prev
                change_pct = (change / prev) * 100
                results[sym] = {
                    "name": name, "price": price, "change": change,
                    "change_pct": change_pct, "decimals": decimals,
                }
            except Exception:
                continue
    return results, fetched_at


KR_NAME_TO_TICKER = {
    "애플": "AAPL", "아이폰": "AAPL",
    "마이크로소프트": "MSFT", "엠에스": "MSFT",
    "구글": "GOOGL", "알파벳": "GOOGL",
    "아마존": "AMZN",
    "메타": "META", "페이스북": "META",
    "엔비디아": "NVDA",
    "테슬라": "TSLA",
    "넷플릭스": "NFLX",
    "디즈니": "DIS",
    "나이키": "NKE",
    "코카콜라": "KO",
    "펩시": "PEP", "펩시코": "PEP",
    "맥도날드": "MCD",
    "스타벅스": "SBUX",
    "비자": "V",
    "마스터카드": "MA",
    "존슨앤존슨": "JNJ",
    "프록터앤갬블": "PG",
    "월마트": "WMT",
    "코스트코": "COST",
    "보잉": "BA",
    "인텔": "INTC",
    "AMD": "AMD", "에이엠디": "AMD",
    "브로드컴": "AVGO",
    "퀄컴": "QCOM",
    "텍사스인스트루먼트": "TXN",
    "어도비": "ADBE",
    "세일즈포스": "CRM",
    "오라클": "ORCL",
    "시스코": "CSCO",
    "아이비엠": "IBM", "IBM": "IBM",
    "팔란티어": "PLTR",
    "스노우플레이크": "SNOW",
    "크라우드스트라이크": "CRWD",
    "우버": "UBER",
    "에어비앤비": "ABNB",
    "스포티파이": "SPOT",
    "쇼피파이": "SHOP",
    "줌": "ZM", "줌비디오": "ZM",
    "페이팔": "PYPL",
    "블록": "SQ", "스퀘어": "SQ",
    "로빈후드": "HOOD",
    "코인베이스": "COIN",
    "리비안": "RIVN",
    "루시드": "LCID",
    "소파이": "SOFI",
    "램리서치": "LRCX",
    "어플라이드머티어리얼즈": "AMAT", "어플라이드": "AMAT",
    "ASML": "ASML", "에이에스엠엘": "ASML",
    "마이크론": "MU",
    "슈퍼마이크로": "SMCI",
    "아리스타네트웍스": "ANET",
    "서비스나우": "NOW",
    "워크데이": "WDAY",
    "몽고디비": "MDB",
    "데이터독": "DDOG",
    "유니티": "U",
    "로블록스": "RBLX",
    "일라이릴리": "LLY",
    "화이자": "PFE",
    "머크": "MRK",
    "애브비": "ABBV",
    "암젠": "AMGN",
    "모더나": "MRNA",
    "유나이티드헬스": "UNH",
    "버크셔해서웨이": "BRK-B", "버크셔": "BRK-B",
    "제이피모건": "JPM", "JP모건": "JPM",
    "골드만삭스": "GS",
    "모건스탠리": "MS",
    "뱅크오브아메리카": "BAC",
    "웰스파고": "WFC",
    "찰스슈왑": "SCHW",
    "블랙록": "BLK",
    "아메리칸익스프레스": "AXP", "아멕스": "AXP",
    "시티그룹": "C", "시티": "C",
    "엑슨모빌": "XOM",
    "셰브론": "CVX",
    "록히드마틴": "LMT",
    "레이시온": "RTX",
    "캐터필러": "CAT",
    "3M": "MMM", "쓰리엠": "MMM",
    "허니웰": "HON",
    "제너럴일렉트릭": "GE", "GE": "GE",
    "포드": "F",
    "제너럴모터스": "GM", "GM": "GM",
    "홈디포": "HD",
    "로우스": "LOW",
    "타겟": "TGT",
    "달러제너럴": "DG",
    "크로거": "KR",
    "AT&T": "T", "에이티앤티": "T",
    "버라이즌": "VZ",
    "티모바일": "TMUS",
    "컴캐스트": "CMCSA",
    "넥스트에라에너지": "NEE",
    "서던컴퍼니": "SO",
    "듀크에너지": "DUK",
    "리얼티인컴": "O",
    "아메리칸타워": "AMT",
    "프롤로지스": "PLD",
    "ARM": "ARM", "에이알엠": "ARM", "암": "ARM",
    "팔로알토": "PANW", "팔로알토네트웍스": "PANW",
    "지스케일러": "ZS",
    "포티넷": "FTNT",
    "델": "DELL", "델테크놀로지": "DELL",
    "HP": "HPQ", "에이치피": "HPQ",
    "트위터": "X",
    "핀터레스트": "PINS",
    "스냅": "SNAP", "스냅챗": "SNAP",
    "레딧": "RDDT",
    "앱러빈": "APP",
    "덱스컴": "DXCM",
    "인튜이티브서지컬": "ISRG",
    "일루미나": "ILMN",
    "도미노피자": "DPZ",
    "치폴레": "CMG",
    "힐튼": "HLT",
    "마리어트": "MAR",
}

_KR_LOOKUP = {k.lower(): v for k, v in KR_NAME_TO_TICKER.items()}


def resolve_ticker(user_input: str) -> tuple[str, str]:
    text = user_input.strip()
    if not text:
        return "", ""

    upper = text.upper()
    if upper.isascii() and len(upper) <= 10:
        return upper, ""

    query = text.lower()

    exact = _KR_LOOKUP.get(query)
    if exact:
        return exact, f"{text} → {exact}"

    best_match = None
    best_len = 0
    for name, ticker in _KR_LOOKUP.items():
        if name == query or query == name:
            return ticker, f"{text} → {ticker}"
        if query.startswith(name) or name.startswith(query):
            if len(name) > best_len:
                best_match = (ticker, name)
                best_len = len(name)

    try:
        import yfinance as _yf
        results = _yf.Search(text, max_results=3)
        quotes = results.quotes if hasattr(results, 'quotes') else []
        if quotes:
            best = quotes[0]
            sym = best.get("symbol", "")
            sname = best.get("shortname", best.get("longname", ""))
            if sym:
                return sym, f"{text} → {sym} ({sname})"
    except Exception:
        pass

    if best_match:
        return best_match[0], f"{text} → {best_match[0]} ({best_match[1]})"

    return text, ""




def load_watchlist() -> list[str]:
    if not os.path.exists(WATCHLIST_PATH):
        return []
    result = []
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if raw.isascii():
                result.append(raw.upper())
            else:
                ticker, _ = resolve_ticker(raw)
                result.append(ticker if ticker else raw)
    return result


def save_watchlist(tickers: list[str]):
    header = "# 관심 종목 리스트 (한 줄에 하나, #은 주석)\n# 빈 줄과 주석은 무시됨\n\n"
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        f.write(header)
        for t in tickers:
            f.write(f"{t}\n")


def add_to_watchlist(ticker: str) -> tuple[bool, str]:
    ticker = ticker.strip().upper()
    if not ticker:
        return False, "Empty ticker"
    if not ticker.isalpha() and not all(c.isalnum() or c in ".-^=" for c in ticker):
        return False, f"Invalid ticker: {ticker}"
    current = load_watchlist()
    if ticker in current:
        return False, f"{ticker} already in watchlist"
    current.append(ticker)
    save_watchlist(current)
    return True, f"{ticker} added"


def remove_from_watchlist(ticker: str) -> tuple[bool, str]:
    ticker = ticker.strip().upper()
    current = load_watchlist()
    if ticker not in current:
        return False, f"{ticker} not found"
    current.remove(ticker)
    save_watchlist(current)
    return True, f"{ticker} removed"


def _plotly_base_layout(**overrides) -> dict:
    base = dict(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0b0e14",
        font=dict(family="Inter, sans-serif", color="#c3c6d4", size=12),
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(gridcolor="rgba(66,71,82,0.12)", zerolinecolor="rgba(66,71,82,0.18)"),
        yaxis=dict(gridcolor="rgba(66,71,82,0.12)", zerolinecolor="rgba(66,71,82,0.18)"),
    )
    base.update(overrides)
    return base


def _signal_pill_html(signal: str) -> str:
    s = signal.upper()
    cls = "buy" if s == "BUY" else ("sell" if s == "SELL" else "hold")
    return f'<span class="signal-pill {cls}"><span class="sp-dot"></span>{s}</span>'


# ═══════════════════════════════════════════════════════════════
#  사이드바 (유틸리티)
# ═══════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown('<div class="sidebar-brand">Stock AI</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">Precision Terminal</div>', unsafe_allow_html=True)

    health = engine_health()
    if health:
        ollama_status = health.get("ollama", "disconnected")
        cached = health.get("cached_results", 0)
        scans = health.get("scan_count", 0)
        status_color = "#02d4a1" if ollama_status == "connected" else "#fd526f"
        st.markdown(f"""
        <div class="sidebar-status-grid">
            <div class="sidebar-status-item">
                <div class="ssi-label">Ollama</div>
                <div class="ssi-value" style="color:{status_color};">{'Online' if ollama_status == 'connected' else 'Offline'}</div>
            </div>
            <div class="sidebar-status-item">
                <div class="ssi-label">Cached</div>
                <div class="ssi-value">{cached}</div>
            </div>
            <div class="sidebar-status-item">
                <div class="ssi-label">Scans</div>
                <div class="ssi-value">{scans}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.error("Engine not available")

    info = engine_info()
    if info:
        last_scan = info.get("last_scan", "")
        thresholds = info.get("thresholds", {})
        buy_th = thresholds.get("buy", "?")
        sell_th = thresholds.get("sell", "?")
        model_name = info.get("model", "?")
        scan_interval = info.get("scan_interval", "?")
        last_line = f'<br>Last: <span>{last_scan[:16]}</span>' if last_scan else ""
        st.markdown(f"""
        <div class="sidebar-info">
            Model: <span>{model_name}</span><br>
            Interval: <span>{scan_interval}</span><br>
            Buy &ge; <span style="color:#02d4a1;">{buy_th}</span>
            &nbsp; Sell &le; <span style="color:#fd526f;">{sell_th}</span>
            {last_line}
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    st.markdown('<div class="sidebar-section-label">Manual Scan</div>', unsafe_allow_html=True)
    scan_ticker = st.text_input("Ticker", placeholder="AAPL or 애플", label_visibility="collapsed")
    if st.button("Scan", use_container_width=True):
        if scan_ticker:
            resolved, hint = resolve_ticker(scan_ticker)
            if hint:
                st.info(hint)
            if resolved:
                with st.spinner(f"Analyzing {resolved}..."):
                    result = engine_scan_ticker(resolved)
                    if result:
                        st.success(f"{resolved}: {result.get('final_signal')} ({result.get('composite_score', 0):+.1f})")
                        st.rerun()

    st.divider()

    st.markdown('<div class="sidebar-section-label">Watchlist</div>', unsafe_allow_html=True)
    watchlist = load_watchlist()

    if watchlist:
        wl_chips = " ".join(f'<span class="wl-chip">{t}</span>' for t in watchlist)
        st.markdown(f'<div style="margin-bottom:8px; line-height:2;">{wl_chips}</div>', unsafe_allow_html=True)
        st.caption(f"{len(watchlist)} tickers")
    else:
        st.caption("No tickers in watchlist")

    add_ticker = st.text_input("Add ticker", placeholder="TSLA or 테슬라", label_visibility="collapsed", key="wl_add")
    wl_col1, wl_col2 = st.columns(2)
    if wl_col1.button("Add", use_container_width=True, key="wl_add_btn"):
        if add_ticker:
            resolved, hint = resolve_ticker(add_ticker)
            if hint:
                st.info(hint)
            if resolved:
                ok, msg = add_to_watchlist(resolved)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.warning(msg)

    if watchlist:
        remove_target = wl_col2.selectbox("Remove", watchlist, label_visibility="collapsed", key="wl_remove")
        if wl_col2.button("Remove", use_container_width=True, key="wl_rm_btn"):
            ok, msg = remove_from_watchlist(remove_target)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.warning(msg)

    if st.button("Scan All", use_container_width=True, key="scan_all_btn"):
        wl = load_watchlist()
        if wl:
            with st.spinner(f"Scanning {len(wl)} tickers..."):
                result = engine_scan_all(wl)
                if result:
                    st.success(f"Done! {len(wl)} tickers scanned.")
            st.rerun()
        else:
            st.warning("Watchlist is empty")



# ═══════════════════════════════════════════════════════════════
#  상단 가로 네비게이션 바
# ═══════════════════════════════════════════════════════════════

NAV_ITEMS = ["Home", "Dashboard", "Report", "Detail", "Backtest", "ML Predict", "Portfolio", "Ranking", "Paper Trade", "History"]

if "page" not in st.session_state:
    st.session_state["page"] = "Home"

nav_cols = st.columns([1.2] + [1] * len(NAV_ITEMS))

with nav_cols[0]:
    st.markdown('<div style="font-size:1rem;font-weight:900;color:var(--primary-ctr);padding:6px 0;letter-spacing:-0.04em;">Stock AI</div>', unsafe_allow_html=True)

for i, nav_name in enumerate(NAV_ITEMS):
    with nav_cols[i + 1]:
        is_active = st.session_state["page"] == nav_name
        btn_type = "primary" if is_active else "secondary"
        if st.button(nav_name, key=f"nav_{nav_name}", use_container_width=True, type=btn_type):
            st.session_state["page"] = nav_name
            st.rerun()

st.markdown('<div style="height:1px;background:var(--outline-variant);opacity:0.15;margin-bottom:16px;"></div>', unsafe_allow_html=True)

page = st.session_state["page"]


# ═══════════════════════════════════════════════════════════════
#  홈 페이지
# ═══════════════════════════════════════════════════════════════

def render_home():
    render_market_ticker_bar()

    data = engine_get_all_results()
    results = data.get("results", {}) if data else {}
    total = len(results)
    buy_count = sum(1 for r in results.values() if r.get("signal") == "BUY")
    sell_count = sum(1 for r in results.values() if r.get("signal") == "SELL")
    hold_count = sum(1 for r in results.values() if r.get("signal") == "HOLD")

    st.markdown("""
    <div class="page-header">
        <div class="page-title">Stock AI</div>
        <div class="page-subtitle">AI-Powered Multi-Tool Stock Analysis Terminal</div>
    </div>
    """, unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total", str(total))
    m2.metric("Buy", str(buy_count))
    m3.metric("Sell", str(sell_count))
    m4.metric("Hold", str(hold_count))

    health = engine_health()
    info = engine_info()
    watchlist = load_watchlist()

    st.markdown("""
    <div class="section-header">
        <div class="section-title">System Status</div>
    </div>
    """, unsafe_allow_html=True)

    s1, s2, s3, s4 = st.columns(4)
    if health:
        ollama_status = health.get("ollama", "disconnected")
        s1.metric("Agent", "Online" if ollama_status == "connected" else "Offline")
        s2.metric("Cached Results", str(health.get("cached_results", 0)))
        s3.metric("Total Scans", str(health.get("scan_count", 0)))
    else:
        s1.metric("Agent", "Offline")
        s2.metric("Cached Results", "—")
        s3.metric("Total Scans", "—")

    if info:
        s4.metric("Model", info.get("model", "—"))
    else:
        s4.metric("Model", "—")

    st.markdown("""
    <div class="section-header">
        <div class="section-title">Watchlist</div>
    </div>
    """, unsafe_allow_html=True)

    if watchlist:
        wl_chips = " ".join(f'<span class="wl-chip">{t}</span>' for t in watchlist)
        st.markdown(f'<div style="line-height:2.2;">{wl_chips}</div>', unsafe_allow_html=True)
    else:
        st.caption("No tickers in watchlist. Add tickers from the sidebar.")

    if results:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">Latest Signals</div>
        </div>
        """, unsafe_allow_html=True)

        rows = []
        for ticker, r in sorted(results.items(), key=lambda x: abs(x[1].get("score", 0)), reverse=True):
            rows.append({
                "Ticker": ticker,
                "Signal": r.get("signal", "?"),
                "Score": r.get("score", 0),
                "Confidence": r.get("confidence", 0),
                "Time": str(r.get("analyzed_at", ""))[:16],
            })
        df = pd.DataFrame(rows)
        st.dataframe(
            df.style.map(
                lambda v: "color: #02d4a1" if v == "BUY" else ("color: #fd526f" if v == "SELL" else "color: #ffb347"),
                subset=["Signal"],
            ),
            use_container_width=True, hide_index=True,
        )


# ═══════════════════════════════════════════════════════════════
#  대시보드 페이지
# ═══════════════════════════════════════════════════════════════

def render_market_ticker_bar():
    indices, market_updated_at = fetch_market_indices()
    if not indices:
        return

    st.markdown(f'<div class="ts-meta">Updated {market_updated_at}</div>', unsafe_allow_html=True)

    cells = []
    for group_key, group in MARKET_INDICES.items():
        for sym, name, decimals in group["items"]:
            info = indices.get(sym)
            if info:
                pct = info["change_pct"]
                css = "ts-up" if pct > 0 else ("ts-down" if pct < 0 else "ts-flat")
                arrow = "+" if pct > 0 else ""
                cells.append(f"""
                <div class="ticker-cell">
                    <div class="tc-name">{info['name']}</div>
                    <div class="tc-price">{info['price']:,.{info['decimals']}f}</div>
                    <div class="tc-change {css}">{arrow}{pct:.2f}%</div>
                </div>""")
            else:
                cells.append(f"""
                <div class="ticker-cell">
                    <div class="tc-name">{name}</div>
                    <div class="tc-price" style="color:var(--outline);">--</div>
                    <div class="tc-change ts-flat">N/A</div>
                </div>""")

    st.markdown(f'<div class="ticker-expanded">{"".join(cells)}</div>', unsafe_allow_html=True)


def render_dashboard():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Dashboard</div>
        <div class="page-subtitle">Market Analysis & Signal Overview</div>
    </div>
    """, unsafe_allow_html=True)

    render_market_ticker_bar()

    data = engine_get_all_results()
    if not data or not data.get("results"):
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">⚡</div>
            <div class="es-text">No analysis results yet. Run a scan from the sidebar.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    _wl = set(load_watchlist())
    results = {k: v for k, v in data["results"].items() if k in _wl} if _wl else data["results"]
    if not results:
        st.info("No results for current watchlist. Run a scan first.")
        return
    total = len(results)
    buy_list = {k: v for k, v in results.items() if v.get("signal") == "BUY"}
    sell_list = {k: v for k, v in results.items() if v.get("signal") == "SELL"}
    hold_list = {k: v for k, v in results.items() if v.get("signal") == "HOLD"}

    analyzed_times = [r.get("analyzed_at", "") for r in results.values() if r.get("analyzed_at")]
    if analyzed_times:
        latest_analysis = max(analyzed_times)[:19].replace("T", " ")
        oldest_analysis = min(analyzed_times)[:19].replace("T", " ")
        analysis_ts = f"Last analyzed: {latest_analysis}" if latest_analysis == oldest_analysis else f"Analyzed: {oldest_analysis} ~ {latest_analysis}"
    else:
        analysis_ts = ""

    buy_pct = int(len(buy_list) / total * 100) if total else 0
    sell_pct = int(len(sell_list) / total * 100) if total else 0
    hold_pct = int(len(hold_list) / total * 100) if total else 0

    st.markdown(f"""
    <div class="summary-grid">
        <div class="summary-card">
            <div class="sc-label">Total Coverage</div>
            <div class="sc-value" style="color:var(--primary-ctr);">{total}</div>
            <div class="sc-sub">Instruments</div>
            <div class="sc-bar"><div class="sc-bar-fill" style="width:100%; background:var(--primary-ctr);"></div></div>
        </div>
        <div class="summary-card">
            <div class="sc-label">Buy Signals</div>
            <div class="sc-value" style="color:var(--buy);">{len(buy_list)}</div>
            <div class="sc-sub">Optimal Entry</div>
            <div class="sc-bar"><div class="sc-bar-fill" style="width:{buy_pct}%; background:var(--buy);"></div></div>
        </div>
        <div class="summary-card">
            <div class="sc-label">Sell Signals</div>
            <div class="sc-value" style="color:var(--sell);">{len(sell_list)}</div>
            <div class="sc-sub">Risk Detected</div>
            <div class="sc-bar"><div class="sc-bar-fill" style="width:{sell_pct}%; background:var(--sell);"></div></div>
        </div>
        <div class="summary-card">
            <div class="sc-label">Hold Signals</div>
            <div class="sc-value" style="color:var(--hold);">{len(hold_list)}</div>
            <div class="sc-sub">Neutral Weight</div>
            <div class="sc-bar"><div class="sc-bar-fill" style="width:{hold_pct}%; background:var(--hold);"></div></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if analysis_ts:
        st.markdown(f'<div class="ts-meta">{analysis_ts}</div>', unsafe_allow_html=True)

    rows = []
    for ticker, r in sorted(results.items(), key=lambda x: x[1].get("score", 0), reverse=True):
        dist = r.get("signal_distribution", {})
        rows.append({
            "ticker": ticker,
            "signal": r.get("signal", "?"),
            "score": r.get("score", 0),
            "confidence": r.get("confidence", 0),
            "buy": dist.get("buy", 0),
            "sell": dist.get("sell", 0),
            "neutral": dist.get("neutral", 0),
            "time": str(r.get("analyzed_at", ""))[:16],
        })

    if not rows:
        return

    df = pd.DataFrame(rows)

    col_score, col_table = st.columns([2, 3])

    with col_score:
        st.markdown('<div class="section-title">Signal Score Matrix</div>', unsafe_allow_html=True)

        fig = go.Figure()
        bar_colors = ["#02d4a1" if s > 0 else "#fd526f" if s < 0 else "#32353c" for s in df["score"]]
        fig.add_trace(go.Bar(
            x=df["score"], y=df["ticker"], orientation='h',
            marker=dict(color=bar_colors, line=dict(width=0)),
            text=[f"{s:+.1f}" for s in df["score"]],
            textposition="outside",
            textfont=dict(color="#8d909e", size=11, family="JetBrains Mono"),
        ))
        fig.update_layout(**_plotly_base_layout(
            height=max(280, len(df) * 52),
            xaxis=dict(range=[-10, 10], title="", gridcolor="rgba(66,71,82,0.15)", zerolinecolor="rgba(66,71,82,0.25)"),
            yaxis=dict(
                autorange="reversed", gridcolor="rgba(0,0,0,0)",
                tickfont=dict(family="JetBrains Mono", size=12, color="#e1e2eb"),
            ),
            margin=dict(l=70, r=60, t=8, b=8),
        ))
        fig.add_vline(x=0, line_color="rgba(66,71,82,0.3)", line_width=1)
        st.plotly_chart(fig, use_container_width=True)

    with col_table:
        st.markdown('<div class="section-title">Analysis Execution Results</div>', unsafe_allow_html=True)

        display_df = df[["ticker", "signal", "score", "confidence"]].rename(columns={
            "ticker": "Ticker", "signal": "Signal", "score": "Score", "confidence": "Confidence",
        })
        st.dataframe(
            display_df.style.map(
                lambda v: "color: #02d4a1" if v == "BUY" else ("color: #fd526f" if v == "SELL" else "color: #ffb347"),
                subset=["Signal"],
            ),
            use_container_width=True, hide_index=True,
            height=max(280, len(df) * 52),
        )


# ═══════════════════════════════════════════════════════════════
#  종목 상세 페이지
# ═══════════════════════════════════════════════════════════════

def _fmt_num(v, decimals=2):
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    return f"{v:,.{decimals}f}"


def _render_tool_detail_card(td: dict):
    tool_name = td.get("tool", "")
    name = td.get("name", tool_name)
    sig = td.get("signal", "neutral")
    sc = td.get("score", 0)
    detail_text = td.get("detail", "")
    sig_color = "#02d4a1" if sig == "buy" else ("#fd526f" if sig == "sell" else "#ffb347")

    st.markdown(f"**{name}**")
    st.markdown(
        f'<span style="color:{sig_color}; font-weight:700; font-size:13px;">'
        f'{sig.upper()} ({sc:+.1f})</span>',
        unsafe_allow_html=True,
    )

    if tool_name == "trend_ma_analysis":
        sma = td.get("sma_values", {})
        pvs = td.get("price_vs_sma", {})
        cols = st.columns(len(sma)) if sma else []
        for col, (period, val) in zip(cols, sma.items()):
            pos = pvs.get(f"SMA_{period}", "—")
            col.metric(f"SMA {period}", f"${_fmt_num(val)}", pos)
        alignment = td.get("alignment", "—")
        cross = td.get("cross_signal", "none")
        c1, c2 = st.columns(2)
        c1.metric("Alignment", alignment.title())
        c2.metric("Cross Signal", cross.title() if cross != "none" else "—")

    elif tool_name == "rsi_divergence_analysis":
        c1, c2, c3 = st.columns(3)
        c1.metric("RSI", _fmt_num(td.get("current_rsi"), 1))
        c2.metric("Zone", str(td.get("rsi_zone", "—")).title())
        c3.metric("Divergence", str(td.get("divergence", "none")).title())

    elif tool_name == "bollinger_squeeze_analysis":
        c1, c2, c3 = st.columns(3)
        c1.metric("BB Upper", f"${_fmt_num(td.get('bb_upper'))}")
        c2.metric("BB Lower", f"${_fmt_num(td.get('bb_lower'))}")
        c3.metric("%B", _fmt_num(td.get("pct_b")))
        c4, c5, c6 = st.columns(3)
        c4.metric("Width %", _fmt_num(td.get("bb_width_pct"), 1))
        c5.metric("Squeeze", "Yes" if td.get("squeeze") else "No")
        c6.metric("Expanding", "Yes" if td.get("expanding") else "No")

    elif tool_name == "macd_momentum_analysis":
        c1, c2, c3 = st.columns(3)
        c1.metric("MACD", _fmt_num(td.get("macd"), 4))
        c2.metric("Signal Line", _fmt_num(td.get("signal_line"), 4))
        c3.metric("Histogram", _fmt_num(td.get("histogram"), 4))
        c4, c5, c6 = st.columns(3)
        c4.metric("Cross", str(td.get("cross", "none")).title())
        c5.metric("Acceleration", str(td.get("histogram_acceleration", "—")).title())
        c6.metric("Zero Position", str(td.get("zero_position", "—")).title())

    elif tool_name == "adx_trend_strength_analysis":
        c1, c2 = st.columns(2)
        c1.metric("ADX", _fmt_num(td.get("adx"), 1))
        c2.metric("Trend Strength", str(td.get("trend_strength", "—")).title())
        c3, c4, c5 = st.columns(3)
        c3.metric("+DI", _fmt_num(td.get("plus_di"), 1))
        c4.metric("-DI", _fmt_num(td.get("minus_di"), 1))
        c5.metric("Direction", str(td.get("trend_direction", "—")).title())

    elif tool_name == "volume_profile_analysis":
        c1, c2 = st.columns(2)
        c1.metric("Volume Ratio", f"{_fmt_num(td.get('volume_ratio'), 2)}x")
        c2.metric("OBV Trend", str(td.get("obv_trend", "—")).title())

    elif tool_name == "fibonacci_retracement_analysis":
        levels = td.get("levels", {})
        if levels:
            level_data = {f"Fib {k}": f"${_fmt_num(v)}" for k, v in levels.items()}
            cols = st.columns(min(len(level_data), 4))
            for col, (label, val) in zip(cols, list(level_data.items())[:4]):
                col.metric(label, val)
        c1, c2, c3 = st.columns(3)
        c1.metric("Retracement", _fmt_num(td.get("current_retracement"), 1))
        c2.metric("Nearest Support", f"${_fmt_num(td.get('nearest_support'))}")
        c3.metric("Nearest Resistance", f"${_fmt_num(td.get('nearest_resistance'))}")

    elif tool_name == "volatility_regime_analysis":
        c1, c2, c3 = st.columns(3)
        c1.metric("ATR", f"${_fmt_num(td.get('current_atr'))}")
        c2.metric("ATR %", f"{_fmt_num(td.get('atr_pct'), 1)}%")
        c3.metric("Regime", str(td.get("regime", "—")).title())
        c4, c5 = st.columns(2)
        c4.metric("Percentile", f"{_fmt_num(td.get('percentile'), 0)}%")
        c5.metric("Annualized Vol", f"{_fmt_num(td.get('annualized_volatility'), 1)}%")

    elif tool_name == "mean_reversion_analysis":
        zscores = td.get("z_scores", {})
        if zscores:
            cols = st.columns(min(len(zscores), 4))
            for col, (period, val) in zip(cols, list(zscores.items())[:4]):
                col.metric(f"Z-Score {period}", _fmt_num(val))
        c1, c2 = st.columns(2)
        c1.metric("Avg Z-Score", _fmt_num(td.get("avg_z_score")))
        c2.metric("Reversion Prob", f"{_fmt_num(td.get('reversion_probability'), 0)}%")

    elif tool_name == "momentum_rank_analysis":
        returns = td.get("returns", {})
        if returns:
            cols = st.columns(min(len(returns), 4))
            for col, (period, val) in zip(cols, list(returns.items())[:4]):
                color = "normal" if val is None else ("off" if val < 0 else "normal")
                col.metric(f"Return {period}", f"{_fmt_num(val, 1)}%" if val is not None else "—")
        c1, c2 = st.columns(2)
        c1.metric("Weighted Return", f"{_fmt_num(td.get('weighted_return'), 2)}%")
        c2.metric("Acceleration", str(td.get("acceleration", "—")).title())

    elif tool_name == "support_resistance_analysis":
        c1, c2, c3 = st.columns(3)
        c1.metric("Pivot", f"${_fmt_num(td.get('pivot'))}")
        c2.metric("Upside %", f"{_fmt_num(td.get('upside_pct'), 1)}%")
        c3.metric("Downside %", f"{_fmt_num(td.get('downside_pct'), 1)}%")
        resistance = td.get("resistance", {})
        support = td.get("support", {})
        if resistance:
            cols = st.columns(len(resistance))
            for col, (level, val) in zip(cols, resistance.items()):
                col.metric(f"R{level}", f"${_fmt_num(val)}")
        if support:
            cols = st.columns(len(support))
            for col, (level, val) in zip(cols, support.items()):
                col.metric(f"S{level}", f"${_fmt_num(val)}")
        rr = td.get("risk_reward_ratio")
        if rr is not None:
            st.metric("Risk/Reward Ratio", _fmt_num(rr))

    elif tool_name == "correlation_regime_analysis":
        ac = td.get("autocorrelations", {})
        if ac:
            cols = st.columns(min(len(ac), 5))
            for col, (lag, val) in zip(cols, list(ac.items())[:5]):
                col.metric(f"Lag {lag}", _fmt_num(val, 3))
        c1, c2, c3 = st.columns(3)
        c1.metric("Avg Autocorrelation", _fmt_num(td.get("avg_autocorrelation"), 3))
        c2.metric("Hurst Exponent", _fmt_num(td.get("hurst_exponent"), 3))
        c3.metric("Regime", str(td.get("regime", "—")).title())

    if detail_text:
        st.caption(detail_text)


def render_detail():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Detail Analysis</div>
        <div class="page-subtitle">In-depth 16-tool analysis for individual stocks</div>
    </div>
    """, unsafe_allow_html=True)

    data = engine_get_all_results()
    if not data or not data.get("results"):
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">🔍</div>
            <div class="es-text">No analysis results available.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    wl = set(load_watchlist())
    tickers = sorted(t for t in data["results"].keys() if t in wl) if wl else sorted(data["results"].keys())
    selected = st.selectbox("Select Ticker", tickers, label_visibility="collapsed")
    if not selected:
        return

    detail = engine_get_ticker_result(selected)
    if not detail:
        summary = data["results"].get(selected, {})
        if not summary:
            st.error(f"Failed to load {selected}")
            return
        detail = {
            "final_signal": summary.get("signal", "?"),
            "composite_score": summary.get("score", 0),
            "confidence": summary.get("confidence", 0),
            "signal_distribution": summary.get("signal_distribution", {}),
            "analyzed_at": summary.get("analyzed_at", ""),
        }
        st.warning("Detail endpoint unavailable — showing summary data only.")

    signal = detail.get("final_signal", "?")
    score = detail.get("composite_score", 0)
    confidence = detail.get("confidence", 0)
    tool_count = detail.get("tool_count", 0)
    dist = detail.get("signal_distribution", {})
    analyzed_at = str(detail.get("analyzed_at", ""))[:19].replace("T", " ")

    badge_class = "buy" if signal == "BUY" else ("sell" if signal == "SELL" else "hold")
    score_color = "var(--buy)" if score > 0 else "var(--sell)" if score < 0 else "var(--outline)"

    st.markdown(f"""
    <div style="margin-bottom:24px;">
        <div style="font-size:10px; color:var(--on-surface-variant); text-transform:uppercase; letter-spacing:1px; margin-bottom:8px;">Signal</div>
        <span class="signal-badge-lg {badge_class}">{signal}</span>
    </div>
    """, unsafe_allow_html=True)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Composite Score", f"{score:+.2f}")
    m2.metric("Confidence", f"{confidence}/10")
    m3.metric("Tools", str(tool_count))
    m4.metric("Buy Votes", str(dist.get("buy", 0)))
    m5.metric("Sell Votes", str(dist.get("sell", 0)))
    m6.metric("Neutral Votes", str(dist.get("neutral", 0)))

    if analyzed_at:
        st.markdown(f'<div class="ts-meta">Analyzed: {analyzed_at}</div>', unsafe_allow_html=True)

    summaries = detail.get("tool_summaries", [])
    if summaries:
        st.markdown(f"""
        <div class="section-header">
            <div class="section-title">Tool Score Overview</div>
            <div class="section-subtitle">{len(summaries)} TOOLS</div>
        </div>
        """, unsafe_allow_html=True)

        names = [s["name"] for s in summaries]
        scores = [s["score"] for s in summaries]
        bar_colors = ["#02d4a1" if s > 0 else "#fd526f" if s < 0 else "#32353c" for s in scores]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=names, x=scores, orientation='h',
            marker=dict(color=bar_colors, line=dict(width=0)),
            text=[f"{s:+.1f}" for s in scores],
            textposition="outside",
            textfont=dict(color="#8d909e", size=11, family="JetBrains Mono"),
        ))
        fig.update_layout(**_plotly_base_layout(
            height=max(400, len(summaries) * 38),
            xaxis=dict(range=[-10, 10], title="", gridcolor="rgba(66,71,82,0.15)", zerolinecolor="rgba(66,71,82,0.25)"),
            yaxis=dict(
                autorange="reversed", gridcolor="rgba(0,0,0,0)",
                tickfont=dict(family="Inter, sans-serif", size=11, color="#c3c6d4"),
            ),
            margin=dict(l=200, r=60, t=8, b=8),
        ))
        fig.add_vline(x=0, line_color="rgba(66,71,82,0.3)", line_width=1)
        st.plotly_chart(fig, use_container_width=True)

    tool_details = detail.get("tool_details", [])
    if tool_details:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">Detailed Tool Analysis</div>
        </div>
        """, unsafe_allow_html=True)

        for td in tool_details:
            with st.expander(f"**{td.get('name', td.get('tool', '?'))}** — {td.get('signal', '?').upper()} ({td.get('score', 0):+.1f})", expanded=False):
                _render_tool_detail_card(td)

    st.markdown("""
    <div class="section-header">
        <div class="section-title">Chart</div>
    </div>
    """, unsafe_allow_html=True)
    chart_path = engine_get_chart_path(selected)
    if chart_path and os.path.exists(chart_path):
        st.image(chart_path, use_container_width=True)
    else:
        st.caption("No chart image available")

    llm = detail.get("llm_conclusion", "")
    if llm and not llm.startswith("[오류]") and not llm.startswith("[LLM"):
        st.markdown("""
        <div class="section-header">
            <div class="section-title">LLM Conclusion</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f'<div class="llm-body">\n\n{llm}\n\n</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
#  스캔 히스토리 페이지
# ═══════════════════════════════════════════════════════════════

def render_history():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Scan History</div>
        <div class="page-subtitle">Recent scan results and alert timeline</div>
    </div>
    """, unsafe_allow_html=True)

    data = engine_get_history(20)
    if not data or not data.get("history"):
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">📜</div>
            <div class="es-text">No scan history yet.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    history = data["history"]
    st.caption(f"Showing {len(history)} of {data.get('count', 0)} scans")

    for i, entry in enumerate(reversed(history)):
        ts = entry.get("timestamp", "")[:16]
        tickers = entry.get("tickers", [])
        results = entry.get("results", {})
        alerts = entry.get("alerts", [])

        alert_label = f" | {len(alerts)} alerts" if alerts else ""

        with st.expander(f"**{ts}** — {len(tickers)} tickers{alert_label}", expanded=(i == 0)):
            if alerts:
                st.markdown(
                    f'<span class="signal-pill sell" style="margin-bottom:8px;">{len(alerts)} alerts</span>',
                    unsafe_allow_html=True,
                )
            if not results:
                st.caption("No results")
                continue

            h_rows = []
            for ticker, r in sorted(results.items(), key=lambda x: x[1].get("score", 0), reverse=True):
                h_rows.append({
                    "Ticker": ticker,
                    "Signal": r.get("signal", "?"),
                    "Score": r.get("score", 0),
                    "Confidence": r.get("confidence", 0),
                })
            hdf = pd.DataFrame(h_rows)
            st.dataframe(
                hdf.style.map(
                    lambda v: "color: #02d4a1" if v == "BUY" else ("color: #fd526f" if v == "SELL" else "color: #ffb347"),
                    subset=["Signal"],
                ),
                use_container_width=True, hide_index=True,
            )


# ═══════════════════════════════════════════════════════════════
#  백테스트 페이지
# ═══════════════════════════════════════════════════════════════

def render_backtest():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Backtest</div>
        <div class="page-subtitle">Strategy backtesting with historical data</div>
    </div>
    """, unsafe_allow_html=True)

    tickers = load_watchlist()
    if not tickers:
        st.info("Watchlist is empty. Add tickers first.")
        return

    ticker = st.selectbox("Select Ticker", sorted(tickers))
    if st.button("Run Backtest", type="primary"):
        with st.spinner(f"Scanning {ticker} for backtest..."):
            scan = engine_scan_ticker(ticker)
        if not scan:
            st.error(f"Scan failed for {ticker}. Cannot run backtest.")
            return
        with st.spinner(f"Backtesting {ticker}..."):
            bt = engine_backtest(ticker)
        if not bt:
            st.error("Backtest failed")
            return

        st.markdown(f"""
        <div class="section-header">
            <div class="section-title">Best Strategy: {bt.get('best_strategy', '?')}</div>
            <div class="section-subtitle">Sharpe: {bt.get('best_sharpe', 0):.3f}</div>
        </div>
        """, unsafe_allow_html=True)

        strategies = bt.get("strategies", {})
        cols = st.columns(len(strategies))
        for i, (name, s) in enumerate(strategies.items()):
            with cols[i]:
                st.markdown(f"**{s.get('strategy', name)}**")
                st.metric("Total Return", f"{s.get('total_return_pct', 0):+.1f}%")
                st.metric("Sharpe Ratio", f"{s.get('sharpe_ratio', 0):.3f}")
                st.metric("Max Drawdown", f"{s.get('max_drawdown_pct', 0):.1f}%")
                st.metric("Win Rate", f"{s.get('win_rate_pct', 0):.1f}%")
                st.metric("Trades", str(s.get("total_trades", 0)))
                st.metric("Profit Factor", f"{s.get('profit_factor', 0):.2f}")
                st.metric("Avg Hold", f"{s.get('avg_holding_days', 0):.0f}d")


# ═══════════════════════════════════════════════════════════════
#  ML 예측 페이지
# ═══════════════════════════════════════════════════════════════

def render_ml_predict():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">ML Prediction</div>
        <div class="page-subtitle">Machine learning direction forecast</div>
    </div>
    """, unsafe_allow_html=True)

    tickers = load_watchlist()
    if not tickers:
        st.info("Watchlist is empty. Add tickers first.")
        return

    ticker = st.selectbox("Select Ticker", sorted(tickers), key="ml_ticker")
    if st.button("Run ML Prediction", type="primary"):
        with st.spinner(f"Training model for {ticker}..."):
            ml = engine_ml_predict(ticker)
        if not ml:
            st.error("ML prediction failed")
            return

        st.markdown(f"""
        <div class="section-header">
            <div class="section-title">{ticker} — {ml.get('best_prediction', '?')}</div>
            <div class="section-subtitle">Best model: {ml.get('best_model', '?').upper()}, Accuracy: {ml.get('best_accuracy', 0):.1%}</div>
        </div>
        """, unsafe_allow_html=True)

        models = ml.get("models", {})
        for name, m in models.items():
            if m.get("error"):
                st.warning(f"{name}: {m['error']}")
                continue

            signal_color = "#02d4a1" if m.get("signal") == "buy" else ("#fd526f" if m.get("signal") == "sell" else "#ffb347")

            with st.expander(f"**{m.get('name', name)}** — {m.get('prediction', '?')} ({m.get('up_probability', 0):.1%})", expanded=True):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Prediction", m.get("prediction", "?"))
                c2.metric("Up Prob", f"{m.get('up_probability', 0):.1%}")
                c3.metric("Test Accuracy", f"{m.get('test_accuracy', 0):.1%}")
                c4.metric("CV Accuracy", f"{m.get('cv_accuracy_mean', 0):.1%}")

                top_feat = m.get("top_features", [])
                if top_feat:
                    feat_df = pd.DataFrame(top_feat)
                    fig = go.Figure(go.Bar(
                        x=[f["importance"] for f in top_feat],
                        y=[f["name"] for f in top_feat],
                        orientation="h",
                        marker_color="#aec6ff",
                    ))
                    fig.update_layout(**_plotly_base_layout(
                        height=300, margin=dict(l=140, r=10, t=10, b=10),
                    ))
                    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════
#  포트폴리오 최적화 페이지
# ═══════════════════════════════════════════════════════════════

def render_portfolio():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Portfolio</div>
        <div class="page-subtitle">Optimization & Correlation Analysis</div>
    </div>
    """, unsafe_allow_html=True)

    tickers = load_watchlist()
    if len(tickers) < 2:
        st.info("Need at least 2 tickers in watchlist for portfolio optimization.")
        return

    tab1, tab2 = st.tabs(["Optimization", "Correlation / Beta"])

    with tab1:
        method = st.selectbox("Method", ["markowitz", "risk_parity"])
        if st.button("Optimize Portfolio", type="primary"):
            with st.spinner("Optimizing..."):
                opt = engine_portfolio_optimize(method)
            if not opt:
                st.error("Optimization failed")
                return
            if opt.get("error"):
                st.error(opt["error"])
                return

            c1, c2, c3 = st.columns(3)
            c1.metric("Expected Return", f"{opt.get('portfolio_return_pct', 0):+.1f}%")
            c2.metric("Volatility", f"{opt.get('portfolio_volatility_pct', 0):.1f}%")
            c3.metric("Sharpe", f"{opt.get('sharpe_ratio', 0):.3f}")

            alloc = opt.get("allocation", {})
            if alloc:
                st.markdown("**Allocation**")
                alloc_rows = []
                for t, a in sorted(alloc.items(), key=lambda x: x[1].get("weight_pct", 0), reverse=True):
                    alloc_rows.append({
                        "Ticker": t,
                        "Weight %": a.get("weight_pct", 0),
                        "Amount $": f"${a.get('amount', 0):,.0f}",
                        "Exp Return %": a.get("expected_return_pct", 0),
                        "Volatility %": a.get("volatility_pct", 0),
                    })
                st.dataframe(pd.DataFrame(alloc_rows), use_container_width=True, hide_index=True)

                fig = go.Figure(go.Pie(
                    labels=[r["Ticker"] for r in alloc_rows],
                    values=[r["Weight %"] for r in alloc_rows],
                    hole=0.4,
                    marker=dict(colors=["#aec6ff", "#02d4a1", "#fd526f", "#ffb347", "#c3c6d4", "#5d8ef1"]),
                    textfont=dict(color="#e1e2eb"),
                ))
                fig.update_layout(**_plotly_base_layout(height=350))
                st.plotly_chart(fig, use_container_width=True)

    with tab2:
        if st.button("Analyze Correlation & Beta", type="primary"):
            with st.spinner("Analyzing..."):
                corr = engine_correlation_beta()
            if not corr:
                st.error("Analysis failed")
                return

            st.metric("Portfolio Beta", f"{corr.get('portfolio_beta', 0):.3f}")

            individual = corr.get("individual", {})
            if individual:
                st.markdown("**Individual Beta / Alpha**")
                beta_rows = []
                for t, v in individual.items():
                    beta_rows.append({
                        "Ticker": t,
                        "Beta": v.get("beta", 0),
                        "Alpha %": v.get("alpha_annualized", 0),
                        "Correlation": v.get("correlation", 0),
                        "R-Squared": v.get("r_squared", 0),
                        "Info Ratio": v.get("information_ratio", 0),
                    })
                st.dataframe(pd.DataFrame(beta_rows), use_container_width=True, hide_index=True)

            pairs = corr.get("pair_correlations", {})
            if pairs:
                st.markdown("**Pair Correlations**")
                pair_rows = [{"Pair": k, "Correlation": v} for k, v in sorted(pairs.items(), key=lambda x: abs(x[1]), reverse=True)]
                st.dataframe(pd.DataFrame(pair_rows), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════
#  팩터 랭킹 페이지
# ═══════════════════════════════════════════════════════════════

def render_ranking():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Factor Ranking</div>
        <div class="page-subtitle">Cross-sectional factor-based stock ranking</div>
    </div>
    """, unsafe_allow_html=True)

    ranking_data = engine_factor_ranking()
    if not ranking_data or not ranking_data.get("ranking"):
        st.info("No ranking data. Run scans for multiple tickers first.")
        return

    ranking = ranking_data["ranking"]
    st.caption(f"{len(ranking)} tickers ranked")

    rows = []
    for r in ranking:
        signal = r.get("signal", "HOLD")
        rows.append({
            "Rank": r.get("rank", 0),
            "Ticker": r.get("ticker", "?"),
            "Signal": signal,
            "Composite": r.get("composite_score", 0),
            "Factor Score": r.get("weighted_factor_score", 0),
            "Momentum": r.get("factor_momentum", 0),
            "Trend": r.get("factor_trend", 0),
            "Value": r.get("factor_value", 0),
            "Volume": r.get("factor_volume", 0),
            "Percentile": r.get("percentile", 0),
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df.style.map(
            lambda v: "color: #02d4a1" if v == "BUY" else ("color: #fd526f" if v == "SELL" else "color: #ffb347"),
            subset=["Signal"],
        ).background_gradient(
            subset=["Factor Score"], cmap="RdYlGn", vmin=-5, vmax=5
        ),
        use_container_width=True, hide_index=True,
    )

    if len(ranking) >= 2:
        fig = go.Figure()
        tickers = [r["ticker"] for r in ranking]
        factors = ["factor_momentum", "factor_trend", "factor_value", "factor_volume"]
        colors = ["#aec6ff", "#02d4a1", "#ffb347", "#fd526f"]
        for factor, color in zip(factors, colors):
            fig.add_trace(go.Bar(
                name=factor.replace("factor_", "").title(),
                x=tickers,
                y=[r.get(factor, 0) for r in ranking],
                marker_color=color,
            ))
        fig.update_layout(**_plotly_base_layout(
            height=350, barmode="group",
            margin=dict(l=50, r=10, t=30, b=60),
            legend=dict(font=dict(color="#c3c6d4")),
        ))
        st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════
#  페이퍼 트레이딩 페이지
# ═══════════════════════════════════════════════════════════════

def render_paper_trade():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Paper Trading</div>
        <div class="page-subtitle">Simulated trading based on agent signals</div>
    </div>
    """, unsafe_allow_html=True)

    status = engine_paper_status()
    if not status:
        st.error("Paper trading service unavailable")
        return

    c1, c2, c3, c4, c5 = st.columns(5)
    total_pnl = status.get("total_pnl", 0)
    pnl_color = "#02d4a1" if total_pnl >= 0 else "#fd526f"
    c1.metric("Total Equity", f"${status.get('total_equity', 0):,.0f}")
    c2.metric("Cash", f"${status.get('cash', 0):,.0f}")
    c3.metric("P&L", f"${total_pnl:+,.0f}")
    c4.metric("P&L %", f"{status.get('total_pnl_pct', 0):+.2f}%")
    c5.metric("Win Rate", f"{status.get('win_rate_pct', 0):.1f}%")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Open Positions", str(status.get("open_positions", 0)))
    m2.metric("Closed Trades", str(status.get("total_closed_trades", 0)))
    m3.metric("Realized P&L", f"${status.get('realized_pnl', 0):+,.0f}")
    m4.metric("Unrealized P&L", f"${status.get('unrealized_pnl', 0):+,.0f}")

    positions = status.get("positions", {})
    if positions:
        st.markdown("**Open Positions**")
        pos_rows = []
        for t, p in positions.items():
            pos_rows.append({
                "Ticker": t,
                "Qty": p.get("qty", 0),
                "Entry": f"${p.get('entry_price', 0):.2f}",
                "Current": f"${p.get('current_price', 0):.2f}",
                "P&L": f"${p.get('pnl', 0):+.2f}",
                "P&L %": f"{p.get('pnl_pct', 0):+.2f}%",
                "Entry Date": str(p.get("entry_date", ""))[:10],
            })
        st.dataframe(pd.DataFrame(pos_rows), use_container_width=True, hide_index=True)

    recent = status.get("recent_trades", [])
    if recent:
        st.markdown("**Recent Closed Trades**")
        trade_rows = []
        for t in reversed(recent):
            trade_rows.append({
                "Ticker": t.get("ticker", "?"),
                "Entry": f"${t.get('entry_price', 0):.2f}",
                "Exit": f"${t.get('exit_price', 0):.2f}",
                "Qty": t.get("qty", 0),
                "P&L": f"${t.get('pnl', 0):+.2f}",
                "Return %": f"{t.get('pnl_pct', 0):+.2f}%",
                "Reason": t.get("reason", ""),
            })
        st.dataframe(pd.DataFrame(trade_rows), use_container_width=True, hide_index=True)

    st.divider()

    tab1, tab2 = st.tabs(["Auto Trade", "Manual Order"])

    with tab1:
        st.caption("Execute paper trades based on latest agent signals")
        if st.button("Execute Auto Trades", type="primary"):
            with st.spinner("Executing..."):
                result = engine_paper_auto()
            if result:
                orders = result.get("orders", [])
                if orders:
                    st.success(f"{len(orders)} orders executed")
                    for o in orders:
                        st.json(o)
                else:
                    st.info("No trades triggered by current signals")

    with tab2:
        oc1, oc2, oc3, oc4 = st.columns(4)
        order_ticker = oc1.text_input("Ticker", placeholder="AAPL", key="pt_ticker")
        order_action = oc2.selectbox("Action", ["BUY", "SELL"], key="pt_action")
        order_qty = oc3.number_input("Qty", min_value=1, value=10, key="pt_qty")
        order_price = oc4.number_input("Price", min_value=0.01, value=100.0, step=0.01, key="pt_price")

        if st.button("Submit Order"):
            if order_ticker:
                result = engine_paper_order(order_ticker, order_action, int(order_qty), float(order_price))
                if result:
                    if result.get("status") == "filled":
                        st.success(f"Order filled: {order_action} {order_qty} {order_ticker.upper()} @ ${order_price}")
                    else:
                        st.warning(f"Order {result.get('status')}: {result.get('reject_reason', '')}")

    st.divider()
    if st.button("Reset Paper Trading", type="secondary"):
        result = engine_paper_reset()
        if result:
            st.success("Paper trading reset")
            st.rerun()


# ═══════════════════════════════════════════════════════════════
#  종합 레포트 페이지
# ═══════════════════════════════════════════════════════════════

def _score_bar_html(score: float, max_val: float = 10) -> str:
    pct = min(abs(score) / max_val * 100, 100)
    color = "var(--buy)" if score > 0 else ("var(--sell)" if score < 0 else "var(--outline)")
    direction = "right" if score >= 0 else "left"
    return f"""
    <div style="display:flex;align-items:center;gap:8px;">
        <div style="width:60%;height:8px;background:var(--L2);border-radius:4px;position:relative;overflow:hidden;">
            <div style="position:absolute;{direction}:50%;width:{pct/2}%;height:100%;background:{color};border-radius:4px;"></div>
            <div style="position:absolute;left:50%;top:0;width:1px;height:100%;background:var(--outline);opacity:0.3;"></div>
        </div>
        <span style="font-family:'JetBrains Mono';font-size:0.75rem;font-weight:700;color:{color};min-width:45px;">{score:+.1f}</span>
    </div>"""


def _fmt_pct(v, decimals=1):
    if v is None:
        return "—"
    return f"{v * 100:.{decimals}f}%" if abs(v) < 10 else f"{v:.{decimals}f}%"


def _fmt_dollar(v):
    if v is None:
        return "—"
    if abs(v) >= 1e12:
        return f"${v/1e12:.1f}T"
    if abs(v) >= 1e9:
        return f"${v/1e9:.1f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:.1f}M"
    return f"${v:,.0f}"


TOOL_EXPLANATIONS = {
    "trend_ma_analysis": {
        "title": "이동평균선 배열 분석",
        "desc": "단기(20일), 중기(50일), 장기(200일) 이동평균선의 배열 상태와 크로스 신호를 분석합니다.",
        "metrics": {
            "SMA 20/50/200": "각 기간의 단순이동평균(Simple Moving Average). 현재가가 이 선 위에 있으면 해당 기간 평균보다 강세.",
            "정배열(Bullish Aligned)": "SMA20 > SMA50 > SMA200 순서. 강한 상승 추세를 의미하며, 추세 추종 매매에 적합.",
            "역배열(Bearish Aligned)": "SMA20 < SMA50 < SMA200 순서. 하락 추세를 의미하며, 매수 진입 시 주의.",
            "골든크로스": "단기 이평선이 장기 이평선을 상향 돌파. 중기적 상승 전환 신호.",
            "데드크로스": "단기 이평선이 장기 이평선을 하향 돌파. 중기적 하락 전환 신호.",
        },
    },
    "rsi_divergence_analysis": {
        "title": "RSI 다이버전스 분석",
        "desc": "RSI(Relative Strength Index)의 과매수/과매도 상태와 가격-RSI 간 다이버전스를 탐지합니다.",
        "metrics": {
            "RSI": "0~100 범위. 70 이상 과매수(단기 조정 가능), 30 이하 과매도(반등 가능). 50이 중립선.",
            "일반 강세 다이버전스": "가격은 저점 갱신, RSI는 저점 상승 → 하락 힘이 약해지며 반등 가능성.",
            "일반 약세 다이버전스": "가격은 고점 갱신, RSI는 고점 하락 → 상승 힘이 약해지며 조정 가능성.",
            "히든 다이버전스": "추세 지속을 확인하는 신호. 히든 강세: 추세 내 매수 기회, 히든 약세: 추세 내 매도 기회.",
        },
    },
    "bollinger_squeeze_analysis": {
        "title": "볼린저밴드 스퀴즈/확장 분석",
        "desc": "볼린저밴드의 폭 변화를 통해 변동성 축소(스퀴즈) 후 확장 패턴을 탐지합니다.",
        "metrics": {
            "BB Width %": "상단-하단밴드 간격을 중간밴드로 나눈 비율. 낮을수록 스퀴즈(변동성 축소), 높을수록 확장.",
            "%B": "현재가의 볼린저밴드 내 위치. 0=하단밴드, 0.5=중간, 1=상단밴드. 0 이하나 1 이상은 밴드 이탈.",
            "스퀴즈(Squeeze)": "밴드 폭이 최근 120일 중 최소 수준으로 좁아진 상태. 큰 움직임 직전의 '에너지 축적' 구간.",
            "확장(Expanding)": "밴드가 넓어지는 상태. 강한 추세 움직임이 진행 중임을 의미.",
        },
    },
    "macd_momentum_analysis": {
        "title": "MACD 모멘텀 분석",
        "desc": "MACD(이동평균수렴확산)의 크로스, 히스토그램 방향, 제로라인 돌파를 분석합니다.",
        "metrics": {
            "MACD": "12일 EMA - 26일 EMA. 양수이면 단기 모멘텀이 장기보다 강세.",
            "Signal": "MACD의 9일 EMA. MACD가 시그널 위로 올라가면 매수 크로스.",
            "Histogram": "MACD - Signal. 양수 증가 = 상승 가속, 양수 감소 = 상승 둔화, 음수 증가 = 하락 감속.",
            "크로스": "MACD가 시그널선을 돌파하는 시점. 골든크로스(상향)=매수, 데드크로스(하향)=매도.",
        },
    },
    "adx_trend_strength_analysis": {
        "title": "ADX 추세 강도 분석",
        "desc": "ADX(Average Directional Index)로 추세의 존재 여부와 강도를 측정합니다.",
        "metrics": {
            "ADX": "추세 강도 지표. 25 이상=추세 존재, 50 이상=매우 강한 추세, 20 이하=비추세(횡보).",
            "+DI / -DI": "상승/하락 방향지표. +DI > -DI이면 상승 추세, +DI < -DI이면 하락 추세.",
            "추세 강도(Trend Strength)": "ADX 값 기반 분류: weak(20 미만), moderate(20-25), strong(25-50), very_strong(50+).",
        },
    },
    "volume_profile_analysis": {
        "title": "거래량 프로파일 분석",
        "desc": "거래량 패턴, OBV(On-Balance Volume), 매집/분산 상태를 분석합니다.",
        "metrics": {
            "Volume Ratio": "최근 거래량 / 평균 거래량. 1.5 이상이면 거래량 급증, 0.5 이하면 거래량 부족.",
            "OBV Trend": "가격 상승일에는 거래량 더하고 하락일에는 빼는 누적선. 상승(rising)이면 매수 압력 우세.",
            "매집/분산(Accum/Dist)": "가격 변화와 거래량으로 스마트머니의 매집(accumulation) 또는 분산(distribution) 판단.",
        },
    },
    "fibonacci_retracement_analysis": {
        "title": "피보나치 되돌림 분석",
        "desc": "주요 피보나치 비율(23.6%, 38.2%, 50%, 61.8%, 78.6%)에서의 지지/저항을 분석합니다.",
        "metrics": {
            "Retracement": "현재가가 최고-최저 범위에서 어디에 위치하는지 비율. 0.382 근처 = 건전한 조정, 0.618 이상 = 깊은 조정.",
            "지지선(Support)": "현재가 아래에서 가격이 반등할 가능성이 높은 피보나치 레벨.",
            "저항선(Resistance)": "현재가 위에서 가격 상승이 막힐 가능성이 높은 피보나치 레벨.",
            "Fib Levels": "0.236, 0.382, 0.5, 0.618, 0.786의 각 레벨별 가격. 이 가격대에서 매매 결정의 참고점.",
        },
    },
    "volatility_regime_analysis": {
        "title": "변동성 체제 분석",
        "desc": "ATR(Average True Range) 기반으로 현재 변동성의 상대적 위치와 체제를 분류합니다.",
        "metrics": {
            "ATR %": "ATR을 현재가로 나눈 비율. 높을수록 변동성이 큰 상태.",
            "Percentile": "최근 1년 기준 현재 ATR의 백분위. 90 이상=극도의 고변동성, 10 이하=극도의 저변동성.",
            "Regime": "low_vol(저변동), normal(보통), high_vol(고변동), extreme(극단). 저변동 후 급등 가능성 높음.",
            "Annualized Vol": "일간 수익률의 표준편차를 연간화한 변동성. S&P500 평균은 약 15~20%.",
        },
    },
    "mean_reversion_analysis": {
        "title": "평균 회귀 분석",
        "desc": "Z-Score를 이용해 현재가가 평균에서 얼마나 벗어났는지, 평균으로 회귀할 확률을 계산합니다.",
        "metrics": {
            "Z-Score": "표준편차 단위로 평균에서의 이탈도. +2 이상=과매수(평균 회귀 매도), -2 이하=과매도(평균 회귀 매수).",
            "Avg Z-Score": "여러 기간 Z-Score의 평균. 방향 일치시 신뢰도 상승.",
            "Reversion Prob": "통계적 평균 회귀 확률. 높을수록 현재 가격이 극단적 위치에 있음을 의미.",
        },
    },
    "momentum_rank_analysis": {
        "title": "모멘텀 순위 분석",
        "desc": "1주, 1개월, 3개월 수익률을 종합하여 모멘텀 강도와 가속/감속 상태를 판단합니다.",
        "metrics": {
            "기간별 수익률": "1w(1주), 1m(1개월), 3m(3개월) 수익률. 모두 양수이면 강한 상승 모멘텀.",
            "Weighted Return": "기간별 가중 평균 수익률. 단기에 높은 가중치를 부여하여 최근 모멘텀을 강조.",
            "Acceleration": "모멘텀의 변화율. 양수=모멘텀 가속(추가 상승 기대), 음수=모멘텀 둔화(조정 가능).",
        },
    },
    "support_resistance_analysis": {
        "title": "지지/저항선 분석",
        "desc": "피봇포인트, 가격 클러스터, 스윙 고저점을 이용해 핵심 가격대를 산출합니다.",
        "metrics": {
            "Pivot": "전일 (고가+저가+종가)/3. 당일 거래의 중심축.",
            "Upside %": "현재가에서 1차 저항선까지의 상승 여력.",
            "Risk/Reward": "상승 여력 / 하방 리스크 비율. 2 이상이면 진입 매력 있음.",
            "R1/R2/R3": "피봇 기반 저항선. 가격 상승 시 매도 압력이 예상되는 가격대.",
            "S1/S2/S3": "피봇 기반 지지선. 가격 하락 시 매수 지지가 예상되는 가격대.",
        },
    },
    "correlation_regime_analysis": {
        "title": "자기상관/허스트 분석",
        "desc": "수익률의 자기상관과 허스트 지수를 통해 추세 지속성 vs 평균회귀 성향을 판단합니다.",
        "metrics": {
            "Avg Autocorrelation": "수익률의 평균 자기상관. 양수=추세 지속 경향, 음수=평균 회귀 경향.",
            "Hurst Exponent": "0.5=랜덤워크, >0.5=추세 추종, <0.5=평균 회귀. 0.7 이상=강한 추세 지속성.",
            "Regime": "trending(추세형), mean_reverting(회귀형), random(랜덤). 매매 전략 선택의 근거.",
        },
    },
    "risk_position_sizing": {
        "title": "포지션 사이징",
        "desc": "ATR 기반 손절가 산출, 계좌 리스크 비율에 따른 적정 수량, 분할 매수 계획을 제시합니다.",
        "metrics": {
            "Entry Price": "현재 종가 기준 진입 가격.",
            "Stop Loss": "ATR x 배수로 산출한 손절 가격. 이 가격 아래로 내려가면 손절 실행.",
            "Take Profit": "손절폭의 리스크:보상 비율만큼 위에 설정한 익절 가격.",
            "Recommended Qty": "계좌 크기 x 리스크 비율 / (진입가-손절가)로 산출한 적정 수량.",
            "Split Entries": "분할 매수 가격대. 한 번에 몰빵하지 않고 2~3차에 나눠 매수하여 리스크 분산.",
        },
    },
    "kelly_criterion_analysis": {
        "title": "켈리 기준 분석",
        "desc": "과거 승률과 손익비를 기반으로 수학적 최적 베팅 비율을 산출합니다.",
        "metrics": {
            "Win Rate": "과거 거래에서의 승률. 50% 이상이면 양의 기대값 가능성.",
            "Kelly Full %": "f* = (bp - q) / b 공식으로 산출한 풀 켈리 비율. 실전에서는 1/2~1/4만 사용.",
            "Optimal Position %": "반 켈리(Half Kelly) 기준 추천 포지션 비율. 보수적으로 적용.",
            "Sharpe Ratio": "초과수익률 / 변동성. 1 이상=양호, 2 이상=우수, 3 이상=탁월.",
        },
    },
    "beta_correlation_analysis": {
        "title": "베타/상관관계 분석",
        "desc": "S&P 500(SPY) 대비 베타, 알파, 상관계수를 산출하여 시장 대비 성과를 평가합니다.",
        "metrics": {
            "Beta": "시장 대비 변동성 배수. 1=시장과 동일, >1=시장보다 변동 큼, <1=시장보다 안정적.",
            "Beta 60d": "최근 60일 기준 단기 베타. 장기 베타와 비교하여 최근 변화 파악.",
            "Alpha (Annual %)": "시장 수익률 대비 초과 수익률. 양수=시장 아웃퍼폼, 음수=언더퍼폼.",
            "Correlation": "SPY와의 상관계수. 1에 가까울수록 시장과 동행, 0이면 무관, 음수이면 역행.",
            "R-Squared": "시장 변동으로 설명되는 가격 변동 비율. 높으면 시장 의존도 높음.",
            "Info Ratio": "정보 비율 = 알파 / 추적 오차. 1 이상이면 우수한 액티브 성과.",
        },
    },
    "event_driven_analysis": {
        "title": "이벤트 드리븐 분석",
        "desc": "실적 발표, 배당락, 52주 신고/저가, 애널리스트 추천 등 이벤트를 추적합니다.",
        "metrics": {
            "52W High/Low": "52주 최고/최저가. 현재가가 고점 근처면 돌파 매매, 저점 근처면 반등 매매 기회.",
            "Analyst Recommendation": "애널리스트 컨센서스 (buy/hold/sell). 시장 심리 파악에 참고.",
            "Earnings Dates": "향후 실적 발표 예정일. 실적 시즌에는 변동성이 급등하므로 포지션 관리 필요.",
        },
    },
}


def _render_tool_explanation(tool_key: str):
    info = TOOL_EXPLANATIONS.get(tool_key)
    if not info:
        return
    st.markdown(f"""<div style="background:var(--surface-low);border-radius:8px;padding:12px 16px;margin:8px 0;border-left:3px solid var(--primary-ctr);">
<div style="font-size:0.75rem;font-weight:700;color:var(--primary);margin-bottom:6px;">{info['title']}</div>
<div style="font-size:0.7rem;color:var(--on-surface-variant);margin-bottom:8px;">{info['desc']}</div>
</div>""", unsafe_allow_html=True)
    for metric_name, metric_desc in info["metrics"].items():
        st.markdown(f"""<div style="font-size:0.7rem;padding:2px 0 2px 16px;color:var(--on-surface-variant);">
<span style="color:var(--on-surface);font-weight:600;">{metric_name}</span> — {metric_desc}</div>""", unsafe_allow_html=True)


def _render_ai_interpret_btn(selected: str, tool_key: str, llm_providers: list):
    if not llm_providers:
        return
    btn_key = f"ai_{tool_key}_{selected}"
    result_key = f"ai_result_{tool_key}_{selected}"
    if st.button("AI 해석", key=btn_key, type="secondary"):
        with st.spinner("AI 분석 중..."):
            st.session_state[result_key] = engine_interpret_tool(selected, tool_key, llm_providers[0])
    if result_key in st.session_state:
        st.markdown(st.session_state[result_key])


def render_report():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Report</div>
        <div class="page-subtitle">Comprehensive analysis report for individual stocks</div>
    </div>
    """, unsafe_allow_html=True)

    data = engine_get_all_results()
    tickers_available = sorted(data.get("results", {}).keys()) if data else []

    wl = load_watchlist()
    ticker_options = sorted(set(wl) | set(tickers_available)) if wl else tickers_available

    if not ticker_options:
        st.info("No tickers available. Add tickers to watchlist and run a scan first.")
        return

    llm_info = engine_available_llm()
    llm_providers = llm_info.get("providers", [])

    col_sel, col_btn, col_llm = st.columns([3, 1, 1.5])
    with col_sel:
        selected = st.selectbox("Select Ticker", ticker_options, label_visibility="collapsed")
    with col_btn:
        run_scan = st.button("Scan & Report", type="primary", use_container_width=True)
    with col_llm:
        provider_labels = {"openai": "GPT-4o", "gemini": "Gemini", "ollama": f"Ollama ({OLLAMA_MODEL})"}
        if llm_providers:
            llm_display = ", ".join(provider_labels.get(p, p) for p in llm_providers)
            st.markdown(f'<div style="font-size:0.65rem;color:var(--on-surface-variant);padding:8px 0;">LLM: <span style="color:var(--buy);">{llm_display}</span></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="font-size:0.65rem;color:var(--sell);padding:8px 0;">LLM: None (.env 설정 필요)</div>', unsafe_allow_html=True)

    if run_scan and selected:
        with st.spinner(f"Analyzing {selected}..."):
            engine_scan_ticker(selected)

    detail = engine_get_ticker_result(selected)
    if not detail:
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">📊</div>
            <div class="es-text">No analysis data. Click "Scan & Report" to analyze.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    signal = detail.get("final_signal", "?")
    score = detail.get("composite_score", 0)
    confidence = detail.get("confidence", 0)
    tool_count = detail.get("tool_count", 0)
    dist = detail.get("signal_distribution", {})
    analyzed_at = str(detail.get("analyzed_at", ""))[:19].replace("T", " ")

    badge_class = "buy" if signal == "BUY" else ("sell" if signal == "SELL" else "hold")
    score_color = "var(--buy)" if score > 0 else ("var(--sell)" if score < 0 else "var(--outline)")

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:24px;margin-bottom:20px;">
        <div>
            <div style="font-size:1.8rem;font-weight:800;letter-spacing:-0.03em;">{selected}</div>
            <div style="font-size:0.7rem;color:var(--on-surface-variant);margin-top:2px;">{analyzed_at}</div>
        </div>
        <span class="signal-badge-lg {badge_class}">{signal}</span>
        <div style="margin-left:auto;text-align:right;">
            <div style="font-family:'JetBrains Mono';font-size:2rem;font-weight:800;color:{score_color};">{score:+.2f}</div>
            <div style="font-size:0.65rem;color:var(--on-surface-variant);text-transform:uppercase;letter-spacing:0.5px;">Composite Score</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Confidence", f"{confidence}/10")
    m2.metric("Tools", str(tool_count))
    m3.metric("Buy Votes", str(dist.get("buy", 0)))
    m4.metric("Sell Votes", str(dist.get("sell", 0)))
    m5.metric("Neutral", str(dist.get("neutral", 0)))

    chart_path = engine_get_chart_path(selected)
    if chart_path and os.path.exists(chart_path):
        st.image(chart_path, use_container_width=True)

    tab_tech, tab_quant, tab_risk, tab_fund, tab_llm = st.tabs([
        "Technical Analysis", "Quantitative", "Risk & Sizing", "Fundamentals", "AI Deep Analysis"
    ])

    tool_details = detail.get("tool_details", [])
    tool_map = {td.get("tool"): td for td in tool_details}

    with tab_tech:
        tech_tools = [
            ("trend_ma_analysis", "Moving Average"),
            ("rsi_divergence_analysis", "RSI Divergence"),
            ("bollinger_squeeze_analysis", "Bollinger Squeeze"),
            ("macd_momentum_analysis", "MACD Momentum"),
            ("adx_trend_strength_analysis", "ADX Trend Strength"),
            ("volume_profile_analysis", "Volume Profile"),
        ]

        for tool_key, tool_label in tech_tools:
            td = tool_map.get(tool_key)
            if not td:
                continue
            tool_signal = td.get("signal", "neutral").upper()
            tool_score = td.get("score", 0)
            pill = _signal_pill_html(tool_signal)

            with st.expander(f"**{tool_label}** — {pill} ({tool_score:+.1f})", expanded=False):
                st.markdown(_score_bar_html(tool_score), unsafe_allow_html=True)
                st.caption(td.get("detail", ""))

                if tool_key == "trend_ma_analysis":
                    sma = td.get("sma_values", {})
                    price_vs = td.get("price_vs_sma", {})
                    cols = st.columns(len(sma)) if sma else []
                    for col, (period, val) in zip(cols, sma.items()):
                        pos = price_vs.get(str(period), "")
                        col.metric(f"SMA {period}", _fmt_num(val), pos)
                    c1, c2 = st.columns(2)
                    c1.metric("Alignment", str(td.get("alignment", "—")))
                    c2.metric("Cross Signal", str(td.get("cross_signal", "—")))

                elif tool_key == "rsi_divergence_analysis":
                    c1, c2, c3 = st.columns(3)
                    c1.metric("RSI", _fmt_num(td.get("current_rsi"), 1))
                    c2.metric("Zone", str(td.get("rsi_zone", "—")))
                    c3.metric("Divergence", str(td.get("divergence", "none")))

                elif tool_key == "bollinger_squeeze_analysis":
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("BB Width %", _fmt_num(td.get("bb_width_pct"), 2))
                    c2.metric("%B", _fmt_num(td.get("pct_b"), 3))
                    c3.metric("Squeeze", str(td.get("squeeze", "—")))
                    c4.metric("Expanding", str(td.get("expanding", "—")))

                elif tool_key == "macd_momentum_analysis":
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("MACD", _fmt_num(td.get("macd"), 3))
                    c2.metric("Signal", _fmt_num(td.get("signal_line"), 3))
                    c3.metric("Histogram", _fmt_num(td.get("histogram"), 3))
                    c4.metric("Cross", str(td.get("cross", "—")))

                elif tool_key == "adx_trend_strength_analysis":
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("ADX", _fmt_num(td.get("adx"), 1))
                    c2.metric("+DI", _fmt_num(td.get("plus_di"), 1))
                    c3.metric("-DI", _fmt_num(td.get("minus_di"), 1))
                    c4.metric("Trend", str(td.get("trend_strength", "—")))

                elif tool_key == "volume_profile_analysis":
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Volume Ratio", _fmt_num(td.get("volume_ratio"), 2))
                    c2.metric("OBV Trend", str(td.get("obv_trend", "—")))
                    c3.metric("Accum/Dist", str(td.get("accumulation_distribution", "—")))

                _render_tool_explanation(tool_key)
                _render_ai_interpret_btn(selected, tool_key, llm_providers)

    with tab_quant:
        quant_tools = [
            ("fibonacci_retracement_analysis", "Fibonacci Retracement"),
            ("volatility_regime_analysis", "Volatility Regime"),
            ("mean_reversion_analysis", "Mean Reversion"),
            ("momentum_rank_analysis", "Momentum Ranking"),
            ("support_resistance_analysis", "Support / Resistance"),
            ("correlation_regime_analysis", "Correlation Regime"),
        ]

        for tool_key, tool_label in quant_tools:
            td = tool_map.get(tool_key)
            if not td:
                continue
            tool_signal = td.get("signal", "neutral").upper()
            tool_score = td.get("score", 0)
            pill = _signal_pill_html(tool_signal)

            with st.expander(f"**{tool_label}** — {pill} ({tool_score:+.1f})", expanded=False):
                st.markdown(_score_bar_html(tool_score), unsafe_allow_html=True)
                st.caption(td.get("detail", ""))

                if tool_key == "fibonacci_retracement_analysis":
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Retracement", _fmt_num(td.get("current_retracement"), 3))
                    c2.metric("Nearest Support", _fmt_num(td.get("nearest_support")))
                    c3.metric("Nearest Resistance", _fmt_num(td.get("nearest_resistance")))
                    levels = td.get("levels", {})
                    if levels:
                        st.markdown("**Fib Levels**")
                        level_cols = st.columns(len(levels))
                        for col, (name, val) in zip(level_cols, levels.items()):
                            col.metric(str(name), _fmt_num(val))

                elif tool_key == "volatility_regime_analysis":
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("ATR %", _fmt_num(td.get("atr_pct"), 2))
                    c2.metric("Percentile", _fmt_num(td.get("percentile"), 1))
                    c3.metric("Regime", str(td.get("regime", "—")))
                    c4.metric("Annualized Vol", _fmt_num(td.get("annualized_volatility"), 1))

                elif tool_key == "mean_reversion_analysis":
                    z_scores = td.get("z_scores", {})
                    if z_scores:
                        cols = st.columns(len(z_scores))
                        for col, (period, val) in zip(cols, z_scores.items()):
                            col.metric(f"Z-Score {period}", _fmt_num(val, 2))
                    c1, c2 = st.columns(2)
                    c1.metric("Avg Z-Score", _fmt_num(td.get("avg_z_score"), 2))
                    c2.metric("Reversion Prob", _fmt_pct(td.get("reversion_probability")))

                elif tool_key == "momentum_rank_analysis":
                    returns = td.get("returns", {})
                    if returns:
                        cols = st.columns(len(returns))
                        for col, (period, val) in zip(cols, returns.items()):
                            col.metric(period, _fmt_pct(val))
                    c1, c2 = st.columns(2)
                    c1.metric("Weighted Return", _fmt_pct(td.get("weighted_return")))
                    c2.metric("Acceleration", _fmt_num(td.get("acceleration"), 3))

                elif tool_key == "support_resistance_analysis":
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Pivot", _fmt_num(td.get("pivot")))
                    c2.metric("Upside %", _fmt_num(td.get("upside_pct"), 1))
                    c3.metric("Risk/Reward", _fmt_num(td.get("risk_reward_ratio"), 2))
                    r_levels = td.get("resistance", {})
                    s_levels = td.get("support", {})
                    if r_levels or s_levels:
                        rc, sc = st.columns(2)
                        with rc:
                            st.markdown("**Resistance**")
                            for name, val in r_levels.items():
                                st.metric(str(name), _fmt_num(val))
                        with sc:
                            st.markdown("**Support**")
                            for name, val in s_levels.items():
                                st.metric(str(name), _fmt_num(val))

                elif tool_key == "correlation_regime_analysis":
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Avg Autocorrelation", _fmt_num(td.get("avg_autocorrelation"), 3))
                    c2.metric("Hurst Exponent", _fmt_num(td.get("hurst_exponent"), 3))
                    c3.metric("Regime", str(td.get("regime", "—")).title())

                _render_tool_explanation(tool_key)
                _render_ai_interpret_btn(selected, tool_key, llm_providers)

    with tab_risk:
        risk_tools = [
            ("risk_position_sizing", "Position Sizing"),
            ("kelly_criterion_analysis", "Kelly Criterion"),
            ("beta_correlation_analysis", "Beta / Correlation"),
            ("event_driven_analysis", "Event-Driven"),
        ]

        for tool_key, tool_label in risk_tools:
            td = tool_map.get(tool_key)
            if not td:
                continue
            tool_signal = td.get("signal", "neutral").upper()
            tool_score = td.get("score", 0)
            pill = _signal_pill_html(tool_signal)

            with st.expander(f"**{tool_label}** — {pill} ({tool_score:+.1f})", expanded=True):
                st.markdown(_score_bar_html(tool_score), unsafe_allow_html=True)
                st.caption(td.get("detail", ""))

                if tool_key == "risk_position_sizing":
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Entry Price", f"${td.get('entry_price', 0):.2f}")
                    c2.metric("Stop Loss", f"${td.get('stop_loss', 0):.2f}")
                    c3.metric("Take Profit", f"${td.get('take_profit', 0):.2f}")
                    c4.metric("Recommended Qty", str(td.get("recommended_qty", "—")))
                    c5, c6 = st.columns(2)
                    c5.metric("Position Value", _fmt_dollar(td.get("position_value")))
                    split = td.get("split_entry", [])
                    if split:
                        parts = []
                        for s in split:
                            if isinstance(s, (int, float)):
                                parts.append(f"${s:.2f}")
                            elif isinstance(s, dict):
                                parts.append(f"${s.get('price', 0):.2f} x{s.get('qty', '')}")
                            else:
                                parts.append(str(s))
                        c6.metric("Split Entries", ", ".join(parts))
                    warnings = td.get("warnings", [])
                    if warnings:
                        for w in warnings:
                            st.warning(w)

                elif tool_key == "kelly_criterion_analysis":
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Win Rate", _fmt_pct(td.get("win_rate")))
                    c2.metric("Kelly Full %", _fmt_num(td.get("kelly_full_pct"), 1))
                    c3.metric("Optimal Position %", _fmt_num(td.get("optimal_position_pct"), 1))
                    c4, c5, c6 = st.columns(3)
                    c4.metric("Avg Win %", _fmt_num(td.get("avg_win_pct"), 2))
                    c5.metric("Avg Loss %", _fmt_num(td.get("avg_loss_pct"), 2))
                    c6.metric("Sharpe Ratio", _fmt_num(td.get("sharpe_ratio"), 3))

                elif tool_key == "beta_correlation_analysis":
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Beta", _fmt_num(td.get("beta"), 3))
                    c2.metric("Beta 60d", _fmt_num(td.get("beta_60d"), 3))
                    c3.metric("Alpha (Annual %)", _fmt_num(td.get("alpha_annual_pct"), 2))
                    c4, c5, c6 = st.columns(3)
                    c4.metric("Correlation", _fmt_num(td.get("correlation"), 3))
                    c5.metric("R-Squared", _fmt_num(td.get("r_squared"), 3))
                    c6.metric("Info Ratio", _fmt_num(td.get("information_ratio"), 3))

                elif tool_key == "event_driven_analysis":
                    events = td.get("events", [])
                    c1, c2 = st.columns(2)
                    c1.metric("52W High", _fmt_num(td.get("52w_high")))
                    c2.metric("52W Low", _fmt_num(td.get("52w_low")))
                    rec = td.get("analyst_recommendation")
                    if rec:
                        st.metric("Analyst Recommendation", str(rec))
                    earnings = td.get("earnings_dates", [])
                    if earnings:
                        st.caption(f"Earnings: {', '.join(str(e)[:10] for e in earnings[:3])}")
                    if events:
                        for ev in events:
                            st.caption(f"Event: {ev}")

                _render_tool_explanation(tool_key)
                _render_ai_interpret_btn(selected, tool_key, llm_providers)

    with tab_fund:
        fund = detail.get("fundamentals", {})
        pcr = detail.get("options_pcr", {})
        insiders = detail.get("insider_trades", [])

        if fund:
            st.markdown("""
            <div class="section-header">
                <div class="section-title">Company Fundamentals</div>
            </div>
            """, unsafe_allow_html=True)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Market Cap", _fmt_dollar(fund.get("market_cap")))
            c2.metric("P/E (TTM)", _fmt_num(fund.get("pe_ratio"), 1))
            c3.metric("Forward P/E", _fmt_num(fund.get("forward_pe"), 1))
            c4.metric("PEG Ratio", _fmt_num(fund.get("peg_ratio"), 2))

            c5, c6, c7, c8 = st.columns(4)
            c5.metric("P/B", _fmt_num(fund.get("price_to_book"), 2))
            c6.metric("EPS", _fmt_num(fund.get("eps"), 2))
            c7.metric("Dividend Yield", _fmt_pct(fund.get("dividend_yield")))
            c8.metric("Beta", _fmt_num(fund.get("beta"), 2))

            c9, c10, c11, c12 = st.columns(4)
            c9.metric("Revenue Growth", _fmt_pct(fund.get("revenue_growth")))
            c10.metric("Profit Margin", _fmt_pct(fund.get("profit_margin")))
            c11.metric("D/E Ratio", _fmt_num(fund.get("debt_to_equity"), 1))
            c12.metric("Free Cash Flow", _fmt_dollar(fund.get("free_cash_flow")))

            c13, c14, c15, c16 = st.columns(4)
            c13.metric("52W High", _fmt_num(fund.get("52w_high")))
            c14.metric("52W Low", _fmt_num(fund.get("52w_low")))
            c15.metric("Avg Volume", _fmt_dollar(fund.get("avg_volume")))
            c16.metric("Short Ratio", _fmt_num(fund.get("short_ratio"), 2))

            sector = fund.get("sector", "")
            industry = fund.get("industry", "")
            if sector or industry:
                st.caption(f"{sector} / {industry}" if sector and industry else (sector or industry))

            st.markdown("""<div style="background:var(--surface-low);border-radius:8px;padding:12px 16px;margin:12px 0;border-left:3px solid var(--primary-ctr);">
<div style="font-size:0.75rem;font-weight:700;color:var(--primary);margin-bottom:6px;">펀더멘털 지표 해설</div>
<div style="font-size:0.7rem;color:var(--on-surface-variant);line-height:1.6;">
<b>P/E (TTM)</b> — 주가/주당순이익. 업종 평균 대비 높으면 고평가, 낮으면 저평가 가능성.<br>
<b>Forward P/E</b> — 향후 1년 예상 EPS 기준 P/E. TTM P/E보다 낮으면 이익 성장 기대.<br>
<b>PEG Ratio</b> — P/E / 이익성장률. 1 미만이면 성장 대비 저평가, 2 이상이면 고평가 주의.<br>
<b>P/B</b> — 주가/주당순자산. 1 미만이면 자산가치 대비 저평가. 기술주는 높은 경향.<br>
<b>D/E Ratio</b> — 부채/자본. 1 이상이면 레버리지 높음. 업종별 기준 상이.<br>
<b>Short Ratio</b> — 공매도 잔고/일평균거래량. 높으면 베어리시 심리, 숏스퀴즈 가능성.
</div></div>""", unsafe_allow_html=True)
        else:
            st.info("No fundamental data available for this ticker.")

        if pcr and pcr.get("put_call_ratio_oi") is not None:
            st.markdown("""
            <div class="section-header">
                <div class="section-title">Options Flow</div>
                <div class="section-subtitle">Put/Call Ratio</div>
            </div>
            """, unsafe_allow_html=True)

            c1, c2, c3 = st.columns(3)
            c1.metric("P/C Ratio (OI)", _fmt_num(pcr.get("put_call_ratio_oi"), 3))
            c2.metric("P/C Ratio (Vol)", _fmt_num(pcr.get("put_call_ratio_vol"), 3))
            c3.metric("Expiration", str(pcr.get("expiration", "—")))

            c4, c5, c6, c7 = st.columns(4)
            c4.metric("Call OI", f"{pcr.get('call_oi', 0):,}")
            c5.metric("Put OI", f"{pcr.get('put_oi', 0):,}")
            c6.metric("Call Volume", f"{pcr.get('call_volume', 0):,}")
            c7.metric("Put Volume", f"{pcr.get('put_volume', 0):,}")

            pcr_oi = pcr.get("put_call_ratio_oi", 0) or 0
            pcr_sentiment = "Bearish (High Put Activity)" if pcr_oi > 1.2 else ("Bullish (High Call Activity)" if pcr_oi < 0.7 else "Neutral")
            pcr_color = "#fd526f" if pcr_oi > 1.2 else ("#02d4a1" if pcr_oi < 0.7 else "var(--outline)")
            st.markdown(f'<div style="font-size:0.8rem;color:{pcr_color};font-weight:600;margin-top:4px;">Sentiment: {pcr_sentiment}</div>', unsafe_allow_html=True)

            st.markdown("""<div style="background:var(--surface-low);border-radius:8px;padding:12px 16px;margin:12px 0;border-left:3px solid var(--primary-ctr);">
<div style="font-size:0.75rem;font-weight:700;color:var(--primary);margin-bottom:6px;">옵션 PCR 해설</div>
<div style="font-size:0.7rem;color:var(--on-surface-variant);line-height:1.6;">
<b>P/C Ratio (OI)</b> — 풋 미결제약정 / 콜 미결제약정. 1.0 이상이면 풋 선호(약세 심리), 0.7 이하면 콜 선호(강세 심리).<br>
<b>P/C Ratio (Vol)</b> — 풋 거래량 / 콜 거래량. OI보다 단기 심리를 더 빠르게 반영.<br>
<b>역발상 활용</b> — 극단적으로 높은 PCR(>1.5)은 오히려 반등 신호일 수 있음 (센티먼트 극단).
</div></div>""", unsafe_allow_html=True)

        if insiders:
            st.markdown("""
            <div class="section-header">
                <div class="section-title">Insider Trades</div>
                <div class="section-subtitle">Recent insider activity</div>
            </div>
            """, unsafe_allow_html=True)

            insider_rows = []
            for trade in insiders:
                insider_rows.append({
                    "Date": str(trade.get("date", ""))[:10],
                    "Insider": trade.get("insider", ""),
                    "Relation": trade.get("relation", ""),
                    "Transaction": trade.get("transaction", ""),
                    "Shares": f"{trade.get('shares', 0):,}" if trade.get("shares") else "—",
                    "Value": _fmt_dollar(trade.get("value")) if trade.get("value") else "—",
                })
            st.dataframe(pd.DataFrame(insider_rows), use_container_width=True, hide_index=True)

            st.markdown("""<div style="background:var(--surface-low);border-radius:8px;padding:12px 16px;margin:12px 0;border-left:3px solid var(--primary-ctr);">
<div style="font-size:0.75rem;font-weight:700;color:var(--primary);margin-bottom:6px;">내부자 거래 해설</div>
<div style="font-size:0.7rem;color:var(--on-surface-variant);line-height:1.6;">
<b>내부자 매수</b> — 경영진/이사회가 자사주 매입. 회사 전망에 대한 자신감의 표현. 대량 매수 시 강한 긍정 신호.<br>
<b>내부자 매도</b> — 스톡옵션 행사 등 일상적 매도는 중립. 단, 대량/다수 동시 매도는 주의.
</div></div>""", unsafe_allow_html=True)

    with tab_llm:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">AI Deep Analysis</div>
            <div class="section-subtitle">LLM 기반 종합 분석 리포트 (GPT-4o / Gemini / Ollama)</div>
        </div>
        """, unsafe_allow_html=True)

        if not llm_providers:
            st.warning("LLM이 설정되지 않았습니다. `.env` 파일에 OPENAI_API_KEY 또는 GOOGLE_API_KEY를 추가하세요.")
        else:
            provider_opts = {p: provider_labels.get(p, p) for p in llm_providers}
            selected_provider = st.radio(
                "LLM Provider",
                options=list(provider_opts.keys()),
                format_func=lambda x: provider_opts[x],
                horizontal=True,
                label_visibility="collapsed",
            )

            full_report_key = f"full_report_{selected}_{selected_provider}"
            if st.button("종합 분석 리포트 생성", type="primary", use_container_width=True):
                with st.spinner(f"{provider_opts[selected_provider]}로 {selected} 종합 분석 중..."):
                    st.session_state[full_report_key] = engine_interpret_full_report(selected, selected_provider)

            if full_report_key in st.session_state:
                st.markdown(st.session_state[full_report_key])

        llm_orig = detail.get("llm_conclusion", "")
        if llm_orig and not llm_orig.startswith("[오류]") and not llm_orig.startswith("[LLM"):
            with st.expander("Scan-time LLM Summary (Original)", expanded=False):
                st.markdown(llm_orig)

        st.divider()
        st.markdown("""
        <div class="section-header">
            <div class="section-title">All Tool Scores</div>
        </div>
        """, unsafe_allow_html=True)

        summaries = detail.get("tool_summaries", [])
        if summaries:
            sorted_tools = sorted(summaries, key=lambda x: x.get("score", 0), reverse=True)
            names = [s.get("name", "?")[:20] for s in sorted_tools]
            scores = [s.get("score", 0) for s in sorted_tools]
            colors = ["#02d4a1" if s > 0 else "#fd526f" if s < 0 else "#8d909e" for s in scores]

            fig = go.Figure(go.Bar(
                x=scores, y=names, orientation='h',
                marker=dict(color=colors),
                text=[f"{s:+.1f}" for s in scores],
                textposition='outside',
                textfont=dict(family="JetBrains Mono", size=11, color="#c3c6d4"),
            ))
            fig.update_layout(**_plotly_base_layout(
                height=max(350, len(names) * 32),
                xaxis=dict(range=[-10, 10], gridcolor="rgba(66,71,82,0.12)", zerolinecolor="rgba(141,144,158,0.3)"),
                yaxis=dict(autorange="reversed"),
                margin=dict(l=160, r=50, t=10, b=10),
            ))
            st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════
#  라우팅
# ═══════════════════════════════════════════════════════════════

if page == "Home":
    render_home()
elif page == "Dashboard":
    render_dashboard()
elif page == "Report":
    render_report()
elif page == "Detail":
    render_detail()
elif page == "Backtest":
    render_backtest()
elif page == "ML Predict":
    render_ml_predict()
elif page == "Portfolio":
    render_portfolio()
elif page == "Ranking":
    render_ranking()
elif page == "Paper Trade":
    render_paper_trade()
elif page == "History":
    render_history()
