"""홈 페이지 — 마켓 티커 바, 워치리스트 칩, 한국장 도구 패널.

`webui.py` 분해 — 페이지 단위 (CLAUDE.md §6-10). 분리 후 **렌더 함수를 직접
호출**해 확인한다: ast 파싱·import·HTTP 200 은 화면 결함을 잡지 못한다 (§13.9a).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from ui.api_client import api_get
from ui.korean_optional import (
    KOREAN_STOCKS_AVAILABLE,
    KOREAN_STOCKS_UNAVAILABLE_REASON,
    KoreanStockData,
    get_kr_indices,
)
from ui.components import _css_key, _plotly_base_layout, ticker_chip_html
from ui.market import MARKET_INDICES, _INDEX_PERIODS, fetch_index_history, fetch_market_indices
from ui.tickers import _is_korean_ticker, _market_code, _market_flag, add_to_watchlist, clear_watchlist, get_ticker_display_name, load_watchlist, remove_from_watchlist


def render_home():
    """통합 홈 페이지 — 미국/한국 시장 구분 없이 한 화면에서 관리."""
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Stock AI</div>
        <div class="page-subtitle">AI-Powered Multi-Tool Stock Analysis Terminal · 미국/한국 통합</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 1. 시장 지수 바 (S&P/NASDAQ/DOW/KOSPI/KOSDAQ/원달러/상품) ──
    render_market_ticker_bar()

    # ── 2. 분석 요약 (시장 구분 없이 전체) ──
    data = api_get("/results")
    results = data.get("results", {}) if data else {}
    total = len(results)
    buy_count = sum(1 for r in results.values() if r.get("signal") == "BUY")
    sell_count = sum(1 for r in results.values() if r.get("signal") == "SELL")
    hold_count = sum(1 for r in results.values() if r.get("signal") == "HOLD")

    # 시장별 세부 카운트
    us_results = {k: v for k, v in results.items() if not _is_korean_ticker(k)}
    kr_results = {k: v for k, v in results.items() if _is_korean_ticker(k)}

    # DS §05 StatCell — 값 0인 카드 6개가 빈 공간처럼 보이던 것을 1px 분할 행으로 통합.
    render_stat_row([
        ("TOTAL", total), ("BUY", buy_count), ("SELL", sell_count),
        ("HOLD", hold_count), ("US", len(us_results)), ("KR", len(kr_results)),
    ], empty_hint="스캔 없음")

    # ── 3. 시스템 상태 ──
    health = api_get("/health")
    info = api_get("/")
    watchlist = load_watchlist()

    st.markdown("""
    <div class="section-header">
        <div class="section-title">System Status</div>
    </div>
    """, unsafe_allow_html=True)

    s1, s2, s3, s4 = st.columns(4)
    if health:
        ollama_status = health.get("ollama", "disconnected")
        s1.metric("Agent", "Online" if ollama_status == "connected" else "Offline")
        s2.metric("Cached Results", str(health.get("cached_results", 0)))
        s3.metric("Total Scans", str(health.get("scan_count", 0)))
    else:
        s1.metric("Agent", "Offline")
        s2.metric("Cached Results", "—")
        s3.metric("Total Scans", "—")

    if info:
        s4.metric("Model", info.get("model", "—"))
    else:
        s4.metric("Model", "—")

    # ── 4. 통합 Watchlist (시장 플래그 포함) ──
    st.markdown("""
    <div class="section-header">
        <div class="section-title">Watchlist · 통합</div>
    </div>
    """, unsafe_allow_html=True)

    if watchlist:
        # 필터: 전체 / 🇺🇸 US / 🇰🇷 KR
        filter_col, add_col = st.columns([1, 2])
        with filter_col:
            market_filter = st.radio(
                "시장 필터",
                ["전체", "🇺🇸 US", "🇰🇷 KR"],
                horizontal=True,
                label_visibility="collapsed",
                key="home_market_filter",
            )
        with add_col:
            # 동적 key로 추가 성공 시 입력창 비우기
            if "home_quick_add_counter" not in st.session_state:
                st.session_state.home_quick_add_counter = 0
            new_tk = st.text_input(
                "빠른 종목 추가",
                placeholder="AAPL, 005930.KS, 삼성전자 — 미국/한국 구분 없이 입력",
                key=f"home_quick_add_{st.session_state.home_quick_add_counter}",
                label_visibility="collapsed",
            )
            if new_tk and st.button("➕ Watchlist 추가", key="home_add_btn"):
                ok, msg = add_to_watchlist(new_tk)
                if ok:
                    st.success(msg)
                    # 새 key로 widget 재생성 → 입력창 초기화
                    st.session_state.home_quick_add_counter += 1
                    st.rerun()
                else:
                    st.error(msg)

        # watchlist 필터링
        if market_filter == "🇺🇸 US":
            filtered = [t for t in watchlist if not _is_korean_ticker(t)]
        elif market_filter == "🇰🇷 KR":
            filtered = [t for t in watchlist if _is_korean_ticker(t)]
        else:
            filtered = watchlist

        if filtered:
            wl_chips = " ".join(ticker_chip_html(t) for t in filtered)
            st.markdown(f'<div style="line-height:2.2;">{wl_chips}</div>', unsafe_allow_html=True)
            st.caption(f"표시 {len(filtered)}개 / 전체 {len(watchlist)}개")

            # 종목 삭제 — 선택 삭제 + 전체 삭제
            rm_col, clear_col = st.columns([3, 1])
            with rm_col:
                rm_targets = st.multiselect(
                    "삭제할 종목",
                    options=filtered,
                    format_func=lambda t: f"{_market_flag(t)} {get_ticker_display_name(t)} ({t})",
                    key="home_wl_remove",
                    placeholder="삭제할 종목 선택 (복수 선택 가능)",
                    label_visibility="collapsed",
                )
                if rm_targets and st.button(
                    f"🗑 선택 {len(rm_targets)}개 삭제", key="home_wl_rm_btn",
                    use_container_width=True,
                ):
                    failed = []
                    for t in rm_targets:
                        ok, msg = remove_from_watchlist(t)
                        if not ok:
                            failed.append(msg)
                    if failed:
                        for m in failed:
                            st.error(m)
                    else:
                        st.success(f"{len(rm_targets)}개 종목을 삭제했습니다")
                        st.rerun()
            with clear_col:
                # 전체 삭제는 되돌릴 수 없으므로 체크박스로 한 번 더 확인받는다.
                confirm_clear = st.checkbox("전체 삭제 확인", key="home_wl_clear_confirm")
                if st.button(
                    "🗑 전체 삭제", key="home_wl_clear_btn",
                    disabled=not confirm_clear, use_container_width=True,
                ):
                    try:
                        ok, msg = clear_watchlist()
                    except OSError as exc:
                        ok, msg = False, f"❌ 전체 삭제 실패 — 파일 저장 오류: {exc}"
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.warning(msg)
        else:
            st.caption(f"'{market_filter}' 필터에 해당하는 종목 없음")
    else:
        st.caption("No tickers in watchlist. Add tickers from the sidebar or above.")

    # ── 5. 최신 신호 (시장 통합 테이블) ──
    if results:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">Latest Signals · 통합</div>
        </div>
        """, unsafe_allow_html=True)

        # 시장 필터 옵션
        sig_filter = st.radio(
            "신호 필터",
            ["전체", "🇺🇸 US", "🇰🇷 KR", "BUY만", "SELL만"],
            horizontal=True,
            label_visibility="collapsed",
            key="home_sig_filter",
        )

        rows = []
        for ticker, r in sorted(results.items(), key=lambda x: abs(x[1].get("score", 0)), reverse=True):
            flag = _market_flag(ticker)
            market_code = _market_code(ticker)
            signal = r.get("signal", "?")

            # 필터 적용
            if sig_filter == "🇺🇸 US" and flag != "🇺🇸":
                continue
            if sig_filter == "🇰🇷 KR" and flag != "🇰🇷":
                continue
            if sig_filter == "BUY만" and signal != "BUY":
                continue
            if sig_filter == "SELL만" and signal != "SELL":
                continue

            # 종목명 조회 (캐시됨)
            display_name = get_ticker_display_name(ticker)
            name_cell = display_name if display_name and display_name != ticker else "—"

            rows.append({
                "Market": f"{flag} {market_code}",
                "Name": name_cell,
                "Ticker": ticker,
                "Signal": signal,
                "Score": r.get("score", 0),
                "Confidence": r.get("confidence", 0),
                "Time": str(r.get("analyzed_at", ""))[:16],
            })

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(
                df.style.map(
                    lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
                    subset=["Signal"],
                ),
                use_container_width=True, hide_index=True,
            )
        else:
            st.caption(f"'{sig_filter}'에 해당하는 신호 없음")

    # ── 6. 한국 시장 고유 기능 (접이식) ──
    # 모듈이 없어도 섹션을 **지우지 않는다** — 종전에는 통째로 사라져서 기능이
    # 원래 없는 것처럼 보였다 (CLAUDE.md §13: 장애가 정상으로 보이면 안 된다).
    with st.expander("🇰🇷 한국 주식 심화 도구 (매매동향 · DART 공시 · 즐겨찾기)", expanded=False):
        render_korean_tools_panel()


