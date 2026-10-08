"""리서치 — 보유 종목 직접 입력 (전환 제안서 결정 2026-10-08)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.api_client import api_get, api_request


def render_research_holdings():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Holdings</div>
        <div class="page-subtitle">보유 종목을 직접 입력합니다. 손절·목표가는 브리핑의 거리 계산에만 씁니다.</div>
    </div>
    """, unsafe_allow_html=True)

    data = api_get("/research/holdings")
    if data is None:
        st.error("보유 목록을 읽지 못했습니다 — agent-api 응답 없음. 비어 있다는 뜻이 아닙니다.")
        return
    holdings = data.get("holdings") or []
    if holdings:
        st.dataframe(pd.DataFrame(holdings), hide_index=True, use_container_width=True)
    else:
        st.info("입력된 보유 종목이 없습니다.")

    st.markdown("#### 추가 · 수정")
    st.caption("같은 티커를 다시 저장하면 바뀝니다.")
    with st.form("holding_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        ticker = c1.text_input("티커", placeholder="005930.KS / PLTR")
        qty = c2.number_input("수량", min_value=0.0, step=1.0)
        avg = c3.number_input("평단가", min_value=0.0, step=1.0)
        c4, c5, c6 = st.columns(3)
        stop = c4.number_input("손절가 (선택, 0 = 없음)", min_value=0.0, step=1.0)
        target = c5.number_input("목표가 (선택, 0 = 없음)", min_value=0.0, step=1.0)
        note = c6.text_input("메모", max_chars=200)
        submitted = st.form_submit_button("저장", type="primary")
    if submitted:
        body = {"ticker": ticker, "qty": qty, "avg_price": avg, "note": note,
                "stop_price": stop or None, "target_price": target or None}
        code, resp = api_request("PUT", "/research/holdings", json_body=body)
        if code == 200:
            st.success(f"{ticker.upper()} 저장됨")
            st.rerun()
        else:
            # 422 = 입력값 검증 실패 (수량·평단가 0 등) — 사유를 그대로 보여준다
            st.error(f"저장 실패 ({code}): {resp}")

    if holdings:
        st.markdown("#### 삭제")
        c1, c2 = st.columns([2, 1])
        target_ticker = c1.selectbox("삭제할 종목", [h["ticker"] for h in holdings],
                                     label_visibility="collapsed")
        if c2.button("삭제"):
            code, resp = api_request("DELETE", f"/research/holdings/{target_ticker}")
            if code == 200:
                st.success(f"{target_ticker} 삭제됨")
                st.rerun()
            else:
                st.error(f"삭제 실패 ({code}): {resp}")
