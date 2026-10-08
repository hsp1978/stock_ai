"""리서치 — 보유·관심 한국 종목의 최근 DART 공시."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.api_client import api_get


def render_research_disclosures():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Disclosures</div>
        <div class="page-subtitle">보유·관심 한국 종목의 최근 DART 공시 — 원문 링크</div>
    </div>
    """, unsafe_allow_html=True)

    days = st.selectbox("기간", [3, 7, 30], index=1, format_func=lambda d: f"최근 {d}일")
    data = api_get(f"/research/disclosures?days={days}", timeout=120)
    if data is None:
        # API 실패를 '공시 없음'으로 보이게 하지 않는다 (§13 #17)
        st.error("공시를 조회하지 못했습니다 — agent-api 응답 없음. 공시가 없다는 뜻이 아닙니다.")
        return
    for e in data.get("errors") or []:
        # 조회 실패는 '공시 없음'이 아니다 (§13 #17)
        st.warning(f"공시 조회 실패 — {e}")
    rows = data.get("rows") or []
    if not rows:
        if not data.get("errors"):
            st.info(f"최근 {days}일 공시가 없습니다.")
        return
    st.dataframe(
        pd.DataFrame(rows)[["date", "ticker", "title", "kind", "url"]],
        hide_index=True,
        use_container_width=True,
        column_config={
            "date": "접수일", "ticker": "종목", "title": "제목", "kind": "분류",
            "url": st.column_config.LinkColumn("원문", display_text="DART 열기"),
        },
    )
