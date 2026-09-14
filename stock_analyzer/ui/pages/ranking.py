"""랭킹 페이지 — 워치리스트 점수 순위.

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


def render_ranking():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Factor Ranking</div>
        <div class="page-subtitle">Cross-sectional factor-based stock ranking</div>
    </div>
    """, unsafe_allow_html=True)

    ranking_data = api_get("/ranking")
    if not ranking_data or not ranking_data.get("ranking"):
        st.info("No ranking data. Run scans for multiple tickers first.")
        return

    ranking = ranking_data["ranking"]
    st.caption(f"{len(ranking)} tickers ranked")

    rows = []
    for r in ranking:
        signal = r.get("signal", "HOLD")
        rows.append({
            "Rank": r.get("rank", 0),
            "Ticker": r.get("ticker", "?"),
            "Signal": signal,
            "Composite": r.get("composite_score", 0),
            "Factor Score": r.get("weighted_factor_score", 0),
            "Momentum": r.get("factor_momentum", 0),
            "Trend": r.get("factor_trend", 0),
            "Value": r.get("factor_value", 0),
            "Volume": r.get("factor_volume", 0),
            "Percentile": r.get("percentile", 0),
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df.style.map(
            lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
            subset=["Signal"],
        ).background_gradient(
            subset=["Factor Score"], cmap="RdYlGn", vmin=-5, vmax=5
        ),
        use_container_width=True, hide_index=True,
    )

    if len(ranking) >= 2:
        fig = go.Figure()
        tickers = [r["ticker"] for r in ranking]
        factors = ["factor_momentum", "factor_trend", "factor_value", "factor_volume"]
        colors = ["#6D7CFF", "#2BD98A", "#F5B14C", "#FF6B6B"]
        for factor, color in zip(factors, colors):
            fig.add_trace(go.Bar(
                name=factor.replace("factor_", "").title(),
                x=tickers,
                y=[r.get(factor, 0) for r in ranking],
                marker_color=color,
            ))
        fig.update_layout(**_plotly_base_layout(
            height=350, barmode="group",
            margin=dict(l=50, r=10, t=30, b=60),
            legend=dict(font=dict(color="#9BA6B5")),
        ))
        st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════
#  페이퍼 트레이딩 페이지
# ═══════════════════════════════════════════════════════════════
