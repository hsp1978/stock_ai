"""신호 정확도 페이지 — 사후 적중률·표본 독립성·보정 상태.

`webui.py` 분해 5단계 — **페이지 단위** (CLAUDE.md §6-10). 페이지는 세션 상태와
헬퍼 결합이 있어 한 번에 하나씩 옮기고, 매번 3단 검증을 돌린다:
  1. 원본 대비 최상위 심볼 집합 비교 (문법 검사는 함수 중간 절단을 못 잡는다)
  2. 테스트 + ruff
  3. 배포 컨테이너에서 스크립트 실행 + 이 함수 직접 호출
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.api_client import api_get, api_post


def render_signal_accuracy():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">📈 Signal Accuracy</div>
        <div class="page-subtitle">신호별 사후 적중률 · 신뢰도 칼리브레이션 상태</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 컨트롤 ─────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])
    with col1:
        # 기본값은 매매 스타일의 의도 보유기간을 덮는 대표 horizon 이다.
        _primary = (api_get("/signal-accuracy/horizon") or {}).get("primary_horizon_days", 7)
        _options = [7, 14, 30]
        horizon = st.selectbox(
            "평가 기간", _options,
            index=_options.index(_primary) if _primary in _options else 0,
            help="신호 후 N일 수익률 기준. 기본값은 의도 보유기간을 덮는 horizon.",
        )
    with col2:
        min_conf = st.slider("최소 신뢰도", 0.0, 10.0, 0.0, step=0.5)
    with col3:
        signal_filter = st.selectbox("신호 필터", ["전체", "buy", "sell", "neutral"], index=0)
    with col4:
        days_back = st.selectbox("조회 기간", [30, 90, 180, 365], index=2,
                                  format_func=lambda x: f"최근 {x}일")
    with col5:
        dedupe = st.selectbox(
            "표본 단위", ["ticker_day", "ticker_horizon", "none"], index=0,
            format_func=lambda x: {
                "ticker_day": "종목·일 1건",
                "ticker_horizon": "종목·구간 1건",
                "none": "원시 행 전부",
            }[x],
            help="30분 스캔은 같은 종목·같은 날을 최대 48회 기록한다. "
                 "'원시 행 전부'는 독립 표본이 아니라 진단용이다.",
        )

    sig_param = None if signal_filter == "전체" else signal_filter

    # 수동 평가 실행 버튼
    col_refresh, col_eval = st.columns([1, 1])
    with col_refresh:
        if st.button("🔄 새로고침", use_container_width=True):
            st.cache_data.clear() if hasattr(st, "cache_data") else None
            st.rerun()
    with col_eval:
        if st.button("⚡ 과거 신호 재평가 실행", use_container_width=True,
                     help="아직 평가 안 된 과거 스캔의 결과를 지금 계산"):
            with st.spinner("평가 중..."):
                # 파라미터를 넘기지 않는다 — 창/배치 크기는 config가 SSOT.
                # (과거 이 버튼은 days_back=45&limit=500 을 박아 보내 큐 아사 조건을
                #  그대로 재현했다.)
                eval_result = api_post("/signal-accuracy/evaluate")
                if eval_result and isinstance(eval_result, dict):
                    ev = eval_result.get("evaluation", {})
                    st.success(
                        f"✓ 처리: {ev.get('processed', 0)}건, "
                        f"업데이트: {ev.get('updated', 0)}건, "
                        f"남은 대기: {ev.get('pending_due', 0)}건"
                    )
                    if ev.get("unresolved_total"):
                        st.caption(
                            f"시세 없어 종결된 신호 {ev['unresolved_total']}건은 집계에서 제외됩니다."
                        )
                    calib = eval_result.get("calibrator")
                    if calib:
                        st.info(
                            f"칼리브레이터 — active: {calib.get('active')}, "
                            f"표본: {calib.get('total_samples')}건"
                        )
                else:
                    st.error("평가 실행 실패 — API 서버 확인")

    st.divider()

    # ── 통계 조회 ──────────────────────────────────
    url = (
        f"/signal-accuracy?horizon={horizon}&min_confidence={min_conf}"
        f"&days_back={days_back}&dedupe={dedupe}"
    )
    if sig_param:
        url += f"&signal={sig_param}"
    data = api_get(url)

    if not data or data.get("total_evaluated", 0) == 0:
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">📊</div>
            <div class="es-text">평가된 신호가 아직 없습니다.<br>
            최소 7일 경과한 스캔 데이터가 있어야 합니다.<br>
            '과거 신호 재평가 실행' 버튼으로 수동 실행할 수 있습니다.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    # ── 핵심 지표 카드 ───────────────────────────
    total = data.get("total_evaluated", 0)
    hit_rate = data.get("direction_hit_rate_pct", 0)
    band = data.get("band_outcome") or {}
    avg_return = data.get("avg_signed_return_pct", 0)
    avg_raw = data.get("avg_raw_return_pct", 0)
    wins = band.get("win", 0)
    losses = band.get("loss", 0)

    sampling = data.get("sampling") or {}
    rows_raw = sampling.get("rows_raw", total)
    blocks = data.get("independent_blocks", 0)
    ci = data.get("direction_hit_ci95") or []

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        collapsed = rows_raw - total
        st.metric(
            "평가 건수(표본)", f"{total:,}",
            delta=(f"원시 {rows_raw:,}건에서 {collapsed:,}건 접음" if collapsed > 0 else "접힘 없음"),
            delta_color="off",
        )
    with c2:
        # 대표 지표는 밴드 없는 방향 적중률이다 — ±2% 밴드는 임의값이고
        # horizon 이 길수록 넘기 쉬워진다. 밴드 집계는 delta 에 부기한다.
        st.metric(
            "방향 적중률", f"{hit_rate:.1f}%",
            delta=(
                f"±{band.get('threshold_pct', 2)}% 기준 {wins}승/{losses}패"
                if band else ""
            ),
            delta_color="off",
            help="신호 방향대로 움직였는지(부호)만 본다. 밴드 승률은 임계에 의존한다.",
        )
    with c3:
        # 매수는 +수익률, 매도는 -수익률. 원시 평균은 매도가 맞을수록 내려가므로
        # 성과 지표로 쓸 수 없다 (진단용으로 delta 에만 남긴다).
        st.metric(
            "방향보정 기대값", f"{avg_return:+.2f}%",
            delta=f"원시 {avg_raw:+.2f}%", delta_color="off",
            help="매수는 +수익률, 매도는 −수익률로 부호를 맞춘 평균. "
                 "원시 평균은 매도 신호가 맞을수록 내려가 성과 지표가 되지 못한다.",
        )
    with c4:
        # 시장 대비 초과수익 — 절대 수익만으로는 '시장이 올라서'와 '신호가 맞아서'를
        # 구분할 수 없다. 벤치마크 표본이 없으면 그렇다고 적는다.
        bench_n = data.get("benchmark_sample", 0)
        excess = data.get("avg_excess_return_pct", 0)
        beat = data.get("beat_benchmark_rate_pct", 0)
        if bench_n:
            st.metric(
                "시장 대비 초과수익", f"{excess:+.2f}%",
                delta=f"시장 상회 {beat:.0f}% (n={bench_n:,})",
                delta_color="off",
                help="매수는 종목−지수, 매도는 지수−종목. 지수는 KOSPI/KOSDAQ/S&P500.",
            )
        else:
            st.metric("시장 대비 초과수익", "—", delta="벤치마크 미기록", delta_color="off")

    c5, c6 = st.columns(2)
    with c5:
        # 신뢰구간은 독립 블록 수로 계산한다 — 행 수로 계산하면 거짓으로 좁아진다.
        st.metric(
            "방향 적중률 95% 구간",
            f"{ci[0]:.0f}~{ci[1]:.0f}%" if len(ci) == 2 else "—",
            delta=f"독립 블록 {blocks:,}건",
            delta_color="off",
        )

    if not data.get("horizon_covers_holding", True):
        st.warning(
            f"평가 기간 {data.get('horizon_days')}일이 의도 보유기간 "
            f"{data.get('expected_holding_days')}일보다 짧습니다 — 이 지표는 보유 도중의 "
            f"중간 성과입니다 (대표 horizon: {data.get('primary_horizon_days')}일)."
        )

    if sampling:
        dom = sampling.get("dominant_source")
        dom_share = sampling.get("dominant_source_share_pct", 0)
        st.caption(
            f"표본 단위: {sampling.get('mode')} · 원시 {rows_raw:,}행 → 표본 {total:,}건 "
            f"(압축 {sampling.get('collapse_ratio', 1)}x) · 독립 블록 {blocks:,}건"
            + (f" · 최다 소스 {dom} {dom_share}%" if dom else "")
        )
        if dom_share >= 70:
            st.warning(
                f"표본의 {dom_share}%가 `{dom}` 한 소스에서 나왔다. "
                "이 지표는 그 소스의 성격을 주로 반영하며, 다른 경로의 성능이 아니다."
            )

    # ── 신호별 분포 ─────────────────────────────
    st.markdown("### 신호별 적중률")
    by_signal = data.get("by_signal", {})
    sig_cols = st.columns(3)
    for i, sig in enumerate(["buy", "sell", "neutral"]):
        s = by_signal.get(sig, {})
        with sig_cols[i]:
            n = s.get("total", 0)
            wr = s.get("direction_hit_rate_pct", 0)
            avg_r = s.get("avg_signed_return_pct", 0)
            icon = {"buy": "🟢", "sell": "🔴", "neutral": "⚪"}.get(sig, "")
            if n > 0:
                st.markdown(f"""
                <div class="summary-card">
                    <div style="font-size:0.7rem; color:var(--on-surface-variant);">{icon} {sig.upper()}</div>
                    <div style="font-size:1.8rem; font-weight:700;">{wr:.1f}%</div>
                    <div style="font-size:0.8rem; color:var(--on-surface-variant);">
                        n={n} · 방향보정 {avg_r:+.2f}%
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="summary-card" style="opacity:0.5;">
                    <div style="font-size:0.7rem;">{icon} {sig.upper()}</div>
                    <div style="font-size:1rem;">데이터 없음</div>
                </div>
                """, unsafe_allow_html=True)

    # ── 신뢰도 구간별 ───────────────────────────
    st.markdown("### 신뢰도 구간별 적중률")
    bands = data.get("by_confidence_band", [])
    if bands:
        band_table = []
        for b in bands:
            if b["total"] > 0:
                band_table.append({
                    "구간": b["band"],
                    "건수": b["total"],
                    "방향 적중": f"{b['direction_hits']}/{b['direction_sample']}",
                    "방향 적중률": f"{b['direction_hit_rate_pct']:.1f}%",
                    "±2% 승률": f"{b['band_win_rate_pct']:.1f}%",
                    "방향보정 기대값": f"{b['avg_signed_return_pct']:+.2f}%",
                })
        if band_table:
            st.dataframe(band_table, use_container_width=True, row_height=44, hide_index=True)

            # 차트: bar chart - 신뢰도별 적중률
            try:
                import plotly.graph_objects as _go
                x = [b["band"] for b in bands if b["total"] > 0]
                y = [b["direction_hit_rate_pct"] for b in bands if b["total"] > 0]
                ns = [b["total"] for b in bands if b["total"] > 0]
                fig = _go.Figure()
                fig.add_trace(_go.Bar(
                    x=x, y=y,
                    text=[f"{v:.1f}%<br>n={n}" for v, n in zip(y, ns)],
                    textposition="outside",
                    marker_color=["#ef4444" if v < 50 else "#eab308" if v < 60 else "#10b981" for v in y],
                ))
                fig.add_hline(y=50, line_dash="dash", line_color="gray",
                              annotation_text="랜덤 기준선 (50%)")
                fig.update_layout(
                    title=f"{horizon}일 horizon · 신뢰도 구간별 적중률",
                    xaxis_title="신뢰도 구간",
                    yaxis_title="적중률 (%)",
                    yaxis=dict(range=[0, 100]),
                    height=400,
                    margin=dict(l=40, r=20, t=50, b=40),
                )
                st.plotly_chart(fig, use_container_width=True)
            except Exception:
                pass
        else:
            st.info("구간별 데이터가 아직 부족합니다.")
    else:
        st.info("신뢰도 구간별 데이터 없음")

    # ── 칼리브레이터 상태 ───────────────────────
    st.markdown("### 🎯 신뢰도 칼리브레이터 상태")
    calib_data = api_get("/signal-accuracy/calibrator")
    if calib_data:
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            active = calib_data.get("active", False)
            st.metric("활성화 여부",
                      "✅ ON" if active else "⏸ OFF",
                      delta="자동 보정 중" if active else "표본 축적 중",
                      delta_color="off")
        with cc2:
            samples = calib_data.get("total_samples", 0)
            min_req = calib_data.get("min_required", 50)
            st.metric("누적 표본", f"{samples}",
                      delta=f"최소 {min_req}건 필요" if samples < min_req else "충족")
        with cc3:
            last = calib_data.get("last_refit")
            last_str = last[:19] if last else "미실행"
            st.metric("마지막 학습", last_str)

        cal_signals = calib_data.get("signals_calibrated", [])
        if cal_signals:
            st.success(f"보정 적용 신호: {', '.join(cal_signals)}")
        else:
            st.warning("아직 칼리브레이션 학습 전 (raw confidence 사용 중)")
    else:
        st.warning("API 서버에 연결할 수 없습니다")


# ═══════════════════════════════════════════════════════════════
#  Screener 페이지 (V1 — 한국 주식 기술적 스크리너)
# ═══════════════════════════════════════════════════════════════
