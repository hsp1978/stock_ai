"""스캔 로그 페이지 — 과거 스캔 기록 조회.

`webui.py` 분해 — 페이지 단위 (CLAUDE.md §6-10). 분리 후 **렌더 함수를 직접
호출**해 확인한다: ast 파싱·import·HTTP 200 은 화면 결함을 잡지 못한다 (§13.9a).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.api_client import api_get
from ui.components import _plotly_base_layout
from ui.tickers import load_watchlist


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
                    lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
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
                    lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
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
                st.dataframe(wt_df, use_container_width=True, row_height=44, hide_index=True)

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
                            line=dict(color="#6D7CFF", width=3),
                            marker=dict(size=10, color="#6D7CFF"),
                        ))
                        fig.add_hline(y=0, line_color="#1F2733", line_width=1)
                        fig.update_layout(**_plotly_base_layout(
                            height=280,
                            margin=dict(l=40, r=10, t=10, b=40),
                            xaxis=dict(gridcolor="#161C25"),
                            yaxis=dict(title="Score", gridcolor="#161C25"),
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
                                lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
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
                        line=dict(color="#6D7CFF", width=2),
                        marker=dict(
                            size=8,
                            color=[
                                "#2BD98A" if s == "BUY" else "#FF6B6B" if s == "SELL" else "#F5B14C"
                                for s in h_df["signal"]
                            ],
                            line=dict(width=1, color="#06080C"),
                        ),
                        text=[f"{s} ({sc:+.1f})" for s, sc in zip(h_df["signal"], h_df["score"])],
                        hovertemplate="%{text}<br>%{x}<extra></extra>",
                    ))
                    fig.add_hline(y=0, line_color="#1F2733", line_width=1)
                    fig.update_layout(**_plotly_base_layout(
                        height=300,
                        margin=dict(l=50, r=10, t=10, b=40),
                        xaxis=dict(gridcolor="#161C25"),
                        yaxis=dict(title="Score", gridcolor="#161C25"),
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
                            lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
                            subset=["Signal"],
                        ),
                        use_container_width=True, hide_index=True,
                    )
