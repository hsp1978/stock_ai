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

# ═══════════════════════════════════════════════════════════════
#  페이지 설정
# ═══════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Stock Analysis Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 다크 테마 CSS
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .metric-card {
        background: #1a1d23;
        border-radius: 10px;
        padding: 15px;
        border-left: 4px solid #444;
    }
    .buy-card { border-left-color: #26a69a !important; }
    .sell-card { border-left-color: #ef5350 !important; }
    .hold-card { border-left-color: #ffd700 !important; }
    .signal-buy { color: #26a69a; font-size: 24px; font-weight: bold; }
    .signal-sell { color: #ef5350; font-size: 24px; font-weight: bold; }
    .signal-hold { color: #ffd700; font-size: 24px; font-weight: bold; }
    .score-positive { color: #26a69a; }
    .score-negative { color: #ef5350; }
    div[data-testid="stSidebar"] { background-color: #1a1d23; }
    .index-card {
        background: #1a1d23;
        border-radius: 8px;
        padding: 12px 14px;
        border-left: 3px solid #444;
        margin-bottom: 4px;
    }
    .index-card .idx-name {
        color: #999;
        font-size: 11px;
        margin-bottom: 2px;
        letter-spacing: 0.5px;
    }
    .index-card .idx-price {
        color: #e0e0e0;
        font-size: 18px;
        font-weight: 700;
        margin-bottom: 1px;
    }
    .index-card .idx-change-up {
        color: #26a69a;
        font-size: 13px;
        font-weight: 600;
    }
    .index-card .idx-change-down {
        color: #ef5350;
        font-size: 13px;
        font-weight: 600;
    }
    .index-card .idx-change-flat {
        color: #888;
        font-size: 13px;
        font-weight: 600;
    }
    .idx-section-title {
        color: #888;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 1px;
        margin-bottom: 6px;
        padding-bottom: 4px;
        border-bottom: 1px solid #2a2d33;
    }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
#  시장 지수 데이터 수집
# ═══════════════════════════════════════════════════════════════

# 지수 정의: (yfinance 티커, 표시명, 소수점 자릿수)
MARKET_INDICES = {
    "us_market": {
        "title": "US MARKET",
        "items": [
            ("^GSPC", "S&P 500", 2),
            ("^IXIC", "NASDAQ", 2),
            ("^DJI", "DOW", 2),
        ],
    },
    "kr_market": {
        "title": "KR MARKET",
        "items": [
            ("^KS11", "KOSPI", 2),
            ("^KQ11", "KOSDAQ", 2),
            ("USDKRW=X", "USD/KRW", 2),
        ],
    },
    "commodities": {
        "title": "COMMODITIES",
        "items": [
            ("GC=F", "Gold", 2),
            ("SI=F", "Silver", 2),
            ("HG=F", "Copper", 3),
            ("NG=F", "Nat Gas", 2),
        ],
    },
}


@st.cache_data(ttl=300)  # 5분 캐시
def fetch_market_indices() -> dict:
    """주요 시장 지수 현재가 및 등락률 수집"""
    results = {}
    all_tickers = []
    for group in MARKET_INDICES.values():
        for sym, name, decimals in group["items"]:
            all_tickers.append(sym)

    try:
        data = yf.download(
            all_tickers,
            period="5d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception:
        return results

    for group_key, group in MARKET_INDICES.items():
        for sym, name, decimals in group["items"]:
            try:
                if len(all_tickers) == 1:
                    close_series = data['Close']
                else:
                    close_series = data['Close'][sym]

                close_series = close_series.dropna()
                if len(close_series) < 2:
                    continue

                price = float(close_series.iloc[-1])
                prev = float(close_series.iloc[-2])
                change = price - prev
                change_pct = (change / prev) * 100

                results[sym] = {
                    "name": name,
                    "price": price,
                    "change": change,
                    "change_pct": change_pct,
                    "decimals": decimals,
                    "group": group_key,
                }
            except Exception:
                continue

    return results


# ═══════════════════════════════════════════════════════════════
#  API 호출 함수
# ═══════════════════════════════════════════════════════════════

def api_get(path: str, timeout: int = 10):
    """에이전트 API GET 요청"""
    try:
        resp = httpx.get(f"{AGENT_API_URL}{path}", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except Exception as e:
        st.error(f"API 오류: {e}")
        return None


def api_post(path: str, timeout: int = 300):
    """에이전트 API POST 요청"""
    try:
        resp = httpx.post(f"{AGENT_API_URL}{path}", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except Exception as e:
        st.error(f"API 오류: {e}")
        return None


def get_chart_url(ticker: str) -> str:
    return f"{AGENT_API_URL}/chart/{ticker}"


# ═══════════════════════════════════════════════════════════════
#  사이드바
# ═══════════════════════════════════════════════════════════════

with st.sidebar:
    st.title("📊 Stock Agent")

    # 서비스 상태
    health = api_get("/health")
    if health:
        ollama_status = health.get("ollama", "disconnected")
        cached = health.get("cached_results", 0)
        scans = health.get("scan_count", 0)

        col1, col2 = st.columns(2)
        col1.metric("Ollama", "🟢" if ollama_status == "connected" else "🔴")
        col2.metric("캐시", f"{cached}종목")
        st.caption(f"스캔 횟수: {scans}회")
    else:
        st.error(f"에이전트 연결 실패\n{AGENT_API_URL}")

    st.divider()

    # 서비스 정보
    info = api_get("/")
    if info:
        st.caption(f"모델: {info.get('model', '?')}")
        st.caption(f"스캔 주기: {info.get('scan_interval', '?')}")
        st.caption(f"매수 임계: ≥{info.get('thresholds', {}).get('buy', '?')}")
        st.caption(f"매도 임계: ≤{info.get('thresholds', {}).get('sell', '?')}")
        last_scan = info.get("last_scan", "")
        if last_scan:
            st.caption(f"마지막 스캔: {last_scan[:16]}")

    st.divider()

    # 즉시 스캔
    st.subheader("수동 스캔")
    scan_ticker = st.text_input("종목 티커", placeholder="AAPL")
    col1, col2 = st.columns(2)
    if col1.button("종목 스캔", use_container_width=True):
        if scan_ticker:
            with st.spinner(f"{scan_ticker.upper()} 분석 중..."):
                result = api_post(f"/scan/{scan_ticker.upper()}")
                if result:
                    st.success(f"{scan_ticker.upper()}: {result.get('final_signal')} ({result.get('composite_score', 0):+.1f})")
                    st.rerun()
    if col2.button("전체 스캔", use_container_width=True):
        with st.spinner("전체 watchlist 스캔 중..."):
            api_post("/scan")
            st.rerun()

    st.divider()

    # 페이지 선택
    page = st.radio("페이지", ["대시보드", "종목 상세", "스캔 히스토리"], label_visibility="collapsed")


# ═══════════════════════════════════════════════════════════════
#  대시보드 페이지
# ═══════════════════════════════════════════════════════════════

def _render_index_card(info: dict) -> str:
    """단일 지수 카드 HTML 생성"""
    price = info["price"]
    decimals = info["decimals"]
    change = info["change"]
    change_pct = info["change_pct"]

    # 가격 포맷
    price_str = f"{price:,.{decimals}f}"

    # 등락 포맷
    if change_pct > 0:
        arrow = "▲"
        css_class = "idx-change-up"
    elif change_pct < 0:
        arrow = "▼"
        css_class = "idx-change-down"
    else:
        arrow = "−"
        css_class = "idx-change-flat"

    change_str = f"{arrow} {abs(change):,.{decimals}f} ({abs(change_pct):.2f}%)"

    # 카드 좌측 보더 색상
    if change_pct > 0:
        border_color = "#26a69a"
    elif change_pct < 0:
        border_color = "#ef5350"
    else:
        border_color = "#444"

    return f"""
    <div class="index-card" style="border-left-color: {border_color};">
        <div class="idx-name">{info['name']}</div>
        <div class="idx-price">{price_str}</div>
        <div class="{css_class}">{change_str}</div>
    </div>
    """


def render_market_indices():
    """대시보드 상단에 시장 지수 표시"""
    indices = fetch_market_indices()
    if not indices:
        return

    # 3개 그룹을 3개 컬럼으로 배치
    cols = st.columns(3)

    for col_idx, (group_key, group) in enumerate(MARKET_INDICES.items()):
        with cols[col_idx]:
            st.markdown(f'<div class="idx-section-title">{group["title"]}</div>', unsafe_allow_html=True)
            for sym, name, decimals in group["items"]:
                info = indices.get(sym)
                if info:
                    st.markdown(_render_index_card(info), unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div class="index-card">
                        <div class="idx-name">{name}</div>
                        <div class="idx-price" style="color: #555;">-</div>
                        <div class="idx-change-flat">데이터 없음</div>
                    </div>
                    """, unsafe_allow_html=True)

    st.divider()


def render_dashboard():
    st.header("📊 에이전트 대시보드")

    # 시장 지수 표시
    render_market_indices()

    data = api_get("/results")
    if not data or not data.get("results"):
        st.info("분석 결과 없음. 사이드바에서 스캔을 실행하세요.")
        return

    results = data["results"]

    # 신호별 분류
    buy_list = {k: v for k, v in results.items() if v.get("signal") == "BUY"}
    sell_list = {k: v for k, v in results.items() if v.get("signal") == "SELL"}
    hold_list = {k: v for k, v in results.items() if v.get("signal") == "HOLD"}

    # 상단 요약 카드
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("전체 종목", len(results))
    col2.metric("🟢 매수", len(buy_list))
    col3.metric("🔴 매도", len(sell_list))
    col4.metric("🟡 관망", len(hold_list))

    st.divider()

    # 종목 테이블
    rows = []
    for ticker, r in sorted(results.items(), key=lambda x: x[1].get("score", 0), reverse=True):
        dist = r.get("signal_distribution", {})
        rows.append({
            "종목": ticker,
            "신호": r.get("signal", "?"),
            "점수": r.get("score", 0),
            "신뢰도": r.get("confidence", 0),
            "매수": dist.get("buy", 0),
            "매도": dist.get("sell", 0),
            "중립": dist.get("neutral", 0),
            "분석시간": str(r.get("analyzed_at", ""))[:16],
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return

    # 점수 바 차트
    fig = go.Figure()
    colors = ["#26a69a" if s > 0 else "#ef5350" if s < 0 else "#888" for s in df["점수"]]
    fig.add_trace(go.Bar(
        x=df["점수"],
        y=df["종목"],
        orientation='h',
        marker_color=colors,
        text=[f"{s:+.1f} ({sig})" for s, sig in zip(df["점수"], df["신호"])],
        textposition="outside",
        textfont=dict(color="white"),
    ))
    fig.update_layout(
        title="종목별 종합 점수",
        template="plotly_dark",
        height=max(300, len(df) * 50),
        xaxis=dict(range=[-10, 10], title="Score"),
        yaxis=dict(autorange="reversed"),
        margin=dict(l=80, r=120, t=40, b=30),
    )
    fig.add_vline(x=0, line_color="#666", line_width=1)
    st.plotly_chart(fig, use_container_width=True)

    # 테이블
    st.dataframe(
        df.style.map(
            lambda v: "color: #26a69a" if v == "BUY" else ("color: #ef5350" if v == "SELL" else "color: #ffd700"),
            subset=["신호"]
        ),
        use_container_width=True,
        hide_index=True,
    )


# ═══════════════════════════════════════════════════════════════
#  종목 상세 페이지
# ═══════════════════════════════════════════════════════════════

def render_detail():
    st.header("🔍 종목 상세 분석")

    # 종목 선택
    data = api_get("/results")
    if not data or not data.get("results"):
        st.info("분석 결과 없음.")
        return

    tickers = sorted(data["results"].keys())
    selected = st.selectbox("종목 선택", tickers)

    if not selected:
        return

    detail = api_get(f"/results/{selected}")
    if not detail:
        st.error(f"{selected} 상세 조회 실패")
        return

    # 상단 요약
    signal = detail.get("final_signal", "?")
    score = detail.get("composite_score", 0)
    confidence = detail.get("confidence", 0)
    dist = detail.get("signal_distribution", {})

    signal_class = {"BUY": "signal-buy", "SELL": "signal-sell"}.get(signal, "signal-hold")
    score_class = "score-positive" if score > 0 else "score-negative"

    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(f"### <span class='{signal_class}'>{signal}</span>", unsafe_allow_html=True)
    col2.metric("종합 점수", f"{score:+.2f}")
    col3.metric("신뢰도", f"{confidence}/10")
    col4.metric("분석 도구", f"{detail.get('tool_count', 0)}개")

    st.divider()

    # 12개 기법 스코어
    summaries = detail.get("tool_summaries", [])
    if summaries:
        st.subheader("12개 분석 기법 결과")

        col_chart, col_table = st.columns([3, 2])

        with col_chart:
            names = [s["name"] for s in summaries]
            scores = [s["score"] for s in summaries]
            bar_colors = ["#26a69a" if s > 0 else "#ef5350" if s < 0 else "#888" for s in scores]

            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=names,
                x=scores,
                orientation='h',
                marker_color=bar_colors,
                text=[f"{s:+.1f}" for s in scores],
                textposition="outside",
                textfont=dict(color="white"),
            ))
            fig.update_layout(
                template="plotly_dark",
                height=450,
                xaxis=dict(range=[-10, 10], title="Score"),
                yaxis=dict(autorange="reversed"),
                margin=dict(l=120, r=60, t=10, b=30),
            )
            fig.add_vline(x=0, line_color="#666", line_width=1)
            st.plotly_chart(fig, use_container_width=True)

        with col_table:
            tool_rows = []
            for s in summaries:
                emoji = "🟢" if s["signal"] == "buy" else ("🔴" if s["signal"] == "sell" else "🟡")
                tool_rows.append({
                    "": emoji,
                    "기법": s["name"],
                    "신호": s["signal"],
                    "점수": s["score"],
                    "요약": s.get("detail", "")[:50],
                })
            st.dataframe(pd.DataFrame(tool_rows), use_container_width=True, hide_index=True, height=450)

    st.divider()

    # 에이전트 차트 이미지
    st.subheader("분석 차트")
    chart_url = get_chart_url(selected)
    try:
        resp = httpx.get(chart_url, timeout=5)
        if resp.status_code == 200:
            st.image(resp.content, use_container_width=True)
        else:
            st.caption("차트 이미지 없음")
    except Exception:
        st.caption("차트 로드 실패")

    st.divider()

    # LLM 종합 판단
    llm = detail.get("llm_conclusion", "")
    if llm and not llm.startswith("[오류]") and not llm.startswith("[LLM"):
        st.subheader("LLM 종합 판단")
        st.markdown(llm)

    st.divider()

    # 12개 기법 상세 데이터
    tool_details = detail.get("tool_details", [])
    if tool_details:
        with st.expander("12개 기법 상세 데이터 (JSON)", expanded=False):
            for td in tool_details:
                st.json(td)


# ═══════════════════════════════════════════════════════════════
#  스캔 히스토리 페이지
# ═══════════════════════════════════════════════════════════════

def render_history():
    st.header("📜 스캔 히스토리")

    data = api_get("/history?limit=20")
    if not data or not data.get("history"):
        st.info("히스토리 없음.")
        return

    history = data["history"]
    st.caption(f"전체 {data.get('count', 0)}회 중 최근 {len(history)}회")

    for i, entry in enumerate(reversed(history)):
        ts = entry.get("timestamp", "")[:16]
        tickers = entry.get("tickers", [])
        results = entry.get("results", {})
        alerts = entry.get("alerts", [])

        with st.expander(f"**{ts}** — {len(tickers)}종목 스캔" + (f" ⚡ 알림 {len(alerts)}건" if alerts else ""), expanded=(i == 0)):
            if not results:
                st.caption("결과 없음")
                continue

            rows = []
            for ticker, r in sorted(results.items(), key=lambda x: x[1].get("score", 0), reverse=True):
                signal = r.get("signal", "?")
                emoji = "🟢" if signal == "BUY" else ("🔴" if signal == "SELL" else "🟡")
                alert_mark = " ⚡" if ticker in alerts else ""
                rows.append({
                    "종목": f"{emoji} {ticker}{alert_mark}",
                    "신호": signal,
                    "점수": r.get("score", 0),
                    "신뢰도": r.get("confidence", 0),
                })

            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════
#  라우팅
# ═══════════════════════════════════════════════════════════════

if page == "대시보드":
    render_dashboard()
elif page == "종목 상세":
    render_detail()
elif page == "스캔 히스토리":
    render_history()
