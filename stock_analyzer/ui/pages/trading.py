"""실거래 페이지 — 브로커 주문·계좌 (TRADING_MODE 에 따라 동작이 갈린다).

`webui.py` 분해 — 페이지 단위 (CLAUDE.md §6-10). 분리 후 **렌더 함수를 직접
호출**해 확인한다: ast 파싱·import·HTTP 200 은 화면 결함을 잡지 못한다 (§13.9a).
"""

from __future__ import annotations

import streamlit as st

from ui.api_client import api_get, api_post
from ui.format import _fmt_price


def render_trading():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">🛡️ Trading Center</div>
        <div class="page-subtitle">주문 모드 · 안전장치 · 승인 큐 · 감사 로그</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 상단: 현재 모드 + 안전 상태 ───────────────
    mode_data = api_get("/trading/mode")
    if not mode_data:
        st.error("API 서버에 연결할 수 없습니다. chart_agent_service가 실행 중인지 확인하세요.")
        return

    current_mode = mode_data.get("mode", "paper")
    safety = mode_data.get("safety", {})
    kill_active = safety.get("kill_switch_active", False)

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        mode_desc = {
            "paper": "🟢 PAPER — 시뮬레이션 (안전)",
            "dry_run": "🟡 DRY RUN — 주문 생성·로그만",
            "approval": "🟠 APPROVAL — 승인 후 실행",
            "live": "🔴 LIVE — 실제 자금 이동",
        }
        st.metric("현재 모드", mode_desc.get(current_mode, current_mode))
    with col2:
        st.metric("Kill Switch", "🚨 활성" if kill_active else "✅ 정상")
    with col3:
        broker_health = api_get("/trading/broker-health")
        if broker_health:
            h = broker_health.get("health", {})
            st.metric("브로커", f"{'✅' if h.get('ok') else '❌'} {broker_health.get('broker', '?')}")

    # ── Alpaca 연결 + 데이터 소스 상태 (Phase 2.2) ─
    with st.expander("🔌 증권사 · 데이터 소스 연결 상태", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Alpaca 증권사**")
            alpaca_h = api_get("/trading/broker-health/alpaca")
            if alpaca_h:
                h = alpaca_h.get("health", {})
                if h.get("ok"):
                    st.success(f"✅ {h.get('message', '정상')} ({h.get('latency_ms', 0)}ms)")
                else:
                    st.warning(f"⚠️ {h.get('message', '미연결')}")
            else:
                st.caption("연결 정보 없음")
        with col_b:
            st.markdown("**데이터 소스**")
            ds = api_get("/data-source")
            if ds:
                configured = ds.get("configured", "?")
                active = ds.get("active", "?")
                h = ds.get("health", {})
                if configured != active:
                    st.info(f"설정: **{configured}** → 폴백: **{active}**")
                else:
                    st.markdown(f"활성: **{active}**")
                if h.get("ok"):
                    st.success(f"✅ {h.get('message', '정상')} ({h.get('latency_ms', 0)}ms)")
                else:
                    st.warning(f"⚠️ {h.get('message', '응답 없음')}")

    # ── 모드 변경 ──────────────────────────────
    with st.expander("⚙️ 모드 변경 (주의)", expanded=False):
        new_mode = st.selectbox(
            "TRADING_MODE",
            ["paper", "dry_run", "approval", "live"],
            index=["paper", "dry_run", "approval", "live"].index(current_mode),
        )
        if st.button("모드 적용", type="secondary"):
            resp = api_post(f"/trading/mode?mode={new_mode}")
            if resp and resp.get("ok"):
                st.success(f"모드 변경: {resp.get('mode')}")
                st.rerun()
            else:
                st.error(f"변경 실패: {resp}")

    # ── Kill Switch 제어 ───────────────────────
    col_ks1, col_ks2 = st.columns(2)
    with col_ks1:
        if not kill_active:
            if st.button("🚨 긴급 중지 활성화", type="primary", use_container_width=True):
                resp = api_post("/trading/kill-switch/activate?reason=manual_webui")
                if resp and resp.get("ok"):
                    st.warning("Kill Switch 활성화됨 — 모든 신규 주문 차단")
                    st.rerun()
    with col_ks2:
        if kill_active:
            if st.button("✅ 긴급 중지 해제", use_container_width=True):
                resp = api_post("/trading/kill-switch/deactivate?reason=manual_webui")
                if resp and resp.get("ok"):
                    st.success("Kill Switch 해제됨")
                    st.rerun()

    st.divider()

    # ── 일일 한도 사용량 ────────────────────────
    st.markdown("### 💰 일일 주문 한도 사용량")
    limits = safety.get("daily_limits", {})
    col_us, col_kr = st.columns(2)
    for col, market in [(col_us, "US"), (col_kr, "KR")]:
        with col:
            m = limits.get(market, {})
            spent = m.get("spent", 0)
            limit = m.get("limit", 1)
            pct = min(100, (spent / limit * 100) if limit > 0 else 0)
            currency = "₩" if market == "KR" else "$"
            st.markdown(f"**{market}** — 주문 {m.get('count', 0)}건")
            st.progress(pct / 100)
            st.caption(f"{currency}{spent:,.0f} / {currency}{limit:,.0f} ({pct:.1f}%)")

    st.divider()

    # ── 계좌 및 포지션 ────────────────────────
    st.markdown("### 📊 계좌 상태")
    account = api_get("/trading/account")
    if account:
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            st.metric("총 자산", f"${account.get('total_equity', 0):,.2f}")
        with a2:
            st.metric("현금", f"${account.get('cash', 0):,.2f}")
        with a3:
            pnl = account.get('total_pnl_pct', 0)
            st.metric("수익률", f"{pnl:+.2f}%", delta_color="normal" if pnl >= 0 else "inverse")
        with a4:
            st.metric("포지션", f"{account.get('open_positions', 0)}개")

    positions_data = api_get("/trading/positions")
    if positions_data and positions_data.get("positions"):
        st.markdown("#### 보유 포지션")
        rows = []
        for p in positions_data["positions"]:
            ticker = p.get("ticker", "")
            rows.append({
                "Ticker": ticker,
                "Qty": p.get("qty"),
                "Entry": _fmt_price(p.get("avg_entry_price"), ticker),
                "Current": _fmt_price(p.get("current_price"), ticker),
                "P&L": _fmt_price(p.get("unrealized_pnl"), ticker),
                "P&L %": f"{p.get('unrealized_pnl_pct', 0):+.2f}%",
            })
        st.dataframe(rows, use_container_width=True, row_height=44, hide_index=True)

    st.divider()

    # ── 승인 대기 큐 (APPROVAL 모드용) ────────
    st.markdown("### 🔔 승인 대기 주문")
    pending_data = api_get("/trading/approval/pending")
    if pending_data:
        pending = pending_data.get("pending", [])
        if pending:
            st.info(f"**{len(pending)}건** 승인 대기 중")
            for p in pending:
                queue_id = p.get("id")
                ticker = p.get("ticker", "?")
                side = p.get("side", "?").upper()
                qty = p.get("qty", 0)
                price = p.get("limit_price")
                price_str = f"@ {_fmt_price(price, ticker)}" if price else "@ 시장가"

                cols = st.columns([4, 1, 1])
                with cols[0]:
                    st.markdown(f"**#{queue_id}** · `{ticker}` {side} {qty}주 {price_str}")
                    st.caption(f"요청: {p.get('requested_at', '')[:19]}")
                with cols[1]:
                    if st.button("✅ 승인", key=f"approve_{queue_id}"):
                        result = api_post(f"/trading/approval/{queue_id}/approve")
                        if result and result.get("executed"):
                            st.success(f"주문 #{queue_id} 실행됨")
                            st.rerun()
                        else:
                            st.error(f"실행 실패: {result}")
                with cols[2]:
                    if st.button("❌ 거절", key=f"reject_{queue_id}"):
                        result = api_post(f"/trading/approval/{queue_id}/reject")
                        if result and result.get("ok"):
                            st.info(f"주문 #{queue_id} 거절됨")
                            st.rerun()
        else:
            st.caption("대기 중인 주문 없음")

    st.divider()

    # ── 최근 주문 감사 로그 ───────────────────
    st.markdown("### 📝 최근 주문 (감사 로그)")
    recent = api_get("/trading/orders/recent?limit=20")
    if recent and recent.get("orders"):
        rows = []
        for o in recent["orders"]:
            status_icon = "✅" if o.get("result_success") else ("🚫" if not o.get("safety_check_passed") else "⚠️")
            ticker = o.get("ticker", "")
            limit_price = o.get("limit_price")
            rows.append({
                "시각": (o.get("created_at") or "")[:19],
                "모드": o.get("trading_mode", ""),
                "Ticker": ticker,
                "Side": o.get("side", "").upper(),
                "Qty": o.get("qty", 0),
                "가격": _fmt_price(limit_price, ticker) if limit_price else "—",
                "결과": f"{status_icon} {o.get('result_status') or o.get('safety_reason', '?')}",
            })
        st.dataframe(rows, use_container_width=True, row_height=44, hide_index=True)

    # 통계
    stats = api_get("/trading/orders/stats?days_back=7")
    if stats:
        st.markdown("#### 7일 통계")
        s1, s2, s3 = st.columns(3)
        with s1:
            st.metric("총 시도", stats.get("total_orders", 0))
        with s2:
            st.metric("안전장치 차단", stats.get("blocked_by_safety", 0))
        with s3:
            by_mode = stats.get("by_trading_mode", {})
            st.caption(f"모드별: {by_mode}")
