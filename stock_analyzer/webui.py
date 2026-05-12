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
from typing import Dict, Tuple

import httpx
import yfinance as yf
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import load_dotenv

# ── 프로젝트 경로 설정 ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)

# 루트 .env를 먼저 로드 (통합 설정 SSOT), 로컬 stock_analyzer/.env로 덮어쓰기 허용
_root_env = os.path.join(_PROJECT_ROOT, ".env")
if os.path.exists(_root_env):
    load_dotenv(_root_env)
load_dotenv()
_SERVICE_DIR = os.path.join(_PROJECT_ROOT, 'chart_agent_service')

if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

# ── config 모듈에서 API 설정 가져오기 ──
try:
    from chart_agent_service.config import AGENT_API_HOST, AGENT_API_PORT
except ImportError:
    # fallback to default values
    AGENT_API_HOST = os.getenv("AGENT_API_HOST", "localhost")
    AGENT_API_PORT = int(os.getenv("AGENT_API_PORT", "8100"))

# ── local_engine 연결 (직접 import 우선, HTTP fallback) ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from local_engine import (
        engine_dispatch_get, engine_dispatch_post, engine_get_chart_path,
    )
    _USE_LOCAL_ENGINE = True
except ImportError:
    _USE_LOCAL_ENGINE = False

# ── 한국 주식 모듈 import ──
try:
    from korean_stocks import KoreanStockData, get_market_indices as get_kr_indices
    from ticker_manager import TickerManager, normalize_ticker, detect_market, get_stock_info, format_price
    _KOREAN_STOCKS_AVAILABLE = True
except ImportError:
    _KOREAN_STOCKS_AVAILABLE = False
    print("[WARNING] Korean stocks module not available")

AGENT_API_URL = os.getenv("AGENT_API_URL", f"http://{AGENT_API_HOST}:{AGENT_API_PORT}")
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

    # 한글이 포함된 경우 ticker_suggestion 먼저 시도 (한국 주식 우선)
    if any(ord(char) >= 0xAC00 and ord(char) <= 0xD7A3 for char in text):
        try:
            from ticker_suggestion import suggest_ticker
            result = suggest_ticker(text)

            if result['found'] and result['best_match']:
                # 95% 이상 매치로 자동 선택
                ticker = result['best_match']
                name = result['suggestions'][0].get('name', text) if result['suggestions'] else text
                return ticker, f"{text} → {ticker} ({name})"
            elif result['found'] and result['suggestions']:
                # 첫 번째 제안 사용
                ticker = result['suggestions'][0]['ticker']
                name = result['suggestions'][0].get('name', text)
                return ticker, f"{text} → {ticker} ({name})"
        except Exception as e:
            print(f"ticker_suggestion 오류: {e}")

    # 기존 미국 주식 한글 매핑 확인
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

    # yfinance 검색 (미국 주식 위주)
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
    # /ml/* 는 LSTM(TF) 풀스택이 webui 컨테이너에 없으므로 agent-api(GPU TF)로
    # 강제 HTTP. 다른 path 는 in-process 우선(_USE_LOCAL_ENGINE).
    if _USE_LOCAL_ENGINE and not path.startswith("/ml/"):
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


def api_post(path: str, timeout: int = 300, json_body: dict = None):
    """API POST. json_body가 주어지면 FastAPI body 파라미터로 전달."""
    if _USE_LOCAL_ENGINE:
        return engine_dispatch_post(path)
    try:
        if json_body is not None:
            resp = httpx.post(f"{AGENT_API_URL}{path}", json=json_body, timeout=timeout)
        else:
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


def export_comprehensive_data(ticker: str, include_multi_agent: bool = True) -> dict:
    """
    종목의 모든 분석 데이터를 수집하여 export용 dict 반환
    - Single LLM (V1.0) 결과
    - Multi-Agent (V2.0) 결과
    - 백테스트 결과
    - ML 예측 결과
    """
    export_data = {
        "ticker": ticker,
        "export_timestamp": datetime.now().isoformat(),
        "version": "2.0"
    }

    # 1. Single LLM 분석 결과
    single_result = api_get(f"/results/{ticker}")
    if single_result:
        export_data["single_llm_analysis"] = {
            "final_signal": single_result.get("final_signal"),
            "composite_score": single_result.get("composite_score"),
            "confidence": single_result.get("confidence"),
            "signal_distribution": single_result.get("signal_distribution"),
            "tool_summaries": single_result.get("tool_summaries", []),
            "tool_details": single_result.get("tool_details", []),
            "llm_conclusion": single_result.get("llm_conclusion"),
            "analyzed_at": single_result.get("analyzed_at")
        }

    # 2. Multi-Agent 분석 결과 (옵션)
    if include_multi_agent:
        # 8개 에이전트 병렬 LLM 호출. 백엔드 MULTI_AGENT_TIMEOUT(기본 600s)보다 약간 더 길게.
        multi_result = api_get(f"/multi-agent/{ticker}", timeout=660)
        if multi_result and not multi_result.get("error"):
            export_data["multi_agent_analysis"] = {
                "ticker": multi_result.get("ticker"),
                "multi_agent_mode": multi_result.get("multi_agent_mode"),
                "agent_results": multi_result.get("agent_results", []),
                "final_decision": multi_result.get("final_decision"),
                "total_execution_time": multi_result.get("total_execution_time"),
                "timestamp": multi_result.get("timestamp")
            }

    # 3. 백테스트 결과
    backtest_result = api_get(f"/backtest/{ticker}")
    if backtest_result:
        export_data["backtest"] = backtest_result

    # 4. ML 예측 결과
    ml_result = api_get(f"/ml/{ticker}")
    if ml_result:
        export_data["ml_prediction"] = ml_result

    # 5. 펀더멘털 데이터
    if single_result:
        export_data["fundamentals"] = single_result.get("fundamentals", {})
        export_data["options_pcr"] = single_result.get("options_pcr", {})
        export_data["insider_trades"] = single_result.get("insider_trades", [])

    return export_data


import re as _re_market

# 한국 주식 코드 패턴: 6자리 숫자 (예: 072130) 또는 4자리숫자+알파벳+숫자 (예: 0126Z0)
_KR_CODE_PATTERN = _re_market.compile(r'^(?:\d{6}|\d{4}[A-Z]\d)$')


def _is_korean_ticker(ticker: str) -> bool:
    """
    한국 주식 판별. .KS/.KQ 접미사 또는 코드 패턴 기반.

    유엔젤(072130.KQ) 같은 종목을 접미사 없이 072130으로 저장해도
    정확하게 한국 주식으로 인식합니다.
    """
    if not ticker:
        return False
    t = ticker.upper().strip()
    if t.endswith(".KS") or t.endswith(".KQ"):
        # 접미사 제거 후 패턴 검사 (예: 072130.KQ → 072130)
        code = t[:-3]
        return bool(_KR_CODE_PATTERN.match(code))
    return bool(_KR_CODE_PATTERN.match(t))


def _confidence_label(signal: str) -> str:
    """
    신호 종류에 따라 적절한 신뢰도 라벨 반환.

    - BUY/SELL → "신뢰도" (방향 확신도)
    - HOLD/NEUTRAL → "관망 확신도" (중립 확신도)

    '신뢰도 5.9로 HOLD'처럼 방향 신호처럼 오해되는 ambiguity 제거.
    """
    s = (signal or "").upper()
    if s in ("HOLD", "NEUTRAL"):
        return "관망 확신도"
    return "신뢰도"


def _render_confidence_gap_warning(single: dict, final_decision: dict):
    """
    Single LLM과 Multi-Agent 신뢰도 갭이 크면 해설 배너 표시.

    갭 ≥ 2.0이면 "왜 차이나는지" 사용자에게 명시.
    """
    if not single or not final_decision:
        return

    single_sig = (single.get("final_signal") or "").upper()
    single_conf = float(single.get("confidence") or 0)
    multi_sig = (final_decision.get("final_signal") or "").upper()
    multi_conf = float(final_decision.get("final_confidence") or 0)

    gap = abs(single_conf - multi_conf)
    if gap < 2.0:
        return

    # 신호도 다른 경우 추가 강조
    same_signal = single_sig == multi_sig or (
        single_sig in ("HOLD", "NEUTRAL") and multi_sig in ("HOLD", "NEUTRAL")
    )

    msg_parts = []
    msg_parts.append(
        f"**Single LLM {single_conf:.1f}/10** vs **Multi-Agent {multi_conf:.1f}/10** "
        f"— 신뢰도 갭 **{gap:.1f}** 감지"
    )
    msg_parts.append("")
    if single_sig == multi_sig:
        msg_parts.append(f"두 시스템 모두 **{single_sig}** 방향성에 동의하나 확신도 다름:")
    else:
        msg_parts.append(f"신호도 차이: Single **{single_sig}** vs Multi **{multi_sig}**")
    msg_parts.append("")
    msg_parts.append("**원인**")
    msg_parts.append("- **Single LLM**: 16+개 도구 점수를 LLM이 자체 통합 → 종합 점수 기반 판단")
    msg_parts.append("- **Multi-Agent**: 7명 전문가가 각자 분석 → Decision Maker가 합의/충돌 평가 후 종합")
    msg_parts.append("- 전문가 의견이 엇갈릴수록 Multi-Agent 신뢰도가 낮게 나오는 구조 (보수적)")
    msg_parts.append("")
    msg_parts.append("**권장 해석**")
    if not same_signal:
        msg_parts.append("- ⚠️ 신호도 다르므로 **매매 보류 권장**")
    elif multi_conf < 3.0:
        msg_parts.append("- ⚠️ Multi-Agent 확신도가 매우 낮음 → **전문가 의견 불일치**, 추가 관찰 권장")
    else:
        msg_parts.append("- ℹ️ 방향은 일치. Single LLM 점수의 강도 참고")

    st.warning("\n".join(msg_parts))


def _market_flag(ticker: str) -> str:
    """티커에서 시장 플래그 반환 (🇰🇷 / 🇺🇸)."""
    return "🇰🇷" if _is_korean_ticker(ticker) else "🇺🇸"


# 주요 한국 종목 이름 폴백 맵 (pykrx/FDR 미설치 환경에서 기본 제공)
# yfinance는 영문명을 주거나 깨진 응답을 주는 경우가 많아 한글명 보장용
_KR_TICKER_NAME_FALLBACK = {
    "005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER",
    "035720": "카카오", "051910": "LG화학", "006400": "삼성SDI",
    "005380": "현대차", "207940": "삼성바이오로직스", "000270": "기아",
    "068270": "셀트리온", "136480": "하림", "003380": "하림지주",
    "012330": "현대모비스", "066570": "LG전자", "033780": "KT&G",
    "015760": "한국전력", "105560": "KB금융", "055550": "신한지주",
    "086790": "하나금융지주", "096770": "SK이노베이션", "034730": "SK",
    "032830": "삼성생명", "017670": "SK텔레콤", "030200": "KT",
    "138040": "메리츠금융지주", "251270": "넷마블", "259960": "크래프톤",
    "018260": "삼성에스디에스", "006800": "미래에셋증권", "028260": "삼성물산",
    "010130": "고려아연", "011200": "HMM", "009150": "삼성전기",
    "267250": "HD현대중공업", "010950": "S-Oil", "161890": "한국콜마",
    "047050": "포스코인터내셔널", "028050": "삼성E&A", "036570": "엔씨소프트",
    "352820": "하이브", "0126Z0": "삼성에피스홀딩스",
}


@st.cache_data(ttl=3600, show_spinner=False)
def get_ticker_display_name(ticker: str) -> str:
    """
    티커 → 종목명 변환. 실패 시 티커 그대로 반환.

    다중 소스 폴백:
    1. 한국 주식: pykrx → FinanceDataReader → 내장 맵 → yfinance
    2. 미국 주식: yfinance shortName/longName
    3. 실패 시: 티커 원본

    1시간 세션 캐시로 반복 호출 최소화.
    """
    if not ticker:
        return ""
    t = ticker.upper().strip()

    # 한국 주식: 종목코드 추출
    code = None
    if _is_korean_ticker(t):
        if t.endswith(".KS") or t.endswith(".KQ"):
            code = t[:-3]
        else:
            code = t

    # ─── 한국 주식: korean_stocks_database.json 최우선 확인 ───
    if code:
        try:
            import os
            import json
            db_file = os.path.join(os.path.dirname(__file__), 'korean_stocks_database.json')
            if os.path.exists(db_file):
                with open(db_file, 'r', encoding='utf-8') as f:
                    db_data = json.load(f)
                    stocks = db_data.get('stocks', {})
                    if code in stocks:
                        return stocks[code]['name']
        except Exception:
            pass

        # ─── 한국 주식: ticker_suggestion 모듈 시도 ───
        try:
            from ticker_suggestion import suggest_ticker
            result = suggest_ticker(code, max_results=1)
            if result['found'] and result['suggestions']:
                suggestion = result['suggestions'][0]
                if suggestion['score'] >= 0.95:  # 95% 이상 매치만 신뢰
                    return suggestion['name']
        except Exception:
            pass

        # ─── 한국 주식: pykrx 시도 (빠르고 정확) ───
        try:
            from pykrx import stock as _krx
            name = _krx.get_market_ticker_name(code)
            if name and name.strip() and name != code:
                return name.strip()
        except Exception:
            pass

        # ─── 한국 주식: FinanceDataReader ───
        try:
            import FinanceDataReader as _fdr
            krx_list = _fdr.StockListing('KRX')
            # Symbol 또는 Code 컬럼
            sym_col = 'Symbol' if 'Symbol' in krx_list.columns else (
                'Code' if 'Code' in krx_list.columns else None
            )
            if sym_col:
                match = krx_list[krx_list[sym_col].astype(str) == code]
                name_col = None
                for col in ('Name', '종목명', 'CompanyName'):
                    if col in krx_list.columns:
                        name_col = col
                        break
                if not match.empty and name_col:
                    name = str(match.iloc[0][name_col]).strip()
                    if name and name != code:
                        return name
        except Exception:
            pass

        # ─── 한국 주식: 내장 fallback 맵 (pykrx/FDR 미설치 환경 대비) ───
        if code in _KR_TICKER_NAME_FALLBACK:
            return _KR_TICKER_NAME_FALLBACK[code]

        # ─── 한국 주식: korean_stocks 모듈 시도 ───
        if _KOREAN_STOCKS_AVAILABLE:
            try:
                collector = KoreanStockData()
                name = collector.get_stock_name(t)
                # yfinance가 깨진 응답을 줄 수 있음 — 티커 포함이면 거부
                if name and name != code and not _looks_broken_name(name, t, code):
                    return name
            except Exception:
                pass

    # ─── 미국 주식 / 폴백: yfinance ───
    try:
        import yfinance as yf
        info = yf.Ticker(t).info or {}
        # shortName이 longName보다 더 짧고 깔끔한 경우가 많음
        for key in ('shortName', 'longName'):
            name = info.get(key)
            if name and not _looks_broken_name(str(name), t, code):
                return str(name).strip()
    except Exception:
        pass

    # 모두 실패: 티커 그대로
    return t


def _looks_broken_name(name: str, ticker: str, code: str = None) -> bool:
    """yfinance가 돌려주는 깨진 응답 감지.

    예: "136480.KS,0P0000T1HA,516440" 같은 ticker/ID 나열 형태.
    """
    if not name:
        return True
    name_s = name.strip()
    # 티커나 코드가 이름에 포함되면 깨진 응답 의심
    if ticker and ticker in name_s:
        return True
    if code and code in name_s:
        return True
    # 콤마로 구분된 3개 이상 토큰이면 ID 나열일 가능성 농후
    if name_s.count(',') >= 2:
        return True
    return False


def format_ticker_label(ticker: str, style: str = "name_with_code") -> str:
    """
    표시용 라벨 생성.

    style:
      "name_with_code" (기본) - "하림 (136480.KS)"
      "name_only"             - "하림"
      "code_only"             - "136480.KS"
      "compact"               - "하림 · 136480.KS"
      "flag_name"             - "🇰🇷 하림"
      "flag_name_code"        - "🇰🇷 하библi(136480.KS)"
    """
    if not ticker:
        return ""
    name = get_ticker_display_name(ticker)
    flag = _market_flag(ticker)

    # 이름 조회 실패 시 티커만
    if not name or name == ticker:
        if style.startswith("flag_"):
            return f"{flag} {ticker}"
        return ticker

    if style == "name_only":
        return name
    if style == "code_only":
        return ticker
    if style == "compact":
        return f"{name} · {ticker}"
    if style == "flag_name":
        return f"{flag} {name}"
    if style == "flag_name_code":
        return f"{flag} {name} ({ticker})"
    # default: name_with_code
    return f"{name} ({ticker})"


