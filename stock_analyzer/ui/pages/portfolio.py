"""포트폴리오 페이지 — 최적 비중·상관.

`webui.py` 분해 — 페이지 단위 (CLAUDE.md §6-10). 분리 후 **렌더 함수를 직접 호출**해
확인한다: 테스트·ruff·HTTP 200 은 화면 결함을 잡지 못한다 (§13.9a).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.api_client import api_get, api_post
from ui.components import _plotly_base_layout, _quant_signal_style, _signal_pill_html
from ui.format import _fmt_price


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
                    marker=dict(colors=["#6D7CFF", "#2BD98A", "#FF6B6B", "#F5B14C", "#9BA6B5", "#6D7CFF"]),
                    textfont=dict(color="#EDF1F7"),
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
#  퀀트 지표 전용 분석 페이지
# ═══════════════════════════════════════════════════════════════
