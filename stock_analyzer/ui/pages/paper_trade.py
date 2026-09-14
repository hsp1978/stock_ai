"""페이퍼 트레이딩 페이지.

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
    pnl_color = "#2BD98A" if total_pnl >= 0 else "#FF6B6B"
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