def _market_code(ticker: str) -> str:
    """
    티커에서 시장 코드 반환 (KOSPI / KOSDAQ / KR / US).

    - `.KS` → KOSPI
    - `.KQ` → KOSDAQ
    - 접미사 없는 한국 6자리 코드 → 'KR' (KOSPI/KOSDAQ 확정 불가)
    - 그 외 → US
    """
    t = (ticker or "").upper().strip()
    if t.endswith(".KS"):
        return "KOSPI"
    if t.endswith(".KQ"):
        return "KOSDAQ"
    if _is_korean_ticker(t):
        return "KR"
    return "US"


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
    return sorted(result)  # 알파벳 순으로 정렬


def save_watchlist(tickers: list[str]):
    header = (
        "# 관심 종목 리스트 (SSOT: WebUI/백엔드/배치 스크립트 공용)\n"
        "# 한 줄에 하나, #은 주석, 빈 줄은 무시됨\n"
        "# 편집 권장 방법: WebUI 사이드바 → 관심 종목 관리\n"
        "# 직접 편집 시 WebUI 재시작 또는 새로고침 필요\n\n"
    )
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        f.write(header)
        for t in sorted(tickers):  # 알파벳 순으로 정렬하여 저장
            f.write(f"{t}\n")


_TICKER_VALIDATION_CACHE: Dict[str, Tuple[bool, str]] = {}


def validate_ticker_webui(ticker: str) -> tuple[bool, str]:
    """
    [WebUI 전용] 종목 코드 유효성 검증 - yfinance 실시간 조회 + 한글 이름 검색 포함.

    참고: 백엔드 포맷 검증은 `stock_analyzer.ticker_validator.validate_ticker()`를 사용하세요.
    이 함수는 UI 표시용 메시지를 함께 반환하기 위해 별도로 유지됩니다.
    같은 입력에 대해서는 세션 캐시를 사용해 반복 yfinance 호출을 피합니다.
    Returns: (is_valid, message)
    """
    ticker_input = ticker.strip()
    ticker = ticker_input.upper()

    # 캐시 조회 (세션 내 반복 검증 시 UI 블로킹 방지)
    cache_key = ticker_input
    if cache_key in _TICKER_VALIDATION_CACHE:
        return _TICKER_VALIDATION_CACHE[cache_key]

    result = _validate_ticker_webui_impl(ticker_input, ticker)
    # 긍정 결과만 캐싱 (부정 결과는 일시적 네트워크 장애일 수 있음)
    if result[0]:
        _TICKER_VALIDATION_CACHE[cache_key] = result
    return result


def _validate_ticker_webui_impl(ticker_input: str, ticker: str) -> tuple[bool, str]:

    # 기본 형식 검증
    if not ticker:
        return False, "종목 코드를 입력하세요"

    # 한국 주식 이름 검색 (한글이 포함된 경우)
    if any(ord(char) >= 0xAC00 and ord(char) <= 0xD7A3 for char in ticker_input):
        try:
            from ticker_suggestion import suggest_ticker

            # 개선된 ticker_suggestion 사용
            result = suggest_ticker(ticker_input)

            if result['found'] and result['best_match']:
                # 95% 이상 매치로 자동 선택된 경우
                ticker = result['best_match']
                print(f"✅ 종목 자동 선택: {result['suggestions'][0]['name']} ({ticker})")
            elif result['found'] and result['suggestions']:
                # 여러 제안이 있는 경우 첫번째 사용 (또는 UI에서 선택하게 할 수 있음)
                ticker = result['suggestions'][0]['ticker']
                print(f"✅ 종목 선택: {result['suggestions'][0]['name']} ({ticker})")
            else:
                return False, f"❌ '{ticker_input}'를 찾을 수 없습니다. 정확한 종목명이나 종목코드를 입력하세요."
        except Exception as e:
            print(f"한국 주식 이름 검색 오류: {e}")

    if len(ticker) > 10:  # 대부분의 티커는 10자 이내
        return False, f"종목 코드가 너무 깁니다: {ticker}"

    # 한국 주식 코드 자동 감지 (6자리 숫자 또는 특수 코드 0126Z0 형식)
    import re
    if (ticker.isdigit() and len(ticker) == 6) or re.match(r'^[0-9]{4}[A-Z][0-9]$', ticker):
        # KOSPI (.KS) 또는 KOSDAQ (.KQ) 자동 시도
        import yfinance as yf

        valid_markets = []

        # 두 시장 모두 확인
        for suffix in ['.KS', '.KQ']:
            test_ticker = ticker + suffix
            try:
                stock = yf.Ticker(test_ticker)
                # UI 블로킹 최소화를 위해 2일만 조회 (존재 여부만 확인하면 충분)
                info = stock.history(period="2d")

                if not info.empty:
                    # 종목명 가져오기
                    try:
                        stock_info = stock.info
                        company_name = stock_info.get('longName', stock_info.get('shortName', ''))
                        market = "KOSPI" if suffix == '.KS' else "KOSDAQ"

                        # 유효한 이름이 있는 경우만 추가 (잘못된 데이터 필터링)
                        if company_name and not company_name.startswith(ticker):
                            valid_markets.append({
                                'ticker': test_ticker,
                                'name': company_name,
                                'market': market
                            })
                        elif not company_name:
                            # 이름이 없어도 데이터가 있으면 추가
                            valid_markets.append({
                                'ticker': test_ticker,
                                'name': 'N/A',
                                'market': market
                            })
                    except:
                        # info 가져오기 실패해도 데이터는 있음
                        market = "KOSPI" if suffix == '.KS' else "KOSDAQ"
                        valid_markets.append({
                            'ticker': test_ticker,
                            'name': 'N/A',
                            'market': market
                        })
            except:
                continue

        # 결과 처리
        if len(valid_markets) == 0:
            return False, f"❌ '{ticker}'는 유효하지 않은 한국 주식 코드입니다. KOSPI(.KS) 또는 KOSDAQ(.KQ) 모두에서 찾을 수 없습니다."
        elif len(valid_markets) == 1:
            m = valid_markets[0]
            if m['name'] != 'N/A':
                return True, f"✅ {m['ticker']} ({m['name']}, {m['market']})"
            else:
                return True, f"✅ {m['ticker']} ({m['market']})"
        else:
            # 두 시장 모두에 있는 경우
            options = []
            for m in valid_markets:
                if m['name'] != 'N/A':
                    options.append(f"{m['ticker']} ({m['name']}, {m['market']})")
                else:
                    options.append(f"{m['ticker']} ({m['market']})")

            # KOSDAQ을 우선 선택 (일반적으로 더 많은 신규 기업)
            kosdaq_option = next((m for m in valid_markets if m['market'] == 'KOSDAQ'), None)
            if kosdaq_option:
                selected = kosdaq_option
            else:
                selected = valid_markets[0]

            msg = f"✅ {selected['ticker']}"
            if selected['name'] != 'N/A':
                msg += f" ({selected['name']}, {selected['market']})"
            else:
                msg += f" ({selected['market']})"
            msg += f"\n⚠️ 참고: {ticker}는 두 시장에 모두 존재합니다: " + " / ".join(options)

            return True, msg

    # Yahoo Finance에서 실제 데이터 존재 여부 확인
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.history(period="5d")

        if info.empty:
            return False, f"❌ '{ticker}'는 유효하지 않은 종목 코드입니다. Yahoo Finance에서 데이터를 찾을 수 없습니다."

        # 추가 정보 가져오기 시도
        try:
            stock_info = stock.info
            company_name = stock_info.get('longName', stock_info.get('shortName', ''))
            if company_name:
                return True, f"✅ {ticker} ({company_name})"
            else:
                return True, f"✅ {ticker}"
        except:
            return True, f"✅ {ticker}"

    except Exception as e:
        return False, f"❌ '{ticker}' 검증 실패: 유효하지 않은 종목 코드이거나 네트워크 오류입니다."


def add_to_watchlist(ticker: str) -> tuple[bool, str]:
    ticker = ticker.strip().upper()
    if not ticker:
        return False, "종목 코드를 입력하세요"

    # 기본 문자 검증
    if not ticker.replace('.', '').replace('-', '').replace('^', '').replace('=', '').isalnum():
        return False, f"❌ 잘못된 형식: '{ticker}'"

    # 실제 종목 유효성 검증
    is_valid, message = validate_ticker_webui(ticker)
    if not is_valid:
        return False, message

    # 한국 주식의 경우 자동 해결된 ticker를 추출
    resolved_ticker = ticker
    import re
    # 6자리 숫자 또는 특수 코드 (예: 0126Z0) 처리
    if ((ticker.isdigit() and len(ticker) == 6) or
        re.match(r'^[0-9]{4}[A-Z][0-9]$', ticker)) and "✅" in message:
        # 메시지에서 실제 ticker 추출 (예: "✅ 072130.KQ (유엔젤, KOSDAQ)")
        match = re.search(r'✅\s+(\S+)\s+\(', message)
        if match:
            resolved_ticker = match.group(1)

    # Watchlist에 추가
    current = load_watchlist()
    if resolved_ticker in current:
        return False, f"⚠️ {resolved_ticker}는 이미 Watchlist에 있습니다"

    current.append(resolved_ticker)
    save_watchlist(current)

    # 성공 메시지에 회사명 포함
    if "✅" in message:
        return True, f"{message.replace('✅', '➕')} - Watchlist에 추가됨"
    else:
        return True, f"➕ {resolved_ticker} added to Watchlist"


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

    st.markdown('<div class="sidebar-section-label">Watchlist · 통합</div>', unsafe_allow_html=True)
    watchlist = load_watchlist()

    if watchlist:
        # 시장 플래그 + 종목명 (캐시됨) + 티커
        def _wl_chip(t):
            name = get_ticker_display_name(t)
            flag = _market_flag(t)
            if name and name != t:
                return f'<span class="wl-chip" title="{t}">{flag} {name}</span>'
            return f'<span class="wl-chip">{flag} {t}</span>'
        wl_chips = " ".join(_wl_chip(t) for t in watchlist)
        st.markdown(f'<div style="margin-bottom:8px; line-height:2;">{wl_chips}</div>', unsafe_allow_html=True)
        kr_count = sum(1 for t in watchlist if _is_korean_ticker(t))
        us_count = len(watchlist) - kr_count
        st.caption(f"{len(watchlist)} tickers — 🇺🇸 {us_count} · 🇰🇷 {kr_count}")
    else:
        st.caption("No tickers in watchlist")

    # 카운터 기반 동적 key — Add 성공 시 key를 변경하여 입력창을 초기화
    if "wl_add_counter" not in st.session_state:
        st.session_state.wl_add_counter = 0
    add_ticker = st.text_input(
        "Add ticker",
        placeholder="AAPL · 005930.KS · 삼성전자 — 미국/한국 구분 없이",
        label_visibility="collapsed",
        key=f"wl_add_{st.session_state.wl_add_counter}",
    )
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
                    # 새 key로 widget 재생성 → 입력창 비워짐
                    st.session_state.wl_add_counter += 1
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
            import os as _os_scan
            workers = int(_os_scan.getenv("SCAN_PARALLEL_WORKERS", "3"))
            import math as _math_scan
            est_rounds = _math_scan.ceil(len(wl) / workers)
            # 배치 다운로드 ~15s + 병렬 LLM 라운드 × 65s 예상
            est_sec = 15 + est_rounds * 65
            est_min, est_s = divmod(int(est_sec), 60)
            est_str = f"{est_min}분 {est_s}초" if est_min else f"{est_s}초"

            tickers_param = ",".join(wl)
            with st.spinner(
                f"🔄 {len(wl)}개 종목 병렬 스캔 중 (워커 {workers}개, 예상 {est_str})..."
            ):
                result = api_post(f"/scan?tickers={tickers_param}", timeout=900)
                if result:
                    st.success(f"✅ 완료! {len(wl)}개 종목 스캔")
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

    page = st.radio("Navigation", ["Home", "Dashboard", "Detail", "Multi-Agent", "Scan Log", "Signal Accuracy", "Screener", "Trading", "Virtual Trade", "Backtest", "ML Predict", "Portfolio", "Ranking", "Paper Trade", "History"], label_visibility="collapsed")


# ═══════════════════════════════════════════════════════════════
#  홈 페이지
# ═══════════════════════════════════════════════════════════════


