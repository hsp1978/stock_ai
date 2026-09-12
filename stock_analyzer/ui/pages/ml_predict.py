"""ML 예측 페이지 — 5모델 앙상블 결과.

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
from ui.tickers import get_ticker_display_name, load_watchlist


def render_ml_predict():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">ML Prediction</div>
        <div class="page-subtitle">Machine learning direction forecast</div>
    </div>
    """, unsafe_allow_html=True)

    data = api_get("/results")
    results = data.get("results", {}) if data else {}
    tickers = sorted(results.keys()) if results else load_watchlist()
    if not tickers:
        st.info("No tickers available.")
        return

    # 티커 선택 드롭다운 (종목명 표시)
    ticker_options = {ticker: f"{get_ticker_display_name(ticker)} ({ticker})" for ticker in tickers}
    selected_display = st.selectbox("Select Ticker", list(ticker_options.values()), key="ml_ticker")
    ticker = [k for k, v in ticker_options.items() if v == selected_display][0]

    if st.button("Run ML Prediction", type="primary"):
        ticker_name = get_ticker_display_name(ticker)
        with st.spinner(f"Training model for {ticker_name}..."):
            ml = api_get(f"/ml/{ticker}", timeout=120)
        if not ml:
            st.error("ML prediction failed")
            return

        st.markdown(f"""
        <div class="section-header">
            <div class="section-title">{ticker_name} ({ticker}) — {ml.get('best_prediction', '?')}</div>
            <div class="section-subtitle">Best model: {ml.get('best_model', '?').upper()}, Accuracy: {ml.get('best_accuracy', 0):.1%}</div>
        </div>
        """, unsafe_allow_html=True)

        models = ml.get("models", {})
        for name, m in models.items():
            if m.get("error"):
                st.warning(f"{name}: {m['error']}")
                continue

            signal_color = "#2BD98A" if m.get("signal") == "buy" else ("#FF6B6B" if m.get("signal") == "sell" else "#F5B14C")

            with st.expander(f"**{m.get('name', name)}** — {m.get('prediction', '?')} ({m.get('up_probability', 0):.1%})", expanded=True):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Prediction", m.get("prediction", "?"))
                c2.metric("Up Prob", f"{m.get('up_probability', 0):.1%}")
                c3.metric("Test Accuracy", f"{m.get('test_accuracy', 0):.1%}")
                c4.metric("CV Accuracy", f"{m.get('cv_accuracy_mean', 0):.1%}")

                top_feat = m.get("top_features", [])
                if top_feat:
                    feat_df = pd.DataFrame(top_feat)
                    fig = go.Figure(go.Bar(
                        x=[f["importance"] for f in top_feat],
                        y=[f["name"] for f in top_feat],
                        orientation="h",
                        marker_color="#6D7CFF",
                    ))
                    fig.update_layout(**_plotly_base_layout(
                        height=300, margin=dict(l=140, r=10, t=10, b=10),
                    ))
                    st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════
#  포트폴리오 최적화 페이지
# ═══════════════════════════════════════════════════════════════