def render_korean_tools_panel():
    """한국 주식 전용 도구 (통합 홈의 접이식 섹션)."""
    if not KOREAN_STOCKS_AVAILABLE:
        st.warning("한국 주식 모듈을 사용할 수 없습니다.")
        if KOREAN_STOCKS_UNAVAILABLE_REASON:
            st.caption(f"사유: {KOREAN_STOCKS_UNAVAILABLE_REASON}")
        return

    # KOSPI/KOSDAQ 지수
    try:
        indices = get_kr_indices()
        kospi = indices.get('kospi', {})
        kosdaq = indices.get('kosdaq', {})

        if kospi or kosdaq:
            col1, col2 = st.columns(2)
            if kospi:
                with col1:
                    change_pct = kospi.get('change_pct', 0)
                    st.metric(
                        "KOSPI",
                        f"{kospi.get('current', 0):,.2f}",
                        f"{change_pct:+.2f}%",
                        delta_color="normal" if change_pct >= 0 else "inverse",
                    )
            if kosdaq:
                with col2:
                    change_pct = kosdaq.get('change_pct', 0)
                    st.metric(
                        "KOSDAQ",
                        f"{kosdaq.get('current', 0):,.2f}",
                        f"{change_pct:+.2f}%",
                        delta_color="normal" if change_pct >= 0 else "inverse",
                    )
    except Exception as e:
        st.caption(f"지수 로드 실패: {e}")

    # Watchlist의 한국 종목만 사용 (SSOT) — 별도 즐겨찾기 파일 사용하지 않음
    watchlist = load_watchlist()
    kr_tickers = [t for t in watchlist if _is_korean_ticker(t)]

    if not kr_tickers:
        st.info(
            "📭 Watchlist에 한국 종목이 없습니다.\n\n"
            "사이드바 또는 홈 페이지의 Watchlist에 한국 종목 추가 시 여기에 자동 표시됩니다.\n\n"
            "입력 예시: `136480.KS` (하림), `005930.KS` (삼성전자), `하림` (한글명)"
        )
        return

    # ticker → (code, name) 변환 헬퍼
    def _to_code_name(ticker):
        """Watchlist 티커에서 (순수코드, 종목명) 반환."""
        t = ticker.upper()
        if t.endswith('.KS') or t.endswith('.KQ'):
            code = t[:-3]
        else:
            code = t
        name = get_ticker_display_name(ticker)
        if not name or name == ticker:
            name = code
        return code, name

    # 한국 종목 (code, name, ticker) 리스트
    kr_items = [(_to_code_name(t), t) for t in kr_tickers]
    # kr_items = [((code, name), full_ticker), ...]

    # ── Watchlist 한국 종목 현재가 카드 ──
    st.markdown(f"**📌 Watchlist 한국 종목** ({len(kr_tickers)}개)")
    cols = st.columns(3)
    for idx, ((code, name), ticker) in enumerate(kr_items):
        with cols[idx % 3]:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='5d')
                if not hist.empty:
                    current = hist['Close'].iloc[-1]
                    prev = hist['Close'].iloc[-2] if len(hist) > 1 else current
                    change_pct = ((current / prev) - 1) * 100 if prev else 0
                    st.metric(
                        f"{name} ({code})",
                        f"₩{current:,.0f}",
                        f"{change_pct:+.2f}%",
                        delta_color="normal" if change_pct >= 0 else "inverse",
                    )
                else:
                    st.metric(f"{name} ({code})", "데이터 없음", "—")
            except Exception:
                st.metric(f"{name} ({code})", "로드 실패", "—")

    # ── 투자자별 매매 동향 — Watchlist 한국 종목에서만 선택 ──
    st.markdown("**📊 투자자별 매매 동향** (외국인 · 기관 · 개인)")
    try:
        ticker_options = [f"{code} ({name})" for (code, name), _ in kr_items]
        sample_ticker = st.selectbox(
            "종목 선택 (Watchlist의 한국 종목)",
            ticker_options,
            key="home_kr_inst_select",
        )

        if st.button("📊 매매동향 조회", key="home_kr_inst_btn"):
            ticker_code = sample_ticker.split()[0] if sample_ticker else ""
            if ticker_code:
                with st.spinner(f"{ticker_code} 매매동향 조회 중..."):
                    collector = KoreanStockData()
                    trading_data = collector.fetch_institutional_trading(ticker_code, days=5)
                    if trading_data and 'summary' in trading_data:
                        summary = trading_data['summary']
                        c1, c2, c3 = st.columns(3)
                        c1.metric("외국인 순매수", f"{summary.get('foreign_net', 0):,}주")
                        c2.metric("기관 순매수", f"{summary.get('institution_net', 0):,}주")
                        c3.metric("개인 순매수", f"{summary.get('individual_net', 0):,}주")
                    else:
                        st.caption("데이터 없음")
    except Exception as e:
        st.caption(f"매매동향 조회 실패: {e}")

    # ── DART 공시 — Watchlist 한국 종목에서만 선택 ──
    st.markdown("**📄 DART 공시**")
    try:
        from dart_api import DARTClient
        dart_client = DARTClient()
        if dart_client.is_configured():
            ticker_options = [f"{code} ({name})" for (code, name), _ in kr_items]
            disclosure_ticker = st.selectbox(
                "공시 조회 종목 (Watchlist의 한국 종목)",
                ticker_options,
                key="home_kr_dart_select",
            )
            if st.button("📄 최근 공시 조회", key="home_kr_dart_btn"):
                ticker_code = disclosure_ticker.split()[0] if disclosure_ticker else ""
                with st.spinner(f"{ticker_code} 공시 조회 중..."):
                    disclosures = dart_client.fetch_recent_disclosures(ticker_code, days=30)
                    if disclosures:
                        st.write(f"최근 30일 공시: {len(disclosures)}건")
                        for d in disclosures[:10]:
                            with st.expander(f"{d['date']}: {d['title'][:60]}..."):
                                st.markdown(f"**보고서 유형**: {d.get('report_type', 'N/A')}")
                                st.markdown(f"**링크**: {d.get('url', 'N/A')}")
                    else:
                        st.caption("공시 데이터 없음")
        else:
            st.caption("⚠️ DART_API_KEY 미설정 — opendart.fss.or.kr에서 무료 발급")
    except ImportError:
        st.caption("DART API 모듈 로드 실패")