def render_home():
    """통합 홈 페이지 — 미국/한국 시장 구분 없이 한 화면에서 관리."""
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Stock AI</div>
        <div class="page-subtitle">AI-Powered Multi-Tool Stock Analysis Terminal · 미국/한국 통합</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 1. 시장 지수 바 (S&P/NASDAQ/DOW/KOSPI/KOSDAQ/원달러/상품) ──
    render_market_ticker_bar()

    # ── 2. 분석 요약 (시장 구분 없이 전체) ──
    data = api_get("/results")
    results = data.get("results", {}) if data else {}
    total = len(results)
    buy_count = sum(1 for r in results.values() if r.get("signal") == "BUY")
    sell_count = sum(1 for r in results.values() if r.get("signal") == "SELL")
    hold_count = sum(1 for r in results.values() if r.get("signal") == "HOLD")

    # 시장별 세부 카운트
    us_results = {k: v for k, v in results.items() if not _is_korean_ticker(k)}
    kr_results = {k: v for k, v in results.items() if _is_korean_ticker(k)}

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total", str(total))
    m2.metric("Buy", str(buy_count))
    m3.metric("Sell", str(sell_count))
    m4.metric("Hold", str(hold_count))
    m5.metric("🇺🇸 US", str(len(us_results)))
    m6.metric("🇰🇷 KR", str(len(kr_results)))

    # ── 3. 시스템 상태 ──
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

    # ── 4. 통합 Watchlist (시장 플래그 포함) ──
    st.markdown("""
    <div class="section-header">
        <div class="section-title">Watchlist · 통합</div>
    </div>
    """, unsafe_allow_html=True)

    if watchlist:
        # 필터: 전체 / 🇺🇸 US / 🇰🇷 KR
        filter_col, add_col = st.columns([1, 2])
        with filter_col:
            market_filter = st.radio(
                "시장 필터",
                ["전체", "🇺🇸 US", "🇰🇷 KR"],
                horizontal=True,
                label_visibility="collapsed",
                key="home_market_filter",
            )
        with add_col:
            # 동적 key로 추가 성공 시 입력창 비우기
            if "home_quick_add_counter" not in st.session_state:
                st.session_state.home_quick_add_counter = 0
            new_tk = st.text_input(
                "빠른 종목 추가",
                placeholder="AAPL, 005930.KS, 삼성전자 — 미국/한국 구분 없이 입력",
                key=f"home_quick_add_{st.session_state.home_quick_add_counter}",
                label_visibility="collapsed",
            )
            if new_tk and st.button("➕ Watchlist 추가", key="home_add_btn"):
                ok, msg = add_to_watchlist(new_tk)
                if ok:
                    st.success(msg)
                    # 새 key로 widget 재생성 → 입력창 초기화
                    st.session_state.home_quick_add_counter += 1
                    st.rerun()
                else:
                    st.error(msg)

        # watchlist 필터링
        if market_filter == "🇺🇸 US":
            filtered = [t for t in watchlist if not _is_korean_ticker(t)]
        elif market_filter == "🇰🇷 KR":
            filtered = [t for t in watchlist if _is_korean_ticker(t)]
        else:
            filtered = watchlist

        if filtered:
            def _home_chip(t):
                name = get_ticker_display_name(t)
                flag = _market_flag(t)
                if name and name != t:
                    # tooltip으로 티커 노출
                    return f'<span class="wl-chip" title="{t}">{flag} {name}</span>'
                return f'<span class="wl-chip">{flag} {t}</span>'
            wl_chips = " ".join(_home_chip(t) for t in filtered)
            st.markdown(f'<div style="line-height:2.2;">{wl_chips}</div>', unsafe_allow_html=True)
            st.caption(f"표시 {len(filtered)}개 / 전체 {len(watchlist)}개")
        else:
            st.caption(f"'{market_filter}' 필터에 해당하는 종목 없음")
    else:
        st.caption("No tickers in watchlist. Add tickers from the sidebar or above.")

    # ── 5. 최신 신호 (시장 통합 테이블) ──
    if results:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">Latest Signals · 통합</div>
        </div>
        """, unsafe_allow_html=True)

        # 시장 필터 옵션
        sig_filter = st.radio(
            "신호 필터",
            ["전체", "🇺🇸 US", "🇰🇷 KR", "BUY만", "SELL만"],
            horizontal=True,
            label_visibility="collapsed",
            key="home_sig_filter",
        )

        rows = []
        for ticker, r in sorted(results.items(), key=lambda x: abs(x[1].get("score", 0)), reverse=True):
            flag = _market_flag(ticker)
            market_code = _market_code(ticker)
            signal = r.get("signal", "?")

            # 필터 적용
            if sig_filter == "🇺🇸 US" and flag != "🇺🇸":
                continue
            if sig_filter == "🇰🇷 KR" and flag != "🇰🇷":
                continue
            if sig_filter == "BUY만" and signal != "BUY":
                continue
            if sig_filter == "SELL만" and signal != "SELL":
                continue

            # 종목명 조회 (캐시됨)
            display_name = get_ticker_display_name(ticker)
            name_cell = display_name if display_name and display_name != ticker else "—"

            rows.append({
                "Market": f"{flag} {market_code}",
                "Name": name_cell,
                "Ticker": ticker,
                "Signal": signal,
                "Score": r.get("score", 0),
                "Confidence": r.get("confidence", 0),
                "Time": str(r.get("analyzed_at", ""))[:16],
            })

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(
                df.style.map(
                    lambda v: "color: #02d4a1" if v == "BUY" else ("color: #fd526f" if v == "SELL" else "color: #ffb347"),
                    subset=["Signal"],
                ),
                use_container_width=True, hide_index=True,
            )
        else:
            st.caption(f"'{sig_filter}'에 해당하는 신호 없음")

    # ── 6. 한국 시장 고유 기능 (접이식) ──
    if _KOREAN_STOCKS_AVAILABLE:
        with st.expander("🇰🇷 한국 주식 심화 도구 (매매동향 · DART 공시 · 즐겨찾기)", expanded=False):
            render_korean_tools_panel()


def render_korean_tools_panel():
    """한국 주식 전용 도구 (통합 홈의 접이식 섹션)."""
    if not _KOREAN_STOCKS_AVAILABLE:
        st.warning("한국 주식 모듈을 사용할 수 없습니다.")
        return

    # KOSPI/KOSDAQ 지수
    try:
        indices = get_kr_indices()
        kospi = indices.get('kospi', {})
        kosdaq = indices.get('kosdaq', {})

        if kospi or kosdaq:
            col1, col2 = st.columns(2)
            if kospi:
                with col1:
                    change_pct = kospi.get('change_pct', 0)
                    st.metric(
                        "KOSPI",
                        f"{kospi.get('current', 0):,.2f}",
                        f"{change_pct:+.2f}%",
                        delta_color="normal" if change_pct >= 0 else "inverse",
                    )
            if kosdaq:
                with col2:
                    change_pct = kosdaq.get('change_pct', 0)
                    st.metric(
                        "KOSDAQ",
                        f"{kosdaq.get('current', 0):,.2f}",
                        f"{change_pct:+.2f}%",
                        delta_color="normal" if change_pct >= 0 else "inverse",
                    )
    except Exception as e:
        st.caption(f"지수 로드 실패: {e}")

    # Watchlist의 한국 종목만 사용 (SSOT) — 별도 즐겨찾기 파일 사용하지 않음
    watchlist = load_watchlist()
    kr_tickers = [t for t in watchlist if _is_korean_ticker(t)]

    if not kr_tickers:
        st.info(
            "📭 Watchlist에 한국 종목이 없습니다.\n\n"
            "사이드바 또는 홈 페이지의 Watchlist에 한국 종목 추가 시 여기에 자동 표시됩니다.\n\n"
            "입력 예시: `136480.KS` (하림), `005930.KS` (삼성전자), `하림` (한글명)"
        )
        return

    # ticker → (code, name) 변환 헬퍼
    def _to_code_name(ticker):
        """Watchlist 티커에서 (순수코드, 종목명) 반환."""
        t = ticker.upper()
        if t.endswith('.KS') or t.endswith('.KQ'):
            code = t[:-3]
        else:
            code = t
        name = get_ticker_display_name(ticker)
        if not name or name == ticker:
            name = code
        return code, name

    # 한국 종목 (code, name, ticker) 리스트
    kr_items = [(_to_code_name(t), t) for t in kr_tickers]
    # kr_items = [((code, name), full_ticker), ...]

    # ── Watchlist 한국 종목 현재가 카드 ──
    st.markdown(f"**📌 Watchlist 한국 종목** ({len(kr_tickers)}개)")
    cols = st.columns(3)
    for idx, ((code, name), ticker) in enumerate(kr_items):
        with cols[idx % 3]:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='5d')
                if not hist.empty:
                    current = hist['Close'].iloc[-1]
                    prev = hist['Close'].iloc[-2] if len(hist) > 1 else current
                    change_pct = ((current / prev) - 1) * 100 if prev else 0
                    st.metric(
                        f"{name} ({code})",
                        f"₩{current:,.0f}",
                        f"{change_pct:+.2f}%",
                        delta_color="normal" if change_pct >= 0 else "inverse",
                    )
                else:
                    st.metric(f"{name} ({code})", "데이터 없음", "—")
            except Exception:
                st.metric(f"{name} ({code})", "로드 실패", "—")

    # ── 투자자별 매매 동향 — Watchlist 한국 종목에서만 선택 ──
    st.markdown("**📊 투자자별 매매 동향** (외국인 · 기관 · 개인)")
    try:
        ticker_options = [f"{code} ({name})" for (code, name), _ in kr_items]
        sample_ticker = st.selectbox(
            "종목 선택 (Watchlist의 한국 종목)",
            ticker_options,
            key="home_kr_inst_select",
        )

        if st.button("📊 매매동향 조회", key="home_kr_inst_btn"):
            ticker_code = sample_ticker.split()[0] if sample_ticker else ""
            if ticker_code:
                with st.spinner(f"{ticker_code} 매매동향 조회 중..."):
                    collector = KoreanStockData()
                    trading_data = collector.fetch_institutional_trading(ticker_code, days=5)
                    if trading_data and 'summary' in trading_data:
                        summary = trading_data['summary']
                        c1, c2, c3 = st.columns(3)
                        c1.metric("외국인 순매수", f"{summary.get('foreign_net', 0):,}주")
                        c2.metric("기관 순매수", f"{summary.get('institution_net', 0):,}주")
                        c3.metric("개인 순매수", f"{summary.get('individual_net', 0):,}주")
                    else:
                        st.caption("데이터 없음")
    except Exception as e:
        st.caption(f"매매동향 조회 실패: {e}")

    # ── DART 공시 — Watchlist 한국 종목에서만 선택 ──
    st.markdown("**📄 DART 공시**")
    try:
        from dart_api import DARTClient
        dart_client = DARTClient()
        if dart_client.is_configured():
            ticker_options = [f"{code} ({name})" for (code, name), _ in kr_items]
            disclosure_ticker = st.selectbox(
                "공시 조회 종목 (Watchlist의 한국 종목)",
                ticker_options,
                key="home_kr_dart_select",
            )
            if st.button("📄 최근 공시 조회", key="home_kr_dart_btn"):
                ticker_code = disclosure_ticker.split()[0] if disclosure_ticker else ""
                with st.spinner(f"{ticker_code} 공시 조회 중..."):
                    disclosures = dart_client.fetch_recent_disclosures(ticker_code, days=30)
                    if disclosures:
                        st.write(f"최근 30일 공시: {len(disclosures)}건")
                        for d in disclosures[:10]:
                            with st.expander(f"{d['date']}: {d['title'][:60]}..."):
                                st.markdown(f"**보고서 유형**: {d.get('report_type', 'N/A')}")
                                st.markdown(f"**링크**: {d.get('url', 'N/A')}")
                    else:
                        st.caption("공시 데이터 없음")
        else:
            st.caption("⚠️ DART_API_KEY 미설정 — opendart.fss.or.kr에서 무료 발급")
    except ImportError:
        st.caption("DART API 모듈 로드 실패")


def _deprecated_render_korean_market_home():
    """[Deprecated] 통합 홈과 render_korean_tools_panel()로 대체됨.

    내부 코드는 한국 전용 즐겨찾기 파일을 직접 참조해 SSOT(Watchlist) 원칙을
    위반했기 때문에 제거됨. 라우팅에서 호출되지 않으며 호환성을 위해 이름만 유지.
    """
    pass


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

    # 통합 시장 필터 (미국/한국 구분 없이 한 테이블에 표시하되 필터로 선택 가능)
    dashboard_filter = st.radio(
        "시장 필터",
        ["전체", "🇺🇸 US", "🇰🇷 KR"],
        horizontal=True,
        label_visibility="collapsed",
        key="dashboard_market_filter",
    )

    rows = []
    # Fix: API returns 'composite_score', not 'score'
    for ticker, r in sorted(results.items(), key=lambda x: x[1].get("composite_score", x[1].get("score", 0)), reverse=True):
        flag = _market_flag(ticker)
        market_code = _market_code(ticker)

        # 시장 필터 적용
        if dashboard_filter == "🇺🇸 US" and flag != "🇺🇸":
            continue
        if dashboard_filter == "🇰🇷 KR" and flag != "🇰🇷":
            continue

        dist = r.get("signal_distribution", {})
        display_name = get_ticker_display_name(ticker)
        name_cell = display_name if display_name and display_name != ticker else "—"
        rows.append({
            "market": f"{flag} {market_code}",
            "name": name_cell,
            "ticker": ticker,
            "signal": r.get("signal", "?"),
            "score": r.get("composite_score", r.get("score", 0)),  # Try composite_score first
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

    # Export functionality for Dashboard
    st.markdown("---")
    st.markdown('<div class="section-title">📤 Export All Data</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([3, 1])

    with col1:
        export_options = st.radio(
            "Export Format:",
            ["JSON (Full Data)", "CSV (Summary)", "Markdown (Report)"],
            horizontal=True,
            key="dashboard_export_format"
        )

        include_multi = st.checkbox(
            "Include Multi-Agent Analysis",
            value=True,
            key="dashboard_include_multi",
            help="Include detailed Multi-Agent analysis data for each ticker"
        )

    with col2:
        if st.button("🚀 Export All", key="dashboard_export_all", use_container_width=True):
            with st.spinner("Collecting data for all tickers..."):
                all_export_data = {
                    "export_timestamp": datetime.now().isoformat(),
                    "total_tickers": total,
                    "signal_summary": {
                        "buy": len(buy_list),
                        "sell": len(sell_list),
                        "hold": len(hold_list)
                    },
                    "analysis_period": {
                        "oldest": oldest_analysis if 'oldest_analysis' in locals() else None,
                        "latest": latest_analysis if 'latest_analysis' in locals() else None
                    },
                    "tickers": {}
                }

                # Collect data for each ticker
                progress_text = st.empty()
                progress_bar = st.progress(0)

                for idx, ticker in enumerate(sorted(results.keys())):
                    progress_text.text(f"Processing {ticker}... ({idx+1}/{total})")
                    progress_bar.progress((idx + 1) / total)

                    try:
                        ticker_data = export_comprehensive_data(ticker, include_multi_agent=include_multi)
                        all_export_data["tickers"][ticker] = ticker_data
                    except Exception as e:
                        all_export_data["tickers"][ticker] = {"error": str(e)}

                progress_text.empty()
                progress_bar.empty()

                # Prepare export based on selected format
                if "JSON" in export_options:
                    export_json = json.dumps(all_export_data, indent=2, ensure_ascii=False)
                    st.download_button(
                        label="📥 Download JSON",
                        data=export_json,
                        file_name=f"stock_analysis_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json",
                        key="dashboard_download_json"
                    )

                elif "CSV" in export_options:
                    # Create summary CSV
                    csv_rows = []
                    for ticker, data in all_export_data["tickers"].items():
                        if "error" not in data:
                            row = {
                                "Ticker": ticker,
                                "Signal": data.get("single_llm_analysis", {}).get("signal", "N/A"),
                                "Score": data.get("single_llm_analysis", {}).get("score", 0),
                                "Confidence": data.get("single_llm_analysis", {}).get("confidence", 0),
                                "Multi-Agent Signal": data.get("multi_agent_analysis", {}).get("final_decision", {}).get("final_signal", "N/A"),
                                "Multi-Agent Confidence": data.get("multi_agent_analysis", {}).get("final_decision", {}).get("final_confidence", 0),
                                "Buy Agents": data.get("multi_agent_analysis", {}).get("final_decision", {}).get("signal_distribution", {}).get("buy", 0),
                                "Sell Agents": data.get("multi_agent_analysis", {}).get("final_decision", {}).get("signal_distribution", {}).get("sell", 0),
                                "Neutral Agents": data.get("multi_agent_analysis", {}).get("final_decision", {}).get("signal_distribution", {}).get("neutral", 0),
                                "Analyzed At": data.get("single_llm_analysis", {}).get("analyzed_at", "")
                            }
                        else:
                            row = {
                                "Ticker": ticker,
                                "Signal": "ERROR",
                                "Score": 0,
                                "Confidence": 0,
                                "Multi-Agent Signal": "ERROR",
                                "Multi-Agent Confidence": 0,
                                "Buy Agents": 0,
                                "Sell Agents": 0,
                                "Neutral Agents": 0,
                                "Analyzed At": ""
                            }
                        csv_rows.append(row)

                    if csv_rows:
                        export_df = pd.DataFrame(csv_rows)
                        csv_data = export_df.to_csv(index=False, encoding='utf-8-sig')

                        st.download_button(
                            label="📥 Download CSV",
                            data=csv_data,
                            file_name=f"stock_analysis_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv",
                            key="dashboard_download_csv"
                        )

                else:  # Markdown Report
                    # Create comprehensive markdown report
                    report = f"""# Stock Analysis Report - All Tickers
## 📅 Report Information
- **Export Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **Total Tickers Analyzed**: {total}
- **Analysis Period**: {oldest_analysis if 'oldest_analysis' in locals() else 'N/A'} ~ {latest_analysis if 'latest_analysis' in locals() else 'N/A'}

## 📊 Market Overview
- **Buy Signals**: {len(buy_list)} ({buy_pct}%)
- **Sell Signals**: {len(sell_list)} ({sell_pct}%)
- **Hold Signals**: {len(hold_list)} ({hold_pct}%)

## 🎯 Top Buy Recommendations
"""
                    # Add top buy recommendations
                    buy_sorted = sorted(buy_list.items(), key=lambda x: x[1].get("score", 0), reverse=True)[:5]
                    for ticker, data in buy_sorted:
                        report += f"### {ticker}\n"
                        report += f"- **Score**: {data.get('score', 0):+.2f}\n"
                        report += f"- **Confidence**: {data.get('confidence', 0)}/10\n"
                        if include_multi and ticker in all_export_data["tickers"]:
                            ma_data = all_export_data["tickers"][ticker].get("multi_agent_analysis", {})
                            if ma_data:
                                final = ma_data.get("final_decision", {})
                                report += f"- **Multi-Agent Signal**: {final.get('final_signal', 'N/A')}\n"
                                report += f"- **Multi-Agent Confidence**: {final.get('final_confidence', 0)}/10\n"
                        report += "\n"

                    report += """## 📉 Risk Alerts (Sell Signals)
"""
                    # Add sell signals
                    sell_sorted = sorted(sell_list.items(), key=lambda x: x[1].get("score", 0))[:5]
                    for ticker, data in sell_sorted:
                        report += f"### {ticker}\n"
                        report += f"- **Score**: {data.get('score', 0):+.2f}\n"
                        report += f"- **Confidence**: {data.get('confidence', 0)}/10\n"
                        report += "\n"

                    report += """## 📋 Full Analysis Results
