"""멀티에이전트 리포트 페이지 — 8개 에이전트 결과와 최종 판단.

`webui.py` 분해 — 페이지 단위 (CLAUDE.md §6-10). 분리 후 **렌더 함수를 직접
호출**해 확인한다: ast 파싱·import·HTTP 200 은 화면 결함을 잡지 못한다 (§13.9a).
"""

from __future__ import annotations

import json
import pandas as pd
import re
import streamlit as st

from datetime import datetime
from ui.api_client import api_get, api_post, log_action
from ui.tickers import format_ticker_label, get_ticker_display_name, load_watchlist, validate_ticker_webui


def _confidence_label(signal: str) -> str:
    """
    신호 종류에 따라 적절한 신뢰도 라벨 반환.

    - BUY/SELL → "신뢰도" (방향 확신도)
    - HOLD/NEUTRAL → "관망 확신도" (중립 확신도)

    '신뢰도 5.9로 HOLD'처럼 방향 신호처럼 오해되는 ambiguity 제거.
    """
    s = (signal or "").upper()
    if s in ("HOLD", "NEUTRAL"):
        return "관망 확신도"
    return "신뢰도"


def _render_confidence_gap_warning(single: dict, final_decision: dict):
    """
    Single LLM과 Multi-Agent 신뢰도 갭이 크면 해설 배너 표시.

    갭 ≥ 2.0이면 "왜 차이나는지" 사용자에게 명시.
    """
    if not single or not final_decision:
        return

    single_sig = (single.get("final_signal") or "").upper()
    single_conf = float(single.get("confidence") or 0)
    multi_sig = (final_decision.get("final_signal") or "").upper()
    multi_conf = float(final_decision.get("final_confidence") or 0)

    gap = abs(single_conf - multi_conf)
    if gap < 2.0:
        return

    # 신호도 다른 경우 추가 강조
    same_signal = single_sig == multi_sig or (
        single_sig in ("HOLD", "NEUTRAL") and multi_sig in ("HOLD", "NEUTRAL")
    )

    msg_parts = []
    msg_parts.append(
        f"**Single LLM {single_conf:.1f}/10** vs **Multi-Agent {multi_conf:.1f}/10** "
        f"— 신뢰도 갭 **{gap:.1f}** 감지"
    )
    msg_parts.append("")
    if single_sig == multi_sig:
        msg_parts.append(f"두 시스템 모두 **{single_sig}** 방향성에 동의하나 확신도 다름:")
    else:
        msg_parts.append(f"신호도 차이: Single **{single_sig}** vs Multi **{multi_sig}**")
    msg_parts.append("")
    msg_parts.append("**원인**")
    msg_parts.append("- **Single LLM**: 16+개 도구 점수를 LLM이 자체 통합 → 종합 점수 기반 판단")
    msg_parts.append("- **Multi-Agent**: 7명 전문가가 각자 분석 → Decision Maker가 합의/충돌 평가 후 종합")
    msg_parts.append("- 전문가 의견이 엇갈릴수록 Multi-Agent 신뢰도가 낮게 나오는 구조 (보수적)")
    msg_parts.append("")
    msg_parts.append("**권장 해석**")
    if not same_signal:
        msg_parts.append("- ⚠️ 신호도 다르므로 **매매 보류 권장**")
    elif multi_conf < 3.0:
        msg_parts.append("- ⚠️ Multi-Agent 확신도가 매우 낮음 → **전문가 의견 불일치**, 추가 관찰 권장")
    else:
        msg_parts.append("- ℹ️ 방향은 일치. Single LLM 점수의 강도 참고")

    st.warning("\n".join(msg_parts))


