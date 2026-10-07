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

        render_ml_result(ml, ticker_name, ticker)


_PIPELINE_LABEL = {
    "ml_pipeline_fix": "판정 경로 (ml_pipeline_fix)",
    "ml_predictor_fallback": "폴백 (ml_predictor) — 주 파이프라인 모델 0개",
}


def _model_accuracy(m: dict) -> float | None:
    """주 경로는 `accuracy`, 폴백(ml_predictor)은 `test_accuracy` 를 쓴다."""
    acc = m.get("test_accuracy", m.get("accuracy"))
    return float(acc) if isinstance(acc, (int, float)) else None


def render_ml_result(ml: dict, ticker_name: str, ticker: str) -> None:
    """앙상블(판정이 쓰는 값)을 먼저, 개별 모델을 그 아래에 그린다."""
    ens = ml.get("ensemble", {}) or {}
    pipeline = ml.get("pipeline", "unknown")
    horizon = ens.get("horizon_days", ml.get("horizon_days", 5))
    subtitle = (
        f"{_PIPELINE_LABEL.get(pipeline, pipeline)} · {horizon}일 후 방향 · "
        f"피처 기준일 {ml.get('prediction_feature_date', '?')}"
    )
    st.markdown(f"""
    <div class="section-header">
        <div class="section-title">{ticker_name} ({ticker}) — {ens.get('prediction', '?')}</div>
        <div class="section-subtitle">{subtitle}</div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ensemble", ens.get("prediction", "?"))
    c2.metric("Up Prob", f"{ens.get('up_probability', 0):.1%}")
    c3.metric("Avg Accuracy", f"{ens.get('avg_accuracy', 0):.1%}")
    c4.metric("Models", ens.get("model_count", 0))
    st.caption("멀티에이전트 판정(ML Specialist)이 쓰는 것과 같은 결과다.")

    for w in ml.get("warnings", []) or []:
        st.warning(w)

    for name, m in (ml.get("models", {}) or {}).items():
        if m.get("error") or m.get("status") in ("failed", "skipped"):
            st.warning(f"{name}: {m.get('error') or m.get('reason') or m.get('status')}")
            continue
        up = m.get("up_probability", 0) or 0
        pred = m.get("prediction") or ("UP" if up > 0.5 else "DOWN")
        acc = _model_accuracy(m)
        with st.expander(f"**{m.get('name', name)}** — {pred} ({up:.1%})", expanded=False):
            k1, k2, k3 = st.columns(3)
            k1.metric("Prediction", pred)
            k2.metric("Up Prob", f"{up:.1%}")
            k3.metric("Test Accuracy", f"{acc:.1%}" if acc is not None else "N/A")

            top_feat = m.get("top_features", [])
            if top_feat:
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