| Ticker | Signal | Score | Confidence | Multi-Agent Signal | MA Confidence |
|--------|--------|-------|------------|-------------------|---------------|
"""
                    # Add all tickers
                    for ticker in sorted(results.keys()):
                        r = results[ticker]
                        ma_signal = "N/A"
                        ma_conf = "N/A"

                        if include_multi and ticker in all_export_data["tickers"]:
                            ma_data = all_export_data["tickers"][ticker].get("multi_agent_analysis", {})
                            if ma_data:
                                final = ma_data.get("final_decision", {})
                                ma_signal = final.get("final_signal", "N/A")
                                ma_conf = f"{final.get('final_confidence', 0)}/10"

                        report += f"| {ticker} | {r.get('signal', 'N/A')} | {r.get('score', 0):+.2f} | {r.get('confidence', 0)}/10 | {ma_signal} | {ma_conf} |\n"

                    report += f"""
---
*Generated by Stock AI Analysis System v2.0*
*Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""

                    st.download_button(
                        label="📥 Download Report",
                        data=report,
                        file_name=f"stock_analysis_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                        mime="text/markdown",
                        key="dashboard_download_report"
                    )

                st.success(f"✅ Export prepared for {total} tickers!")


# ═══════════════════════════════════════════════════════════════
#  종목 상세 페이지
# ═══════════════════════════════════════════════════════════════

def _fmt_num(v, decimals=2):
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    return f"{v:,.{decimals}f}"


def _is_korean_stock(ticker: str) -> bool:
    """한국 주식 여부 판단 (.KS/.KQ 또는 6자리 숫자 코드)"""
    if not ticker:
        return False
    ticker_upper = ticker.upper()
    return ticker_upper.endswith(('.KS', '.KQ')) or (ticker_upper.isdigit() and len(ticker_upper) == 6)


def _get_currency_symbol(ticker: str) -> str:
    """티커에 맞는 통화 기호 반환 (₩ 또는 $)"""
    return "₩" if _is_korean_stock(ticker) else "$"


def _fmt_price(price, ticker: str, decimals: int = None) -> str:
    """가격을 통화 기호와 함께 포맷 (한국: ₩, 미국: $)"""
    if price is None:
        return "—"
    if isinstance(price, str):
        return price

    currency = _get_currency_symbol(ticker)
    # 한국 주식은 소수점 없이, 미국 주식은 소수점 2자리
    if decimals is None:
        decimals = 0 if _is_korean_stock(ticker) else 2

    return f"{currency}{price:,.{decimals}f}"