@st.cache_data(ttl=300)
def render_index_chart(symbol: str, label: str, decimals: int):
    """선택한 지수의 추이 차트."""
    # DS §05: 기간 선택은 라디오 대신 세그먼트 컨트롤 (클릭 타깃 확대)
    period_label = st.segmented_control(
        "기간",
        list(_INDEX_PERIODS.keys()),
        default="6개월",
        key=f"idx_period_{symbol}",
        label_visibility="collapsed",
    ) or "6개월"
    hist = fetch_index_history(symbol, _INDEX_PERIODS[period_label])
    if hist is None or hist.empty:
        st.warning(f"{label} 이력을 불러오지 못했습니다 ({symbol})")
        return

    close = hist["Close"].dropna()
    first, last = float(close.iloc[0]), float(close.iloc[-1])
    change_pct = (last / first - 1) * 100 if first else 0.0
    line_color = "#2BD98A" if change_pct >= 0 else "#FF6B6B"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=close.index, y=close.values, mode="lines", name=label,
        line=dict(color=line_color, width=2),
        fill="tozeroy", fillcolor=f"rgba({'2,212,161' if change_pct >= 0 else '253,82,111'},0.08)",
        hovertemplate=f"%{{x|%Y-%m-%d}}<br>{label} %{{y:,.{decimals}f}}<extra></extra>",
    ))
    fig.update_layout(**_plotly_base_layout(
        height=320,
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=False,
        title=dict(text=f"{label} · {period_label} {change_pct:+.2f}%", font=dict(size=14)),
    ))
    # 지수/환율은 0부터 그리면 변동이 안 보인다 — 실제 범위에 여백만 준다.
    lo, hi = float(close.min()), float(close.max())
    pad = (hi - lo) * 0.08 or (hi * 0.01 or 1)
    fig.update_yaxes(range=[lo - pad, hi + pad])
    st.plotly_chart(fig, use_container_width=True, key=f"idx_chart_{symbol}")

    c1, c2, c3 = st.columns(3)
    c1.metric("현재", f"{last:,.{decimals}f}", f"{change_pct:+.2f}%")
    c2.metric("기간 최고", f"{hi:,.{decimals}f}")
    c3.metric("기간 최저", f"{lo:,.{decimals}f}")


