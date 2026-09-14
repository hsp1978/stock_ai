"""종목 상세 페이지 — 도구별 원시 출력과 차트.

`webui.py` 분해 — 페이지 단위 (CLAUDE.md §6-10). 분리 후 **렌더 함수를 직접
호출**해 확인한다: ast 파싱·import·HTTP 200 은 화면 결함을 잡지 못한다 (§13.9a).
"""

from __future__ import annotations

import httpx
import json
import os
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from datetime import datetime
from ui.api_client import USE_LOCAL_ENGINE, api_get, get_chart_url, log_action
from ui.components import _plotly_base_layout
from ui.export import export_comprehensive_data
from ui.format import _fmt_num, _fmt_price
from ui.tickers import format_ticker_label


def _render_tool_detail_card(td: dict, ticker: str = ""):
    tool_name = td.get("tool", "")
    name = td.get("name", tool_name)
    sig = td.get("signal", "neutral")
    sc = td.get("score", 0)
    detail_text = td.get("detail", "")
    sig_color = "#2BD98A" if sig == "buy" else ("#FF6B6B" if sig == "sell" else "#F5B14C")

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
    log_action("page_view", page="detail")
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
    selected = st.selectbox(
        "Select Ticker",
        tickers,
        format_func=lambda ticker: format_ticker_label(ticker, "flag_name_code"),
        label_visibility="collapsed",
    )
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
        bar_colors = ["#2BD98A" if s > 0 else "#FF6B6B" if s < 0 else "#2C3745" for s in scores]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=names, x=scores, orientation='h',
            marker=dict(color=bar_colors, line=dict(width=0)),
            text=[f"{s:+.1f}" for s in scores],
            textposition="outside",
            textfont=dict(color="#6A7482", size=11, family="JetBrains Mono"),
        ))
        fig.update_layout(**_plotly_base_layout(
            height=max(400, len(summaries) * 38),
            xaxis=dict(range=[-10, 10], title="", gridcolor="#161C25", zerolinecolor="#161C25"),
            yaxis=dict(
                autorange="reversed", gridcolor="rgba(0,0,0,0)",
                tickfont=dict(family="JetBrains Mono, monospace", size=11, color="#9BA6B5"),
            ),
            margin=dict(l=200, r=60, t=8, b=8),
        ))
        fig.add_vline(x=0, line_color="#1F2733", line_width=1)
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
    if USE_LOCAL_ENGINE:
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
