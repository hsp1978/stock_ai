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

    st.markdown("#### 요약")
    st.caption("원문에 근거가 확인된 문장만 보여줍니다. 평가·전망은 쓰지 않습니다. 같은 공시는 한 번만 요약합니다.")
    labels = {r["rcept_no"]: f"{r['date']} {r['ticker']} — {r['title']}" for r in rows}
    pick = st.selectbox("공시 선택", list(labels), format_func=lambda k: labels[k],
                        label_visibility="collapsed")
    if st.button("요약 보기"):
        row = next(r for r in rows if r["rcept_no"] == pick)
        from urllib.parse import quote

        with st.spinner("요약 중 (처음 한 번은 최대 1분)..."):
            summ = api_get(
                f"/research/disclosures/{pick}/summary?ticker={quote(row['ticker'])}"
                f"&title={quote(row['title'])}",
                timeout=120,
            )
        if summ is None:
            st.error("요약을 받지 못했습니다 — agent-api 응답 없음.")
        elif summ.get("status") == "unavailable":
            st.warning(f"요약 없음 — {summ.get('reason')}")
        else:
            for b in summ.get("bullets") or []:
                st.markdown(f"- {b}")
            if summ.get("numbers"):
                st.caption("핵심 수치: " + " · ".join(summ["numbers"]))
            if summ.get("dropped"):
                st.caption(f"근거를 확인할 수 없거나 평가가 섞인 문장 {summ['dropped']}개는 뺐습니다.")
            st.markdown(f"[DART 원문]({summ.get('url')}) · 요약: {summ.get('served_by') or '?'}")
