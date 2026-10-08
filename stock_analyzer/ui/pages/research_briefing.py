"""리서치 — 일일 브리핑 (사실·거리만, 판단 없음).

agent-api `/research/briefing` 을 읽는다. 매수·매도 신호는 이 화면에 없다 — 전환 제안서
(2026-10-08) 범위.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.api_client import api_get, api_post, log_action


def _num(v, fmt: str = "{:,.2f}") -> str:
    """표 셀 문자열. 빈 값은 빈칸.

    숫자와 '' 를 한 열에 섞으면 Arrow 직렬화가 실패한다 (2026-10-08 webui 로그:
    ArrowTypeError, column 실적 D) — 열 전체를 문자열로 만든다.
    """
    return "" if v is None else fmt.format(float(v))


def render_research_briefing():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Briefing</div>
        <div class="page-subtitle">보유·관심 종목 점검 — 사실과 거리만 표시합니다. 매수·매도 판단이 아닙니다.</div>
    </div>
    """, unsafe_allow_html=True)

    log_action("page_view", page="research_briefing")
    _render_holdings_notice()

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
            "종가": _num(i.get("close"), "{:,.0f}" if i.get("market") == "KRX" else "{:,.2f}"),
            "등락%": _num(i.get("change_pct"), "{:+.2f}"),
            "손익%": _num(i.get("pnl_pct"), "{:+.2f}"),
            "손절까지%": _num(i.get("to_stop_pct"), "{:+.2f}"),
            "목표까지%": _num(i.get("to_target_pct"), "{:+.2f}"),
            "실적 D": _num(i.get("days_to_earnings") if i.get("earnings_status") == "ok" else None,
                         "{:.1f}"),
            "공시": str(len(i.get("disclosures") or [])),
            "볼 것": " · ".join(i.get("flags") or []),
            "가격 검증": i.get("price_check"),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    for i in items:
        notes = [n for n in (i.get("bar_note"), i.get("earnings_note")) if n]
        if not (i.get("disclosures") or i.get("errors") or notes):
            continue
        parts = []
        if i.get("disclosures"):
            parts.append(f"공시 {len(i['disclosures'])}건")
        if i.get("errors"):
            parts.append(f"수집 실패 {len(i['errors'])}건")
        if notes:
            parts.append("참고 " + str(len(notes)))
        with st.expander(f"{i['ticker']} — " + " · ".join(parts)):
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


def _render_holdings_notice() -> None:
    """보유 목록이 비어 있으면 입력 위치로 안내한다. 조회 실패는 '비어 있음'과 구분한다."""
    data = api_get("/research/holdings")
    if data is None:
        st.warning("보유 목록을 읽지 못했습니다 — 보유 손익이 빠질 수 있습니다.")
        return
    if data.get("holdings"):
        return
    c1, c2 = st.columns([3, 1])
    c1.warning(
        "보유 종목이 비어 있어 손익·손절/목표가 거리가 나오지 않습니다. "
        "상단 검색창은 종목 분석(스캔)용이라 보유 목록에 들어가지 않습니다."
    )
    if c2.button("보유 종목 입력하러 가기", use_container_width=True):
        st.session_state.nav_page = "Holdings"
        st.rerun()