def _render_tool_detail_card(td: dict, ticker: str = ""):
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
            level_data = {f"Fib {k}": _fmt_price(v, ticker) for k, v in levels.items()}
            cols = st.columns(min(len(level_data), 4))
            for col, (label, val) in zip(cols, list(level_data.items())[:4]):
                col.metric(label, val)
        c1, c2, c3 = st.columns(3)
        c1.metric("Retracement", _fmt_num(td.get("current_retracement"), 1))
        c2.metric("Nearest Support", _fmt_price(td.get('nearest_support'), ticker))
        c3.metric("Nearest Resistance", _fmt_price(td.get('nearest_resistance'), ticker))

    elif tool_name == "volatility_regime_analysis":
        c1, c2, c3 = st.columns(3)
        c1.metric("ATR", _fmt_price(td.get('current_atr'), ticker))
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
        c1.metric("Pivot", _fmt_price(td.get('pivot'), ticker))
        c2.metric("Upside %", f"{_fmt_num(td.get('upside_pct'), 1)}%")
        c3.metric("Downside %", f"{_fmt_num(td.get('downside_pct'), 1)}%")
        resistance = td.get("resistance", {})
        support = td.get("support", {})
        if resistance:
            cols = st.columns(len(resistance))
            for col, (level, val) in zip(cols, resistance.items()):
                col.metric(f"R{level}", _fmt_price(val, ticker))
        if support:
            cols = st.columns(len(support))
            for col, (level, val) in zip(cols, support.items()):
                col.metric(f"S{level}", _fmt_price(val, ticker))
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
                _render_tool_detail_card(td, selected)

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

    # Export 섹션 추가
    st.markdown("""
    <div class="section-header">
        <div class="section-title">📥 Export All Data</div>
    </div>
    """, unsafe_allow_html=True)

    # Export 옵션
    col1, col2 = st.columns(2)
    with col1:
        include_multi = st.checkbox("Include Multi-Agent Analysis", value=True,
                                   help="Multi-Agent 분석 포함 (시간이 더 걸립니다)")

    # Export 버튼들
    export_col1, export_col2, export_col3 = st.columns(3)

    with export_col1:
        if st.button("📄 Export as JSON", use_container_width=True, key="detail_export_json"):
            with st.spinner(f"Collecting all data for {selected}..."):
                export_data = export_comprehensive_data(selected, include_multi)
                json_str = json.dumps(export_data, indent=2, ensure_ascii=False, default=str)

                st.download_button(
                    label="📥 Download JSON",
                    data=json_str,
                    file_name=f"{selected}_comprehensive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                    use_container_width=True
                )
                st.success(f"✅ Data collected! Click 'Download JSON' to save.")

    with export_col2:
        if st.button("📊 Export as CSV", use_container_width=True, key="detail_export_csv"):
            with st.spinner(f"Preparing CSV for {selected}..."):
                export_data = export_comprehensive_data(selected, include_multi)

                # CSV로 변환 (주요 데이터만)
                csv_data = []

                # Single LLM 데이터
                if "single_llm_analysis" in export_data:
                    single = export_data["single_llm_analysis"]
                    csv_data.append({
                        "Type": "Single LLM",
                        "Signal": single.get("final_signal"),
                        "Score": single.get("composite_score"),
                        "Confidence": single.get("confidence"),
                        "Timestamp": single.get("analyzed_at")
                    })

                # Multi-Agent 데이터
                if "multi_agent_analysis" in export_data:
                    multi = export_data["multi_agent_analysis"]
                    if multi.get("agent_results"):
                        for agent in multi["agent_results"]:
                            csv_data.append({
                                "Type": f"Agent: {agent.get('agent')}",
                                "Signal": agent.get("signal"),
                                "Score": agent.get("score", 0),
                                "Confidence": agent.get("confidence"),
                                "Timestamp": multi.get("timestamp")
                            })

                    # Final decision
                    if multi.get("final_decision"):
                        final = multi["final_decision"]
                        csv_data.append({
                            "Type": "Multi-Agent Final",
                            "Signal": final.get("final_signal"),
                            "Score": 0,
                            "Confidence": final.get("final_confidence"),
                            "Timestamp": multi.get("timestamp")
                        })

                if csv_data:
                    df = pd.DataFrame(csv_data)
                    csv_str = df.to_csv(index=False, encoding='utf-8-sig')

                    st.download_button(
                        label="📥 Download CSV",
                        data=csv_str,
                        file_name=f"{selected}_comprehensive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                    st.success(f"✅ CSV prepared! Click 'Download CSV' to save.")
                else:
                    st.warning("No data available for CSV export")

    with export_col3:
        if st.button("📝 Export as Report", use_container_width=True, key="detail_export_report"):
            with st.spinner(f"Generating report for {selected}..."):
                export_data = export_comprehensive_data(selected, include_multi)

                # Markdown 리포트 생성
                report = f"""# 📊 {selected} Comprehensive Analysis Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 1. Single LLM Analysis (V1.0)
"""
                if "single_llm_analysis" in export_data:
                    single = export_data["single_llm_analysis"]
                    report += f"""
- **Final Signal**: {single.get('final_signal')}
- **Composite Score**: {single.get('composite_score')}
- **Confidence**: {single.get('confidence')}/10
- **Analyzed**: {single.get('analyzed_at')}

### Signal Distribution
- Buy votes: {single.get('signal_distribution', {}).get('buy', 0)}
- Sell votes: {single.get('signal_distribution', {}).get('sell', 0)}
- Neutral votes: {single.get('signal_distribution', {}).get('neutral', 0)}
"""

                report += """
## 2. Multi-Agent Analysis (V2.0)
"""
                if "multi_agent_analysis" in export_data:
                    multi = export_data["multi_agent_analysis"]
                    if multi.get("final_decision"):
                        final = multi["final_decision"]
                        report += f"""
### Final Decision
- **Signal**: {final.get('final_signal')}
- **Confidence**: {final.get('final_confidence')}/10
- **Consensus**: {final.get('consensus')}

### Agent Results
"""
                        for agent in multi.get("agent_results", []):
                            report += f"""
#### {agent.get('agent')}
- Signal: {agent.get('signal')}
- Confidence: {agent.get('confidence')}/10
- LLM Provider: {agent.get('llm_provider')}
- Reasoning: {agent.get('reasoning', 'N/A')[:200]}...
"""
                else:
                    report += "\n*Multi-Agent analysis not included or not available*\n"

                report += """
## 3. Backtest Results
"""
                if "backtest" in export_data and export_data["backtest"]:
                    bt = export_data["backtest"]
                    report += f"""
- **Strategy**: Composite
- **Annual Return**: {bt.get('annual_return', 'N/A')}%
- **Sharpe Ratio**: {bt.get('sharpe_ratio', 'N/A')}
- **Max Drawdown**: {bt.get('max_drawdown', 'N/A')}%
"""
                else:
                    report += "\n*Backtest data not available*\n"

                report += """
## 4. ML Prediction
"""
                if "ml_prediction" in export_data and export_data["ml_prediction"]:
                    ml = export_data["ml_prediction"]
                    report += f"""
- **Direction**: {ml.get('ensemble_direction', 'N/A')}
- **Probability**: {ml.get('ensemble_probability', 'N/A')}%
- **Confidence**: {ml.get('ensemble_confidence', 'N/A')}/10
"""
                else:
                    report += "\n*ML prediction not available*\n"

                report += """
---
*Report generated by Stock AI Analysis System v2.0*
"""

                st.download_button(
                    label="📥 Download Report",
                    data=report,
                    file_name=f"{selected}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                    mime="text/markdown",
                    use_container_width=True
                )
                st.success(f"✅ Report generated! Click 'Download Report' to save.")


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

    # 티커 선택 드롭다운 (종목명 표시)
    ticker_options = {ticker: f"{get_ticker_display_name(ticker)} ({ticker})" for ticker in tickers}
    selected_display = st.selectbox("Select Ticker", list(ticker_options.values()), key="ml_ticker")
    ticker = [k for k, v in ticker_options.items() if v == selected_display][0]

    if st.button("Run ML Prediction", type="primary"):
        ticker_name = get_ticker_display_name(ticker)
        with st.spinner(f"Training model for {ticker_name}..."):
            ml = api_get(f"/ml/{ticker}", timeout=120)
        if not ml:
            st.error("ML prediction failed")
            return

        st.markdown(f"""
        <div class="section-header">
            <div class="section-title">{ticker_name} ({ticker}) — {ml.get('best_prediction', '?')}</div>
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
                "Entry": _fmt_price(p.get('entry_price', 0), t),
                "Current": _fmt_price(p.get('current_price', 0), t),
                "P&L": _fmt_price(p.get('pnl', 0), t),
                "P&L %": f"{p.get('pnl_pct', 0):+.2f}%",
                "Entry Date": str(p.get("entry_date", ""))[:10],
            })
        st.dataframe(pd.DataFrame(pos_rows), use_container_width=True, hide_index=True)

    recent = status.get("recent_trades", [])
    if recent:
        st.markdown("**Recent Closed Trades**")
        trade_rows = []
        for t in reversed(recent):
            ticker = t.get("ticker", "?")
            trade_rows.append({
                "Ticker": ticker,
                "Entry": _fmt_price(t.get('entry_price', 0), ticker),
                "Exit": _fmt_price(t.get('exit_price', 0), ticker),
                "Qty": t.get("qty", 0),
                "P&L": _fmt_price(t.get('pnl', 0), ticker),
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
#  Multi-Agent 페이지 (V2.0)
# ═══════════════════════════════════════════════════════════════

def render_multi_agent():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">🤖 Multi-Agent Analysis</div>
        <div class="page-subtitle">8개 전문 AI 에이전트 협업 분석 (V2.0 Enhanced)</div>
    </div>
    """, unsafe_allow_html=True)

    # Watchlist 로드 (참고용)
    watchlist = load_watchlist()

    # 종목 입력 방식 선택
    input_method = st.radio(
        "종목 입력 방식",
        ["Watchlist에서 선택", "직접 입력"],
        horizontal=True,
        label_visibility="collapsed"
    )

    # 종목 선택/입력
    col1, col2 = st.columns([3, 1])
    with col1:
        if input_method == "Watchlist에서 선택":
            if not watchlist:
                st.warning("Watchlist가 비어있습니다. 직접 입력을 선택하거나 사이드바에서 종목을 추가하세요.")
                ticker = st.text_input(
                    "종목 코드 입력",
                    placeholder="예: AAPL, 삼성전자, 005930.KS, 네이버",
                    label_visibility="collapsed",
                )
            else:
                # 종목명과 함께 표시
                ticker_options = {t: f"{get_ticker_display_name(t)} ({t})" for t in watchlist}
                selected_display = st.selectbox("분석할 종목 선택", list(ticker_options.values()), label_visibility="collapsed")
                ticker = [k for k, v in ticker_options.items() if v == selected_display][0]
        else:
            # 한글 종목명 입력을 지원하기 위해 .upper()는 영문/숫자 입력일 때만 적용
            ticker_raw = st.text_input(
                "종목 코드 입력",
                placeholder="예: AAPL, 삼성전자, 005930.KS, 네이버",
                label_visibility="collapsed",
            )
            ticker = ticker_raw.upper() if ticker_raw and ticker_raw.isascii() else ticker_raw

    with col2:
        analyze_btn = st.button("🤖 Multi-Agent 분석", use_container_width=True, type="primary", disabled=not ticker)

    if not ticker and not analyze_btn:
        st.info("👆 종목을 선택하거나 입력하고 'Multi-Agent 분석' 버튼을 클릭하세요.")
        return

    if not analyze_btn and "multi_agent_result" not in st.session_state:
        if ticker:
            st.info(f"📊 {ticker}를 분석하려면 'Multi-Agent 분석' 버튼을 클릭하세요.")
        return

    # 분석 실행
    if analyze_btn:
        # 종목 코드 유효성 검증
        is_valid, validation_message = validate_ticker_webui(ticker)
        if not is_valid:
            st.error(validation_message)
            # 검증 실패 시 유사 종목 자동 추천 (UX 개선)
            try:
                from stock_analyzer.ticker_suggestion import suggest_ticker as _suggest
                sug = _suggest(ticker, max_results=8)
                if sug.get('found') and sug.get('suggestions'):
                    # WebUI는 편의성 우선: 0.80 이상이면 자동 교정 제안
                    top = sug['suggestions'][0]
                    if top['score'] >= 0.80:
                        st.info(
                            f"💡 혹시 이 종목을 찾으시나요? **{top['name']} ({top['ticker']})** "
                            f"(매치율 {top['score']*100:.0f}%)"
                        )
                    with st.expander(f"🔍 유사 종목 {len(sug['suggestions'])}개 추천", expanded=True):
                        for s in sug['suggestions']:
                            score = int(s['score'] * 100)
                            st.markdown(
                                f"- **{s['name']}** (`{s['ticker']}`) · {s.get('exchange','')} · 매치율 {score}%"
                            )
            except Exception:
                pass  # 추천 모듈이 실패해도 원래 에러 메시지는 유지
            return

        # 한국 주식의 경우 자동 해결된 ticker 추출
        resolved_ticker = ticker
        import re
        # 6자리 숫자 또는 특수 코드 (예: 0126Z0) 처리
        if ((ticker.isdigit() and len(ticker) == 6) or
            re.match(r'^[0-9]{4}[A-Z][0-9]$', ticker)) and "✅" in validation_message:
            match = re.search(r'✅\s+(\S+)\s+\(', validation_message)
            if match:
                resolved_ticker = match.group(1)

        # 사용자 입력과 분석 대상이 다르면 명시적으로 안내 (UX: 정정된 티커 투명성)
        if resolved_ticker != ticker:
            resolved_label = format_ticker_label(resolved_ticker, style="name_with_code")
            st.info(f"📝 입력: **{ticker}** → 분석 대상: **{resolved_label}**")

        # 분석 헤더에도 종목명 포함
        analysis_label = format_ticker_label(resolved_ticker, style="name_with_code")
        with st.status(f"🤖 {analysis_label} 멀티에이전트 분석 (약 1-2분)", expanded=True) as status:
            # Single LLM 분석
            st.write("📊 1/3 · 단일 LLM 분석 (V1.0) 진행 중...")
            single_result = api_get(f"/results/{resolved_ticker}")
            if not single_result:
                single_result = api_post(f"/scan/{resolved_ticker}")

            # Multi-Agent 분석 (백엔드가 8개 에이전트 병렬 실행)
            st.write("🤖 2/3 · 8개 에이전트 병렬 분석 중 (Technical · Quant · Risk · ML · Event · Geopolitical · Value · Decision)...")
            # 8개 에이전트 병렬 LLM 호출. 백엔드 MULTI_AGENT_TIMEOUT(기본 600s)보다 약간 더 길게.
            multi_result = api_get(f"/multi-agent/{resolved_ticker}", timeout=660)

            # API 실패 시 사용자 친화적 안내
            if multi_result is None:
                st.write("⚠️ Multi-Agent API 서버에 연결할 수 없어 단일 LLM 결과만 표시합니다.")
                multi_result = {
                    "error": "멀티에이전트 API에 연결할 수 없습니다. chart_agent_service가 실행 중인지 확인하세요.",
                    "final_decision": {
                        "final_signal": "N/A",
                        "final_confidence": 0,
                        "consensus": "API 서버 미응답"
                    }
                }
            else:
                st.write("✅ 3/3 · 결과 수집 완료, 렌더링 중...")
            status.update(label=f"✅ {analysis_label} 분석 완료", state="complete", expanded=False)

            st.session_state.multi_agent_result = {
                "ticker": resolved_ticker,
                "single": single_result if single_result else {},
                "multi": multi_result,
                "timestamp": datetime.now().isoformat()
            }

    # 결과 표시
    if "multi_agent_result" in st.session_state:
        result = st.session_state.multi_agent_result
        ticker = result["ticker"]
        ticker_name = get_ticker_display_name(ticker)
        single = result.get("single", {})
        multi = result.get("multi", {})

        # === 비교 카드 ===
        st.markdown(f"### 📊 {ticker_name} ({ticker}) — Single LLM vs Multi-Agent 비교")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("""
            <div class="summary-card">
                <div style="font-size:0.7rem; color:var(--on-surface-variant); margin-bottom:8px;">Single LLM (V1.0)</div>
                <div style="font-size:1.8rem; font-family:'JetBrains Mono'; font-weight:700; margin-bottom:12px;">
                    {}
                </div>
                <div style="font-size:0.8rem; color:var(--on-surface-variant);">
                    점수: <span style="color:{};">{:+.2f}</span> / {}: {}/10
                </div>
                <div style="margin-top:12px; font-size:0.7rem; opacity:0.6;">
                    {}개 도구 분석 → 단일 LLM 판단
                </div>
            </div>
            """.format(
                single.get("final_signal", "?"),
                "var(--buy)" if single.get("composite_score", 0) > 0 else "var(--sell)" if single.get("composite_score", 0) < 0 else "var(--outline)",
                single.get("composite_score", 0),
                _confidence_label((single.get("final_signal") or "").upper()),
                single.get("confidence", 0),
                len(single.get("tool_summaries") or []) or 17,
            ), unsafe_allow_html=True)

        with col2:
            # multi가 None이거나 error가 있는 경우 처리
            if multi is None:
                multi = {"error": "Multi-Agent API not available"}

            final_decision = multi.get("final_decision", {})

            # API 에러가 있는 경우 에러 표시
            if "error" in multi:
                st.markdown("""
                <div class="summary-card" style="border:2px solid var(--error);">
                    <div style="font-size:0.7rem; color:var(--error); margin-bottom:8px;">Multi-Agent (V2.0) ⚠️</div>
                    <div style="font-size:1.2rem; font-family:'JetBrains Mono'; font-weight:700; margin-bottom:12px; color:var(--error);">
                        API 연결 실패
                    </div>
                    <div style="font-size:0.8rem; color:var(--on-surface-variant);">
                        Multi-Agent 서버가 응답하지 않습니다
                    </div>
                    <div style="margin-top:12px; font-size:0.7rem; opacity:0.6;">
                        chart_agent_service가 실행 중인지 확인하세요
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                # 에이전트 개수 자동 감지 (하드코딩 대신 실제 데이터 기반)
                agent_count_actual = len(multi.get("agent_results", []))
                valid_count = final_decision.get("valid_agent_count", agent_count_actual)
                excluded_count = final_decision.get("excluded_failed_count", 0)
                agent_detail = f"{agent_count_actual}개 에이전트"
                if excluded_count:
                    agent_detail += f" (유효 {valid_count}, 실패 {excluded_count} 제외)"

                # 신호 라벨 (HOLD/neutral일 경우 '관망 확신도' 표기)
                multi_sig = (final_decision.get("final_signal") or "").upper()
                multi_conf = final_decision.get("final_confidence", 0)
                conf_label = _confidence_label(multi_sig)

                st.markdown("""
                <div class="summary-card" style="border:2px solid var(--primary-ctr);">
                    <div style="font-size:0.7rem; color:var(--primary); margin-bottom:8px;">Multi-Agent (V2.0) ⭐</div>
                    <div style="font-size:1.8rem; font-family:'JetBrains Mono'; font-weight:700; margin-bottom:12px;">
                        {}
                    </div>
                    <div style="font-size:0.8rem; color:var(--on-surface-variant);">
                        {}: {:.1f}/10 | 의견: {}
                    </div>
                    <div style="margin-top:12px; font-size:0.7rem; opacity:0.6;">
                        {} 병렬 분석 → Decision Maker 종합
                    </div>
                </div>
                """.format(
                    final_decision.get("final_signal", "?"),
                    conf_label,
                    multi_conf,
                    final_decision.get("consensus", "?"),
                    agent_detail,
                ), unsafe_allow_html=True)

        # === 신뢰도 갭 경고 (개선 #1) ===
        if not multi.get("error"):
            _render_confidence_gap_warning(single, final_decision)

        # === 에이전트 의견 ===
        st.markdown("### 👥 에이전트 의견")

        if multi.get("error"):
            st.error(f"멀티에이전트 분석 오류: {multi['error']}")
            return

        agent_results = multi.get("agent_results", [])

        for agent in agent_results:
            agent_name = agent.get("agent", "?")
            signal = agent.get("signal", "neutral")
            confidence = agent.get("confidence", 0)
            reasoning = agent.get("reasoning", "")
            llm = agent.get("llm_provider", "?")
            exec_time = agent.get("execution_time", 0)
            error = agent.get("error")

            # 신호 색상
            if signal == "buy":
                signal_color = "var(--buy)"
                signal_icon = "📈"
            elif signal == "sell":
                signal_color = "var(--sell)"
                signal_icon = "📉"
            else:
                signal_color = "var(--hold)"
                signal_icon = "➖"

            # 에러 표시
            status_icon = "✓" if not error else "✗"
            status_color = "var(--agent-success)" if not error else "var(--agent-error)"

            with st.expander(f"{status_icon} **{agent_name}**: {signal_icon} {signal.upper()} ({confidence:.1f}/10) — {llm} [{exec_time:.1f}s]"):
                if error:
                    st.error(f"에러: {error}")
                else:
                    st.markdown(f"**판단 근거:**\n\n{reasoning}")

                # 신뢰도 바
                st.progress(confidence / 10.0)

        # === Decision Maker 종합 ===
        st.markdown("### 🎯 Decision Maker 최종 판단")

        # 최종 신호와 신뢰도
        col1, col2, col3 = st.columns(3)
        with col1:
            signal = final_decision.get('final_signal', 'N/A').upper()
            color = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}.get(signal, "⚪")
            st.metric("최종 신호", f"{color} {signal}")
        with col2:
            confidence = final_decision.get('final_confidence', 0)
            # HOLD/NEUTRAL일 때 "관망 확신도"로 라벨 분리
            st.metric(_confidence_label(signal), f"{confidence:.1f}/10")
        with col3:
            st.metric("의견 분포", final_decision.get('consensus', 'N/A'))

        # 의견 충돌 해결
        st.markdown("#### 의견 충돌 해결")
        conflicts = final_decision.get('conflicts', 'N/A')
        st.info(conflicts)

        # 종합 판단 근거
        st.markdown("#### 종합 판단 근거")
        reasoning = final_decision.get('reasoning', 'N/A')
        st.write(reasoning)

        # 핵심 리스크
        st.markdown("#### ⚠️ 핵심 리스크")
        risks = final_decision.get('key_risks', [])
        if risks:
            for risk in risks:
                st.write(f"• {risk}")
        else:
            st.write("• 리스크 정보 없음")

        # === 진입 계획 (매매 시점/분할/손절익절) ===
        entry_plan = final_decision.get("entry_plan")
        if entry_plan:
            st.markdown("### 📋 실전 진입 계획")

            # 진입 보류 케이스
            if entry_plan.get("entry_timing") == "wait":
                st.warning("⏸ **진입 보류 권장**")
                for note in entry_plan.get("notes", []):
                    st.write(f"• {note}")
            else:
                # 주요 레벨 요약
                is_kr = ticker.upper().endswith(".KS") or ticker.upper().endswith(".KQ")
                currency = "₩" if is_kr else "$"
                fmt = (lambda v: f"{currency}{v:,.0f}") if is_kr else (lambda v: f"{currency}{v:,.2f}")

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    order_type_kr = {"market": "시장가", "limit": "지정가", "wait": "대기"}.get(
                        entry_plan.get("order_type"), entry_plan.get("order_type", "?")
                    )
                    timing_kr = {"immediate": "즉시", "pullback": "풀백 대기",
                                 "breakout_confirm": "돌파 확인", "wait": "대기"}.get(
                        entry_plan.get("entry_timing"), entry_plan.get("entry_timing", "?")
                    )
                    st.metric("주문 유형", f"{order_type_kr}", delta=timing_kr, delta_color="off")
                with col2:
                    lp = entry_plan.get("limit_price")
                    st.metric("진입가", fmt(lp) if lp else "—")
                with col3:
                    sl = entry_plan.get("stop_loss")
                    st.metric("🛑 손절", fmt(sl) if sl else "—")
                with col4:
                    tp = entry_plan.get("take_profit")
                    st.metric("🎯 익절", fmt(tp) if tp else "—")

                # 분할 진입 표
                splits = entry_plan.get("split_entry") or []
                if splits:
                    st.markdown("**📊 분할 진입 전략**")
                    split_rows = []
                    for i, s in enumerate(splits, 1):
                        price_str = fmt(s["price"]) if s.get("price") else "—"
                        split_rows.append({
                            "차수": f"{i}차",
                            "비중": f"{s.get('pct', 0)}%",
                            "진입가": price_str,
                            "트리거": s.get("trigger", ""),
                        })
                    st.dataframe(split_rows, use_container_width=True, hide_index=True)

                # 기타 정보
                col_a, col_b = st.columns(2)
                with col_a:
                    days = entry_plan.get("expected_holding_days")
                    if days:
                        st.info(f"⏱ **예상 보유 기간**: {days}일")
                with col_b:
                    inv = entry_plan.get("invalidation_price")
                    if inv:
                        st.error(f"🚨 **무효화 가격**: {fmt(inv)} (이 가격 이하면 분석 무효)")

                # 참고 사항
                if entry_plan.get("notes"):
                    with st.expander("📝 참고 사항", expanded=False):
                        for note in entry_plan["notes"]:
                            st.write(f"• {note}")

                # === 가상 매수 연동 (Virtual Trade 페이지로 프리필) ===
                st.markdown("---")
                vt_col1, vt_col2 = st.columns([2, 1])
                with vt_col1:
                    st.caption(
                        "💡 이 진입 계획으로 가상 거래를 추적하시려면 아래 버튼을 누르세요. "
                        "Virtual Trade 페이지에서 수량을 조정하고 최종 확인 후 체결됩니다."
                    )
                with vt_col2:
                    final_signal = (final_decision.get("final_signal") or "").upper()
                    disabled = final_signal != "BUY" or entry_plan.get("entry_timing") == "wait"
                    if st.button(
                        "📝 이 계획대로 가상 매수",
                        use_container_width=True, type="primary",
                        disabled=disabled,
                        help="Virtual Trade 페이지로 이동 (가격/손절/익절 자동 입력됨)"
                        if not disabled
                        else "매수 신호가 아니거나 진입 보류 상태입니다",
                    ):
                        # 세션에 프리필 저장
                        st.session_state.vt_prefill = {
                            "ticker": ticker,
                            "price": entry_plan.get("limit_price"),
                            "stop_loss": entry_plan.get("stop_loss"),
                            "take_profit": entry_plan.get("take_profit"),
                            "reason": (
                                f"Multi-Agent {final_signal} "
                                f"신뢰도 {final_decision.get('final_confidence', 0):.1f}/10"
                            ),
                        }
                        st.success("✅ Virtual Trade 페이지로 이동하세요 (좌측 네비게이션)")
                        st.info("💡 사이드바 → Virtual Trade 를 클릭")

        # === 실행 통계 ===
        st.markdown("### 📈 실행 통계")

        # 에이전트 수 자동 감지 (응답에서 추출)
        total_agents = final_decision.get("agent_count") or len(multi.get("agent_results") or [])
        valid_agents = final_decision.get("valid_agent_count", total_agents)
        excluded = final_decision.get("excluded_failed_count", 0)
        dist = final_decision.get("signal_distribution", {})

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if excluded:
                st.metric("에이전트", f"{valid_agents}/{total_agents}",
                          delta=f"실패 {excluded}명 제외", delta_color="off")
            else:
                st.metric("에이전트 수", total_agents)
        with col2:
            st.metric("BUY 의견", dist.get("buy", 0))
        with col3:
            st.metric("SELL 의견", dist.get("sell", 0))
        with col4:
            st.metric("실행 시간", f"{multi.get('total_execution_time', 0):.1f}s")

        # === Export 기능 ===
        st.markdown("### 💾 분석 결과 Export")

        # Export 데이터 준비
        export_data = {
            "analysis_info": {
                "ticker": ticker,
                "analyzed_at": multi.get('analyzed_at', datetime.now().isoformat()),
                "total_execution_time": multi.get('total_execution_time', 0)
            },
            "single_llm_analysis": {
                "final_signal": single.get("final_signal"),
                "composite_score": single.get("composite_score"),
                "confidence": single.get("confidence"),
                "llm_interpretation": single.get("llm_interpretation")
            },
            "multi_agent_analysis": {
                "final_decision": final_decision,
                "agent_results": multi.get("agent_results", [])
            },
            "tool_analysis_results": single.get("tool_results", {})
        }

        col1, col2, col3 = st.columns(3)

        with col1:
            # JSON Export
            json_str = json.dumps(export_data, indent=2, ensure_ascii=False)
            st.download_button(
                label="📄 JSON으로 다운로드",
                data=json_str,
                file_name=f"{ticker}_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True
            )

        with col2:
            # CSV Export (요약 정보)
            summary_df = pd.DataFrame([{
                "Ticker": ticker,
                "분석시간": multi.get('analyzed_at', ''),
                "Single LLM 신호": single.get("final_signal", "N/A"),
                "Single LLM 점수": single.get("composite_score", 0),
                "Multi-Agent 신호": final_decision.get('final_signal', 'N/A'),
                "Multi-Agent 신뢰도": final_decision.get('final_confidence', 0),
                "Buy 의견": dist.get("buy", 0),
                "Sell 의견": dist.get("sell", 0),
                "Neutral 의견": dist.get("neutral", 0),
                "실행시간(초)": multi.get('total_execution_time', 0)
            }])

            csv_str = summary_df.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📊 CSV로 다운로드",
                data=csv_str,
                file_name=f"{ticker}_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )

        with col3:
            # Markdown Report Export
            markdown_report = f"""# {ticker} 주식 분석 리포트

## 📅 분석 정보
- **종목**: {ticker}
- **분석 일시**: {multi.get('analyzed_at', 'N/A')}
- **총 실행 시간**: {multi.get('total_execution_time', 0):.1f}초

## 🎯 분석 결과 요약

### Single LLM Analysis (V1.0)
- **최종 신호**: {single.get("final_signal", "N/A")}
- **종합 점수**: {single.get("composite_score", 0):+.2f}
- **{_confidence_label((single.get("final_signal") or "").upper())}**: {single.get("confidence", 0)}/10

### Multi-Agent Analysis (V2.0)
- **최종 신호**: {final_decision.get('final_signal', 'N/A')}
- **{_confidence_label((final_decision.get('final_signal') or '').upper())}**: {final_decision.get('final_confidence', 0)}/10
- **의견 분포**: Buy({dist.get("buy", 0)}), Sell({dist.get("sell", 0)}), Neutral({dist.get("neutral", 0)})
- **에이전트**: 총 {total_agents}명 (유효 {valid_agents}, 실패 제외 {excluded})

## 📊 에이전트별 분석 결과
"""
            for agent in multi.get("agent_results", []):
                markdown_report += f"""
### {agent['agent']}
- **신호**: {agent['signal']}
- **신뢰도**: {agent['confidence']}/10
- **LLM**: {agent['llm_provider']}
- **판단 근거**: {agent['reasoning'][:200]}...
"""

            markdown_report += f"""
## 🎯 최종 판단 근거
{final_decision.get('reasoning', 'N/A')}

## ⚠️ 핵심 리스크
"""
            for risk in final_decision.get('key_risks', []):
                markdown_report += f"- {risk}\n"

            markdown_report += f"""
---
*생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Stock AI Multi-Agent Analysis System v2.0*
"""

            st.download_button(
                label="📝 Markdown으로 다운로드",
                data=markdown_report,
                file_name=f"{ticker}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown",
                use_container_width=True
            )


# ═══════════════════════════════════════════════════════════════
#  신호 정확도 페이지 (Sprint 2)
# ═══════════════════════════════════════════════════════════════

def render_signal_accuracy():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">📈 Signal Accuracy</div>
        <div class="page-subtitle">신호별 사후 적중률 · 신뢰도 칼리브레이션 상태</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 컨트롤 ─────────────────────────────────────
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    with col1:
        horizon = st.selectbox("평가 기간", [7, 14, 30], index=0, help="신호 후 N일 수익률 기준")
    with col2:
        min_conf = st.slider("최소 신뢰도", 0.0, 10.0, 0.0, step=0.5)
    with col3:
        signal_filter = st.selectbox("신호 필터", ["전체", "buy", "sell", "neutral"], index=0)
    with col4:
        days_back = st.selectbox("조회 기간", [30, 90, 180, 365], index=2,
                                  format_func=lambda x: f"최근 {x}일")

    sig_param = None if signal_filter == "전체" else signal_filter

    # 수동 평가 실행 버튼
    col_refresh, col_eval = st.columns([1, 1])
    with col_refresh:
        if st.button("🔄 새로고침", use_container_width=True):
            st.cache_data.clear() if hasattr(st, "cache_data") else None
            st.rerun()
    with col_eval:
        if st.button("⚡ 과거 신호 재평가 실행", use_container_width=True,
                     help="아직 평가 안 된 과거 스캔의 결과를 지금 계산"):
            with st.spinner("평가 중..."):
                eval_result = api_post("/signal-accuracy/evaluate?days_back=45&limit=500")
                if eval_result and isinstance(eval_result, dict):
                    ev = eval_result.get("evaluation", {})
                    st.success(
                        f"✓ 처리: {ev.get('processed', 0)}건, "
                        f"업데이트: {ev.get('updated', 0)}건, "
                        f"엔트리 없음: {ev.get('skipped_no_entry', 0)}건"
                    )
                    calib = eval_result.get("calibrator")
                    if calib:
                        st.info(
                            f"칼리브레이터 — active: {calib.get('active')}, "
                            f"표본: {calib.get('total_samples')}건"
                        )
                else:
                    st.error("평가 실행 실패 — API 서버 확인")

    st.divider()

    # ── 통계 조회 ──────────────────────────────────
    url = (
        f"/signal-accuracy?horizon={horizon}&min_confidence={min_conf}"
        f"&days_back={days_back}"
    )
    if sig_param:
        url += f"&signal={sig_param}"
    data = api_get(url)

    if not data or data.get("total_evaluated", 0) == 0:
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">📊</div>
            <div class="es-text">평가된 신호가 아직 없습니다.<br>
            최소 7일 경과한 스캔 데이터가 있어야 합니다.<br>
            '과거 신호 재평가 실행' 버튼으로 수동 실행할 수 있습니다.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    # ── 핵심 지표 카드 ───────────────────────────
    total = data.get("total_evaluated", 0)
    win_rate = data.get("win_rate_pct", 0)
    avg_return = data.get("avg_return_pct", 0)
    wins = data.get("win_count", 0)
    losses = data.get("loss_count", 0)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("평가 건수", f"{total:,}")
    with c2:
        delta = "" if wins == 0 else f"{wins}승 / {losses}패"
        st.metric("적중률", f"{win_rate:.1f}%", delta=delta, delta_color="off")
    with c3:
        color = "normal" if avg_return >= 0 else "inverse"
        st.metric("평균 수익", f"{avg_return:+.2f}%")
    with c4:
        # 간단한 baseline 비교: 랜덤(33%)보다 얼마나 나은지
        edge = win_rate - 33.3
        st.metric("랜덤 대비 엣지", f"{edge:+.1f}%p",
                  delta="우수" if edge > 10 else ("보통" if edge > 0 else "부진"),
                  delta_color="normal" if edge > 0 else "inverse")

    # ── 신호별 분포 ─────────────────────────────
    st.markdown("### 신호별 적중률")
    by_signal = data.get("by_signal", {})
    sig_cols = st.columns(3)
    for i, sig in enumerate(["buy", "sell", "neutral"]):
        s = by_signal.get(sig, {})
        with sig_cols[i]:
            n = s.get("total", 0)
            wr = s.get("win_rate_pct", 0)
            avg_r = s.get("avg_return_pct", 0)
            icon = {"buy": "🟢", "sell": "🔴", "neutral": "⚪"}.get(sig, "")
            if n > 0:
                st.markdown(f"""
                <div class="summary-card">
                    <div style="font-size:0.7rem; color:var(--on-surface-variant);">{icon} {sig.upper()}</div>
                    <div style="font-size:1.8rem; font-weight:700;">{wr:.1f}%</div>
                    <div style="font-size:0.8rem; color:var(--on-surface-variant);">
                        n={n} · 평균수익 {avg_r:+.2f}%
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="summary-card" style="opacity:0.5;">
                    <div style="font-size:0.7rem;">{icon} {sig.upper()}</div>
                    <div style="font-size:1rem;">데이터 없음</div>
                </div>
                """, unsafe_allow_html=True)

    # ── 신뢰도 구간별 ───────────────────────────
    st.markdown("### 신뢰도 구간별 적중률")
    bands = data.get("by_confidence_band", [])
    if bands:
        band_table = []
        for b in bands:
            if b["total"] > 0:
                band_table.append({
                    "구간": b["band"],
                    "건수": b["total"],
                    "적중": b["wins"],
                    "적중률": f"{b['win_rate_pct']:.1f}%",
                    "평균 수익": f"{b['avg_return_pct']:+.2f}%",
                })
        if band_table:
            st.dataframe(band_table, use_container_width=True, hide_index=True)

            # 차트: bar chart - 신뢰도별 적중률
            try:
                import plotly.graph_objects as _go
                x = [b["band"] for b in bands if b["total"] > 0]
                y = [b["win_rate_pct"] for b in bands if b["total"] > 0]
                ns = [b["total"] for b in bands if b["total"] > 0]
                fig = _go.Figure()
                fig.add_trace(_go.Bar(
                    x=x, y=y,
                    text=[f"{v:.1f}%<br>n={n}" for v, n in zip(y, ns)],
                    textposition="outside",
                    marker_color=["#ef4444" if v < 50 else "#eab308" if v < 60 else "#10b981" for v in y],
                ))
                fig.add_hline(y=50, line_dash="dash", line_color="gray",
                              annotation_text="랜덤 기준선 (50%)")
                fig.update_layout(
                    title=f"{horizon}일 horizon · 신뢰도 구간별 적중률",
                    xaxis_title="신뢰도 구간",
                    yaxis_title="적중률 (%)",
                    yaxis=dict(range=[0, 100]),
                    height=400,
                    margin=dict(l=40, r=20, t=50, b=40),
                )
                st.plotly_chart(fig, use_container_width=True)
            except Exception:
                pass
        else:
            st.info("구간별 데이터가 아직 부족합니다.")
    else:
        st.info("신뢰도 구간별 데이터 없음")

    # ── 칼리브레이터 상태 ───────────────────────
    st.markdown("### 🎯 신뢰도 칼리브레이터 상태")
    calib_data = api_get("/signal-accuracy/calibrator")
    if calib_data:
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            active = calib_data.get("active", False)
            st.metric("활성화 여부",
                      "✅ ON" if active else "⏸ OFF",
                      delta="자동 보정 중" if active else "표본 축적 중",
                      delta_color="off")
        with cc2:
            samples = calib_data.get("total_samples", 0)
            min_req = calib_data.get("min_required", 50)
            st.metric("누적 표본", f"{samples}",
                      delta=f"최소 {min_req}건 필요" if samples < min_req else "충족")
        with cc3:
            last = calib_data.get("last_refit")
            last_str = last[:19] if last else "미실행"
            st.metric("마지막 학습", last_str)

        cal_signals = calib_data.get("signals_calibrated", [])
        if cal_signals:
            st.success(f"보정 적용 신호: {', '.join(cal_signals)}")
        else:
            st.warning("아직 칼리브레이션 학습 전 (raw confidence 사용 중)")
    else:
        st.warning("API 서버에 연결할 수 없습니다")


# ═══════════════════════════════════════════════════════════════
#  Screener 페이지 (V1 — 한국 주식 기술적 스크리너)
# ═══════════════════════════════════════════════════════════════

def render_screener():
    """
    매일 장 마감 후 한국 시총 2,000억+ 종목에서 기술적 점수 상위 20개 발굴.

    설계 원칙:
    - Watchlist 자동 등록 안 함 (사용자 명시 선택 시에만)
    - Multi-Agent 분석과 독립 (스크리너 = 후보 발굴, Multi-Agent = 심층 분석)
    - 결과는 screener_results 테이블에만 저장 (scan_log 오염 방지)
    """
    st.markdown("""
    <div class="page-header">
        <div class="page-title">📡 Screener · 한국 주식</div>
        <div class="page-subtitle">기술적 신호 기반 매수 후보 발굴 (시총 2,000억+ · 상위 20개)</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 상단 컨트롤 ─────────────────────────────
    c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
    with c1:
        min_cap_bn = st.number_input(
            "최소 시총 (억원)",
            min_value=100, max_value=100_000, value=2000, step=100,
            help="이 값 이상의 종목만 분석 대상"
        )
    with c2:
        top_n = st.number_input(
            "상위 N개",
            min_value=5, max_value=100, value=20, step=5,
        )
    with c3:
        analyze_top = st.number_input(
            "자동 심층",
            min_value=0, max_value=20, value=5, step=1,
            help="상위 N개 중 Multi-Agent 자동 분석할 개수 (0=안 함)"
        )
    with c4:
        run_now = st.button(
            "▶ 스크리너만" if analyze_top == 0 else f"🚀 스크리너 + Multi-Agent {analyze_top}개",
            type="primary", use_container_width=True,
        )

    # ── 실행 (스크리너 단독 or 파이프라인) ─────────
    if run_now:
        est_total = 120 + (analyze_top * 60) if analyze_top > 0 else 120
        est_min = est_total // 60
        est_s = est_total % 60
        est_str = f"{est_min}분 {est_s}초" if est_min else f"{est_s}초"

        if analyze_top == 0:
            # 스크리너만
            with st.status("한국 주식 스크리너 실행 중...", expanded=True) as status:
                st.write(f"🔍 시총 {min_cap_bn:,}억원+ 종목 로딩...")
                result = api_post(
                    f"/screener/run?min_market_cap_bn={min_cap_bn}&top_n={top_n}",
                    timeout=900,
                )
                if result and "error" not in result:
                    st.write(f"✅ 유니버스 {result['universe_size']}개")
                    st.write(f"✅ {result['analyzed_count']}개 점수 완료 ({result['elapsed_seconds']:.0f}s)")
                    status.update(label="✅ 스크리너 완료", state="complete", expanded=False)
                    st.session_state.screener_result = result
                else:
                    st.error(f"실행 실패: {(result or {}).get('error', 'API 응답 없음')}")
        else:
            # 파이프라인 (스크리너 + Multi-Agent)
            with st.status(
                f"🚀 파이프라인 실행 중 (예상 {est_str})...",
                expanded=True,
            ) as status:
                st.write("📡 1/2 · 스크리너로 후보 선별 중...")
                st.write(f"   시총 {min_cap_bn:,}억원+ · 상위 {top_n}개")
                st.write(f"🤖 2/2 · 상위 {analyze_top}개 Multi-Agent 심층 분석...")
                st.write(f"   (병렬 실행, {analyze_top}개 × 약 60s ÷ WORKERS)")

                result = api_post(
                    f"/screener/pipeline?min_market_cap_bn={min_cap_bn}"
                    f"&top_n={top_n}&analyze_top={analyze_top}",
                    timeout=1800,
                )
                if result and "error" not in result:
                    st.write(f"✅ 스크리너 {result['elapsed_seconds']:.0f}s")
                    st.write(f"✅ Multi-Agent {result.get('multi_agent_elapsed_seconds', 0):.0f}s")
                    st.write(f"✅ 총 소요 {result.get('total_elapsed_seconds', 0):.0f}s")
                    status.update(label="✅ 파이프라인 완료", state="complete", expanded=False)
                    st.session_state.screener_result = result
                    st.session_state.screener_has_pipeline = True
                else:
                    st.error(f"파이프라인 실패: {(result or {}).get('error', 'API 응답 없음')}")

    # ── 최신 결과 로드 (실행 안 했으면 DB에서) ──
    data = None
    if "screener_result" in st.session_state:
        data = st.session_state.screener_result
        st.caption(f"세션 실행 결과: {data.get('run_id', '?')}")
    else:
        data = api_get("/screener/latest?limit=100")
        if data and data.get("count", 0) > 0:
            st.caption(f"DB 최근 실행: {data.get('scanned_at', '')[:19]} (run_id: {data.get('run_id')})")
        else:
            st.info("📭 스크리너 실행 기록 없음. 위 '▶ 지금 실행' 버튼으로 시작하세요.")
            st.markdown("""
            **매일 자동 실행**: 평일 15:35 KST (장 마감 후)
            **분석 기준**: MACD · 이동평균 · RSI · 거래량 · 20일선 지지 (총 100점)
            **감점 항목**: 데드크로스 · 과매수 · 거래량↓ · 장기 역행
            **주의**: 스크리너 결과는 **매수 제안**일 뿐, Multi-Agent 심층 분석을 거쳐 최종 판단하세요.
            """)
            return

    results = data.get("results", [])
    if not results:
        st.warning("결과 없음")
        return

    # ── 요약 통계 ─────────────────────────────
    st.markdown("### 📊 결과 요약")
    s_count = sum(1 for r in results if r.get("grade") == "S")
    a_count = sum(1 for r in results if r.get("grade") == "A")
    b_count = sum(1 for r in results if r.get("grade") == "B")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("총 후보", len(results))
    m2.metric("S 등급", s_count)
    m3.metric("A 등급", a_count)
    m4.metric("B 등급", b_count)

    if s_count == 0 and a_count == 0:
        st.warning("⚠️ S/A 등급 없음 — 현재 시장이 약세이거나 조건 완화 필요")

    # ── 결과 테이블 ───────────────────────────
    st.markdown("### 🏆 상위 종목 리스트")
    rows = []
    for r in results:
        cap_bn = (r.get("market_cap") or 0) / 1e8
        grade_emoji = {"S": "⭐⭐", "A": "⭐", "B": "•", "C": "·", "D": ""}.get(r.get("grade"), "")
        ticker = r.get("ticker", "")
        rows.append({
            "순위": r.get("rank", 0),
            "등급": f"{grade_emoji} {r.get('grade', '?')}",
            "종목": r.get("name", "?"),
            "티커": ticker,
            "시장": r.get("market", ""),
            "점수": r.get("score", 0),
            "시총(억)": f"{cap_bn:,.0f}",
            "현재가": _fmt_price(r.get('current_price', 0), ticker),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # ── 파이프라인 뷰 (스크리너 + Multi-Agent 합의도) ──
    combined = data.get("combined_view")
    if combined:
        st.markdown("### 🔗 스크리너 × Multi-Agent 합의도 분석")
        st.caption(
            f"상위 {data.get('analyzed_top', 0)}개 Multi-Agent 심층 분석 완료. "
            f"Multi-Agent 소요 {data.get('multi_agent_elapsed_seconds', 0):.0f}s"
        )

        # 합의도 통계 카드
        stats = data.get("agreement_stats", {})
        ag_cols = st.columns(5)
        labels = {
            "strong_match":    ("🟢🟢 강한 일치", "스크리너↑ + MA 매수"),
            "partial_match":   ("🟢 부분 일치", "스크리너↑ + MA 보수적"),
            "conflict":        ("⚠️ 신호 충돌", "스크리너↑ vs MA 매도"),
            "unexpected_buy":  ("🟡 이례적 매수", "스크리너↓ + MA 매수"),
            "aligned_weak":    ("⚪ 동반 약세", "둘 다 약한 후보"),
        }
        for i, (key, (label, desc)) in enumerate(labels.items()):
            count = stats.get(key, 0)
            with ag_cols[i]:
                st.metric(label, count, help=desc)

        # 파이프라인 상세 테이블
        pipe_rows = []
        for e in combined:
            agreement = e.get("agreement") or {}
            if not e.get("multi_agent_analyzed") and agreement.get("level") == "pending":
                # 미분석 항목은 회색으로
                pipe_rows.append({
                    "순위": e["rank"],
                    "합의": agreement.get("emoji", "⏳"),
                    "종목": e.get("name", "?"),
                    "스크리너": f"{e['screener_score']}점 ({e['screener_grade']})",
                    "MA 신호": "—",
                    "MA 확신": "—",
                    "Entry": "—",
                })
            else:
                ma_sig = (e.get("multi_agent_signal") or "?").upper()
                ma_conf = e.get("multi_agent_confidence", 0)
                entry = e.get("entry_plan") or {}
                entry_str = "—"
                if entry and entry.get("limit_price"):
                    entry_str = f"₩{entry['limit_price']:,.0f}"
                pipe_rows.append({
                    "순위": e["rank"],
                    "합의": f"{agreement.get('emoji', '')} {agreement.get('label', '')}",
                    "종목": e.get("name", "?"),
                    "스크리너": f"{e['screener_score']}점 ({e['screener_grade']})",
                    "MA 신호": ma_sig,
                    "MA 확신": f"{ma_conf:.1f}/10",
                    "Entry": entry_str,
                })

        st.dataframe(pipe_rows, use_container_width=True, hide_index=True)

        # 🟢🟢 강한 일치만 별도 하이라이트
        strong = [e for e in combined if (e.get("agreement") or {}).get("level") == "strong_match"]
        if strong:
            st.markdown("#### 🎯 최우선 관심 종목 (강한 일치)")
            for e in strong:
                ag = e.get("agreement", {})
                entry_plan = e.get("entry_plan") or {}
                with st.expander(
                    f"{ag.get('emoji','')} **{e.get('name')}** ({e['ticker']}) — "
                    f"스크리너 {e['screener_score']}점 {e['screener_grade']}등급 / "
                    f"MA {(e.get('multi_agent_signal') or '').upper()} "
                    f"{e.get('multi_agent_confidence', 0):.1f}/10",
                    expanded=True,
                ):
                    st.info(ag.get("description", ""))
                    if e.get("multi_agent_reasoning"):
                        st.markdown(f"**Multi-Agent 판단 근거**: {e['multi_agent_reasoning']}")
                    if entry_plan:
                        ep_cols = st.columns(4)
                        lp = entry_plan.get("limit_price")
                        sl = entry_plan.get("stop_loss")
                        tp = entry_plan.get("take_profit")
                        ep_cols[0].metric("진입가", f"₩{lp:,.0f}" if lp else "—")
                        ep_cols[1].metric("손절", f"₩{sl:,.0f}" if sl else "—")
                        ep_cols[2].metric("익절", f"₩{tp:,.0f}" if tp else "—")
                        ep_cols[3].metric("보유일", f"{entry_plan.get('expected_holding_days', '?')}일")

    # ── 개별 종목 상세 (점수 분해) ──────────────
    st.markdown("### 🔎 종목별 점수 분해")
    options = [f"{i+1}. {r['name']} ({r['ticker']}) — {r['score']}점" for i, r in enumerate(results)]
    selected_idx = st.selectbox("상세 보기 종목 선택", range(len(options)), format_func=lambda i: options[i])

    sel = results[selected_idx]
    breakdown = sel.get("breakdown") or {}
    penalties = sel.get("penalties") or []

    # breakdown은 JSON 문자열일 수 있음 (DB에서 조회된 경우)
    if isinstance(breakdown, str):
        import json as _json
        try:
            breakdown = _json.loads(breakdown)
        except Exception:
            breakdown = {}
    if isinstance(penalties, str):
        import json as _json
        try:
            penalties = _json.loads(penalties)
        except Exception:
            penalties = []

    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown("**✅ 득점 항목**")
        if breakdown:
            for k, v in breakdown.items():
                if isinstance(v, dict):
                    pts = v.get("points", 0)
                    reason = v.get("reason", "")
                    st.write(f"  +{pts:.1f}점 · {k}: {reason}")
        else:
            st.caption("득점 항목 없음")

    with sc2:
        st.markdown("**❌ 감점 항목**")
        if penalties:
            for p in penalties:
                if isinstance(p, dict):
                    pts = p.get("points", 0)
                    reason = p.get("reason", "")
                    st.write(f"  {pts:.1f}점 · {p.get('name','?')}: {reason}")
        else:
            st.caption("감점 항목 없음")

    # ── 액션 버튼 (SSOT 정책 준수: 사용자 명시 선택 시에만) ──
    st.markdown("### 🎯 다음 단계")
    ac1, ac2, ac3 = st.columns(3)
    with ac1:
        if st.button("📋 선택 종목 Watchlist 추가", use_container_width=True, key="screener_add_wl"):
            ok, msg = add_to_watchlist(sel.get("ticker", ""))
            if ok:
                st.success(msg)
            else:
                st.warning(msg)
    with ac2:
        if st.button("🤖 Multi-Agent 심층 분석", use_container_width=True, key="screener_ma"):
            ticker = sel.get("ticker", "")
            with st.spinner(f"{ticker} 심층 분석 중..."):
                r = api_post(f"/scan/{ticker}", timeout=300)
                if r:
                    st.success(f"완료! {ticker} → {r.get('final_signal')} ({r.get('composite_score', 0):+.1f})")
    with ac3:
        if st.button("📝 Virtual Trade 프리필", use_container_width=True, key="screener_vt"):
            # Virtual Trade 페이지의 프리필 세션 변수에 저장
            st.session_state.vt_prefill = {
                "ticker": sel.get("ticker", ""),
                "price": sel.get("current_price"),
                "stop_loss": None,
                "take_profit": None,
                "reason": f"Screener 순위 {sel.get('rank')}위 (점수 {sel.get('score')}, {sel.get('grade')}등급)",
            }
            st.success("✅ Virtual Trade 페이지로 이동하세요 (사이드바에서 선택)")

    # ── 주의 배너 ─────────────────────────────
    st.divider()
    st.caption(
        "⚠️ 스크리너 결과는 **기술적 신호 기반 후보 발굴**입니다. "
        "매수 결정 전 반드시 Multi-Agent 심층 분석 + 본인 판단을 거치세요. "
        "자동 매매 권고가 아닙니다."
    )


# ═══════════════════════════════════════════════════════════════
#  Trading 페이지 (Phase 2.1)
# ═══════════════════════════════════════════════════════════════

def render_trading():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">🛡️ Trading Center</div>
        <div class="page-subtitle">주문 모드 · 안전장치 · 승인 큐 · 감사 로그</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 상단: 현재 모드 + 안전 상태 ───────────────
    mode_data = api_get("/trading/mode")
    if not mode_data:
        st.error("API 서버에 연결할 수 없습니다. chart_agent_service가 실행 중인지 확인하세요.")
        return

    current_mode = mode_data.get("mode", "paper")
    safety = mode_data.get("safety", {})
    kill_active = safety.get("kill_switch_active", False)

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        mode_desc = {
            "paper": "🟢 PAPER — 시뮬레이션 (안전)",
            "dry_run": "🟡 DRY RUN — 주문 생성·로그만",
            "approval": "🟠 APPROVAL — 승인 후 실행",
            "live": "🔴 LIVE — 실제 자금 이동",
        }
        st.metric("현재 모드", mode_desc.get(current_mode, current_mode))
    with col2:
        st.metric("Kill Switch", "🚨 활성" if kill_active else "✅ 정상")
    with col3:
        broker_health = api_get("/trading/broker-health")
        if broker_health:
            h = broker_health.get("health", {})
            st.metric("브로커", f"{'✅' if h.get('ok') else '❌'} {broker_health.get('broker', '?')}")

    # ── Alpaca 연결 + 데이터 소스 상태 (Phase 2.2) ─
    with st.expander("🔌 증권사 · 데이터 소스 연결 상태", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Alpaca 증권사**")
            alpaca_h = api_get("/trading/broker-health/alpaca")
            if alpaca_h:
                h = alpaca_h.get("health", {})
                if h.get("ok"):
                    st.success(f"✅ {h.get('message', '정상')} ({h.get('latency_ms', 0)}ms)")
                else:
                    st.warning(f"⚠️ {h.get('message', '미연결')}")
            else:
                st.caption("연결 정보 없음")
        with col_b:
            st.markdown("**데이터 소스**")
            ds = api_get("/data-source")
            if ds:
                configured = ds.get("configured", "?")
                active = ds.get("active", "?")
                h = ds.get("health", {})
                if configured != active:
                    st.info(f"설정: **{configured}** → 폴백: **{active}**")
                else:
                    st.markdown(f"활성: **{active}**")
                if h.get("ok"):
                    st.success(f"✅ {h.get('message', '정상')} ({h.get('latency_ms', 0)}ms)")
                else:
                    st.warning(f"⚠️ {h.get('message', '응답 없음')}")

    # ── 모드 변경 ──────────────────────────────
    with st.expander("⚙️ 모드 변경 (주의)", expanded=False):
        new_mode = st.selectbox(
            "TRADING_MODE",
            ["paper", "dry_run", "approval", "live"],
            index=["paper", "dry_run", "approval", "live"].index(current_mode),
        )
        if st.button("모드 적용", type="secondary"):
            resp = api_post(f"/trading/mode?mode={new_mode}")
            if resp and resp.get("ok"):
                st.success(f"모드 변경: {resp.get('mode')}")
                st.rerun()
            else:
                st.error(f"변경 실패: {resp}")

    # ── Kill Switch 제어 ───────────────────────
    col_ks1, col_ks2 = st.columns(2)
    with col_ks1:
        if not kill_active:
            if st.button("🚨 긴급 중지 활성화", type="primary", use_container_width=True):
                resp = api_post("/trading/kill-switch/activate?reason=manual_webui")
                if resp and resp.get("ok"):
                    st.warning("Kill Switch 활성화됨 — 모든 신규 주문 차단")
                    st.rerun()
    with col_ks2:
        if kill_active:
            if st.button("✅ 긴급 중지 해제", use_container_width=True):
                resp = api_post("/trading/kill-switch/deactivate?reason=manual_webui")
                if resp and resp.get("ok"):
                    st.success("Kill Switch 해제됨")
                    st.rerun()

    st.divider()

    # ── 일일 한도 사용량 ────────────────────────
    st.markdown("### 💰 일일 주문 한도 사용량")
    limits = safety.get("daily_limits", {})
    col_us, col_kr = st.columns(2)
    for col, market in [(col_us, "US"), (col_kr, "KR")]:
        with col:
            m = limits.get(market, {})
            spent = m.get("spent", 0)
            limit = m.get("limit", 1)
            pct = min(100, (spent / limit * 100) if limit > 0 else 0)
            currency = "₩" if market == "KR" else "$"
            st.markdown(f"**{market}** — 주문 {m.get('count', 0)}건")
            st.progress(pct / 100)
            st.caption(f"{currency}{spent:,.0f} / {currency}{limit:,.0f} ({pct:.1f}%)")

    st.divider()

    # ── 계좌 및 포지션 ────────────────────────
    st.markdown("### 📊 계좌 상태")
    account = api_get("/trading/account")
    if account:
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            st.metric("총 자산", f"${account.get('total_equity', 0):,.2f}")
        with a2:
            st.metric("현금", f"${account.get('cash', 0):,.2f}")
        with a3:
            pnl = account.get('total_pnl_pct', 0)
            st.metric("수익률", f"{pnl:+.2f}%", delta_color="normal" if pnl >= 0 else "inverse")
        with a4:
            st.metric("포지션", f"{account.get('open_positions', 0)}개")

    positions_data = api_get("/trading/positions")
    if positions_data and positions_data.get("positions"):
        st.markdown("#### 보유 포지션")
        rows = []
        for p in positions_data["positions"]:
            ticker = p.get("ticker", "")
            rows.append({
                "Ticker": ticker,
                "Qty": p.get("qty"),
                "Entry": _fmt_price(p.get("avg_entry_price"), ticker),
                "Current": _fmt_price(p.get("current_price"), ticker),
                "P&L": _fmt_price(p.get("unrealized_pnl"), ticker),
                "P&L %": f"{p.get('unrealized_pnl_pct', 0):+.2f}%",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.divider()

    # ── 승인 대기 큐 (APPROVAL 모드용) ────────
    st.markdown("### 🔔 승인 대기 주문")
    pending_data = api_get("/trading/approval/pending")
    if pending_data:
        pending = pending_data.get("pending", [])
        if pending:
            st.info(f"**{len(pending)}건** 승인 대기 중")
            for p in pending:
                queue_id = p.get("id")
                ticker = p.get("ticker", "?")
                side = p.get("side", "?").upper()
                qty = p.get("qty", 0)
                price = p.get("limit_price")
                price_str = f"@ {_fmt_price(price, ticker)}" if price else "@ 시장가"

                cols = st.columns([4, 1, 1])
                with cols[0]:
                    st.markdown(f"**#{queue_id}** · `{ticker}` {side} {qty}주 {price_str}")
                    st.caption(f"요청: {p.get('requested_at', '')[:19]}")
                with cols[1]:
                    if st.button("✅ 승인", key=f"approve_{queue_id}"):
                        result = api_post(f"/trading/approval/{queue_id}/approve")
                        if result and result.get("executed"):
                            st.success(f"주문 #{queue_id} 실행됨")
                            st.rerun()
                        else:
                            st.error(f"실행 실패: {result}")
                with cols[2]:
                    if st.button("❌ 거절", key=f"reject_{queue_id}"):
                        result = api_post(f"/trading/approval/{queue_id}/reject")
                        if result and result.get("ok"):
                            st.info(f"주문 #{queue_id} 거절됨")
                            st.rerun()
        else:
            st.caption("대기 중인 주문 없음")

    st.divider()

    # ── 최근 주문 감사 로그 ───────────────────
    st.markdown("### 📝 최근 주문 (감사 로그)")
    recent = api_get("/trading/orders/recent?limit=20")
    if recent and recent.get("orders"):
        rows = []
        for o in recent["orders"]:
            status_icon = "✅" if o.get("result_success") else ("🚫" if not o.get("safety_check_passed") else "⚠️")
            ticker = o.get("ticker", "")
            limit_price = o.get("limit_price")
            rows.append({
                "시각": (o.get("created_at") or "")[:19],
                "모드": o.get("trading_mode", ""),
                "Ticker": ticker,
                "Side": o.get("side", "").upper(),
                "Qty": o.get("qty", 0),
                "가격": _fmt_price(limit_price, ticker) if limit_price else "—",
                "결과": f"{status_icon} {o.get('result_status') or o.get('safety_reason', '?')}",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    # 통계
    stats = api_get("/trading/orders/stats?days_back=7")
    if stats:
        st.markdown("#### 7일 통계")
        s1, s2, s3 = st.columns(3)
        with s1:
            st.metric("총 시도", stats.get("total_orders", 0))
        with s2:
            st.metric("안전장치 차단", stats.get("blocked_by_safety", 0))
        with s3:
            by_mode = stats.get("by_trading_mode", {})
            st.caption(f"모드별: {by_mode}")


# ═══════════════════════════════════════════════════════════════
#  Virtual Trade 페이지 — 수동 가상 거래 추적
# ═══════════════════════════════════════════════════════════════

def render_virtual_trade():
    """
    사용자가 결정한 시점·가격·수량으로 가상 매수, 지속 추적.

    흐름:
    1) 종목 입력/선택 → 현재가 자동 조회
    2) 수량/가격/손절/익절/메모 지정 → "가상 매수" 버튼
    3) 포지션 모니터링: 현재가/목표까지 거리/경과일
    4) 부분/전량 청산 또는 자동 청산(trailing/SL/TP)
    """
    st.markdown("""
    <div class="page-header">
        <div class="page-title">📝 Virtual Trade</div>
        <div class="page-subtitle">내가 정한 타이밍으로 가상 매수 · 자동 추적</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 1. 상단 요약 카드 ─────────────────────
    status = api_get("/paper")
    if not status:
        st.error("API 서버 연결 실패 — chart_agent_service 실행 상태 확인")
        return

    c1, c2, c3, c4 = st.columns(4)
    total_equity = status.get("total_equity", 0)
    total_pnl = status.get("total_pnl", 0)
    total_pnl_pct = status.get("total_pnl_pct", 0)
    positions_map = status.get("positions", {})

    c1.metric("총 자산", f"${total_equity:,.2f}")
    c2.metric("현금", f"${status.get('cash', 0):,.2f}")
    c3.metric("손익", f"${total_pnl:+,.2f}",
              delta=f"{total_pnl_pct:+.2f}%",
              delta_color="normal" if total_pnl >= 0 else "inverse")
    c4.metric("열린 포지션", f"{len(positions_map)}개")

    st.divider()

    # ── 2. 가상 매수 폼 ─────────────────────
    st.markdown("### 🛒 가상 매수")

    # 세션 상태 관리
    if "vt_ticker" not in st.session_state:
        st.session_state.vt_ticker = ""
    if "vt_quote" not in st.session_state:
        st.session_state.vt_quote = None

    # 분석 결과에서 프리필된 값이 있는지 확인 (Multi-Agent 페이지에서 넘어온 경우)
    prefill = st.session_state.get("vt_prefill")
    if prefill:
        st.info(
            f"📊 **Multi-Agent 분석 프리필**: "
            f"`{prefill.get('ticker')}` @ ${prefill.get('price', 0):.2f} "
            f"· 손절 ${prefill.get('stop_loss', 0):.2f} · 익절 ${prefill.get('take_profit', 0):.2f}"
        )

    col_buy_a, col_buy_b, col_buy_c = st.columns([2, 1, 1])
    with col_buy_a:
        ticker_input = st.text_input(
            "종목 코드",
            value=(prefill.get("ticker", "") if prefill else st.session_state.vt_ticker),
            placeholder="예: AAPL, 005930.KS",
            key="vt_ticker_input",
        ).strip().upper()
    with col_buy_b:
        if st.button("📡 현재가 조회", use_container_width=True, disabled=not ticker_input):
            quote = api_get(f"/paper/quote/{ticker_input}")
            if quote:
                st.session_state.vt_quote = quote
                st.session_state.vt_ticker = ticker_input
                st.rerun()
            else:
                st.error("현재가 조회 실패")
    with col_buy_c:
        if st.button("🔄 폼 초기화", use_container_width=True):
            st.session_state.vt_quote = None
            st.session_state.vt_ticker = ""
            st.session_state.pop("vt_prefill", None)
            st.rerun()

    quote = st.session_state.vt_quote
    if quote:
        # 현재가 정보 표시
        is_kr = ticker_input.endswith((".KS", ".KQ"))
        currency = "₩" if is_kr else "$"
        qa, qb, qc, qd = st.columns(4)
        qa.metric("현재가", f"{currency}{quote.get('current_price', 0):,.2f}",
                  delta=f"{quote.get('change_pct', 0):+.2f}%")
        qb.metric("당일 고가", f"{currency}{quote.get('day_high', 0):,.2f}")
        qc.metric("당일 저가", f"{currency}{quote.get('day_low', 0):,.2f}")
        qd.metric("호가단위", f"{currency}{quote.get('tick_size', 0):,}")
        st.caption(f"기준 시각: {quote.get('as_of', '')}")

    # 매수 파라미터
    if ticker_input:
        default_price = (
            (prefill.get("price") if prefill else None)
            or (quote.get("current_price") if quote else None)
            or 100.0
        )
        default_sl = (prefill.get("stop_loss") if prefill else 0.0) or 0.0
        default_tp = (prefill.get("take_profit") if prefill else 0.0) or 0.0

        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            buy_qty = st.number_input("수량", min_value=1, value=10, step=1, key="vt_qty")
        with pc2:
            buy_price = st.number_input(
                "진입가 (내가 사려는 가격)",
                min_value=0.001, value=float(default_price), step=0.01, format="%.4f",
                key="vt_price",
            )
        with pc3:
            total_cost = buy_qty * buy_price
            st.metric("총 투자금", f"${total_cost:,.2f}")

        # 손절/익절/trailing 설정 (접이식)
        with st.expander("🛡️ 손절·익절·자동 청산 설정 (선택)", expanded=bool(prefill)):
            sl_col, tp_col, ts_col, td_col = st.columns(4)
            with sl_col:
                stop_loss = st.number_input(
                    "손절가", min_value=0.0, value=float(default_sl),
                    step=0.01, format="%.4f",
                    help="0이면 미설정. 도달 시 자동 청산.",
                )
            with tp_col:
                take_profit = st.number_input(
                    "익절가", min_value=0.0, value=float(default_tp),
                    step=0.01, format="%.4f",
                    help="0이면 미설정. 도달 시 자동 청산.",
                )
            with ts_col:
                trailing_pct = st.number_input(
                    "Trailing Stop %",
                    min_value=0.0, max_value=50.0, value=0.0, step=0.5,
                    help="고점 대비 N% 하락 시 자동 청산. 0이면 미사용.",
                )
            with td_col:
                time_stop = st.number_input(
                    "시간 청산 (일)", min_value=0, max_value=365, value=0, step=1,
                    help="N일 경과 시 자동 청산. 0이면 미사용.",
                )

            # 손절/익절 R/R 표시
            if stop_loss > 0 and buy_price > stop_loss:
                risk = buy_price - stop_loss
                risk_pct = risk / buy_price * 100
                st.caption(f"🛑 손절 거리: **{risk_pct:.2f}%** (${risk:.2f}/주)")
            if take_profit > 0 and take_profit > buy_price:
                reward = take_profit - buy_price
                reward_pct = reward / buy_price * 100
                st.caption(f"🎯 익절 거리: **{reward_pct:.2f}%** (${reward:.2f}/주)")
            if stop_loss > 0 and take_profit > buy_price > stop_loss:
                rr = (take_profit - buy_price) / (buy_price - stop_loss)
                st.caption(f"📐 R/R 비율: **{rr:.2f}** (익절/손절)")

        reason = st.text_input(
            "진입 근거 메모 (선택)",
            value=(prefill.get("reason", "") if prefill else ""),
            placeholder="예: Multi-Agent 신호 buy 7.5/10, RSI 반등",
        )

        # 매수 실행
        if st.button("🛒 **가상 매수 실행**", type="primary", use_container_width=True):
            body = {
                "ticker": ticker_input,
                "qty": int(buy_qty),
                "price": float(buy_price),
                "reason": reason or "수동 가상 매수",
                "stop_loss_price": float(stop_loss) if stop_loss > 0 else None,
                "take_profit_price": float(take_profit) if take_profit > 0 else None,
                "trailing_stop_pct": float(trailing_pct / 100) if trailing_pct > 0 else None,
                "time_stop_days": int(time_stop) if time_stop > 0 else None,
            }
            result = api_post("/paper/virtual-buy", json_body=body)
            if result and result.get("status") == "filled":
                st.success(
                    f"✅ **{ticker_input}** {buy_qty}주 @ {currency if quote else '$'}{buy_price:,.2f} 체결됨 "
                    f"(총 ${total_cost:,.2f})"
                )
                # 프리필 제거
                st.session_state.pop("vt_prefill", None)
                st.session_state.vt_quote = None
                st.balloons()
            else:
                reject = (result or {}).get("reject_reason") or "알 수 없는 오류"
                st.error(f"체결 실패: {reject}")

    st.divider()

    # ── 3. 포지션 모니터링 ─────────────────
    st.markdown("### 📊 포지션 모니터링")
    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 현재가 갱신", use_container_width=True):
            with st.spinner("가격 갱신 중..."):
                update_result = api_post("/paper/update-prices")
            if update_result:
                updated = update_result.get("updated", 0)
                auto_closed = update_result.get("auto_closed", [])
                st.success(f"✅ {updated}개 종목 갱신")
                if auto_closed:
                    st.warning(f"⚠️ {len(auto_closed)}개 포지션 자동 청산됨")
                    for ac in auto_closed:
                        st.write(f"  • {ac.get('ticker')} — {ac.get('reason', '?')}")
            st.rerun()
    with col_info:
        st.caption("손절/익절/trailing/시간 조건이 충족되면 자동으로 청산됩니다.")

    if not positions_map:
        st.info("📭 보유 포지션 없음. 위 폼에서 첫 가상 매수를 시작하세요.")
    else:
        # 포지션을 카드로 표시
        for ticker, p in positions_map.items():
            entry = p.get("entry_price", 0)
            current = p.get("current_price", entry)
            qty = p.get("qty", 0)
            pnl = p.get("pnl", 0)
            pnl_pct = p.get("pnl_pct", 0)
            is_kr = ticker.endswith((".KS", ".KQ"))
            cur = "₩" if is_kr else "$"

            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            # 포지션 헤더에 종목명 포함
            pos_label = format_ticker_label(ticker, style="name_with_code")
            with st.expander(
                f"{pnl_emoji} **{pos_label}** · {qty}주 @ {cur}{entry:,.2f} "
                f"→ {cur}{current:,.2f} ({pnl_pct:+.2f}%)",
                expanded=True,
            ):
                cc1, cc2, cc3, cc4 = st.columns(4)
                cc1.metric("수량", f"{qty}주")
                cc2.metric("진입가", f"{cur}{entry:,.2f}")
                cc3.metric("현재가", f"{cur}{current:,.2f}",
                           delta=f"{pnl_pct:+.2f}%",
                           delta_color="normal" if pnl_pct >= 0 else "inverse")
                cc4.metric("손익", f"{cur}{pnl:+,.2f}")

                # 진입일/경과일
                entry_date = p.get("entry_date", "")
                if entry_date:
                    try:
                        ed = datetime.fromisoformat(entry_date.split(".")[0] if "." in entry_date else entry_date)
                        elapsed = (datetime.now() - ed).days
                        st.caption(f"📅 진입: {entry_date[:10]} · 경과 **{elapsed}일**")
                    except Exception:
                        st.caption(f"📅 진입: {entry_date[:19]}")

                # 부분/전량 청산
                st.markdown("**청산 실행**")
                cls1, cls2, cls3, cls4, cls5 = st.columns([1, 1, 1, 1, 1])

                def _close(pct: int):
                    body = {"ticker": ticker, "close_pct": float(pct),
                            "reason": f"수동 {pct}% 청산"}
                    r = api_post("/paper/partial-close", json_body=body)
                    if r and r.get("status") == "filled":
                        realized = r.get("pnl", 0)
                        st.success(
                            f"✅ {pct}% 청산됨 — {r.get('qty')}주 @ {cur}{r.get('price', 0):,.2f} · 실현 손익 {cur}{realized:+,.2f}"
                        )
                        st.rerun()
                    else:
                        st.error(f"청산 실패: {(r or {}).get('reject_reason', '?')}")

                if cls1.button("25%", key=f"close25_{ticker}", use_container_width=True):
                    _close(25)
                if cls2.button("50%", key=f"close50_{ticker}", use_container_width=True):
                    _close(50)
                if cls3.button("75%", key=f"close75_{ticker}", use_container_width=True):
                    _close(75)
                if cls4.button("100%", key=f"close100_{ticker}",
                               type="primary", use_container_width=True):
                    _close(100)
                with cls5:
                    custom_price = st.number_input(
                        "지정가 청산", min_value=0.0, value=0.0, step=0.01,
                        key=f"cp_{ticker}", label_visibility="collapsed",
                        placeholder="지정가"
                    )
                    if st.button("매도", key=f"custom_{ticker}", use_container_width=True):
                        if custom_price > 0:
                            body = {"ticker": ticker, "close_pct": 100.0,
                                    "price": float(custom_price),
                                    "reason": f"수동 지정가 {custom_price} 청산"}
                            r = api_post("/paper/partial-close", json_body=body)
                            if r and r.get("status") == "filled":
                                st.success(f"✅ 지정가 {cur}{custom_price:,.2f} 청산")
                                st.rerun()

                # 손절/익절 표시 (있으면)
                sl = p.get("stop_loss_price", 0)
                tp = p.get("take_profit_price", 0)
                ts = p.get("trailing_stop_pct", 0)
                tsd = p.get("time_stop_days", 0)
                if sl or tp or ts or tsd:
                    st.markdown("**자동 청산 조건**")
                    lines = []
                    if sl:
                        dist = (current - sl) / current * 100
                        lines.append(f"🛑 손절 {cur}{sl:,.2f} (현재가 대비 {dist:+.2f}%)")
                    if tp:
                        dist = (tp - current) / current * 100
                        lines.append(f"🎯 익절 {cur}{tp:,.2f} (현재가 대비 {dist:+.2f}%)")
                    if ts:
                        peak = p.get("peak_price", current)
                        trail_price = peak * (1 - ts)
                        lines.append(f"📉 Trailing {ts*100:.1f}% · 고점 {cur}{peak:,.2f} → 트리거 {cur}{trail_price:,.2f}")
                    if tsd:
                        lines.append(f"⏱ 시간 청산 {tsd}일")
                    for line in lines:
                        st.caption(line)

    st.divider()

    # ── 4. 최근 청산 이력 ─────────────────
    st.markdown("### 📋 최근 청산 이력")
    recent = status.get("recent_trades", [])
    if recent:
        rows = []
        for t in reversed(recent[-20:]):
            is_win = t.get("pnl", 0) > 0
            tkr = t.get("ticker", "?")
            name = get_ticker_display_name(tkr)
            rows.append({
                "종목명": name if name and name != tkr else "—",
                "티커": tkr,
                "수량": t.get("qty", 0),
                "진입가": f"${t.get('entry_price', 0):.2f}",
                "청산가": f"${t.get('exit_price', 0):.2f}",
                "손익": f"${t.get('pnl', 0):+.2f}",
                "수익률": f"{t.get('pnl_pct', 0):+.2f}%",
                "결과": "🟢 WIN" if is_win else "🔴 LOSS",
                "사유": t.get("reason", "")[:40],
                "청산일": (t.get("exit_date", "") or "")[:10],
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("아직 청산된 거래 없음")


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
elif page == "Multi-Agent":
    render_multi_agent()
elif page == "Scan Log":
    render_scan_log()
elif page == "Signal Accuracy":
    render_signal_accuracy()
elif page == "Screener":
    render_screener()
elif page == "Trading":
    render_trading()
elif page == "Virtual Trade":
    render_virtual_trade()
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
