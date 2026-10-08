"""리서치 — 일일 브리핑 (사실·거리만, 판단 없음).

agent-api `/research/briefing` 을 읽는다. 매수·매도 신호는 이 화면에 없다 — 전환 제안서
(2026-10-08) 범위.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.api_client import api_get, api_post


def _pct(v):
    return None if v is None else round(float(v), 2)


def render_research_briefing():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Briefing</div>
        <div class="page-subtitle">보유·관심 종목 점검 — 사실과 거리만 표시합니다. 매수·매도 판단이 아닙니다.</div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("🔄 지금 점검", type="primary"):
        result = api_get("/research/briefing", timeout=180)
        st.session_state["research_briefing"] = result if result is not None else "failed"
    data = st.session_state.get("research_briefing")
    if data == "failed":
        st.error("점검하지 못했습니다 — agent-api 응답 없음.")
        return
    if not data:
        st.info("'지금 점검'을 누르면 보유 + 관심 종목을 조회합니다 (종목당 약 2초).")
        return

    items = data.get("items") or []
    st.caption(f"생성 {str(data.get('generated_at', ''))[:19].replace('T', ' ')} UTC · {len(items)}종목")

    rows = []
    for i in items:
        rows.append({
            "종목": i["ticker"],
            "보유": "●" if i.get("is_holding") else "",
            "종가": i.get("close"),
            "등락%": _pct(i.get("change_pct")),
            "손익%": _pct(i.get("pnl_pct")),
            "손절까지%": _pct(i.get("to_stop_pct")),
            "목표까지%": _pct(i.get("to_target_pct")),
            "실적 D": i.get("days_to_earnings") if i.get("earnings_status") == "ok" else None,
            "공시": len(i.get("disclosures") or []),
            "볼 것": " · ".join(i.get("flags") or []),
            "가격 검증": i.get("price_check"),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    for i in items:
        notes = [n for n in (i.get("bar_note"), i.get("earnings_note")) if n]
        if not (i.get("disclosures") or i.get("errors") or notes):
            continue
        with st.expander(f"{i['ticker']} — 공시 {len(i.get('disclosures') or [])}건"
                         + (f" · 수집 실패 {len(i['errors'])}건" if i.get("errors") else "")):
            for d in i.get("disclosures") or []:
                st.markdown(f"- {d['date']} [{d['title']}]({d['url']})")
            for n in notes:
                st.caption(n)
            for e in i.get("errors") or []:
                st.warning(e)

    st.divider()
    c1, c2 = st.columns([1, 2])
    with c1:
        market = st.selectbox("텔레그램 발송", ["KRX", "NYSE"], label_visibility="collapsed")
    with c2:
        if st.button("📨 이 시장 브리핑을 텔레그램으로 보내기"):
            res = (api_post(f"/research/briefing/send?market={market}", timeout=180) or {}).get("result") or {}
            if res.get("delivered"):
                st.success(f"전송됨 — {res.get('items')}종목, 볼 것 {res.get('flagged')}개")
            elif res.get("status") == "skipped_holiday":
                st.info("오늘은 휴장일이라 보내지 않았습니다.")
            else:
                st.error(f"전송되지 않음: {res.get('status') or '응답 없음'}")
