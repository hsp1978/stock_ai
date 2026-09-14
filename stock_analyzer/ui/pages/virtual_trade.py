"""가상매매 페이지 — 포지션 관리와 부분 청산.

`webui.py` 분해 — 페이지 단위 (CLAUDE.md §6-10). 분리 후 **렌더 함수를 직접
호출**해 확인한다: ast 파싱·import·HTTP 200 은 화면 결함을 잡지 못한다 (§13.9a).
"""

from __future__ import annotations

import streamlit as st

from datetime import datetime
from ui.api_client import api_get, api_post
from ui.format import _fmt_price
from ui.tickers import format_ticker_label, get_ticker_display_name, resolve_ticker


def render_virtual_trade():
    """
    사용자가 결정한 시점·가격·수량으로 가상 매수, 지속 추적.

    흐름:
    1) 종목 입력/선택 → 현재가 자동 조회
    2) 수량/가격/손절/익절/메모 지정 → "가상 매수" 버튼
    3) 포지션 모니터링: 현재가/목표까지 거리/경과일
    4) 부분/전량 청산 또는 자동 청산(trailing/SL/TP)
    """
    st.markdown("""
    <div class="page-header">
        <div class="page-title">📝 Virtual Trade</div>
        <div class="page-subtitle">내가 정한 타이밍으로 가상 매수 · 자동 추적</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 1. 상단 요약 카드 ─────────────────────
    status = api_get("/paper")
    if not status:
        st.error("API 서버 연결 실패 — chart_agent_service 실행 상태 확인")
        return

    c1, c2, c3, c4 = st.columns(4)
    total_equity = status.get("total_equity", 0)
    total_pnl = status.get("total_pnl", 0)
    total_pnl_pct = status.get("total_pnl_pct", 0)
    positions_map = status.get("positions", {})

    c1.metric("총 자산", f"${total_equity:,.2f}")
    c2.metric("현금", f"${status.get('cash', 0):,.2f}")
    c3.metric("손익", f"${total_pnl:+,.2f}",
              delta=f"{total_pnl_pct:+.2f}%",
              delta_color="normal" if total_pnl >= 0 else "inverse")
    c4.metric("열린 포지션", f"{len(positions_map)}개")

    st.divider()

    # ── 2. 가상 매수 폼 ─────────────────────
    st.markdown("### 🛒 가상 매수")

    # 세션 상태 관리
    if "vt_ticker" not in st.session_state:
        st.session_state.vt_ticker = ""
    if "vt_quote" not in st.session_state:
        st.session_state.vt_quote = None

    # 분석 결과에서 프리필된 값이 있는지 확인 (Multi-Agent 페이지에서 넘어온 경우)
    prefill = st.session_state.get("vt_prefill")
    if prefill:
        st.info(
            f"📊 **Multi-Agent 분석 프리필**: "
            f"`{prefill.get('ticker')}` @ ${prefill.get('price') or 0:.2f} "
            f"· 손절 ${prefill.get('stop_loss') or 0:.2f} · 익절 ${prefill.get('take_profit') or 0:.2f}"
        )

    col_buy_a, col_buy_b, col_buy_c = st.columns([2, 1, 1])
    with col_buy_a:
        ticker_input = st.text_input(
            "종목 코드",
            value=(prefill.get("ticker", "") if prefill else st.session_state.vt_ticker),
            placeholder="예: AAPL, 005930.KS",
            key="vt_ticker_input",
        ).strip().upper()
        trade_ticker = ""
        ticker_note = ""
        if ticker_input:
            trade_ticker, ticker_note = resolve_ticker(ticker_input)
            trade_ticker = trade_ticker.upper()
            if ticker_note and trade_ticker != ticker_input:
                st.caption(f"정규화: {ticker_note}")
    with col_buy_b:
        if st.button("📡 현재가 조회", use_container_width=True, disabled=not trade_ticker):
            quote = api_get(f"/paper/quote/{trade_ticker}")
            if quote:
                st.session_state.vt_quote = quote
                st.session_state.vt_ticker = quote.get("ticker") or trade_ticker
                st.rerun()
            else:
                st.error("현재가 조회 실패")
    with col_buy_c:
        if st.button("🔄 폼 초기화", use_container_width=True):
            st.session_state.vt_quote = None
            st.session_state.vt_ticker = ""
            st.session_state.pop("vt_prefill", None)
            st.rerun()

    quote = st.session_state.vt_quote
    if quote:
        # 현재가 정보 표시
        quote_ticker = quote.get("ticker") or trade_ticker
        qa, qb, qc, qd = st.columns(4)
        qa.metric("현재가", _fmt_price(quote.get('current_price', 0), quote_ticker),
                  delta=f"{quote.get('change_pct', 0):+.2f}%")
        qb.metric("당일 고가", _fmt_price(quote.get('day_high', 0), quote_ticker))
        qc.metric("당일 저가", _fmt_price(quote.get('day_low', 0), quote_ticker))
        qd.metric("호가단위", _fmt_price(quote.get('tick_size', 0), quote_ticker))
        st.caption(f"기준 시각: {quote.get('as_of', '')}")

    # 매수 파라미터
    if trade_ticker:
        default_price = (
            (prefill.get("price") if prefill else None)
            or (quote.get("current_price") if quote else None)
            or 100.0
        )
        default_sl = (prefill.get("stop_loss") if prefill else 0.0) or 0.0
        default_tp = (prefill.get("take_profit") if prefill else 0.0) or 0.0

        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            buy_qty = st.number_input("수량", min_value=1, value=10, step=1, key="vt_qty")
        with pc2:
            buy_price = st.number_input(
                "진입가 (내가 사려는 가격)",
                min_value=0.001, value=float(default_price), step=0.01, format="%.4f",
                key="vt_price",
            )
        with pc3:
            total_cost = buy_qty * buy_price
            st.metric("총 투자금", _fmt_price(total_cost, trade_ticker))

        # 손절/익절/trailing 설정 (접이식)
        with st.expander("🛡️ 손절·익절·자동 청산 설정 (선택)", expanded=bool(prefill)):
            sl_col, tp_col, ts_col, td_col = st.columns(4)
            with sl_col:
                stop_loss = st.number_input(
                    "손절가", min_value=0.0, value=float(default_sl),
                    step=0.01, format="%.4f",
                    help="0이면 미설정. 도달 시 자동 청산.",
                )
            with tp_col:
                take_profit = st.number_input(
                    "익절가", min_value=0.0, value=float(default_tp),
                    step=0.01, format="%.4f",
                    help="0이면 미설정. 도달 시 자동 청산.",
                )
            with ts_col:
                trailing_pct = st.number_input(
                    "Trailing Stop %",
                    min_value=0.0, max_value=50.0, value=0.0, step=0.5,
                    help="고점 대비 N% 하락 시 자동 청산. 0이면 미사용.",
                )
            with td_col:
                time_stop = st.number_input(
                    "시간 청산 (일)", min_value=0, max_value=365, value=0, step=1,
                    help="N일 경과 시 자동 청산. 0이면 미사용.",
                )

            # 손절/익절 R/R 표시
            if stop_loss > 0 and buy_price > stop_loss:
                risk = buy_price - stop_loss
                risk_pct = risk / buy_price * 100
                st.caption(f"🛑 손절 거리: **{risk_pct:.2f}%** (${risk:.2f}/주)")
            if take_profit > 0 and take_profit > buy_price:
                reward = take_profit - buy_price
                reward_pct = reward / buy_price * 100
                st.caption(f"🎯 익절 거리: **{reward_pct:.2f}%** (${reward:.2f}/주)")
            if stop_loss > 0 and take_profit > buy_price > stop_loss:
                rr = (take_profit - buy_price) / (buy_price - stop_loss)
                st.caption(f"📐 R/R 비율: **{rr:.2f}** (익절/손절)")

        reason = st.text_input(
            "진입 근거 메모 (선택)",
            value=(prefill.get("reason", "") if prefill else ""),
            placeholder="예: Multi-Agent 신호 buy 7.5/10, RSI 반등",
        )

        # 매수 실행
        if st.button("🛒 **가상 매수 실행**", type="primary", use_container_width=True):
            body = {
                "ticker": trade_ticker,
                "qty": int(buy_qty),
                "price": float(buy_price),
                "reason": reason or "수동 가상 매수",
                "stop_loss_price": float(stop_loss) if stop_loss > 0 else None,
                "take_profit_price": float(take_profit) if take_profit > 0 else None,
                "trailing_stop_pct": float(trailing_pct / 100) if trailing_pct > 0 else None,
                "time_stop_days": int(time_stop) if time_stop > 0 else None,
            }
            result = api_post("/paper/virtual-buy", json_body=body)
            if result and result.get("status") == "filled":
                st.success(
                    f"✅ **{trade_ticker}** {buy_qty}주 @ {_fmt_price(buy_price, trade_ticker)} 체결됨 "
                    f"(총 {_fmt_price(total_cost, trade_ticker)})"
                )
                # 프리필 제거
                st.session_state.pop("vt_prefill", None)
                st.session_state.vt_quote = None
                st.balloons()
            else:
                reject = (result or {}).get("reject_reason") or "알 수 없는 오류"
                st.error(f"체결 실패: {reject}")

    st.divider()

    # ── 3. 포지션 모니터링 ─────────────────
    st.markdown("### 📊 포지션 모니터링")
    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 현재가 갱신", use_container_width=True):
            with st.spinner("가격 갱신 중..."):
                update_result = api_post("/paper/update-prices")
            if update_result:
                updated = update_result.get("updated", 0)
                auto_closed = update_result.get("auto_closed", [])
                st.success(f"✅ {updated}개 종목 갱신")
                if auto_closed:
                    st.warning(f"⚠️ {len(auto_closed)}개 포지션 자동 청산됨")
                    for ac in auto_closed:
                        st.write(f"  • {ac.get('ticker')} — {ac.get('reason', '?')}")
            st.rerun()
    with col_info:
        st.caption(
            "손절/익절/trailing/시간 조건은 **현재가 갱신 시에만** 평가됩니다. "
            "자동 갱신은 `position_mark_to_market` 잡이 담당합니다."
        )

    if not positions_map:
        st.info("📭 보유 포지션 없음. 위 폼에서 첫 가상 매수를 시작하세요.")
    else:
        # 포지션을 카드로 표시
        for ticker, p in positions_map.items():
            entry = p.get("entry_price", 0)
            current = p.get("current_price", entry)
            qty = p.get("qty", 0)
            pnl = p.get("pnl", 0)
            pnl_pct = p.get("pnl_pct", 0)
            is_kr = ticker.endswith((".KS", ".KQ"))
            cur = "₩" if is_kr else "$"

            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            # 포지션 헤더에 종목명 포함
            pos_label = format_ticker_label(ticker, style="name_with_code")
            with st.expander(
                f"{pnl_emoji} **{pos_label}** · {qty}주 @ {cur}{entry:,.2f} "
                f"→ {cur}{current:,.2f} ({pnl_pct:+.2f}%)",
                expanded=True,
            ):
                cc1, cc2, cc3, cc4 = st.columns(4)
                cc1.metric("수량", f"{qty}주")
                cc2.metric("진입가", f"{cur}{entry:,.2f}")
                cc3.metric("현재가", f"{cur}{current:,.2f}",
                           delta=f"{pnl_pct:+.2f}%",
                           delta_color="normal" if pnl_pct >= 0 else "inverse")
                cc4.metric("손익", f"{cur}{pnl:+,.2f}")

                # 언제 평가된 손익인지 — 시각이 없으면 진입가 그대로일 수 있다.
                # 2026-09-14 이전에는 갱신 잡이 없어 144일간 진입가에 멈춰 있었다.
                stamp = p.get("price_updated_at")
                if stamp:
                    st.caption(f"현재가 갱신: {str(stamp)[:19].replace('T', ' ')}")
                else:
                    st.warning("현재가가 한 번도 갱신되지 않았습니다 — 손익은 진입가 기준입니다.")

                # 진입일/경과일
                entry_date = p.get("entry_date", "")
                if entry_date:
                    try:
                        ed = datetime.fromisoformat(entry_date.split(".")[0] if "." in entry_date else entry_date)
                        elapsed = (datetime.now() - ed).days
                        st.caption(f"📅 진입: {entry_date[:10]} · 경과 **{elapsed}일**")
                    except Exception:
                        st.caption(f"📅 진입: {entry_date[:19]}")

                # 부분/전량 청산
                st.markdown("**청산 실행**")
                cls1, cls2, cls3, cls4, cls5 = st.columns([1, 1, 1, 1, 1])

                def _close(pct: int):
                    body = {"ticker": ticker, "close_pct": float(pct),
                            "reason": f"수동 {pct}% 청산"}
                    r = api_post("/paper/partial-close", json_body=body)
                    if r and r.get("status") == "filled":
                        realized = r.get("pnl", 0)
                        st.success(
                            f"✅ {pct}% 청산됨 — {r.get('qty')}주 @ {cur}{r.get('price', 0):,.2f} · 실현 손익 {cur}{realized:+,.2f}"
                        )
                        st.rerun()
                    else:
                        st.error(f"청산 실패: {(r or {}).get('reject_reason', '?')}")

                if cls1.button("25%", key=f"close25_{ticker}", use_container_width=True):
                    _close(25)
                if cls2.button("50%", key=f"close50_{ticker}", use_container_width=True):
                    _close(50)
                if cls3.button("75%", key=f"close75_{ticker}", use_container_width=True):
                    _close(75)
                if cls4.button("100%", key=f"close100_{ticker}",
                               type="primary", use_container_width=True):
                    _close(100)
                with cls5:
                    custom_price = st.number_input(
                        "지정가 청산", min_value=0.0, value=0.0, step=0.01,
                        key=f"cp_{ticker}", label_visibility="collapsed",
                        placeholder="지정가"
                    )
                    if st.button("매도", key=f"custom_{ticker}", use_container_width=True):
                        if custom_price > 0:
                            body = {"ticker": ticker, "close_pct": 100.0,
                                    "price": float(custom_price),
                                    "reason": f"수동 지정가 {custom_price} 청산"}
                            r = api_post("/paper/partial-close", json_body=body)
                            if r and r.get("status") == "filled":
                                st.success(f"✅ 지정가 {cur}{custom_price:,.2f} 청산")
                                st.rerun()

                # 손절/익절 표시 (있으면)
                sl = p.get("stop_loss_price", 0)
                tp = p.get("take_profit_price", 0)
                ts = p.get("trailing_stop_pct", 0)
                tsd = p.get("time_stop_days", 0)
                if sl or tp or ts or tsd:
                    st.markdown("**자동 청산 조건**")
                    lines = []
                    if sl:
                        dist = (current - sl) / current * 100
                        lines.append(f"🛑 손절 {cur}{sl:,.2f} (현재가 대비 {dist:+.2f}%)")
                    if tp:
                        dist = (tp - current) / current * 100
                        lines.append(f"🎯 익절 {cur}{tp:,.2f} (현재가 대비 {dist:+.2f}%)")
                    if ts:
                        peak = p.get("peak_price", current)
                        trail_price = peak * (1 - ts)
                        lines.append(f"📉 Trailing {ts*100:.1f}% · 고점 {cur}{peak:,.2f} → 트리거 {cur}{trail_price:,.2f}")
                    if tsd:
                        lines.append(f"⏱ 시간 청산 {tsd}일")
                    for line in lines:
                        st.caption(line)

    st.divider()

    # ── 4. 최근 청산 이력 ─────────────────
    st.markdown("### 📋 최근 청산 이력")
    recent = status.get("recent_trades", [])
    if recent:
        rows = []
        for t in reversed(recent[-20:]):
            is_win = t.get("pnl", 0) > 0
            tkr = t.get("ticker", "?")
            name = get_ticker_display_name(tkr)
            rows.append({
                "종목명": name if name and name != tkr else "—",
                "티커": tkr,
                "수량": t.get("qty", 0),
                "진입가": f"${t.get('entry_price', 0):.2f}",
                "청산가": f"${t.get('exit_price', 0):.2f}",
                "손익": f"${t.get('pnl', 0):+.2f}",
                "수익률": f"{t.get('pnl_pct', 0):+.2f}%",
                "결과": "🟢 WIN" if is_win else "🔴 LOSS",
                "사유": t.get("reason", "")[:40],
                "청산일": (t.get("exit_date", "") or "")[:10],
            })
        st.dataframe(rows, use_container_width=True, row_height=44, hide_index=True)
    else:
        st.caption("아직 청산된 거래 없음")
