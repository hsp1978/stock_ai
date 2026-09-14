"""분석 이력 페이지.

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
                    lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
                    subset=["Signal"],
                ),
                use_container_width=True, hide_index=True,
            )


# ═══════════════════════════════════════════════════════════════
#  백테스트 페이지
# ═══════════════════════════════════════════════════════════════