def render_multi_agent():
    log_action("page_view", page="multi_agent")
    st.markdown("""
    <div class="page-header">
        <div class="page-title">🤖 Multi-Agent Analysis</div>
        <div class="page-subtitle">8개 전문 AI 에이전트 협업 분석 (V2.0 Enhanced)</div>
    </div>
    """, unsafe_allow_html=True)

    # Watchlist 로드 (참고용)
    watchlist = load_watchlist()

    # 종목 입력 방식 선택
    input_method = st.radio(
        "종목 입력 방식",
        ["Watchlist에서 선택", "직접 입력"],
        horizontal=True,
        label_visibility="collapsed"
    )

    # 종목 선택/입력
    col1, col2 = st.columns([3, 1])
    with col1:
        if input_method == "Watchlist에서 선택":
            if not watchlist:
                st.warning("Watchlist가 비어있습니다. 직접 입력을 선택하거나 사이드바에서 종목을 추가하세요.")
                ticker = st.text_input(
                    "종목 코드 입력",
                    placeholder="예: AAPL, 삼성전자, 005930.KS, 네이버",
                    label_visibility="collapsed",
                )
            else:
                # 종목명과 함께 표시
                ticker_options = {t: f"{get_ticker_display_name(t)} ({t})" for t in watchlist}
                selected_display = st.selectbox("분석할 종목 선택", list(ticker_options.values()), label_visibility="collapsed")
                ticker = [k for k, v in ticker_options.items() if v == selected_display][0]
        else:
            # 한글 종목명 입력을 지원하기 위해 .upper()는 영문/숫자 입력일 때만 적용
            ticker_raw = st.text_input(
                "종목 코드 입력",
                placeholder="예: AAPL, 삼성전자, 005930.KS, 네이버",
                label_visibility="collapsed",
            )
            ticker = ticker_raw.upper() if ticker_raw and ticker_raw.isascii() else ticker_raw

    with col2:
        analyze_btn = st.button("🤖 Multi-Agent 분석", use_container_width=True, type="primary", disabled=not ticker)

    if not ticker and not analyze_btn:
        st.info("👆 종목을 선택하거나 입력하고 'Multi-Agent 분석' 버튼을 클릭하세요.")
        return

    if not analyze_btn and "multi_agent_result" not in st.session_state:
        if ticker:
            st.info(f"📊 {ticker}를 분석하려면 'Multi-Agent 분석' 버튼을 클릭하세요.")
        return

    # 분석 실행
    if analyze_btn:
        # 종목 코드 유효성 검증
        is_valid, validation_message = validate_ticker_webui(ticker)
        if not is_valid:
            st.error(validation_message)
            # 검증 실패 시 유사 종목 자동 추천 (UX 개선)
            try:
                from stock_analyzer.ticker_suggestion import suggest_ticker as _suggest
                sug = _suggest(ticker, max_results=8)
                if sug.get('found') and sug.get('suggestions'):
                    # WebUI는 편의성 우선: 0.80 이상이면 자동 교정 제안
                    top = sug['suggestions'][0]
                    if top['score'] >= 0.80:
                        st.info(
                            f"💡 혹시 이 종목을 찾으시나요? **{top['name']} ({top['ticker']})** "
                            f"(매치율 {top['score']*100:.0f}%)"
                        )
                    with st.expander(f"🔍 유사 종목 {len(sug['suggestions'])}개 추천", expanded=True):
                        for s in sug['suggestions']:
                            score = int(s['score'] * 100)
                            st.markdown(
                                f"- **{s['name']}** (`{s['ticker']}`) · {s.get('exchange','')} · 매치율 {score}%"
                            )
            except Exception:
                pass  # 추천 모듈이 실패해도 원래 에러 메시지는 유지
            return

        # 한국 주식의 경우 자동 해결된 ticker 추출
        resolved_ticker = ticker
        import re
        # 6자리 숫자 또는 특수 코드 (예: 0126Z0) 처리
        if ((ticker.isdigit() and len(ticker) == 6) or
            re.match(r'^[0-9]{4}[A-Z][0-9]$', ticker)) and "✅" in validation_message:
            match = re.search(r'✅\s+(\S+)\s+\(', validation_message)
            if match:
                resolved_ticker = match.group(1)

        # 사용자 입력과 분석 대상이 다르면 명시적으로 안내 (UX: 정정된 티커 투명성)
        if resolved_ticker != ticker:
            resolved_label = format_ticker_label(resolved_ticker, style="name_with_code")
            st.info(f"📝 입력: **{ticker}** → 분석 대상: **{resolved_label}**")

        # 분석 헤더에도 종목명 포함
        analysis_label = format_ticker_label(resolved_ticker, style="name_with_code")
        with st.status(f"🤖 {analysis_label} 멀티에이전트 분석 (약 1-2분)", expanded=True) as status:
            # Single LLM 분석
            st.write("📊 1/3 · 단일 LLM 분석 (V1.0) 진행 중...")
            single_result = api_get(f"/results/{resolved_ticker}")
            if not single_result:
                log_action(
                    "manual_scan",
                    page="multi_agent",
                    ticker=resolved_ticker,
                )
                single_result = api_post(f"/scan/{resolved_ticker}")

            # Multi-Agent 분석 (백엔드가 7개 분석 에이전트 실행 후 Decision Maker가 종합)
            st.write("🤖 2/3 · 7개 분석 에이전트 병렬 분석 중 (Technical · Quant · Risk · ML · Event · Geopolitical · Value)...")
            # 7개 분석 에이전트 병렬 LLM 호출. 백엔드 MULTI_AGENT_TIMEOUT보다 약간 더 길게.
            multi_result = api_get(f"/multi-agent/{resolved_ticker}", timeout=660)

            # API 실패 시 사용자 친화적 안내
            if multi_result is None:
                st.write("⚠️ Multi-Agent API 서버에 연결할 수 없어 단일 LLM 결과만 표시합니다.")
                multi_result = {
                    "error": "멀티에이전트 API에 연결할 수 없습니다. chart_agent_service가 실행 중인지 확인하세요.",
                    "final_decision": {
                        "final_signal": "N/A",
                        "final_confidence": 0,
                        "consensus": "API 서버 미응답"
                    }
                }
            else:
                st.write("✅ 3/3 · 결과 수집 완료, 렌더링 중...")
            status.update(label=f"✅ {analysis_label} 분석 완료", state="complete", expanded=False)

            st.session_state.multi_agent_result = {
                "ticker": resolved_ticker,
                "single": single_result if single_result else {},
                "multi": multi_result,
                "timestamp": datetime.now().isoformat()
            }

    # 결과 표시
    if "multi_agent_result" in st.session_state:
        result = st.session_state.multi_agent_result
        ticker = result["ticker"]
        ticker_name = get_ticker_display_name(ticker)
        single = result.get("single", {})
        multi = result.get("multi", {})

        # === 비교 카드 ===
        st.markdown(f"### 📊 {ticker_name} ({ticker}) — Single LLM vs Multi-Agent 비교")

        col1, col2 = st.columns(2)

        with col1:
            # V1.0 실행 실패는 N/A/0.00으로 위장하지 않고 명시적으로 표기한다.
            single_failed = not single or not single.get("final_signal")
            if single_failed:
                st.markdown("""
                <div class="summary-card" style="border:2px solid var(--error);">
                    <div style="font-size:0.7rem; color:var(--error); margin-bottom:8px;">Single LLM (V1.0) ⚠️</div>
                    <div style="font-size:1.2rem; font-family:'JetBrains Mono'; font-weight:700; margin-bottom:12px; color:var(--error);">
                        실행 실패
                    </div>
                    <div style="font-size:0.8rem; color:var(--on-surface-variant);">
                        V1.0 분석 결과를 가져오지 못했습니다 (신호/점수 없음)
                    </div>
                    <div style="margin-top:12px; font-size:0.7rem; opacity:0.6;">
                        agent-api /scan 실패 여부를 확인하세요
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div class="summary-card">
                    <div style="font-size:0.7rem; color:var(--on-surface-variant); margin-bottom:8px;">Single LLM (V1.0)</div>
                    <div style="font-size:1.8rem; font-family:'JetBrains Mono'; font-weight:700; margin-bottom:12px;">
                        {}
                    </div>
                    <div style="font-size:0.8rem; color:var(--on-surface-variant);">
                        점수: <span style="color:{};">{:+.2f}</span> / {}: {}/10
                    </div>
                    <div style="margin-top:12px; font-size:0.7rem; opacity:0.6;">
                        {}개 도구 분석 → 단일 LLM 판단
                    </div>
                </div>
                """.format(
                    single.get("final_signal", "?"),
                    "var(--buy)" if single.get("composite_score", 0) > 0 else "var(--sell)" if single.get("composite_score", 0) < 0 else "var(--outline)",
                    single.get("composite_score", 0),
                    _confidence_label((single.get("final_signal") or "").upper()),
                    single.get("confidence", 0),
                    len(single.get("tool_summaries") or []) or 17,
                ), unsafe_allow_html=True)

        with col2:
            # multi가 None이거나 error가 있는 경우 처리
            if multi is None:
                multi = {"error": "Multi-Agent API not available"}

            final_decision = multi.get("final_decision", {})

            # API 에러가 있는 경우 에러 표시
            if "error" in multi:
                st.markdown("""
                <div class="summary-card" style="border:2px solid var(--error);">
                    <div style="font-size:0.7rem; color:var(--error); margin-bottom:8px;">Multi-Agent (V2.0) ⚠️</div>
                    <div style="font-size:1.2rem; font-family:'JetBrains Mono'; font-weight:700; margin-bottom:12px; color:var(--error);">
                        API 연결 실패
                    </div>
                    <div style="font-size:0.8rem; color:var(--on-surface-variant);">
                        Multi-Agent 서버가 응답하지 않습니다
                    </div>
                    <div style="margin-top:12px; font-size:0.7rem; opacity:0.6;">
                        chart_agent_service가 실행 중인지 확인하세요
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                # 에이전트 개수 자동 감지 (하드코딩 대신 실제 데이터 기반)
                agent_count_actual = len(multi.get("agent_results", []))
                valid_count = final_decision.get("valid_agent_count", agent_count_actual)
                excluded_count = final_decision.get("excluded_failed_count", 0)
                agent_detail = f"{agent_count_actual}개 에이전트"
                if excluded_count:
                    agent_detail += f" (유효 {valid_count}, 실패 {excluded_count} 제외)"

                # 신호 라벨 (HOLD/neutral일 경우 '관망 확신도' 표기)
                multi_sig = (final_decision.get("final_signal") or "").upper()
                multi_conf = final_decision.get("final_confidence", 0)
                conf_label = _confidence_label(multi_sig)

                st.markdown("""
                <div class="summary-card" style="border:2px solid var(--primary-ctr);">
                    <div style="font-size:0.7rem; color:var(--primary); margin-bottom:8px;">Multi-Agent (V2.0) ⭐</div>
                    <div style="font-size:1.8rem; font-family:'JetBrains Mono'; font-weight:700; margin-bottom:12px;">
                        {}
                    </div>
                    <div style="font-size:0.8rem; color:var(--on-surface-variant);">
                        {}: {:.1f}/10 | 의견: {}
                    </div>
                    <div style="margin-top:12px; font-size:0.7rem; opacity:0.6;">
                        {} 병렬 분석 → Decision Maker 종합
                    </div>
                </div>
                """.format(
                    final_decision.get("final_signal", "?"),
                    conf_label,
                    multi_conf,
                    final_decision.get("consensus", "?"),
                    agent_detail,
                ), unsafe_allow_html=True)

        # === 신뢰도 갭 경고 (개선 #1) ===
        if not multi.get("error"):
            _render_confidence_gap_warning(single, final_decision)

        # === 에이전트 의견 ===
        st.markdown("### 👥 에이전트 의견")

        if multi.get("error"):
            st.error(f"멀티에이전트 분석 오류: {multi['error']}")
            return

        agent_results = multi.get("agent_results", [])

        for agent in agent_results:
            agent_name = agent.get("agent", "?")
            signal = agent.get("signal", "neutral")
            confidence = agent.get("confidence", 0)
            reasoning = agent.get("reasoning", "")
            llm = agent.get("llm_provider", "?")
            exec_time = agent.get("execution_time", 0)
            error = agent.get("error")

            # 신호 색상
            if signal == "buy":
                signal_color = "var(--buy)"
                signal_icon = "📈"
            elif signal == "sell":
                signal_color = "var(--sell)"
                signal_icon = "📉"
            else:
                signal_color = "var(--hold)"
                signal_icon = "➖"

            # 에러 표시
            status_icon = "✓" if not error else "✗"
            status_color = "var(--agent-success)" if not error else "var(--agent-error)"

            with st.expander(f"{status_icon} **{agent_name}**: {signal_icon} {signal.upper()} ({confidence:.1f}/10) — {llm} [{exec_time:.1f}s]"):
                if error:
                    st.error(f"에러: {error}")
                else:
                    st.markdown(f"**판단 근거:**\n\n{reasoning}")

                # 신뢰도 바
                st.progress(confidence / 10.0)

        # === Decision Maker 종합 ===
        st.markdown("### 🎯 Decision Maker 최종 판단")

        # 최종 신호와 신뢰도
        col1, col2, col3 = st.columns(3)
        with col1:
            signal = final_decision.get('final_signal', 'N/A').upper()
            color = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}.get(signal, "⚪")
            st.metric("최종 신호", f"{color} {signal}")
        with col2:
            confidence = final_decision.get('final_confidence', 0)
            # HOLD/NEUTRAL일 때 "관망 확신도"로 라벨 분리
            st.metric(_confidence_label(signal), f"{confidence:.1f}/10")
        with col3:
            st.metric("의견 분포", final_decision.get('consensus', 'N/A'))

        # 의견 충돌 해결
        st.markdown("#### 의견 충돌 해결")
        conflicts = final_decision.get('conflicts', 'N/A')
        st.info(conflicts)

        # 종합 판단 근거
        st.markdown("#### 종합 판단 근거")
        reasoning = final_decision.get('reasoning', 'N/A')
        st.write(reasoning)

        # 핵심 리스크
        st.markdown("#### ⚠️ 핵심 리스크")
        risks = final_decision.get('key_risks', [])
        if risks:
            for risk in risks:
                st.write(f"• {risk}")
        else:
            st.write("• 리스크 정보 없음")

        # === 진입 계획 (매매 시점/분할/손절익절) ===
        entry_plan = final_decision.get("entry_plan")
        if entry_plan:
            st.markdown("### 📋 실전 진입 계획")

            # 진입 보류 케이스
            if entry_plan.get("entry_timing") == "wait":
                st.warning("⏸ **진입 보류 권장**")
                for note in entry_plan.get("notes", []):
                    st.write(f"• {note}")
            else:
                # 주요 레벨 요약
                is_kr = ticker.upper().endswith(".KS") or ticker.upper().endswith(".KQ")
                currency = "₩" if is_kr else "$"
                fmt = (lambda v: f"{currency}{v:,.0f}") if is_kr else (lambda v: f"{currency}{v:,.2f}")

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    order_type_kr = {"market": "시장가", "limit": "지정가", "wait": "대기"}.get(
                        entry_plan.get("order_type"), entry_plan.get("order_type", "?")
                    )
                    timing_kr = {"immediate": "즉시", "pullback": "풀백 대기",
                                 "breakout_confirm": "돌파 확인", "wait": "대기"}.get(
                        entry_plan.get("entry_timing"), entry_plan.get("entry_timing", "?")
                    )
                    st.metric("주문 유형", f"{order_type_kr}", delta=timing_kr, delta_color="off")
                with col2:
                    lp = entry_plan.get("limit_price")
                    st.metric("진입가", fmt(lp) if lp else "—")
                with col3:
                    sl = entry_plan.get("stop_loss")
                    st.metric("🛑 손절", fmt(sl) if sl else "—")
                with col4:
                    tp = entry_plan.get("take_profit")
                    st.metric("🎯 익절", fmt(tp) if tp else "—")

                # 분할 진입 표
                splits = entry_plan.get("split_entry") or []
                if splits:
                    st.markdown("**📊 분할 진입 전략**")
                    split_rows = []
                    for i, s in enumerate(splits, 1):
                        price_str = fmt(s["price"]) if s.get("price") else "—"
                        split_rows.append({
                            "차수": f"{i}차",
                            "비중": f"{s.get('pct', 0)}%",
                            "진입가": price_str,
                            "트리거": s.get("trigger", ""),
                        })
                    st.dataframe(split_rows, use_container_width=True, row_height=44, hide_index=True)

                # 기타 정보
                col_a, col_b = st.columns(2)
                with col_a:
                    days = entry_plan.get("expected_holding_days")
                    if days:
                        st.info(f"⏱ **예상 보유 기간**: {days}일")
                with col_b:
                    inv = entry_plan.get("invalidation_price")
                    if inv:
                        st.error(f"🚨 **무효화 가격**: {fmt(inv)} (이 가격 이하면 분석 무효)")

                # 참고 사항
                if entry_plan.get("notes"):
                    with st.expander("📝 참고 사항", expanded=False):
                        for note in entry_plan["notes"]:
                            st.write(f"• {note}")

                # === 가상 매수 연동 (Virtual Trade 페이지로 프리필) ===
                st.markdown("---")
                vt_col1, vt_col2 = st.columns([2, 1])
                with vt_col1:
                    st.caption(
                        "💡 이 진입 계획으로 가상 거래를 추적하시려면 아래 버튼을 누르세요. "
                        "Virtual Trade 페이지에서 수량을 조정하고 최종 확인 후 체결됩니다."
                    )
                with vt_col2:
                    final_signal = (final_decision.get("final_signal") or "").upper()
                    disabled = final_signal != "BUY" or entry_plan.get("entry_timing") == "wait"
                    if st.button(
                        "📝 이 계획대로 가상 매수",
                        use_container_width=True, type="primary",
                        disabled=disabled,
                        help="Virtual Trade 페이지로 이동 (가격/손절/익절 자동 입력됨)"
                        if not disabled
                        else "매수 신호가 아니거나 진입 보류 상태입니다",
                    ):
                        # 세션에 프리필 저장
                        st.session_state.vt_prefill = {
                            "ticker": ticker,
                            "price": entry_plan.get("limit_price"),
                            "stop_loss": entry_plan.get("stop_loss"),
                            "take_profit": entry_plan.get("take_profit"),
                            "reason": (
                                f"Multi-Agent {final_signal} "
                                f"신뢰도 {final_decision.get('final_confidence', 0):.1f}/10"
                            ),
                        }
                        st.success("✅ Virtual Trade 페이지로 이동하세요 (좌측 네비게이션)")
                        st.info("💡 사이드바 → Virtual Trade 를 클릭")

        # === 실행 통계 ===
        st.markdown("### 📈 실행 통계")

        # 에이전트 수 자동 감지 (응답에서 추출)
        total_agents = final_decision.get("agent_count") or len(multi.get("agent_results") or [])
        valid_agents = final_decision.get("valid_agent_count", total_agents)
        excluded = final_decision.get("excluded_failed_count", 0)
        dist = final_decision.get("signal_distribution", {})

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if excluded:
                st.metric("에이전트", f"{valid_agents}/{total_agents}",
                          delta=f"실패 {excluded}명 제외", delta_color="off")
            else:
                st.metric("에이전트 수", total_agents)
        with col2:
            st.metric("BUY 의견", dist.get("buy", 0))
        with col3:
            st.metric("SELL 의견", dist.get("sell", 0))
        with col4:
            st.metric("실행 시간", f"{multi.get('total_execution_time', 0):.1f}s")

        # === Export 기능 ===
        st.markdown("### 💾 분석 결과 Export")

        # Export 데이터 준비
        export_data = {
            "analysis_info": {
                "ticker": ticker,
                "analyzed_at": multi.get('analyzed_at', datetime.now().isoformat()),
                "total_execution_time": multi.get('total_execution_time', 0)
            },
            "single_llm_analysis": {
                "final_signal": single.get("final_signal"),
                "composite_score": single.get("composite_score"),
                "confidence": single.get("confidence"),
                "llm_interpretation": single.get("llm_interpretation")
            },
            "multi_agent_analysis": {
                "final_decision": final_decision,
                "agent_results": multi.get("agent_results", [])
            },
            "tool_analysis_results": single.get("tool_results", {})
        }

        col1, col2, col3 = st.columns(3)

        with col1:
            # JSON Export
            json_str = json.dumps(export_data, indent=2, ensure_ascii=False)
            st.download_button(
                label="📄 JSON으로 다운로드",
                data=json_str,
                file_name=f"{ticker}_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True
            )

        with col2:
            # CSV Export (요약 정보)
            summary_df = pd.DataFrame([{
                "Ticker": ticker,
                "분석시간": multi.get('analyzed_at', ''),
                "Single LLM 신호": single.get("final_signal") or "실행 실패",
                "Single LLM 점수": single.get("composite_score", 0),
                "Multi-Agent 신호": final_decision.get('final_signal', 'N/A'),
                "Multi-Agent 신뢰도": final_decision.get('final_confidence', 0),
                "Buy 의견": dist.get("buy", 0),
                "Sell 의견": dist.get("sell", 0),
                "Neutral 의견": dist.get("neutral", 0),
                "실행시간(초)": multi.get('total_execution_time', 0)
            }])

            csv_str = summary_df.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📊 CSV로 다운로드",
                data=csv_str,
                file_name=f"{ticker}_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )

        with col3:
            # Markdown Report Export
            if not single or not single.get("final_signal"):
                single_v1_section = (
                    "- **상태**: ⚠️ 실행 실패 — V1.0 분석 결과 없음 "
                    "(agent-api /scan 실패 여부 확인 필요)"
                )
            else:
                single_v1_section = (
                    f"- **최종 신호**: {single.get('final_signal')}\n"
                    f"- **종합 점수**: {single.get('composite_score', 0):+.2f}\n"
                    f"- **{_confidence_label((single.get('final_signal') or '').upper())}**: "
                    f"{single.get('confidence', 0)}/10"
                )
            markdown_report = f"""# {ticker} 주식 분석 리포트

## 📅 분석 정보
- **종목**: {ticker}
- **분석 일시**: {multi.get('analyzed_at', 'N/A')}
- **총 실행 시간**: {multi.get('total_execution_time', 0):.1f}초

## 🎯 분석 결과 요약

### Single LLM Analysis (V1.0)
{single_v1_section}

### Multi-Agent Analysis (V2.0)
- **최종 신호**: {final_decision.get('final_signal', 'N/A')}
- **{_confidence_label((final_decision.get('final_signal') or '').upper())}**: {final_decision.get('final_confidence', 0)}/10
- **의견 분포**: Buy({dist.get("buy", 0)}), Sell({dist.get("sell", 0)}), Neutral({dist.get("neutral", 0)})
- **에이전트**: 총 {total_agents}명 (유효 {valid_agents}, 실패 제외 {excluded})

## 📊 에이전트별 분석 결과
"""
            for agent in multi.get("agent_results", []):
                markdown_report += f"""
### {agent['agent']}
- **신호**: {agent['signal']}
- **신뢰도**: {agent['confidence']}/10
- **LLM**: {agent['llm_provider']}
- **판단 근거**: {agent['reasoning'][:200]}...
"""

            # 매매 파라미터 — 화면에는 있는데 export에만 없어서 "매수 신호인데
            # 진입/손절 전무"한 리포트가 나갔다 (2026-08-03 수정).
            from report_format import (
                format_entry_plan_markdown,
                format_execution_status_markdown,
            )

            markdown_report += "\n" + format_entry_plan_markdown(ticker, final_decision)

            markdown_report += f"""
## 🎯 최종 판단 근거
{final_decision.get('reasoning', 'N/A')}
{format_execution_status_markdown(final_decision)}
## ⚠️ 핵심 리스크
"""
            for risk in final_decision.get('key_risks', []):
                markdown_report += f"- {risk}\n"

            markdown_report += f"""
---
*생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Stock AI Multi-Agent Analysis System v2.0*
"""

            st.download_button(
                label="📝 Markdown으로 다운로드",
                data=markdown_report,
                file_name=f"{ticker}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown",
                use_container_width=True
            )
