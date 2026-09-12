"""스크리너 페이지 — KOSPI/KOSDAQ 기술적 후보 발굴.

`webui.py` 분해 5단계 — **페이지 단위** (CLAUDE.md §6-10). 페이지는 세션 상태와
헬퍼 결합이 있어 한 번에 하나씩 옮기고, 매번 3단 검증을 돌린다:
  1. 원본 대비 최상위 심볼 집합 비교 (문법 검사는 함수 중간 절단을 못 잡는다)
  2. 테스트 + ruff
  3. 배포 컨테이너에서 스크립트 실행 + 이 함수 직접 호출
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.api_client import api_get, api_post
from ui.format import _fmt_price
from ui.tickers import add_to_watchlist


def render_screener():
    """
    매일 장 마감 후 한국 시총 2,000억+ 종목에서 기술적 점수 상위 20개 발굴.

    설계 원칙:
    - Watchlist 자동 등록 안 함 (사용자 명시 선택 시에만)
    - Multi-Agent 분석과 독립 (스크리너 = 후보 발굴, Multi-Agent = 심층 분석)
    - 결과는 screener_results 테이블에만 저장 (scan_log 오염 방지)
    """
    st.markdown("""
    <div class="page-header">
        <div class="page-title">📡 Screener · 한국 주식</div>
        <div class="page-subtitle">기술적 신호 기반 매수 후보 발굴 (시총 2,000억+ · 상위 20개)</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 상단 컨트롤 ─────────────────────────────
    c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
    with c1:
        min_cap_100m = st.number_input(
            "최소 시총 (억원)",
            min_value=100, max_value=100_000, value=2000, step=100,
            help="이 값 이상의 종목만 분석 대상"
        )
    with c2:
        top_n = st.number_input(
            "상위 N개",
            min_value=5, max_value=100, value=20, step=5,
        )
    with c3:
        analyze_top = st.number_input(
            "자동 심층",
            min_value=0, max_value=20, value=5, step=1,
            help="상위 N개 중 Multi-Agent 자동 분석할 개수 (0=안 함)"
        )
    with c4:
        run_now = st.button(
            "▶ 스크리너만" if analyze_top == 0 else f"🚀 스크리너 + Multi-Agent {analyze_top}개",
            type="primary", use_container_width=True,
        )

    # ── 실행 (스크리너 단독 or 파이프라인) ─────────
    if run_now:
        workers = max(1, int(os.getenv("SCAN_PARALLEL_WORKERS", "2")))
        ma_batches = (int(analyze_top) + workers - 1) // workers
        est_total = 120 + (ma_batches * 300) if analyze_top > 0 else 120
        est_min = est_total // 60
        est_s = est_total % 60
        est_str = f"{est_min}분 {est_s}초" if est_min else f"{est_s}초"

        if analyze_top == 0:
            # 스크리너만
            with st.status("한국 주식 스크리너 실행 중...", expanded=True) as status:
                st.write(f"🔍 시총 {min_cap_100m:,}억원+ 종목 로딩...")
                result = api_post(
                    f"/screener/run?min_market_cap_100m={min_cap_100m}&top_n={top_n}",
                    timeout=900,
                )
                if result and "error" not in result:
                    st.write(f"✅ 유니버스 {result['universe_size']}개")
                    st.write(f"✅ {result['analyzed_count']}개 점수 완료 ({result['elapsed_seconds']:.0f}s)")
                    status.update(label="✅ 스크리너 완료", state="complete", expanded=False)
                    st.session_state.screener_result = result
                else:
                    st.error(f"실행 실패: {(result or {}).get('error', 'API 응답 없음')}")
        else:
            # 파이프라인 (스크리너 + Multi-Agent)
            with st.status(
                f"🚀 파이프라인 실행 중 (예상 {est_str})...",
                expanded=True,
            ) as status:
                st.write("📡 1/2 · 스크리너로 후보 선별 중...")
                st.write(f"   시총 {min_cap_100m:,}억원+ · 상위 {top_n}개")
                st.write(f"🤖 2/2 · 상위 {analyze_top}개 Multi-Agent 심층 분석...")
                st.write(f"   (병렬 실행, {analyze_top}개 × 약 60s ÷ WORKERS)")

                result = api_post(
                    f"/screener/pipeline?min_market_cap_100m={min_cap_100m}"
                    f"&top_n={top_n}&analyze_top={analyze_top}",
                    timeout=1800,
                )
                if result and "error" not in result:
                    st.write(f"✅ 스크리너 {result['elapsed_seconds']:.0f}s")
                    st.write(f"✅ Multi-Agent {result.get('multi_agent_elapsed_seconds', 0):.0f}s")
                    st.write(f"✅ 총 소요 {result.get('total_elapsed_seconds', 0):.0f}s")
                    status.update(label="✅ 파이프라인 완료", state="complete", expanded=False)
                    st.session_state.screener_result = result
                    st.session_state.screener_has_pipeline = True
                else:
                    st.error(f"파이프라인 실패: {(result or {}).get('error', 'API 응답 없음')}")

    # ── 최신 결과 로드 (실행 안 했으면 DB에서) ──
    data = None
    if "screener_result" in st.session_state:
        data = st.session_state.screener_result
        st.caption(f"세션 실행 결과: {data.get('run_id', '?')}")
    else:
        data = api_get("/screener/latest?limit=100")
        if data and data.get("count", 0) > 0:
            st.caption(f"DB 최근 실행: {data.get('scanned_at', '')[:19]} (run_id: {data.get('run_id')})")
        else:
            st.info("📭 스크리너 실행 기록 없음. 위 '▶ 지금 실행' 버튼으로 시작하세요.")
            st.markdown("""
            **매일 자동 실행**: 평일 15:35 KST (장 마감 후)
            **분석 기준**: MACD · 이동평균 · RSI · 거래량 · 20일선 지지 (총 100점)
            **감점 항목**: 데드크로스 · 과매수 · 거래량↓ · 장기 역행
            **주의**: 스크리너 결과는 **매수 제안**일 뿐, Multi-Agent 심층 분석을 거쳐 최종 판단하세요.
            """)
            return

    results = data.get("results", [])
    if not results:
        st.warning("결과 없음")
        return

    # ── 요약 통계 ─────────────────────────────
    st.markdown("### 📊 결과 요약")
    s_count = sum(1 for r in results if r.get("grade") == "S")
    a_count = sum(1 for r in results if r.get("grade") == "A")
    b_count = sum(1 for r in results if r.get("grade") == "B")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("총 후보", len(results))
    m2.metric("S 등급", s_count)
    m3.metric("A 등급", a_count)
    m4.metric("B 등급", b_count)

    if s_count == 0 and a_count == 0:
        st.warning("⚠️ S/A 등급 없음 — 현재 시장이 약세이거나 조건 완화 필요")

    # ── 결과 테이블 ───────────────────────────
    st.markdown("### 🏆 상위 종목 리스트")
    rows = []
    for r in results:
        cap_bn = (r.get("market_cap") or 0) / 1e8
        grade_emoji = {"S": "⭐⭐", "A": "⭐", "B": "•", "C": "·", "D": ""}.get(r.get("grade"), "")
        ticker = r.get("ticker", "")
        rows.append({
            "순위": r.get("rank", 0),
            "등급": f"{grade_emoji} {r.get('grade', '?')}",
            "종목": r.get("name", "?"),
            "티커": ticker,
            "시장": r.get("market", ""),
            "점수": r.get("score", 0),
            "시총(억)": f"{cap_bn:,.0f}",
            "현재가": _fmt_price(r.get('current_price', 0), ticker),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, row_height=44, hide_index=True)

    # ── 파이프라인 뷰 (스크리너 + Multi-Agent 합의도) ──
    combined = data.get("combined_view")
    if combined:
        st.markdown("### 🔗 스크리너 × Multi-Agent 합의도 분석")
        st.caption(
            f"상위 {data.get('analyzed_top', 0)}개 Multi-Agent 심층 분석 완료. "
            f"Multi-Agent 소요 {data.get('multi_agent_elapsed_seconds', 0):.0f}s"
        )

        # 합의도 통계 카드
        stats = data.get("agreement_stats", {})
        ag_cols = st.columns(5)
        labels = {
            "strong_match":    ("🟢🟢 강한 일치", "스크리너↑ + MA 매수"),
            "partial_match":   ("🟢 부분 일치", "스크리너↑ + MA 보수적"),
            "conflict":        ("⚠️ 신호 충돌", "스크리너↑ vs MA 매도"),
            "unexpected_buy":  ("🟡 이례적 매수", "스크리너↓ + MA 매수"),
            "aligned_weak":    ("⚪ 동반 약세", "둘 다 약한 후보"),
        }
        for i, (key, (label, desc)) in enumerate(labels.items()):
            count = stats.get(key, 0)
            with ag_cols[i]:
                st.metric(label, count, help=desc)

        # 파이프라인 상세 테이블
        pipe_rows = []
        for e in combined:
            agreement = e.get("agreement") or {}
            if not e.get("multi_agent_analyzed") and agreement.get("level") == "pending":
                # 미분석 항목은 회색으로
                pipe_rows.append({
                    "순위": e["rank"],
                    "합의": agreement.get("emoji", "⏳"),
                    "종목": e.get("name", "?"),
                    "스크리너": f"{e['screener_score']}점 ({e['screener_grade']})",
                    "기간": f"{e.get('horizon_days') or agreement.get('horizon_days', 7)}일",
                    "MA 신호": "—",
                    "MA 확신": "—",
                    "차이 사유": "미분석",
                    "Entry": "—",
                })
            else:
                ma_sig = (e.get("multi_agent_signal") or "?").upper()
                ma_conf = e.get("multi_agent_confidence", 0)
                reason_codes = agreement.get("reason_codes") or []
                reason_label = ", ".join(reason_codes[:2]) if reason_codes else "—"
                entry = e.get("entry_plan") or {}
                entry_str = "—"
                if entry and entry.get("limit_price"):
                    entry_str = f"₩{entry['limit_price']:,.0f}"
                pipe_rows.append({
                    "순위": e["rank"],
                    "합의": f"{agreement.get('emoji', '')} {agreement.get('label', '')}",
                    "종목": e.get("name", "?"),
                    "스크리너": f"{e['screener_score']}점 ({e['screener_grade']})",
                    "기간": f"{e.get('horizon_days') or agreement.get('horizon_days', 7)}일",
                    "MA 신호": ma_sig,
                    "MA 확신": f"{ma_conf:.1f}/10",
                    "차이 사유": reason_label,
                    "Entry": entry_str,
                })

        st.dataframe(pipe_rows, use_container_width=True, row_height=44, hide_index=True)

        # 🟢🟢 강한 일치만 별도 하이라이트
        strong = [e for e in combined if (e.get("agreement") or {}).get("level") == "strong_match"]
        if strong:
            st.markdown("#### 🎯 최우선 관심 종목 (강한 일치)")
            for e in strong:
                ag = e.get("agreement", {})
                entry_plan = e.get("entry_plan") or {}
                with st.expander(
                    f"{ag.get('emoji','')} **{e.get('name')}** ({e['ticker']}) — "
                    f"스크리너 {e['screener_score']}점 {e['screener_grade']}등급 / "
                    f"MA {(e.get('multi_agent_signal') or '').upper()} "
                    f"{e.get('multi_agent_confidence', 0):.1f}/10",
                    expanded=True,
                ):
                    st.info(ag.get("description", ""))
                    if e.get("multi_agent_reasoning"):
                        st.markdown(f"**Multi-Agent 판단 근거**: {e['multi_agent_reasoning']}")
                    if entry_plan:
                        ep_cols = st.columns(4)
                        lp = entry_plan.get("limit_price")
                        sl = entry_plan.get("stop_loss")
                        tp = entry_plan.get("take_profit")
                        ep_cols[0].metric("진입가", f"₩{lp:,.0f}" if lp else "—")
                        ep_cols[1].metric("손절", f"₩{sl:,.0f}" if sl else "—")
                        ep_cols[2].metric("익절", f"₩{tp:,.0f}" if tp else "—")
                        ep_cols[3].metric("보유일", f"{entry_plan.get('expected_holding_days', '?')}일")

    # ── 개별 종목 상세 (점수 분해) ──────────────
    st.markdown("### 🔎 종목별 점수 분해")
    options = [f"{i+1}. {r['name']} ({r['ticker']}) — {r['score']}점" for i, r in enumerate(results)]
    selected_idx = st.selectbox("상세 보기 종목 선택", range(len(options)), format_func=lambda i: options[i])

    sel = results[selected_idx]
    breakdown = sel.get("breakdown") or {}
    penalties = sel.get("penalties") or []

    # breakdown은 JSON 문자열일 수 있음 (DB에서 조회된 경우)
    if isinstance(breakdown, str):
        import json as _json
        try:
            breakdown = _json.loads(breakdown)
        except Exception:
            breakdown = {}
    if isinstance(penalties, str):
        import json as _json
        try:
            penalties = _json.loads(penalties)
        except Exception:
            penalties = []

    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown("**✅ 득점 항목**")
        if breakdown:
            for k, v in breakdown.items():
                if isinstance(v, dict):
                    pts = v.get("points", 0)
                    reason = v.get("reason", "")
                    st.write(f"  +{pts:.1f}점 · {k}: {reason}")
        else:
            st.caption("득점 항목 없음")

    with sc2:
        st.markdown("**❌ 감점 항목**")
        if penalties:
            for p in penalties:
                if isinstance(p, dict):
                    pts = p.get("points", 0)
                    reason = p.get("reason", "")
                    st.write(f"  {pts:.1f}점 · {p.get('name','?')}: {reason}")
        else:
            st.caption("감점 항목 없음")

    # ── 액션 버튼 (SSOT 정책 준수: 사용자 명시 선택 시에만) ──
    st.markdown("### 🎯 다음 단계")
    ac1, ac2, ac3 = st.columns(3)
    with ac1:
        if st.button("📋 선택 종목 Watchlist 추가", use_container_width=True, key="screener_add_wl"):
            ok, msg = add_to_watchlist(sel.get("ticker", ""))
            if ok:
                st.success(msg)
            else:
                st.warning(msg)
    with ac2:
        if st.button("🤖 Multi-Agent 심층 분석", use_container_width=True, key="screener_ma"):
            ticker = sel.get("ticker", "")
            with st.spinner(f"{ticker} 심층 분석 중..."):
                r = api_get(f"/multi-agent/{ticker}", timeout=660)
                if r and "error" not in r:
                    fd = r.get("final_decision", {})
                    sig = (fd.get("final_signal") or "?").upper()
                    conf = float(fd.get("final_confidence") or 0)
                    st.session_state.multi_agent_result = {
                        "ticker": ticker,
                        "single": {},
                        "multi": r,
                        "timestamp": datetime.now().isoformat(),
                    }
                    st.success(f"완료! {ticker} → {sig} ({conf:.1f}/10)")
                elif r:
                    st.error(f"Multi-Agent 분석 실패: {r.get('error', '알 수 없는 오류')}")
                else:
                    st.error("Multi-Agent API 응답 없음")
    with ac3:
        if st.button("📝 Virtual Trade 프리필", use_container_width=True, key="screener_vt"):
            # Virtual Trade 페이지의 프리필 세션 변수에 저장
            st.session_state.vt_prefill = {
                "ticker": sel.get("ticker", ""),
                "price": sel.get("current_price"),
                "stop_loss": None,
                "take_profit": None,
                "reason": f"Screener 순위 {sel.get('rank')}위 (점수 {sel.get('score')}, {sel.get('grade')}등급)",
            }
            st.success("✅ Virtual Trade 페이지로 이동하세요 (사이드바에서 선택)")

    # ── 주의 배너 ─────────────────────────────
    st.divider()
    st.caption(
        "⚠️ 스크리너 결과는 **기술적 신호 기반 후보 발굴**입니다. "
        "매수 결정 전 반드시 Multi-Agent 심층 분석 + 본인 판단을 거치세요. "
        "자동 매매 권고가 아닙니다."
    )


# ═══════════════════════════════════════════════════════════════
#  Trading 페이지 (Phase 2.1)
# ═══════════════════════════════════════════════════════════════
