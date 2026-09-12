"""백테스트 페이지.

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
