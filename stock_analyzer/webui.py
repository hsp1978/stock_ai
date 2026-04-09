#!/usr/bin/env python3
"""
주식 분석 시스템 WebUI (Streamlit)
Mac Studio 에이전트 API 연동 + 전체 리포트 대시보드

실행:
    streamlit run webui.py --server.port 8501
"""
import json
import os
from datetime import datetime

import httpx
import yfinance as yf
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import load_dotenv

load_dotenv()

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


def api_get(path: str, timeout: int = 10):
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
    return f"{AGENT_API_URL}/chart/{ticker}"


def load_watchlist() -> list[str]:
    if not os.path.exists(WATCHLIST_PATH):
        return []
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        return [
            line.strip().upper()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]


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
    scan_ticker = st.text_input("Ticker", placeholder="AAPL", label_visibility="collapsed")
    col1, col2 = st.columns(2)
    if col1.button("Scan", use_container_width=True):
        if scan_ticker:
            with st.spinner(f"Analyzing {scan_ticker.upper()}..."):
                result = api_post(f"/scan/{scan_ticker.upper()}")
                if result:
                    st.success(f"{scan_ticker.upper()}: {result.get('final_signal')} ({result.get('composite_score', 0):+.1f})")
                    st.rerun()
    if col2.button("Scan All", use_container_width=True):
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

    st.markdown('<div class="sidebar-section-label">Watchlist</div>', unsafe_allow_html=True)
    watchlist = load_watchlist()

    if watchlist:
        wl_chips = " ".join(f'<span class="wl-chip">{t}</span>' for t in watchlist)
        st.markdown(f'<div style="margin-bottom:8px; line-height:2;">{wl_chips}</div>', unsafe_allow_html=True)
        st.caption(f"{len(watchlist)} tickers")
    else:
        st.caption("No tickers in watchlist")

    add_ticker = st.text_input("Add ticker", placeholder="TSLA", label_visibility="collapsed", key="wl_add")
    wl_col1, wl_col2 = st.columns(2)
    if wl_col1.button("Add", use_container_width=True, key="wl_add_btn"):
        if add_ticker:
            ok, msg = add_to_watchlist(add_ticker)
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

    page = st.radio("Navigation", ["Home", "Dashboard", "Detail", "History"], label_visibility="collapsed")


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
        st.error(f"Failed to load {selected}")
        return

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
    chart_url = get_chart_url(selected)
    try:
        resp = httpx.get(chart_url, timeout=5)
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
#  라우팅
# ═══════════════════════════════════════════════════════════════

if page == "Home":
    render_home()
elif page == "Dashboard":
    render_dashboard()
elif page == "Detail":
    render_detail()
elif page == "History":
    render_history()
