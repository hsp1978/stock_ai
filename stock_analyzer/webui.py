#!/usr/bin/env python3
"""
주식 분석 시스템 WebUI (Streamlit)
Mac Studio 에이전트 API 연동 + 전체 리포트 대시보드

실행:
    streamlit run webui.py --server.port 8501
"""
import json
import os
import sys
from datetime import datetime

import httpx
import yfinance as yf
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import load_dotenv

load_dotenv()

# ── local_engine 연결 (직접 import 우선, HTTP fallback) ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from local_engine import (
        engine_dispatch_get, engine_dispatch_post, engine_get_chart_path,
    )
    _USE_LOCAL_ENGINE = True
except ImportError:
    _USE_LOCAL_ENGINE = False

AGENT_API_URL = os.getenv("AGENT_API_URL", "http://100.108.11.20:8100")
WATCHLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.txt")

st.set_page_config(
    page_title="Stock AI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
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


def api_get(path: str, timeout: int = 10):
    if _USE_LOCAL_ENGINE:
        return engine_dispatch_get(path)
    try:
        resp = httpx.get(f"{AGENT_API_URL}{path}", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except Exception as e:
        st.error(f"API Error: {e}")
        return None


def api_post(path: str, timeout: int = 300):
    if _USE_LOCAL_ENGINE:
        return engine_dispatch_post(path)
    try:
        resp = httpx.post(f"{AGENT_API_URL}{path}", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except Exception as e:
        st.error(f"API Error: {e}")
        return None


def get_chart_url(ticker: str) -> str:
    """local_engine 모드: 파일 경로 반환 / HTTP 모드: URL 반환"""
    if _USE_LOCAL_ENGINE:
        return engine_get_chart_path(ticker) or ""
    return f"{AGENT_API_URL}/chart/{ticker}"


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
#  사이드바
# ═══════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown('<div class="sidebar-brand">Stock AI</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">Precision Terminal</div>', unsafe_allow_html=True)

    health = api_get("/health")
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
        st.error(f"Agent Offline: {AGENT_API_URL}")

    info = api_get("/")
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
                    result = api_post(f"/scan/{resolved}")
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
            tickers_param = ",".join(wl)
            with st.spinner(f"Scanning {len(wl)} tickers..."):
                result = api_post(f"/scan?tickers={tickers_param}", timeout=600)
                if result:
                    st.success(f"Done! {len(wl)} tickers scanned.")
            st.rerun()
        else:
            st.warning("Watchlist is empty")

    st.divider()

    st.markdown('<div class="sidebar-section-label">Agent Control</div>', unsafe_allow_html=True)
    if st.button("Restart Agent", use_container_width=True, type="secondary"):
        with st.spinner("Restarting agent service..."):
            resp = api_post("/restart", timeout=5)
            if resp and resp.get("status") == "restarting":
                st.success("Agent restarting...")
                import time as _time
                _time.sleep(3)
                st.rerun()
            else:
                st.error("Restart failed. Agent may be offline.")

    st.divider()

    page = st.radio("Navigation", ["Home", "Dashboard", "Detail", "Scan Log", "Backtest", "ML Predict", "Portfolio", "Ranking", "Paper Trade", "History"], label_visibility="collapsed")


# ═══════════════════════════════════════════════════════════════
#  홈 페이지
# ═══════════════════════════════════════════════════════════════

def render_home():
    render_market_ticker_bar()

    data = api_get("/results")
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

    health = api_get("/health")
    info = api_get("/")
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

    data = api_get("/results")
    if not data or not data.get("results"):
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">⚡</div>
            <div class="es-text">No analysis results yet. Run a scan from the sidebar.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    results = data["results"]
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

    data = api_get("/results")
    if not data or not data.get("results"):
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">🔍</div>
            <div class="es-text">No analysis results available.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    tickers = sorted(data["results"].keys())
    selected = st.selectbox("Select Ticker", tickers, label_visibility="collapsed")
    if not selected:
        return

    detail = api_get(f"/results/{selected}")
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
    chart_ref = get_chart_url(selected)
    if _USE_LOCAL_ENGINE:
        if chart_ref and os.path.exists(chart_ref):
            st.image(chart_ref, use_container_width=True)
        else:
            st.caption("No chart image available")
    else:
        try:
            resp = httpx.get(chart_ref, timeout=5)
            if resp.status_code == 200:
                st.image(resp.content, use_container_width=True)
            else:
                st.caption("No chart image available")
        except Exception:
            st.caption("Chart load failed")

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

    data = api_get("/history?limit=20")
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

    data = api_get("/results")
    results = data.get("results", {}) if data else {}
    if not results:
        st.info("No analysis results. Run a scan first.")
        return

    ticker = st.selectbox("Select Ticker", sorted(results.keys()))
    if st.button("Run Backtest", type="primary"):
        with st.spinner(f"Backtesting {ticker}..."):
            bt = api_get(f"/backtest/{ticker}", timeout=60)
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

    data = api_get("/results")
    results = data.get("results", {}) if data else {}
    tickers = sorted(results.keys()) if results else load_watchlist()
    if not tickers:
        st.info("No tickers available.")
        return

    ticker = st.selectbox("Select Ticker", tickers, key="ml_ticker")
    if st.button("Run ML Prediction", type="primary"):
        with st.spinner(f"Training model for {ticker}..."):
            ml = api_get(f"/ml/{ticker}", timeout=120)
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

    data = api_get("/results")
    results = data.get("results", {}) if data else {}
    if len(results) < 2:
        st.info("Need at least 2 analyzed tickers for portfolio optimization.")
        return

    tab1, tab2 = st.tabs(["Optimization", "Correlation / Beta"])

    with tab1:
        method = st.selectbox("Method", ["markowitz", "risk_parity"])
        if st.button("Optimize Portfolio", type="primary"):
            with st.spinner("Optimizing..."):
                opt = api_get(f"/portfolio/optimize?method={method}", timeout=60)
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
                corr = api_get("/portfolio/correlation", timeout=60)
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

    ranking_data = api_get("/ranking")
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

    status = api_get("/paper")
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
                result = api_post("/paper/auto", timeout=60)
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
                result = api_post(
                    f"/paper/order?ticker={order_ticker.upper()}&action={order_action}&qty={order_qty}&price={order_price}",
                    timeout=10,
                )
                if result:
                    if result.get("status") == "filled":
                        st.success(f"Order filled: {order_action} {order_qty} {order_ticker.upper()} @ ${order_price}")
                    else:
                        st.warning(f"Order {result.get('status')}: {result.get('reject_reason', '')}")

    st.divider()
    if st.button("Reset Paper Trading", type="secondary"):
        result = api_post("/paper/reset", timeout=5)
        if result:
            st.success("Paper trading reset")
            st.rerun()


# ═══════════════════════════════════════════════════════════════
#  스캔 로그 (DB) 페이지
# ═══════════════════════════════════════════════════════════════

def render_scan_log():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Scan Log</div>
        <div class="page-subtitle">Persistent scan result database &amp; analytics</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 통계 요약 ──
    scan_data = api_get("/scan-log?limit=50")
    if not scan_data or scan_data.get("total", 0) == 0:
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">📊</div>
            <div class="es-text">No scan logs yet. Run a scan to start building history.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    total_scans = scan_data.get("total", 0)
    logs = scan_data.get("logs", [])

    # 카드 집계
    buy_cnt = sum(1 for l in logs if l.get("signal") == "BUY")
    sell_cnt = sum(1 for l in logs if l.get("signal") == "SELL")
    hold_cnt = sum(1 for l in logs if l.get("signal") == "HOLD")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Scans", str(total_scans))
    m2.metric("Buy (recent)", str(buy_cnt))
    m3.metric("Sell (recent)", str(sell_cnt))
    m4.metric("Hold (recent)", str(hold_cnt))

    # ── 탭 구성 ──
    tab_overview, tab_weekly, tab_search, tab_ticker = st.tabs(
        ["Overview", "Weekly Summary", "Search / Range", "Ticker History"]
    )

    # ── Overview 탭 ──
    with tab_overview:
        # 최근 스캔 라운드
        latest = api_get("/scan-log/latest")
        latest_logs = latest.get("logs", []) if latest else []
        if latest_logs:
            st.markdown("""
            <div class="section-header">
                <div class="section-title">Latest Scan Round</div>
            </div>
            """, unsafe_allow_html=True)
            lt_rows = []
            for r in latest_logs:
                lt_rows.append({
                    "Ticker": r.get("ticker", "?"),
                    "Signal": r.get("signal", "?"),
                    "Score": r.get("score", 0),
                    "Confidence": r.get("confidence", 0),
                    "Alert": "Yes" if r.get("alert_sent") else "",
                    "Time": str(r.get("scanned_at", ""))[:19].replace("T", " "),
                })
            lt_df = pd.DataFrame(lt_rows)
            st.dataframe(
                lt_df.style.map(
                    lambda v: "color: #02d4a1" if v == "BUY" else ("color: #fd526f" if v == "SELL" else "color: #ffb347"),
                    subset=["Signal"],
                ),
                use_container_width=True, hide_index=True,
            )

        # 전체 최근 로그 테이블
        if logs:
            st.markdown("""
            <div class="section-header">
                <div class="section-title">Recent Scans</div>
                <div class="section-subtitle">LAST 50</div>
            </div>
            """, unsafe_allow_html=True)
            rc_rows = []
            for r in logs:
                rc_rows.append({
                    "ID": r.get("id", 0),
                    "Time": str(r.get("scanned_at", ""))[:19].replace("T", " "),
                    "Ticker": r.get("ticker", "?"),
                    "Signal": r.get("signal", "?"),
                    "Score": r.get("score", 0),
                    "Confidence": r.get("confidence", 0),
                    "BUY": r.get("buy_count", 0),
                    "SELL": r.get("sell_count", 0),
                    "HOLD": r.get("neutral_count", 0),
                })
            rc_df = pd.DataFrame(rc_rows)
            st.dataframe(
                rc_df.style.map(
                    lambda v: "color: #02d4a1" if v == "BUY" else ("color: #fd526f" if v == "SELL" else "color: #ffb347"),
                    subset=["Signal"],
                ),
                use_container_width=True, hide_index=True,
            )

    # ── Weekly Summary 탭 ──
    with tab_weekly:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">Weekly Summary</div>
            <div class="section-subtitle">WEEKLY REPORT</div>
        </div>
        """, unsafe_allow_html=True)

        wt_weeks_ago = st.slider("Weeks Ago (0=this week)", 0, 8, 0, key="wt_weeks_ago")
        weekly_data = api_get(f"/weekly?weeks_ago={wt_weeks_ago}")

        if not weekly_data or weekly_data.get("total_scans", 0) == 0:
            st.info("No scan data for this week.")
        else:
            w1, w2, w3, w4 = st.columns(4)
            w1.metric("Period", f"{weekly_data.get('week_start','')} ~ {weekly_data.get('week_end','')}")
            w2.metric("Total Scans", str(weekly_data.get("total_scans", 0)))
            w3.metric("Alerts", str(weekly_data.get("alert_count", 0)))
            sig_dist = weekly_data.get("signal_distribution", {})
            w4.metric("Signal Ratio", f"B:{sig_dist.get('BUY',0)} S:{sig_dist.get('SELL',0)} H:{sig_dist.get('HOLD',0)}")

            # 종목별 요약 테이블
            tickers_data = weekly_data.get("tickers", [])
            if tickers_data:
                st.markdown("""
                <div class="section-header">
                    <div class="section-title">Per-Ticker Summary</div>
                </div>
                """, unsafe_allow_html=True)
                wt_rows = []
                for t in tickers_data:
                    wt_rows.append({
                        "Ticker": t.get("ticker", "?"),
                        "Scans": t.get("scan_count", 0),
                        "Avg Score": t.get("avg_score", 0),
                        "Avg Conf": t.get("avg_confidence", 0),
                        "BUY": t.get("buy_cnt", 0),
                        "SELL": t.get("sell_cnt", 0),
                        "HOLD": t.get("hold_cnt", 0),
                        "Alerts": t.get("alerts", 0),
                    })
                wt_df = pd.DataFrame(wt_rows)
                st.dataframe(wt_df, use_container_width=True, hide_index=True)

            # Top BUY / Top SELL
            col_buy, col_sell = st.columns(2)
            with col_buy:
                top_buy = weekly_data.get("top_buy", [])
                if top_buy:
                    st.markdown("**Top BUY Signals**")
                    for b in top_buy:
                        st.markdown(f'`{b.get("ticker","?")}` score: **{b.get("best_score",0):+.2f}**')
            with col_sell:
                top_sell = weekly_data.get("top_sell", [])
                if top_sell:
                    st.markdown("**Top SELL Signals**")
                    for s in top_sell:
                        st.markdown(f'`{s.get("ticker","?")}` score: **{s.get("worst_score",0):+.2f}**')

            # 종목별 주간 상세
            st.divider()
            wt_tickers_list = [t.get("ticker", "?") for t in tickers_data] if tickers_data else load_watchlist()
            wt_sel = st.selectbox("Ticker Detail", wt_tickers_list, key="wt_ticker_detail")
            if wt_sel:
                ticker_weekly = api_get(f"/weekly/{wt_sel}?weeks_ago={wt_weeks_ago}")
                if ticker_weekly and ticker_weekly.get("stats", {}).get("scan_count", 0) > 0:
                    tw_stats = ticker_weekly["stats"]
                    tw1, tw2, tw3, tw4 = st.columns(4)
                    tw1.metric("Scans", str(tw_stats.get("scan_count", 0)))
                    tw2.metric("Avg Score", f"{tw_stats.get('avg_score', 0):+.2f}")
                    tw3.metric("Min/Max", f"{tw_stats.get('min_score', 0):+.2f} / {tw_stats.get('max_score', 0):+.2f}")
                    tw4.metric("Alerts", str(tw_stats.get("alert_count", 0)))

                    daily_trend = ticker_weekly.get("daily_trend", [])
                    if daily_trend:
                        dt_df = pd.DataFrame(daily_trend)
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=dt_df["day"], y=dt_df["avg_score"],
                            mode="lines+markers",
                            name="Avg Score",
                            line=dict(color="#5d8ef1", width=3),
                            marker=dict(size=10, color="#5d8ef1"),
                        ))
                        fig.add_hline(y=0, line_color="rgba(66,71,82,0.3)", line_width=1)
                        fig.update_layout(**_plotly_base_layout(
                            height=280,
                            margin=dict(l=40, r=10, t=10, b=40),
                            xaxis=dict(gridcolor="rgba(66,71,82,0.12)"),
                            yaxis=dict(title="Score", gridcolor="rgba(66,71,82,0.12)"),
                        ))
                        st.plotly_chart(fig, use_container_width=True)

    # ── Search / Range 탭 ──
    with tab_search:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">Search by Date Range</div>
        </div>
        """, unsafe_allow_html=True)

        fc1, fc2 = st.columns(2)
        search_start = fc1.text_input("Start (YYYY-MM-DD)", placeholder="2026-04-07", key="sl_search_start")
        search_end = fc2.text_input("End (YYYY-MM-DD)", placeholder="2026-04-13", key="sl_search_end")

        if st.button("Search Range", type="primary", key="sl_search_btn"):
            if search_start and search_end:
                with st.spinner("Searching..."):
                    result = api_get(f"/scan-log/range?start={search_start.strip()}&end={search_end.strip()}")

                if not result:
                    st.error("Query failed")
                elif result.get("count", 0) == 0:
                    st.info("No records in this date range.")
                else:
                    st.caption(f"Found {result['count']} records")
                    rows = result.get("logs", [])
                    if rows:
                        sr_rows = []
                        for r in rows:
                            sr_rows.append({
                                "ID": r.get("id", 0),
                                "Time": str(r.get("scanned_at", ""))[:19].replace("T", " "),
                                "Ticker": r.get("ticker", "?"),
                                "Signal": r.get("signal", "?"),
                                "Score": r.get("score", 0),
                                "Confidence": r.get("confidence", 0),
                            })
                        sr_df = pd.DataFrame(sr_rows)
                        st.dataframe(
                            sr_df.style.map(
                                lambda v: "color: #02d4a1" if v == "BUY" else ("color: #fd526f" if v == "SELL" else "color: #ffb347"),
                                subset=["Signal"],
                            ),
                            use_container_width=True, hide_index=True,
                        )
            else:
                st.warning("Start and End dates are required.")

    # ── Ticker History 탭 ──
    with tab_ticker:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">Ticker Scan History</div>
        </div>
        """, unsafe_allow_html=True)

        # 종목 선택
        all_tickers = load_watchlist()
        if not all_tickers:
            st.info("No ticker data available.")
        else:
            sel_ticker = st.selectbox("Select Ticker", all_tickers, key="sl_ticker_hist")
            if sel_ticker:
                hist_data = api_get(f"/scan-log/{sel_ticker}?limit=50")
                history = hist_data.get("logs", []) if hist_data else []

                if not history:
                    st.info(f"No scan history for {sel_ticker}")
                else:
                    st.caption(f"{hist_data.get('total', len(history))} total records for {sel_ticker} (showing last 50)")

                    # 점수 시계열 차트
                    h_df = pd.DataFrame(history)
                    h_df["scanned_at"] = pd.to_datetime(h_df["scanned_at"])
                    h_df = h_df.sort_values("scanned_at")

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=h_df["scanned_at"], y=h_df["score"],
                        mode="lines+markers",
                        line=dict(color="#5d8ef1", width=2),
                        marker=dict(
                            size=8,
                            color=[
                                "#02d4a1" if s == "BUY" else "#fd526f" if s == "SELL" else "#ffb347"
                                for s in h_df["signal"]
                            ],
                            line=dict(width=1, color="#0b0e14"),
                        ),
                        text=[f"{s} ({sc:+.1f})" for s, sc in zip(h_df["signal"], h_df["score"])],
                        hovertemplate="%{text}<br>%{x}<extra></extra>",
                    ))
                    fig.add_hline(y=0, line_color="rgba(66,71,82,0.3)", line_width=1)
                    fig.update_layout(**_plotly_base_layout(
                        height=300,
                        margin=dict(l=50, r=10, t=10, b=40),
                        xaxis=dict(gridcolor="rgba(66,71,82,0.12)"),
                        yaxis=dict(title="Score", gridcolor="rgba(66,71,82,0.12)"),
                    ))
                    st.plotly_chart(fig, use_container_width=True)

                    # 이력 테이블
                    th_rows = []
                    for r in history:
                        th_rows.append({
                            "ID": r.get("id", 0),
                            "Time": str(r.get("scanned_at", ""))[:19].replace("T", " "),
                            "Signal": r.get("signal", "?"),
                            "Score": r.get("score", 0),
                            "Confidence": r.get("confidence", 0),
                            "BUY": r.get("buy_count", 0),
                            "SELL": r.get("sell_count", 0),
                            "HOLD": r.get("neutral_count", 0),
                            "Alert": "Yes" if r.get("alert_sent") else "",
                        })
                    th_df = pd.DataFrame(th_rows)
                    st.dataframe(
                        th_df.style.map(
                            lambda v: "color: #02d4a1" if v == "BUY" else ("color: #fd526f" if v == "SELL" else "color: #ffb347"),
                            subset=["Signal"],
                        ),
                        use_container_width=True, hide_index=True,
                    )


# ═══════════════════════════════════════════════════════════════
#  라우팅
# ═══════════════════════════════════════════════════════════════

if page == "Home":
    render_home()
elif page == "Dashboard":
    render_dashboard()
elif page == "Detail":
    render_detail()
elif page == "Scan Log":
    render_scan_log()
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
