"""퀀트 지표 페이지 — 도구 24종의 원시 신호와 기여도.

`webui.py` 분해 — 페이지 단위 (CLAUDE.md §6-10). 분리 후 **렌더 함수를 직접
호출**해 확인한다: ast 파싱·import·HTTP 200 은 화면 결함을 잡지 못한다 (§13.9a).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.api_client import api_get, log_action
from ui.components import _plotly_base_layout, _quant_signal_style
from ui.format import _fmt_price
from ui.tickers import format_ticker_label, load_watchlist, resolve_ticker


def render_quant_indicators():
    log_action("page_view", page="quant_indicators")
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Quant Indicators</div>
        <div class="page-subtitle">가격·거래량·변동성·상관 기반 정량 지표 전용 분석</div>
    </div>
    """, unsafe_allow_html=True)

    watchlist = load_watchlist()
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        input_mode = st.radio(
            "종목 선택 방식",
            ["Watchlist", "직접 입력"],
            horizontal=True,
            label_visibility="collapsed",
            key="quant_input_mode",
        )
    with c2:
        if input_mode == "Watchlist" and watchlist:
            options = {format_ticker_label(t, "flag_name_code"): t for t in watchlist}
            selected_label = st.selectbox(
                "분석 종목",
                list(options.keys()),
                label_visibility="collapsed",
                key="quant_watchlist_ticker",
            )
            ticker = options[selected_label]
            resolved_note = ""
        else:
            raw_ticker = st.text_input(
                "티커 또는 종목명",
                value=st.session_state.get("quant_last_input", "005930.KS"),
                placeholder="예: AAPL, NVDA, 삼성전자, 005930",
                label_visibility="collapsed",
                key="quant_raw_ticker",
            )
            ticker, resolved_note = resolve_ticker(raw_ticker)
            st.session_state.quant_last_input = raw_ticker
    with c3:
        custom_benchmark = st.text_input(
            "Benchmark",
            value="",
            placeholder="기본값",
            help="비워두면 한국은 KOSPI, 미국은 SPY 사용",
            label_visibility="collapsed",
            key="quant_benchmark",
        )

    if resolved_note:
        st.caption(resolved_note)

    run_cols = st.columns([1, 1, 3])
    with run_cols[0]:
        run_now = st.button(
            "Run Quant",
            type="primary",
            use_container_width=True,
            disabled=not ticker,
            key="quant_run_btn",
        )
    with run_cols[1]:
        refresh_latest = st.button("Latest", use_container_width=True, key="quant_latest_btn")

    if run_now:
        query = f"/quant/{ticker}"
        if custom_benchmark.strip():
            query += f"?benchmark={custom_benchmark.strip().upper()}"
        with st.status(f"{ticker} 퀀트 지표 분석 중...", expanded=True) as status:
            st.write("OHLCV 수집 및 기본 지표 계산")
            st.write("모멘텀·평균회귀·변동성·추세·거래량·벤치마크 점수화")
            result = api_get(query, timeout=180)
            if result and result.get("status") == "ok":
                st.session_state.quant_result = result
                status.update(label="퀀트 분석 완료", state="complete", expanded=False)
            elif result:
                status.update(label="퀀트 분석 실패", state="error", expanded=True)
                st.error(result.get("error") or ", ".join(result.get("invalid_reasons", [])) or "분석 실패")
            else:
                status.update(label="퀀트 분석 실패", state="error", expanded=True)
                st.error("API 응답 없음")

    if refresh_latest:
        latest = api_get("/quant/latest?limit=20")
        if latest and latest.get("results"):
            st.session_state.quant_latest = latest
        else:
            st.info("최근 퀀트 분석 결과가 없습니다.")

    latest_data = st.session_state.get("quant_latest")
    if latest_data and latest_data.get("results"):
        with st.expander("최근 퀀트 분석 결과", expanded=False):
            rows = []
            for row in latest_data["results"]:
                rows.append({
                    "Ticker": row.get("ticker"),
                    "Score": row.get("quant_score"),
                    "Grade": row.get("grade"),
                    "Bias": row.get("signal_label"),
                    "Confidence": row.get("confidence"),
                    "Regime": row.get("regime"),
                    "Analyzed": (row.get("analyzed_at") or "")[:19],
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    data = st.session_state.get("quant_result")
    if not data:
        st.info("종목을 선택하고 Run Quant를 실행하세요. 이 탭은 뉴스·공시·LLM 판단을 제외한 정량 지표만 사용합니다.")
        return

    if data.get("status") != "ok":
        st.warning(f"분석 불가: {', '.join(data.get('invalid_reasons', []))}")
        return

    signal_class = _quant_signal_style(data.get("signal"))
    st.markdown(
        f"""
        <div class="section-header">
            <div>
                <div class="section-title">{format_ticker_label(data.get('ticker', ''), 'flag_name_code')}</div>
                <div class="section-subtitle">as of {(data.get('as_of') or '')[:19]} · benchmark {data.get('benchmark_ticker') or 'n/a'}</div>
            </div>
            <span class="signal-badge-lg {signal_class}">{data.get('signal_label', 'NEUTRAL')}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Quant Score", f"{data.get('quant_score', 0):.1f}/100")
    m2.metric("Grade", data.get("grade", "?"))
    m3.metric("Confidence", f"{data.get('confidence', 0):.1f}/10")
    m4.metric("Regime", str(data.get("regime", "?")).replace("_", " ").title())
    m5.metric("Current", _fmt_price(data.get("current_price", 0), data.get("ticker", "")))

    risk_penalty = float(data.get("risk_penalty") or 0)
    if risk_penalty <= -8:
        st.warning(f"리스크 페널티 {risk_penalty:.1f}점 적용: 변동성, 낙폭, 하방 위험을 먼저 확인하세요.")
    elif data.get("warnings"):
        st.caption("Warnings: " + ", ".join(data.get("warnings", [])[:5]))

    components = data.get("components") or {}
    component_labels = {
        "momentum": "Momentum",
        "mean_reversion": "Mean Reversion",
        "volatility": "Volatility",
        "trend": "Trend",
        "volume": "Volume",
        "benchmark": "Benchmark",
    }
    component_rows = []
    for key, comp in components.items():
        weight = float(comp.get("weight") or 0)
        score = float(comp.get("score") or 0)
        component_rows.append({
            "Factor": component_labels.get(key, key),
            "Score": score,
            "Weight": weight,
            "Percent": round(score / weight * 100, 1) if weight else 0,
            "Direction": comp.get("direction", "neutral"),
        })

    if component_rows:
        comp_df = pd.DataFrame(component_rows)
        colors = [
            "#2BD98A" if d == "buy" else "#FF6B6B" if d == "sell" else "#F5B14C"
            for d in comp_df["Direction"]
        ]
        fig = go.Figure(go.Bar(
            x=comp_df["Percent"],
            y=comp_df["Factor"],
            orientation="h",
            marker_color=colors,
            text=[f"{s:.1f}/{w:.0f}" for s, w in zip(comp_df["Score"], comp_df["Weight"])],
            textposition="auto",
        ))
        fig.update_layout(**_plotly_base_layout(
            height=320,
            margin=dict(l=120, r=30, t=20, b=30),
            xaxis=dict(range=[0, 100], ticksuffix="%", gridcolor="rgba(255,255,255,0.08)"),
            yaxis=dict(autorange="reversed"),
            showlegend=False,
        ))
        st.plotly_chart(fig, use_container_width=True)
    else:
        comp_df = pd.DataFrame()

    tab_summary, tab_details, tab_risk, tab_json = st.tabs(["Factor Table", "Indicator Detail", "Risk", "JSON"])
    with tab_summary:
        if not comp_df.empty:
            st.dataframe(comp_df, use_container_width=True, row_height=44, hide_index=True)
        cols = st.columns(2)
        with cols[0]:
            st.markdown("**Strengths**")
            strengths = data.get("strengths") or []
            if strengths:
                for item in strengths:
                    st.write(f"- {item}")
            else:
                st.caption("강점 신호 없음")
        with cols[1]:
            st.markdown("**Warnings**")
            warnings = data.get("warnings") or []
            if warnings:
                for item in warnings:
                    st.write(f"- {item}")
            else:
                st.caption("경고 신호 없음")

    with tab_details:
        detail_rows = []
        for factor, comp in components.items():
            for key, value in comp.items():
                if key in ("score", "weight", "direction"):
                    continue
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        detail_rows.append({
                            "Factor": component_labels.get(factor, factor),
                            "Metric": f"{key}.{sub_key}",
                            "Value": sub_value,
                        })
                else:
                    detail_rows.append({
                        "Factor": component_labels.get(factor, factor),
                        "Metric": key,
                        "Value": value,
                    })
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    with tab_risk:
        risk = data.get("risk") or {}
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Max DD 120D", f"{risk.get('max_drawdown_120d', 0) or 0:.1f}%")
        r2.metric("Downside Vol", f"{risk.get('downside_volatility', 0) or 0:.1f}%")
        r3.metric("VaR 95%", f"{risk.get('var_95_daily', 0) or 0:.2f}%")
        r4.metric("Sharpe", f"{risk.get('sharpe_120d', 0) or 0:.2f}")
        r5.metric("Penalty", f"{risk.get('penalty', 0) or 0:.1f}")
        st.caption("VaR/CVaR는 최근 수익률 분포 기반 일간 손실 추정치입니다.")

    with tab_json:
        st.json(data)