def render_stat_row(items: "list[tuple[str, int]]", empty_hint: str = "—"):
    """StatCell 분할 행 (DS §05) — 카드 대신 1px 구분선 6열.

    전부 0이면 큰 숫자를 반복하지 않고 안내 문구로 대체한다.
    """
    all_zero = all(not v for _, v in items)
    cells = []
    for label, value in items:
        if all_zero:
            val_html = f'<div class="sc-value empty">{empty_hint}</div>'
        else:
            val_html = f'<div class="sc-value">{value:,}</div>'
        cells.append(f'<div class="statcell"><div class="sc-label">{label}</div>{val_html}</div>')
    # 열 수는 항목 수에 맞춘다 — 6열 고정이면 3개짜리 행에 빈 칸이 생긴다.
    st.markdown(
        f'<div class="statcell-row" style="grid-template-columns:repeat({len(items)},1fr);">'
        f'{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )


def render_market_ticker_bar():
    indices, market_updated_at = fetch_market_indices()
    if not indices:
        return

    st.markdown(f'<div class="ts-meta">Updated {market_updated_at}</div>', unsafe_allow_html=True)

    # 클릭 가능해야 하므로 HTML 셀 대신 버튼을 쓴다. Streamlit은 순수 HTML에
    # 콜백을 붙일 수 없어, 표시와 선택을 한 위젯으로 합친다.
    entries = [
        (sym, name, decimals)
        for group in MARKET_INDICES.values()
        for sym, name, decimals in group["items"]
    ]

    selected = st.session_state.get("selected_index")
    # DS §04: 타일 최소폭 180px. 6열로 잡으면 가격(19px mono)이 줄바꿈된다.
    per_row = 4
    dir_rules = []

    for row_start in range(0, len(entries), per_row):
        row = entries[row_start:row_start + per_row]
        cols = st.columns(per_row, gap="small")
        for col, (sym, name, decimals) in zip(cols, row):
            info = indices.get(sym)
            key = f"idx_btn_{_css_key(sym)}"
            # 라벨 / 가격 / 등락 3단. 등락 줄은 마크다운 이탤릭(*..*)으로 감싸
            # CSS(em)에서 크기를 주고, 방향 색은 위젯 key 클래스로 지정한다 —
            # 버튼 라벨은 줄별 스타일을 직접 지정할 수 없기 때문이다.
            if info:
                pct = info["change_pct"]
                token = "up" if pct > 0 else ("down" if pct < 0 else "text-low")
                arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "―")
                label = (
                    f"{name}  \n{info['price']:,.{info['decimals']}f}  \n"
                    f"*{arrow} {abs(pct):.2f}%*"
                )
            else:
                token = "text-low"
                label = f"{name}  \n— —  \n*데이터 없음*"
            dir_rules.append(f".st-key-{key} button p em{{color:var(--{token});}}")

            with col:
                if st.button(
                    label,
                    key=key,
                    use_container_width=True,
                    type="primary" if selected == sym else "secondary",
                    help=f"{name} ({sym}) 추이 차트",
                ):
                    # 같은 항목을 다시 누르면 차트를 접는다.
                    st.session_state.selected_index = None if selected == sym else sym
                    st.rerun()
    st.markdown(f"<style>{''.join(dir_rules)}</style>", unsafe_allow_html=True)

    selected = st.session_state.get("selected_index")
    if selected:
        meta = next(((s, n, d) for s, n, d in entries if s == selected), None)
        if meta:
            with st.container(border=True):
                render_index_chart(*meta)
