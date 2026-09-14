"""대시보드 페이지 — 워치리스트 일괄 스캔 결과 요약.

`webui.py` 분해 — 페이지 단위 (CLAUDE.md §6-10). 분리 후 **렌더 함수를 직접
호출**해 확인한다: ast 파싱·import·HTTP 200 은 화면 결함을 잡지 못한다 (§13.9a).
"""

from __future__ import annotations

import json
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from datetime import datetime
from ui.api_client import api_get
from ui.components import _plotly_base_layout
from ui.export import export_comprehensive_data
from ui.pages.home import render_market_ticker_bar
from ui.tickers import _market_code, _market_flag, get_ticker_display_name


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
        bar_colors = ["#2BD98A" if s > 0 else "#FF6B6B" if s < 0 else "#2C3745" for s in df["score"]]
        fig.add_trace(go.Bar(
            x=df["score"], y=df["ticker"], orientation='h',
            marker=dict(color=bar_colors, line=dict(width=0)),
            text=[f"{s:+.1f}" for s in df["score"]],
            textposition="outside",
            textfont=dict(color="#6A7482", size=11, family="JetBrains Mono"),
        ))
        fig.update_layout(**_plotly_base_layout(
            height=max(280, len(df) * 52),
            xaxis=dict(range=[-10, 10], title="", gridcolor="#161C25", zerolinecolor="#161C25"),
            yaxis=dict(
                autorange="reversed", gridcolor="rgba(0,0,0,0)",
                tickfont=dict(family="JetBrains Mono", size=12, color="#EDF1F7"),
            ),
            margin=dict(l=70, r=60, t=8, b=8),
        ))
        fig.add_vline(x=0, line_color="#1F2733", line_width=1)
        st.plotly_chart(fig, use_container_width=True)

    with col_table:
        st.markdown('<div class="section-title">Analysis Execution Results</div>', unsafe_allow_html=True)

        display_df = df[["ticker", "signal", "score", "confidence"]].rename(columns={
            "ticker": "Ticker", "signal": "Signal", "score": "Score", "confidence": "Confidence",
        })
        st.dataframe(
            display_df.style.map(
                lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
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
