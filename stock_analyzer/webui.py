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

# ═══════════════════════════════════════════════════════════════
#  페이지 설정
# ═══════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Stock AI Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 글로벌 CSS ────────────────────────────────────────────────
st.markdown("""
<style>
    /* ── Base ── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    .stApp {
        background: #0b0e14;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #10141c 0%, #0d1018 100%);
        border-right: 1px solid #1c2030;
    }
    div[data-testid="stSidebar"] .stMarkdown p,
    div[data-testid="stSidebar"] .stMarkdown li {
        font-size: 13px;
    }

    /* ── 기본 텍스트 ── */
    h1, h2, h3 { font-family: 'Inter', sans-serif !important; letter-spacing: -0.02em; }
    .page-title {
        font-size: 26px;
        font-weight: 700;
        color: #f0f2f5;
        margin-bottom: 4px;
        letter-spacing: -0.03em;
    }
    .page-subtitle {
        font-size: 13px;
        color: #5a6270;
        margin-bottom: 24px;
    }

    /* ── 시장 지수 티커 바 ── */
    .ticker-bar {
        display: flex;
        gap: 0;
        background: #111520;
        border: 1px solid #1c2030;
        border-radius: 12px;
        padding: 6px 8px;
        margin-bottom: 24px;
        overflow-x: auto;
    }
    .ticker-item {
        flex: 1;
        min-width: 0;
        padding: 10px 14px;
        text-align: center;
        border-right: 1px solid #1c2030;
        transition: background 0.15s;
    }
    .ticker-item:last-child { border-right: none; }
    .ticker-item:hover { background: #161b28; }
    .ticker-item .t-name {
        font-size: 10px;
        font-weight: 600;
        color: #5a6270;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-bottom: 4px;
    }
    .ticker-item .t-price {
        font-size: 15px;
        font-weight: 700;
        color: #e8eaed;
        font-family: 'JetBrains Mono', monospace;
        letter-spacing: -0.03em;
    }
    .ticker-item .t-change {
        font-size: 11px;
        font-weight: 600;
        margin-top: 2px;
        font-family: 'JetBrains Mono', monospace;
    }
    .t-up { color: #00d4a1; }
    .t-down { color: #ff5370; }
    .t-flat { color: #5a6270; }
    .ticker-group-label {
        writing-mode: vertical-lr;
        text-orientation: mixed;
        font-size: 9px;
        font-weight: 700;
        color: #3a4050;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        padding: 8px 6px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-right: 1px solid #1c2030;
    }

    /* ── 요약 메트릭 카드 ── */
    .summary-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
        margin-bottom: 24px;
    }
    .summary-card {
        background: #111520;
        border: 1px solid #1c2030;
        border-radius: 10px;
        padding: 18px 20px;
        text-align: center;
    }
    .summary-card .sc-label {
        font-size: 11px;
        font-weight: 600;
        color: #5a6270;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-bottom: 8px;
    }
    .summary-card .sc-value {
        font-size: 28px;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
        color: #e8eaed;
    }
    .sc-buy { border-bottom: 3px solid #00d4a1; }
    .sc-sell { border-bottom: 3px solid #ff5370; }
    .sc-hold { border-bottom: 3px solid #ffb347; }
    .sc-total { border-bottom: 3px solid #5b8def; }

    /* ── 상세 시그널 배지 ── */
    .signal-badge {
        display: inline-block;
        padding: 6px 20px;
        border-radius: 6px;
        font-size: 20px;
        font-weight: 700;
        letter-spacing: 1px;
    }
    .signal-badge.buy  { background: rgba(0,212,161,0.12); color: #00d4a1; border: 1px solid rgba(0,212,161,0.25); }
    .signal-badge.sell { background: rgba(255,83,112,0.12); color: #ff5370; border: 1px solid rgba(255,83,112,0.25); }
    .signal-badge.hold { background: rgba(255,179,71,0.12); color: #ffb347; border: 1px solid rgba(255,179,71,0.25); }

    /* ── 상세 메트릭 ── */
    .detail-metrics {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 12px;
        margin-bottom: 20px;
    }
    .dm-card {
        background: #111520;
        border: 1px solid #1c2030;
        border-radius: 10px;
        padding: 16px 20px;
        text-align: center;
    }
    .dm-card .dm-label {
        font-size: 11px;
        font-weight: 600;
        color: #5a6270;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-bottom: 6px;
    }
    .dm-card .dm-value {
        font-size: 22px;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
        color: #e8eaed;
    }

    /* ── 섹션 타이틀 ── */
    .section-title {
        font-size: 15px;
        font-weight: 700;
        color: #c8ccd4;
        margin: 28px 0 14px 0;
        padding-bottom: 8px;
        border-bottom: 1px solid #1c2030;
        letter-spacing: -0.01em;
    }

    /* ── 히스토리 타임스탬프 ── */
    .hist-ts {
        font-family: 'JetBrains Mono', monospace;
        font-size: 13px;
        color: #8890a0;
    }

    /* ── Streamlit 기본 요소 오버라이드 ── */
    .stDivider { opacity: 0.15; }
    div[data-testid="stMetric"] {
        background: #111520;
        border: 1px solid #1c2030;
        border-radius: 10px;
        padding: 14px 18px;
    }
    div[data-testid="stMetric"] label { font-size: 12px !important; color: #5a6270 !important; }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 18px !important;
    }
    .stDataFrame { border-radius: 10px; overflow: hidden; }
    .stSelectbox > div > div { background: #111520 !important; border-color: #1c2030 !important; }
    .stTextInput > div > div > input { background: #111520 !important; border-color: #1c2030 !important; }

    /* ── 사이드바 버튼 ── */
    div[data-testid="stSidebar"] .stButton > button {
        background: #161b28;
        border: 1px solid #252a3a;
        color: #c8ccd4;
        font-weight: 600;
        font-size: 13px;
        transition: all 0.15s;
    }
    div[data-testid="stSidebar"] .stButton > button:hover {
        background: #1e2436;
        border-color: #5b8def;
        color: #e8eaed;
    }

    /* ── Empty state ── */
    .empty-state {
        text-align: center;
        padding: 60px 20px;
        color: #3a4050;
    }
    .empty-state .es-icon { font-size: 48px; margin-bottom: 12px; }
    .empty-state .es-text { font-size: 14px; color: #5a6270; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
#  시장 지수 데이터 수집
# ═══════════════════════════════════════════════════════════════

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
def fetch_market_indices() -> dict:
    """주요 시장 지수 현재가 및 등락률 수집"""
    results = {}
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
        return results

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
    return results


# ═══════════════════════════════════════════════════════════════
#  API 호출 함수
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
#  Watchlist 관리
# ═══════════════════════════════════════════════════════════════

def load_watchlist() -> list[str]:
    """watchlist.txt에서 종목 목록 로드 (주석/빈줄 제외)"""
    if not os.path.exists(WATCHLIST_PATH):
        return []
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        return [
            line.strip().upper()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]


def save_watchlist(tickers: list[str]):
    """watchlist.txt에 종목 목록 저장 (기존 주석 헤더 유지)"""
    header = "# 관심 종목 리스트 (한 줄에 하나, #은 주석)\n# 빈 줄과 주석은 무시됨\n\n"
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        f.write(header)
        for t in tickers:
            f.write(f"{t}\n")


def add_to_watchlist(ticker: str) -> tuple[bool, str]:
    """종목 추가. (성공여부, 메시지) 반환"""
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
    """종목 삭제. (성공여부, 메시지) 반환"""
    ticker = ticker.strip().upper()
    current = load_watchlist()
    if ticker not in current:
        return False, f"{ticker} not found"
    current.remove(ticker)
    save_watchlist(current)
    return True, f"{ticker} removed"


# ═══════════════════════════════════════════════════════════════
#  공통 컴포넌트
# ═══════════════════════════════════════════════════════════════

def _plotly_base_layout(**overrides) -> dict:
    """공통 plotly 레이아웃"""
    base = dict(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0f1319",
        font=dict(family="Inter, sans-serif", color="#8890a0", size=12),
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(gridcolor="#1c2030", zerolinecolor="#1c2030"),
        yaxis=dict(gridcolor="#1c2030", zerolinecolor="#1c2030"),
    )
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════
#  사이드바
# ═══════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown('<div class="page-title">Stock AI Agent</div>', unsafe_allow_html=True)
    st.caption("LLM-powered 16-Tool Analysis")

    # 서비스 상태
    health = api_get("/health")
    if health:
        ollama_status = health.get("ollama", "disconnected")
        cached = health.get("cached_results", 0)
        scans = health.get("scan_count", 0)
        status_color = "#00d4a1" if ollama_status == "connected" else "#ff5370"
        st.markdown(f"""
        <div style="display:flex; gap:16px; margin:12px 0;">
            <div style="flex:1; background:#111520; border:1px solid #1c2030; border-radius:8px; padding:10px 12px; text-align:center;">
                <div style="font-size:10px; color:#5a6270; text-transform:uppercase; letter-spacing:0.5px;">Ollama</div>
                <div style="font-size:14px; font-weight:700; color:{status_color}; margin-top:4px;">{'Online' if ollama_status == 'connected' else 'Offline'}</div>
            </div>
            <div style="flex:1; background:#111520; border:1px solid #1c2030; border-radius:8px; padding:10px 12px; text-align:center;">
                <div style="font-size:10px; color:#5a6270; text-transform:uppercase; letter-spacing:0.5px;">Cached</div>
                <div style="font-size:14px; font-weight:700; color:#e8eaed; margin-top:4px;">{cached}</div>
            </div>
            <div style="flex:1; background:#111520; border:1px solid #1c2030; border-radius:8px; padding:10px 12px; text-align:center;">
                <div style="font-size:10px; color:#5a6270; text-transform:uppercase; letter-spacing:0.5px;">Scans</div>
                <div style="font-size:14px; font-weight:700; color:#e8eaed; margin-top:4px;">{scans}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.error(f"Agent Offline: {AGENT_API_URL}")

    # 서비스 정보
    info = api_get("/")
    if info:
        last_scan = info.get("last_scan", "")
        st.markdown(f"""
        <div style="background:#111520; border:1px solid #1c2030; border-radius:8px; padding:12px 14px; margin:8px 0 16px 0; font-size:12px; color:#8890a0; line-height:1.8;">
            Model: <span style="color:#c8ccd4;">{info.get('model', '?')}</span><br>
            Interval: <span style="color:#c8ccd4;">{info.get('scan_interval', '?')}</span><br>
            Buy &ge; <span style="color:#00d4a1;">{info.get('thresholds', {}).get('buy', '?')}</span>
            &nbsp; Sell &le; <span style="color:#ff5370;">{info.get('thresholds', {}).get('sell', '?')}</span>
            {'<br>Last: <span style="color:#c8ccd4;">' + last_scan[:16] + '</span>' if last_scan else ''}
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # 수동 스캔
    st.markdown('<div style="font-size:12px; font-weight:600; color:#5a6270; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:8px;">Manual Scan</div>', unsafe_allow_html=True)
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
        with st.spinner("Scanning watchlist..."):
            api_post("/scan")
            st.rerun()

    st.divider()

    # Watchlist 관리
    st.markdown('<div style="font-size:12px; font-weight:600; color:#5a6270; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:8px;">Watchlist</div>', unsafe_allow_html=True)

    watchlist = load_watchlist()

    # 현재 종목 표시
    if watchlist:
        wl_chips = " ".join(
            f'<span style="display:inline-block; background:#161b28; border:1px solid #252a3a; border-radius:4px; padding:2px 8px; margin:2px; font-size:12px; font-family:JetBrains Mono,monospace; color:#c8ccd4;">{t}</span>'
            for t in watchlist
        )
        st.markdown(f'<div style="margin-bottom:8px; line-height:1.8;">{wl_chips}</div>', unsafe_allow_html=True)
        st.caption(f"{len(watchlist)} tickers")
    else:
        st.caption("No tickers in watchlist")

    # 추가
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

    # 삭제
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

    # 페이지 선택
    page = st.radio("Navigation", ["Dashboard", "Detail", "History"], label_visibility="collapsed")


# ═══════════════════════════════════════════════════════════════
#  대시보드 페이지
# ═══════════════════════════════════════════════════════════════

def render_market_ticker_bar():
    """시장 지수를 가로 티커 바 형태로 렌더링"""
    indices = fetch_market_indices()
    if not indices:
        return

    html_parts = ['<div class="ticker-bar">']

    for group_key, group in MARKET_INDICES.items():
        html_parts.append(f'<div class="ticker-group-label">{group["title"]}</div>')
        for sym, name, decimals in group["items"]:
            info = indices.get(sym)
            if info:
                pct = info["change_pct"]
                css = "t-up" if pct > 0 else ("t-down" if pct < 0 else "t-flat")
                arrow = "+" if pct > 0 else ""
                html_parts.append(f"""
                <div class="ticker-item">
                    <div class="t-name">{info['name']}</div>
                    <div class="t-price">{info['price']:,.{info['decimals']}f}</div>
                    <div class="t-change {css}">{arrow}{pct:.2f}%</div>
                </div>""")
            else:
                html_parts.append(f"""
                <div class="ticker-item">
                    <div class="t-name">{name}</div>
                    <div class="t-price" style="color:#3a4050;">--</div>
                    <div class="t-change t-flat">N/A</div>
                </div>""")

    html_parts.append('</div>')
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_dashboard():
    st.markdown('<div class="page-title">Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Real-time market overview and agent analysis results</div>', unsafe_allow_html=True)

    # 시장 지수 티커 바
    render_market_ticker_bar()

    data = api_get("/results")
    if not data or not data.get("results"):
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">📡</div>
            <div class="es-text">No analysis results yet. Run a scan from the sidebar.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    results = data["results"]

    # 신호별 분류
    buy_list = {k: v for k, v in results.items() if v.get("signal") == "BUY"}
    sell_list = {k: v for k, v in results.items() if v.get("signal") == "SELL"}
    hold_list = {k: v for k, v in results.items() if v.get("signal") == "HOLD"}

    # 요약 카드
    st.markdown(f"""
    <div class="summary-grid">
        <div class="summary-card sc-total">
            <div class="sc-label">Total</div>
            <div class="sc-value">{len(results)}</div>
        </div>
        <div class="summary-card sc-buy">
            <div class="sc-label">Buy</div>
            <div class="sc-value" style="color:#00d4a1;">{len(buy_list)}</div>
        </div>
        <div class="summary-card sc-sell">
            <div class="sc-label">Sell</div>
            <div class="sc-value" style="color:#ff5370;">{len(sell_list)}</div>
        </div>
        <div class="summary-card sc-hold">
            <div class="sc-label">Hold</div>
            <div class="sc-value" style="color:#ffb347;">{len(hold_list)}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 종목 테이블 데이터
    rows = []
    for ticker, r in sorted(results.items(), key=lambda x: x[1].get("score", 0), reverse=True):
        dist = r.get("signal_distribution", {})
        rows.append({
            "Ticker": ticker,
            "Signal": r.get("signal", "?"),
            "Score": r.get("score", 0),
            "Confidence": r.get("confidence", 0),
            "Buy": dist.get("buy", 0),
            "Sell": dist.get("sell", 0),
            "Neutral": dist.get("neutral", 0),
            "Time": str(r.get("analyzed_at", ""))[:16],
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return

    # 점수 바 차트
    st.markdown('<div class="section-title">Score Overview</div>', unsafe_allow_html=True)

    fig = go.Figure()
    bar_colors = ["#00d4a1" if s > 0 else "#ff5370" if s < 0 else "#3a4050" for s in df["Score"]]
    fig.add_trace(go.Bar(
        x=df["Score"], y=df["Ticker"], orientation='h',
        marker=dict(color=bar_colors, line=dict(width=0)),
        text=[f"{s:+.1f}" for s in df["Score"]],
        textposition="outside",
        textfont=dict(color="#8890a0", size=11, family="JetBrains Mono"),
    ))
    fig.update_layout(**_plotly_base_layout(
        height=max(280, len(df) * 44),
        xaxis=dict(range=[-10, 10], title="", gridcolor="#1c2030", zerolinecolor="#252a3a"),
        yaxis=dict(autorange="reversed", gridcolor="rgba(0,0,0,0)"),
        margin=dict(l=80, r=80, t=8, b=8),
    ))
    fig.add_vline(x=0, line_color="#252a3a", line_width=1)
    st.plotly_chart(fig, use_container_width=True)

    # 종목 테이블
    st.markdown('<div class="section-title">Analysis Results</div>', unsafe_allow_html=True)
    st.dataframe(
        df.style.map(
            lambda v: "color: #00d4a1" if v == "BUY" else ("color: #ff5370" if v == "SELL" else "color: #ffb347"),
            subset=["Signal"]
        ),
        use_container_width=True, hide_index=True,
    )


# ═══════════════════════════════════════════════════════════════
#  종목 상세 페이지
# ═══════════════════════════════════════════════════════════════

def render_detail():
    st.markdown('<div class="page-title">Detail Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">In-depth 16-tool analysis for individual stocks</div>', unsafe_allow_html=True)

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

    # 시그널 배지 + 메트릭
    badge_class = "buy" if signal == "BUY" else ("sell" if signal == "SELL" else "hold")
    score_color = "#00d4a1" if score > 0 else "#ff5370" if score < 0 else "#8890a0"

    st.markdown(f"""
    <div style="display:flex; align-items:center; gap:20px; margin-bottom:20px;">
        <div>
            <div style="font-size:11px; color:#5a6270; text-transform:uppercase; letter-spacing:0.8px; margin-bottom:6px;">Signal</div>
            <div class="signal-badge {badge_class}">{signal}</div>
        </div>
    </div>
    <div class="detail-metrics">
        <div class="dm-card">
            <div class="dm-label">Composite Score</div>
            <div class="dm-value" style="color:{score_color};">{score:+.2f}</div>
        </div>
        <div class="dm-card">
            <div class="dm-label">Confidence</div>
            <div class="dm-value">{confidence}<span style="font-size:14px; color:#5a6270;">/10</span></div>
        </div>
        <div class="dm-card">
            <div class="dm-label">Tools Used</div>
            <div class="dm-value">{tool_count}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 분석 기법 결과
    summaries = detail.get("tool_summaries", [])
    if summaries:
        st.markdown(f'<div class="section-title">Tool Results ({len(summaries)} Tools)</div>', unsafe_allow_html=True)

        col_chart, col_table = st.columns([3, 2])

        with col_chart:
            names = [s["name"] for s in summaries]
            scores = [s["score"] for s in summaries]
            bar_colors = ["#00d4a1" if s > 0 else "#ff5370" if s < 0 else "#3a4050" for s in scores]

            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=names, x=scores, orientation='h',
                marker=dict(color=bar_colors, line=dict(width=0)),
                text=[f"{s:+.1f}" for s in scores],
                textposition="outside",
                textfont=dict(color="#8890a0", size=11, family="JetBrains Mono"),
            ))
            fig.update_layout(**_plotly_base_layout(
                height=max(400, len(summaries) * 34),
                xaxis=dict(range=[-10, 10], title="", gridcolor="#1c2030", zerolinecolor="#252a3a"),
                yaxis=dict(autorange="reversed", gridcolor="rgba(0,0,0,0)"),
                margin=dict(l=160, r=60, t=8, b=8),
            ))
            fig.add_vline(x=0, line_color="#252a3a", line_width=1)
            st.plotly_chart(fig, use_container_width=True)

        with col_table:
            tool_rows = []
            for s in summaries:
                sig = s["signal"]
                color = "#00d4a1" if sig == "buy" else ("#ff5370" if sig == "sell" else "#ffb347")
                tool_rows.append({
                    "Tool": s["name"],
                    "Signal": sig.upper(),
                    "Score": s["score"],
                    "Summary": s.get("detail", "")[:60],
                })
            tdf = pd.DataFrame(tool_rows)
            st.dataframe(
                tdf.style.map(
                    lambda v: "color: #00d4a1" if v == "BUY" else ("color: #ff5370" if v == "SELL" else "color: #ffb347"),
                    subset=["Signal"]
                ),
                use_container_width=True, hide_index=True,
                height=max(400, len(summaries) * 34),
            )

    # 차트 이미지
    st.markdown('<div class="section-title">Chart</div>', unsafe_allow_html=True)
    chart_url = get_chart_url(selected)
    try:
        resp = httpx.get(chart_url, timeout=5)
        if resp.status_code == 200:
            st.image(resp.content, use_container_width=True)
        else:
            st.caption("No chart image available")
    except Exception:
        st.caption("Chart load failed")

    # LLM 종합 판단
    llm = detail.get("llm_conclusion", "")
    if llm and not llm.startswith("[오류]") and not llm.startswith("[LLM"):
        st.markdown('<div class="section-title">LLM Conclusion</div>', unsafe_allow_html=True)
        st.markdown(f"""
        <div style="background:#111520; border:1px solid #1c2030; border-radius:10px; padding:20px 24px; line-height:1.7; color:#c8ccd4; font-size:14px;">
        {llm}
        </div>
        """, unsafe_allow_html=True)

    # 상세 JSON
    tool_details = detail.get("tool_details", [])
    if tool_details:
        with st.expander("Raw Tool Data (JSON)", expanded=False):
            for td in tool_details:
                st.json(td)


# ═══════════════════════════════════════════════════════════════
#  스캔 히스토리 페이지
# ═══════════════════════════════════════════════════════════════

def render_history():
    st.markdown('<div class="page-title">Scan History</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Recent scan results and alert timeline</div>', unsafe_allow_html=True)

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

        alert_badge = f'<span style="background:rgba(255,83,112,0.15); color:#ff5370; padding:2px 8px; border-radius:4px; font-size:11px; margin-left:8px;">{len(alerts)} alerts</span>' if alerts else ""

        with st.expander(f"**{ts}** -- {len(tickers)} tickers{' ' if alerts else ''}", expanded=(i == 0)):
            if alerts:
                st.markdown(alert_badge, unsafe_allow_html=True)
            if not results:
                st.caption("No results")
                continue

            rows = []
            for ticker, r in sorted(results.items(), key=lambda x: x[1].get("score", 0), reverse=True):
                signal = r.get("signal", "?")
                rows.append({
                    "Ticker": ticker,
                    "Signal": signal,
                    "Score": r.get("score", 0),
                    "Confidence": r.get("confidence", 0),
                })

            hdf = pd.DataFrame(rows)
            st.dataframe(
                hdf.style.map(
                    lambda v: "color: #00d4a1" if v == "BUY" else ("color: #ff5370" if v == "SELL" else "color: #ffb347"),
                    subset=["Signal"]
                ),
                use_container_width=True, hide_index=True,
            )


# ═══════════════════════════════════════════════════════════════
#  라우팅
# ═══════════════════════════════════════════════════════════════

if page == "Dashboard":
    render_dashboard()
elif page == "Detail":
    render_detail()
elif page == "History":
    render_history()
