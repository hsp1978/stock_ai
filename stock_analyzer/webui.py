#!/usr/bin/env python3
"""
주식 분석 시스템 WebUI (Streamlit)
Mac Studio 에이전트 API 연동 + 전체 리포트 대시보드

실행:
    streamlit run webui.py --server.port 8501
"""
import json
import os
import re
import sys
from datetime import datetime
from typing import Dict, Tuple

import httpx
import yfinance as yf
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import load_dotenv

# ── 프로젝트 경로 설정 ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)

# 루트 .env를 먼저 로드 (통합 설정 SSOT), 로컬 stock_analyzer/.env로 덮어쓰기 허용
_root_env = os.path.join(_PROJECT_ROOT, ".env")
if os.path.exists(_root_env):
    load_dotenv(_root_env)
load_dotenv()
_SERVICE_DIR = os.path.join(_PROJECT_ROOT, 'chart_agent_service')

if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

# ── config 모듈에서 API 설정 가져오기 ──
try:
    from chart_agent_service.config import AGENT_API_HOST, AGENT_API_PORT
except ImportError:
    # fallback to default values
    AGENT_API_HOST = os.getenv("AGENT_API_HOST", "localhost")
    AGENT_API_PORT = int(os.getenv("AGENT_API_PORT", "8100"))

# ── local_engine 연결 (직접 import 우선, HTTP fallback) ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from local_engine import (
        engine_dispatch_get, engine_dispatch_post, engine_get_chart_path,
    )
    _USE_LOCAL_ENGINE = True
except ImportError:
    _USE_LOCAL_ENGINE = False

# ── UI 공용 모듈 (webui.py 점진 분리 — CLAUDE.md §6-10) ──
from ui.api_client import (  # noqa: E402
    AGENT_API_URL, api_get, api_post, log_action,
)
from ui.format import _fmt_price, _get_currency_symbol, _is_korean_stock  # noqa: E402
from ui.components import (  # noqa: E402
    _plotly_base_layout, _quant_signal_style, _signal_pill_html,
)
from ui.pages.backtest import render_backtest  # noqa: E402
from ui.pages.history import render_history  # noqa: E402
from ui.pages.ml_predict import render_ml_predict  # noqa: E402
from ui.pages.paper_trade import render_paper_trade  # noqa: E402
from ui.pages.quant_indicators import render_quant_indicators  # noqa: E402
from ui.pages.system_monitor import render_system_monitor  # noqa: E402
from ui.pages.trading import render_trading  # noqa: E402
from ui.pages.virtual_trade import render_virtual_trade  # noqa: E402
from ui.pages.portfolio import render_portfolio  # noqa: E402
from ui.pages.ranking import render_ranking  # noqa: E402
from ui.pages.screener import render_screener  # noqa: E402
from ui.pages.signal_accuracy import render_signal_accuracy  # noqa: E402
from ui.market import (  # noqa: E402
    KRW_CROSS, MARKET_INDICES, _krw_cross_series, fetch_market_indices,
)
from ui.theme import inject_theme  # noqa: E402
from ui.tickers import (  # noqa: E402
    WATCHLIST_PATH, resolve_ticker, _is_korean_ticker, _looks_broken_name, _market_code,
    _market_flag, add_to_watchlist, clear_watchlist, format_ticker_label,
    get_ticker_display_name, load_watchlist, remove_from_watchlist,
    save_watchlist, validate_ticker_webui,
)

# ── 한국 주식 모듈 import ──
try:
    from korean_stocks import KoreanStockData, get_market_indices as get_kr_indices
    from ticker_manager import TickerManager, normalize_ticker, detect_market, get_stock_info, format_price
    _KOREAN_STOCKS_AVAILABLE = True
except ImportError:
    _KOREAN_STOCKS_AVAILABLE = False
    print("[WARNING] Korean stocks module not available")


st.set_page_config(
    page_title="Stock AI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Kinetic Terminal Design System CSS ──────────────────────────
# ── Kinetic Terminal Design System CSS (stock_analyzer/ui/theme.py) ──
inject_theme()


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


def get_chart_url(ticker: str) -> str:
    """local_engine 모드: 파일 경로 반환 / HTTP 모드: URL 반환"""
    if _USE_LOCAL_ENGINE:
        return engine_get_chart_path(ticker) or ""
    return f"{AGENT_API_URL}/chart/{ticker}"


def export_comprehensive_data(ticker: str, include_multi_agent: bool = True) -> dict:
    """
    종목의 모든 분석 데이터를 수집하여 export용 dict 반환
    - Single LLM (V1.0) 결과
    - Multi-Agent (V2.0) 결과
    - 백테스트 결과
    - ML 예측 결과
    """
    export_data = {
        "ticker": ticker,
        "export_timestamp": datetime.now().isoformat(),
        "version": "2.0"
    }

    # 1. Single LLM 분석 결과
    single_result = api_get(f"/results/{ticker}")
    if single_result:
        export_data["single_llm_analysis"] = {
            "final_signal": single_result.get("final_signal"),
            "composite_score": single_result.get("composite_score"),
            "confidence": single_result.get("confidence"),
            "signal_distribution": single_result.get("signal_distribution"),
            "tool_summaries": single_result.get("tool_summaries", []),
            "tool_details": single_result.get("tool_details", []),
            "llm_conclusion": single_result.get("llm_conclusion"),
            "analyzed_at": single_result.get("analyzed_at")
        }

    # 2. Multi-Agent 분석 결과 (옵션)
    if include_multi_agent:
        # 8개 에이전트 병렬 LLM 호출. 백엔드 MULTI_AGENT_TIMEOUT(기본 600s)보다 약간 더 길게.
        multi_result = api_get(f"/multi-agent/{ticker}", timeout=660)
        if multi_result and not multi_result.get("error"):
            export_data["multi_agent_analysis"] = {
                "ticker": multi_result.get("ticker"),
                "multi_agent_mode": multi_result.get("multi_agent_mode"),
                "agent_results": multi_result.get("agent_results", []),
                "final_decision": multi_result.get("final_decision"),
                "total_execution_time": multi_result.get("total_execution_time"),
                "timestamp": multi_result.get("timestamp")
            }

    # 3. 백테스트 결과
    backtest_result = api_get(f"/backtest/{ticker}")
    if backtest_result:
        export_data["backtest"] = backtest_result

    # 4. ML 예측 결과
    ml_result = api_get(f"/ml/{ticker}")
    if ml_result:
        export_data["ml_prediction"] = ml_result

    # 5. 펀더멘털 데이터
    if single_result:
        export_data["fundamentals"] = single_result.get("fundamentals", {})
        export_data["options_pcr"] = single_result.get("options_pcr", {})
        export_data["insider_trades"] = single_result.get("insider_trades", [])

    return export_data


def _css_key(symbol: str) -> str:
    """Streamlit 위젯 key는 `.st-key-<key>` 클래스가 되므로 CSS-safe하게 만든다.

    `^GSPC`, `USDKRW=X`처럼 `^`·`=`가 든 심볼을 그대로 쓰면 선택자가 깨진다.
    """
    return re.sub(r"[^A-Za-z0-9_-]", "_", symbol)


# ── 내비게이션 정의 (DS §05 SidebarNav) ──
# 사이드바는 이동 전용. 스캔·GPU·모델 설정 등 조작 패널은 상단 커맨드바로 분리한다.
NAV_GROUPS = {
    "ANALYSIS": [
        "Home", "Dashboard", "Detail", "Multi-Agent",
        "Quant Indicators", "Screener", "Signal Accuracy", "ML Predict", "Backtest",
    ],
    "OPERATIONS": ["Scan Log", "System Monitor", "History", "Ranking"],
    "TRADING": ["Trading", "Virtual Trade", "Paper Trade", "Portfolio"],
}
_NAV_PAGES = [p for items in NAV_GROUPS.values() for p in items]


def render_sidebar_nav() -> str:
    """사이드바 내비게이션 — 3그룹, 항목 h36, 선택 시 accent 좌측 바.

    라디오 목록 대신 진짜 내비게이션 항목으로 렌더한다. 그룹은 접을 수 있고
    접힘 상태는 session_state에 남겨 클릭할 때마다 초기화되지 않게 한다.
    """
    if st.session_state.get("nav_page") not in _NAV_PAGES:
        st.session_state.nav_page = "Home"
    current = st.session_state.nav_page

    st.markdown('<div class="sidebar-brand">Stock AI</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">Precision Terminal</div>', unsafe_allow_html=True)

    for group, items in NAV_GROUPS.items():
        collapse_key = f"nav_collapsed_{group}"
        collapsed = st.session_state.get(collapse_key, False)
        caret = "▸" if collapsed else "▾"
        if st.button(
            f"{caret}  {group}",
            key=f"navgrp_{group}",
            use_container_width=True,
        ):
            st.session_state[collapse_key] = not collapsed
            st.rerun()
        if collapsed:
            continue
        for item in items:
            selected = item == current
            if st.button(
                item,
                key=f"nav_{_css_key(item)}",
                use_container_width=True,
                type="primary" if selected else "secondary",
            ):
                st.session_state.nav_page = item
                st.rerun()

    return current


def _render_system_status(health: dict | None, info: dict | None):
    """시스템 상태 — 사이드바에서 분리해 커맨드바 팝오버로 제공."""
    if not health:
        st.error(f"Agent Offline: {AGENT_API_URL}")
        return
    ollama_status = health.get("ollama", "disconnected")
    online = ollama_status == "connected"
    st.markdown(
        f'<span class="status-badge {"ok" if online else "err"}">'
        f'<span class="sb-dot"></span>{"AGENT ONLINE" if online else "AGENT OFFLINE"}</span>',
        unsafe_allow_html=True,
    )
    render_stat_row([
        ("CACHED", health.get("cached_results", 0)),
        ("SCANS", health.get("scan_count", 0)),
        ("JOBS", len(health.get("jobs") or [])),
    ], empty_hint="—")

    runtime = (health.get("ollama_runtime") or {}).get("status", "unknown")
    delivery = (health.get("alert_delivery") or {}).get("status", "unknown")
    if info:
        thresholds = info.get("thresholds", {})
        st.markdown(
            f'<div class="sidebar-info">'
            f'Model: <span>{info.get("model", "?")}</span><br>'
            f'Interval: <span>{info.get("scan_interval", "?")}</span><br>'
            f'Runtime: <span>{runtime}</span> &nbsp; Alerts: <span>{delivery}</span><br>'
            f'Buy &ge; <span style="color:var(--up);">{thresholds.get("buy", "?")}</span>'
            f'&nbsp; Sell &le; <span style="color:var(--down);">{thresholds.get("sell", "?")}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    if st.button("Restart Agent", use_container_width=True, key="cmd_restart"):
        with st.spinner("Restarting agent service..."):
            resp = api_post("/restart", timeout=5)
            if resp and resp.get("status") == "restarting":
                st.success("Agent restarting...")
                import time as _time
                _time.sleep(3)
                st.rerun()
            else:
                st.error("Restart failed. Agent may be offline.")


def _render_gpu_control():
    """GPU 일시 해제 — 다른 서비스에 GPU를 잠깐 양보할 때."""
    gpu = api_get("/gpu/status") or {}
    if gpu.get("paused"):
        remaining = max(0, int(gpu.get("remaining_seconds") or 0))
        mins, secs = divmod(remaining, 60)
        until = (gpu.get("until") or "")[11:16]
        st.warning(f"⏸ GPU 해제 중 · 자동 복귀까지 {mins}분 {secs}초 ({until})")
        if st.button("▶ 지금 복구", use_container_width=True, type="primary", key="cmd_gpu_resume"):
            if api_post("/gpu/resume", timeout=30) is not None:
                st.success("복구했습니다.")
                st.rerun()

        # 연장 — 작업이 예상보다 길어질 때 남은 시간에 더한다.
        st.caption("작업이 길어지면 연장")
        add_min = st.segmented_control(
            "연장", [15, 30, 60], default=30,
            format_func=lambda m: f"+{m}분", key="cmd_gpu_extend_minutes",
            label_visibility="collapsed",
        ) or 30
        if st.button(f"⏱ {add_min}분 연장", use_container_width=True, key="cmd_gpu_extend"):
            res = api_post("/gpu/extend", timeout=30, json_body={"minutes": int(add_min)})
            if res is None:
                st.error("연장 실패 — agent-api 응답 없음")
            else:
                if res.get("warning"):
                    st.warning(res["warning"])
                else:
                    st.success(f"{add_min}분 연장했습니다.")
                st.rerun()
    else:
        vram_gb = (gpu.get("vram_bytes") or 0) / 1e9
        st.caption(f"사용 중 · {vram_gb:.1f}GB · {gpu.get('ollama_runtime') or 'unknown'}")
        hold_min = st.segmented_control(
            "해제 시간", [30, 60, 90, 120], default=60,
            format_func=lambda m: f"{m}분", key="cmd_gpu_minutes",
            label_visibility="collapsed",
        ) or 60
        if st.button("⏸ GPU 사용 중지", use_container_width=True, key="cmd_gpu_pause"):
            res = api_post("/gpu/pause", timeout=60, json_body={"minutes": int(hold_min)})
            if res is not None:
                st.success(f"{hold_min}분간 해제했습니다.")
                st.rerun()
            else:
                st.error("해제 실패 — agent-api 응답 없음")


def render_command_bar(health: dict | None, info: dict | None):
    """상단 커맨드바 — 검색·스캔·GPU·시스템 상태 (DS §06: 사이드바에서 분리)."""
    c_search, c_scan, c_all, c_gpu, c_sys = st.columns([4, 1.1, 1.1, 1.2, 1.2])

    with c_search:
        scan_ticker = st.text_input(
            "검색", placeholder="AAPL · 005930.KS · 삼성전자 검색",
            label_visibility="collapsed", key="cmd_search",
        )
    with c_scan:
        do_scan = st.button("Scan", use_container_width=True, key="cmd_scan")
    with c_all:
        do_scan_all = st.button("Scan All", use_container_width=True, key="cmd_scan_all")
    with c_gpu:
        with st.popover("GPU", use_container_width=True):
            _render_gpu_control()
    with c_sys:
        with st.popover("시스템", use_container_width=True):
            _render_system_status(health, info)

    if do_scan and scan_ticker:
        resolved, hint = resolve_ticker(scan_ticker)
        if hint:
            st.info(hint)
        if resolved:
            log_action("manual_scan", page="command_bar", ticker=resolved, query=scan_ticker)
            with st.spinner(f"Analyzing {resolved}..."):
                result = api_post(f"/scan/{resolved}")
                if result:
                    st.success(
                        f"{resolved}: {result.get('final_signal')} "
                        f"({result.get('composite_score', 0):+.1f})"
                    )
                    st.rerun()

    if do_scan_all:
        wl = load_watchlist()
        if not wl:
            st.warning("Watchlist is empty")
        else:
            import math as _math_scan
            import os as _os_scan
            workers = int(_os_scan.getenv("SCAN_PARALLEL_WORKERS", "3"))
            est_rounds = _math_scan.ceil(len(wl) / workers)
            # 배치 다운로드 ~15s + 병렬 LLM 라운드 × 65s 예상
            est_sec = 15 + est_rounds * 65
            est_min, est_s = divmod(int(est_sec), 60)
            est_str = f"{est_min}분 {est_s}초" if est_min else f"{est_s}초"
            with st.spinner(
                f"🔄 {len(wl)}개 종목 병렬 스캔 중 (워커 {workers}개, 예상 {est_str})..."
            ):
                result = api_post(f"/scan?tickers={','.join(wl)}", timeout=900)
                if result:
                    st.success(f"✅ 완료! {len(wl)}개 종목 스캔")
            st.rerun()


with st.sidebar:
    page = render_sidebar_nav()


# ═══════════════════════════════════════════════════════════════
#  홈 페이지
# ═══════════════════════════════════════════════════════════════


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
    if _KOREAN_STOCKS_AVAILABLE:
        with st.expander("🇰🇷 한국 주식 심화 도구 (매매동향 · DART 공시 · 즐겨찾기)", expanded=False):
            render_korean_tools_panel()


def render_korean_tools_panel():
    """한국 주식 전용 도구 (통합 홈의 접이식 섹션)."""
    if not _KOREAN_STOCKS_AVAILABLE:
        st.warning("한국 주식 모듈을 사용할 수 없습니다.")
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


def _deprecated_render_korean_market_home():
    """[Deprecated] 통합 홈과 render_korean_tools_panel()로 대체됨.

    내부 코드는 한국 전용 즐겨찾기 파일을 직접 참조해 SSOT(Watchlist) 원칙을
    위반했기 때문에 제거됨. 라우팅에서 호출되지 않으며 호환성을 위해 이름만 유지.
    """
    pass


# ═══════════════════════════════════════════════════════════════
#  대시보드 페이지
# ═══════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def fetch_index_history(symbol: str, period: str = "6mo") -> "pd.DataFrame | None":
    """지수/환율 차트용 이력. 원화 교차 환율은 base 페어에서 계산한다."""
    try:
        if symbol in KRW_CROSS:
            spec = KRW_CROSS[symbol]
            bases = [t for t in (spec["num"], spec["den"]) if t]
            closes = {}
            for t in bases:
                h = yf.Ticker(t).history(period=period)
                if h is None or h.empty:
                    return None
                closes[t] = h["Close"].dropna()
            series = _krw_cross_series(lambda t: closes.get(t), symbol)
            if series is None or series.empty:
                return None
            return pd.DataFrame({"Close": series})

        hist = yf.Ticker(symbol).history(period=period)
        if hist is None or hist.empty:
            return None
        return hist
    except Exception:
        return None


_INDEX_PERIODS = {"1개월": "1mo", "3개월": "3mo", "6개월": "6mo", "1년": "1y", "5년": "5y"}


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


def ticker_chip_html(ticker: str) -> str:
    """TickerChip (DS §05) — 티커 우선 + 시장 배지. 회사 명칭은 툴팁.

    명칭을 칩 본문에 넣으면 폭이 들쭉날쭉해져 목록을 훑는 속도가 떨어진다.
    """
    is_kr = _is_korean_ticker(ticker)
    badge = "KR" if is_kr else "US"
    name = get_ticker_display_name(ticker) or ticker
    title = name if name != ticker else ticker
    return (
        f'<span class="wl-chip" title="{title}">'
        f'<span class="tc-badge {"kr" if is_kr else "us"}">{badge}</span>{ticker}</span>'
    )


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


def render_dashboard():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Dashboard</div>
        <div class="page-subtitle">Market Analysis & Signal Overview</div>
    </div>
    """, unsafe_allow_html=True)

    render_market_ticker_bar()

    data = api_get("/results")
    if not data or not data.get("results"):
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">⚡</div>
            <div class="es-text">No analysis results yet. Run a scan from the sidebar.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    results = data["results"]
    total = len(results)
    buy_list = {k: v for k, v in results.items() if v.get("signal") == "BUY"}
    sell_list = {k: v for k, v in results.items() if v.get("signal") == "SELL"}
    hold_list = {k: v for k, v in results.items() if v.get("signal") == "HOLD"}

    analyzed_times = [r.get("analyzed_at", "") for r in results.values() if r.get("analyzed_at")]
    if analyzed_times:
        latest_analysis = max(analyzed_times)[:19].replace("T", " ")
        oldest_analysis = min(analyzed_times)[:19].replace("T", " ")
        analysis_ts = f"Last analyzed: {latest_analysis}" if latest_analysis == oldest_analysis else f"Analyzed: {oldest_analysis} ~ {latest_analysis}"
    else:
        analysis_ts = ""

    buy_pct = int(len(buy_list) / total * 100) if total else 0
    sell_pct = int(len(sell_list) / total * 100) if total else 0
    hold_pct = int(len(hold_list) / total * 100) if total else 0

    st.markdown(f"""
    <div class="summary-grid">
        <div class="summary-card">
            <div class="sc-label">Total Coverage</div>
            <div class="sc-value" style="color:var(--primary-ctr);">{total}</div>
            <div class="sc-sub">Instruments</div>
            <div class="sc-bar"><div class="sc-bar-fill" style="width:100%; background:var(--primary-ctr);"></div></div>
        </div>
        <div class="summary-card">
            <div class="sc-label">Buy Signals</div>
            <div class="sc-value" style="color:var(--buy);">{len(buy_list)}</div>
            <div class="sc-sub">Optimal Entry</div>
            <div class="sc-bar"><div class="sc-bar-fill" style="width:{buy_pct}%; background:var(--buy);"></div></div>
        </div>
        <div class="summary-card">
            <div class="sc-label">Sell Signals</div>
            <div class="sc-value" style="color:var(--sell);">{len(sell_list)}</div>
            <div class="sc-sub">Risk Detected</div>
            <div class="sc-bar"><div class="sc-bar-fill" style="width:{sell_pct}%; background:var(--sell);"></div></div>
        </div>
        <div class="summary-card">
            <div class="sc-label">Hold Signals</div>
            <div class="sc-value" style="color:var(--hold);">{len(hold_list)}</div>
            <div class="sc-sub">Neutral Weight</div>
            <div class="sc-bar"><div class="sc-bar-fill" style="width:{hold_pct}%; background:var(--hold);"></div></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if analysis_ts:
        st.markdown(f'<div class="ts-meta">{analysis_ts}</div>', unsafe_allow_html=True)

    # 통합 시장 필터 (미국/한국 구분 없이 한 테이블에 표시하되 필터로 선택 가능)
    dashboard_filter = st.radio(
        "시장 필터",
        ["전체", "🇺🇸 US", "🇰🇷 KR"],
        horizontal=True,
        label_visibility="collapsed",
        key="dashboard_market_filter",
    )

    rows = []
    # Fix: API returns 'composite_score', not 'score'
    for ticker, r in sorted(results.items(), key=lambda x: x[1].get("composite_score", x[1].get("score", 0)), reverse=True):
        flag = _market_flag(ticker)
        market_code = _market_code(ticker)

        # 시장 필터 적용
        if dashboard_filter == "🇺🇸 US" and flag != "🇺🇸":
            continue
        if dashboard_filter == "🇰🇷 KR" and flag != "🇰🇷":
            continue

        dist = r.get("signal_distribution", {})
        display_name = get_ticker_display_name(ticker)
        name_cell = display_name if display_name and display_name != ticker else "—"
        rows.append({
            "market": f"{flag} {market_code}",
            "name": name_cell,
            "ticker": ticker,
            "signal": r.get("signal", "?"),
            "score": r.get("composite_score", r.get("score", 0)),  # Try composite_score first
            "confidence": r.get("confidence", 0),
            "buy": dist.get("buy", 0),
            "sell": dist.get("sell", 0),
            "neutral": dist.get("neutral", 0),
            "time": str(r.get("analyzed_at", ""))[:16],
        })

    if not rows:
        return

    df = pd.DataFrame(rows)

    col_score, col_table = st.columns([2, 3])

    with col_score:
        st.markdown('<div class="section-title">Signal Score Matrix</div>', unsafe_allow_html=True)

        fig = go.Figure()
        bar_colors = ["#2BD98A" if s > 0 else "#FF6B6B" if s < 0 else "#2C3745" for s in df["score"]]
        fig.add_trace(go.Bar(
            x=df["score"], y=df["ticker"], orientation='h',
            marker=dict(color=bar_colors, line=dict(width=0)),
            text=[f"{s:+.1f}" for s in df["score"]],
            textposition="outside",
            textfont=dict(color="#6A7482", size=11, family="JetBrains Mono"),
        ))
        fig.update_layout(**_plotly_base_layout(
            height=max(280, len(df) * 52),
            xaxis=dict(range=[-10, 10], title="", gridcolor="#161C25", zerolinecolor="#161C25"),
            yaxis=dict(
                autorange="reversed", gridcolor="rgba(0,0,0,0)",
                tickfont=dict(family="JetBrains Mono", size=12, color="#EDF1F7"),
            ),
            margin=dict(l=70, r=60, t=8, b=8),
        ))
        fig.add_vline(x=0, line_color="#1F2733", line_width=1)
        st.plotly_chart(fig, use_container_width=True)

    with col_table:
        st.markdown('<div class="section-title">Analysis Execution Results</div>', unsafe_allow_html=True)

        display_df = df[["ticker", "signal", "score", "confidence"]].rename(columns={
            "ticker": "Ticker", "signal": "Signal", "score": "Score", "confidence": "Confidence",
        })
        st.dataframe(
            display_df.style.map(
                lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
                subset=["Signal"],
            ),
            use_container_width=True, hide_index=True,
            height=max(280, len(df) * 52),
        )

    # Export functionality for Dashboard
    st.markdown("---")
    st.markdown('<div class="section-title">📤 Export All Data</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([3, 1])

    with col1:
        export_options = st.radio(
            "Export Format:",
            ["JSON (Full Data)", "CSV (Summary)", "Markdown (Report)"],
            horizontal=True,
            key="dashboard_export_format"
        )

        include_multi = st.checkbox(
            "Include Multi-Agent Analysis",
            value=True,
            key="dashboard_include_multi",
            help="Include detailed Multi-Agent analysis data for each ticker"
        )

    with col2:
        if st.button("🚀 Export All", key="dashboard_export_all", use_container_width=True):
            with st.spinner("Collecting data for all tickers..."):
                all_export_data = {
                    "export_timestamp": datetime.now().isoformat(),
                    "total_tickers": total,
                    "signal_summary": {
                        "buy": len(buy_list),
                        "sell": len(sell_list),
                        "hold": len(hold_list)
                    },
                    "analysis_period": {
                        "oldest": oldest_analysis if 'oldest_analysis' in locals() else None,
                        "latest": latest_analysis if 'latest_analysis' in locals() else None
                    },
                    "tickers": {}
                }

                # Collect data for each ticker
                progress_text = st.empty()
                progress_bar = st.progress(0)

                for idx, ticker in enumerate(sorted(results.keys())):
                    progress_text.text(f"Processing {ticker}... ({idx+1}/{total})")
                    progress_bar.progress((idx + 1) / total)

                    try:
                        ticker_data = export_comprehensive_data(ticker, include_multi_agent=include_multi)
                        all_export_data["tickers"][ticker] = ticker_data
                    except Exception as e:
                        all_export_data["tickers"][ticker] = {"error": str(e)}

                progress_text.empty()
                progress_bar.empty()

                # Prepare export based on selected format
                if "JSON" in export_options:
                    export_json = json.dumps(all_export_data, indent=2, ensure_ascii=False)
                    st.download_button(
                        label="📥 Download JSON",
                        data=export_json,
                        file_name=f"stock_analysis_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json",
                        key="dashboard_download_json"
                    )

                elif "CSV" in export_options:
                    # Create summary CSV
                    csv_rows = []
                    for ticker, data in all_export_data["tickers"].items():
                        if "error" not in data:
                            row = {
                                "Ticker": ticker,
                                "Signal": data.get("single_llm_analysis", {}).get("signal", "N/A"),
                                "Score": data.get("single_llm_analysis", {}).get("score", 0),
                                "Confidence": data.get("single_llm_analysis", {}).get("confidence", 0),
                                "Multi-Agent Signal": data.get("multi_agent_analysis", {}).get("final_decision", {}).get("final_signal", "N/A"),
                                "Multi-Agent Confidence": data.get("multi_agent_analysis", {}).get("final_decision", {}).get("final_confidence", 0),
                                "Buy Agents": data.get("multi_agent_analysis", {}).get("final_decision", {}).get("signal_distribution", {}).get("buy", 0),
                                "Sell Agents": data.get("multi_agent_analysis", {}).get("final_decision", {}).get("signal_distribution", {}).get("sell", 0),
                                "Neutral Agents": data.get("multi_agent_analysis", {}).get("final_decision", {}).get("signal_distribution", {}).get("neutral", 0),
                                "Analyzed At": data.get("single_llm_analysis", {}).get("analyzed_at", "")
                            }
                        else:
                            row = {
                                "Ticker": ticker,
                                "Signal": "ERROR",
                                "Score": 0,
                                "Confidence": 0,
                                "Multi-Agent Signal": "ERROR",
                                "Multi-Agent Confidence": 0,
                                "Buy Agents": 0,
                                "Sell Agents": 0,
                                "Neutral Agents": 0,
                                "Analyzed At": ""
                            }
                        csv_rows.append(row)

                    if csv_rows:
                        export_df = pd.DataFrame(csv_rows)
                        csv_data = export_df.to_csv(index=False, encoding='utf-8-sig')

                        st.download_button(
                            label="📥 Download CSV",
                            data=csv_data,
                            file_name=f"stock_analysis_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv",
                            key="dashboard_download_csv"
                        )

                else:  # Markdown Report
                    # Create comprehensive markdown report
                    report = f"""# Stock Analysis Report - All Tickers
## 📅 Report Information
- **Export Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **Total Tickers Analyzed**: {total}
- **Analysis Period**: {oldest_analysis if 'oldest_analysis' in locals() else 'N/A'} ~ {latest_analysis if 'latest_analysis' in locals() else 'N/A'}

## 📊 Market Overview
- **Buy Signals**: {len(buy_list)} ({buy_pct}%)
- **Sell Signals**: {len(sell_list)} ({sell_pct}%)
- **Hold Signals**: {len(hold_list)} ({hold_pct}%)

## 🎯 Top Buy Recommendations
"""
                    # Add top buy recommendations
                    buy_sorted = sorted(buy_list.items(), key=lambda x: x[1].get("score", 0), reverse=True)[:5]
                    for ticker, data in buy_sorted:
                        report += f"### {ticker}\n"
                        report += f"- **Score**: {data.get('score', 0):+.2f}\n"
                        report += f"- **Confidence**: {data.get('confidence', 0)}/10\n"
                        if include_multi and ticker in all_export_data["tickers"]:
                            ma_data = all_export_data["tickers"][ticker].get("multi_agent_analysis", {})
                            if ma_data:
                                final = ma_data.get("final_decision", {})
                                report += f"- **Multi-Agent Signal**: {final.get('final_signal', 'N/A')}\n"
                                report += f"- **Multi-Agent Confidence**: {final.get('final_confidence', 0)}/10\n"
                        report += "\n"

                    report += """## 📉 Risk Alerts (Sell Signals)
"""
                    # Add sell signals
                    sell_sorted = sorted(sell_list.items(), key=lambda x: x[1].get("score", 0))[:5]
                    for ticker, data in sell_sorted:
                        report += f"### {ticker}\n"
                        report += f"- **Score**: {data.get('score', 0):+.2f}\n"
                        report += f"- **Confidence**: {data.get('confidence', 0)}/10\n"
                        report += "\n"

                    report += """## 📋 Full Analysis Results
| Ticker | Signal | Score | Confidence | Multi-Agent Signal | MA Confidence |
|--------|--------|-------|------------|-------------------|---------------|
"""
                    # Add all tickers
                    for ticker in sorted(results.keys()):
                        r = results[ticker]
                        ma_signal = "N/A"
                        ma_conf = "N/A"

                        if include_multi and ticker in all_export_data["tickers"]:
                            ma_data = all_export_data["tickers"][ticker].get("multi_agent_analysis", {})
                            if ma_data:
                                final = ma_data.get("final_decision", {})
                                ma_signal = final.get("final_signal", "N/A")
                                ma_conf = f"{final.get('final_confidence', 0)}/10"

                        report += f"| {ticker} | {r.get('signal', 'N/A')} | {r.get('score', 0):+.2f} | {r.get('confidence', 0)}/10 | {ma_signal} | {ma_conf} |\n"

                    report += f"""
---
*Generated by Stock AI Analysis System v2.0*
*Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""

                    st.download_button(
                        label="📥 Download Report",
                        data=report,
                        file_name=f"stock_analysis_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                        mime="text/markdown",
                        key="dashboard_download_report"
                    )

                st.success(f"✅ Export prepared for {total} tickers!")


# ═══════════════════════════════════════════════════════════════
#  종목 상세 페이지
# ═══════════════════════════════════════════════════════════════

def _fmt_num(v, decimals=2):
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    return f"{v:,.{decimals}f}"


def _render_tool_detail_card(td: dict, ticker: str = ""):
    tool_name = td.get("tool", "")
    name = td.get("name", tool_name)
    sig = td.get("signal", "neutral")
    sc = td.get("score", 0)
    detail_text = td.get("detail", "")
    sig_color = "#2BD98A" if sig == "buy" else ("#FF6B6B" if sig == "sell" else "#F5B14C")

    st.markdown(f"**{name}**")
    st.markdown(
        f'<span style="color:{sig_color}; font-weight:700; font-size:13px;">'
        f'{sig.upper()} ({sc:+.1f})</span>',
        unsafe_allow_html=True,
    )

    if tool_name == "trend_ma_analysis":
        sma = td.get("sma_values", {})
        pvs = td.get("price_vs_sma", {})
        cols = st.columns(len(sma)) if sma else []
        for col, (period, val) in zip(cols, sma.items()):
            pos = pvs.get(f"SMA_{period}", "—")
            col.metric(f"SMA {period}", f"${_fmt_num(val)}", pos)
        alignment = td.get("alignment", "—")
        cross = td.get("cross_signal", "none")
        c1, c2 = st.columns(2)
        c1.metric("Alignment", alignment.title())
        c2.metric("Cross Signal", cross.title() if cross != "none" else "—")

    elif tool_name == "rsi_divergence_analysis":
        c1, c2, c3 = st.columns(3)
        c1.metric("RSI", _fmt_num(td.get("current_rsi"), 1))
        c2.metric("Zone", str(td.get("rsi_zone", "—")).title())
        c3.metric("Divergence", str(td.get("divergence", "none")).title())

    elif tool_name == "bollinger_squeeze_analysis":
        c1, c2, c3 = st.columns(3)
        c1.metric("BB Upper", f"${_fmt_num(td.get('bb_upper'))}")
        c2.metric("BB Lower", f"${_fmt_num(td.get('bb_lower'))}")
        c3.metric("%B", _fmt_num(td.get("pct_b")))
        c4, c5, c6 = st.columns(3)
        c4.metric("Width %", _fmt_num(td.get("bb_width_pct"), 1))
        c5.metric("Squeeze", "Yes" if td.get("squeeze") else "No")
        c6.metric("Expanding", "Yes" if td.get("expanding") else "No")

    elif tool_name == "macd_momentum_analysis":
        c1, c2, c3 = st.columns(3)
        c1.metric("MACD", _fmt_num(td.get("macd"), 4))
        c2.metric("Signal Line", _fmt_num(td.get("signal_line"), 4))
        c3.metric("Histogram", _fmt_num(td.get("histogram"), 4))
        c4, c5, c6 = st.columns(3)
        c4.metric("Cross", str(td.get("cross", "none")).title())
        c5.metric("Acceleration", str(td.get("histogram_acceleration", "—")).title())
        c6.metric("Zero Position", str(td.get("zero_position", "—")).title())

    elif tool_name == "adx_trend_strength_analysis":
        c1, c2 = st.columns(2)
        c1.metric("ADX", _fmt_num(td.get("adx"), 1))
        c2.metric("Trend Strength", str(td.get("trend_strength", "—")).title())
        c3, c4, c5 = st.columns(3)
        c3.metric("+DI", _fmt_num(td.get("plus_di"), 1))
        c4.metric("-DI", _fmt_num(td.get("minus_di"), 1))
        c5.metric("Direction", str(td.get("trend_direction", "—")).title())

    elif tool_name == "volume_profile_analysis":
        c1, c2 = st.columns(2)
        c1.metric("Volume Ratio", f"{_fmt_num(td.get('volume_ratio'), 2)}x")
        c2.metric("OBV Trend", str(td.get("obv_trend", "—")).title())

    elif tool_name == "fibonacci_retracement_analysis":
        levels = td.get("levels", {})
        if levels:
            level_data = {f"Fib {k}": _fmt_price(v, ticker) for k, v in levels.items()}
            cols = st.columns(min(len(level_data), 4))
            for col, (label, val) in zip(cols, list(level_data.items())[:4]):
                col.metric(label, val)
        c1, c2, c3 = st.columns(3)
        c1.metric("Retracement", _fmt_num(td.get("current_retracement"), 1))
        c2.metric("Nearest Support", _fmt_price(td.get('nearest_support'), ticker))
        c3.metric("Nearest Resistance", _fmt_price(td.get('nearest_resistance'), ticker))

    elif tool_name == "volatility_regime_analysis":
        c1, c2, c3 = st.columns(3)
        c1.metric("ATR", _fmt_price(td.get('current_atr'), ticker))
        c2.metric("ATR %", f"{_fmt_num(td.get('atr_pct'), 1)}%")
        c3.metric("Regime", str(td.get("regime", "—")).title())
        c4, c5 = st.columns(2)
        c4.metric("Percentile", f"{_fmt_num(td.get('percentile'), 0)}%")
        c5.metric("Annualized Vol", f"{_fmt_num(td.get('annualized_volatility'), 1)}%")

    elif tool_name == "mean_reversion_analysis":
        zscores = td.get("z_scores", {})
        if zscores:
            cols = st.columns(min(len(zscores), 4))
            for col, (period, val) in zip(cols, list(zscores.items())[:4]):
                col.metric(f"Z-Score {period}", _fmt_num(val))
        c1, c2 = st.columns(2)
        c1.metric("Avg Z-Score", _fmt_num(td.get("avg_z_score")))
        c2.metric("Reversion Prob", f"{_fmt_num(td.get('reversion_probability'), 0)}%")

    elif tool_name == "momentum_rank_analysis":
        returns = td.get("returns", {})
        if returns:
            cols = st.columns(min(len(returns), 4))
            for col, (period, val) in zip(cols, list(returns.items())[:4]):
                color = "normal" if val is None else ("off" if val < 0 else "normal")
                col.metric(f"Return {period}", f"{_fmt_num(val, 1)}%" if val is not None else "—")
        c1, c2 = st.columns(2)
        c1.metric("Weighted Return", f"{_fmt_num(td.get('weighted_return'), 2)}%")
        c2.metric("Acceleration", str(td.get("acceleration", "—")).title())

    elif tool_name == "support_resistance_analysis":
        c1, c2, c3 = st.columns(3)
        c1.metric("Pivot", _fmt_price(td.get('pivot'), ticker))
        c2.metric("Upside %", f"{_fmt_num(td.get('upside_pct'), 1)}%")
        c3.metric("Downside %", f"{_fmt_num(td.get('downside_pct'), 1)}%")
        resistance = td.get("resistance", {})
        support = td.get("support", {})
        if resistance:
            cols = st.columns(len(resistance))
            for col, (level, val) in zip(cols, resistance.items()):
                col.metric(f"R{level}", _fmt_price(val, ticker))
        if support:
            cols = st.columns(len(support))
            for col, (level, val) in zip(cols, support.items()):
                col.metric(f"S{level}", _fmt_price(val, ticker))
        rr = td.get("risk_reward_ratio")
        if rr is not None:
            st.metric("Risk/Reward Ratio", _fmt_num(rr))

    elif tool_name == "correlation_regime_analysis":
        ac = td.get("autocorrelations", {})
        if ac:
            cols = st.columns(min(len(ac), 5))
            for col, (lag, val) in zip(cols, list(ac.items())[:5]):
                col.metric(f"Lag {lag}", _fmt_num(val, 3))
        c1, c2, c3 = st.columns(3)
        c1.metric("Avg Autocorrelation", _fmt_num(td.get("avg_autocorrelation"), 3))
        c2.metric("Hurst Exponent", _fmt_num(td.get("hurst_exponent"), 3))
        c3.metric("Regime", str(td.get("regime", "—")).title())

    if detail_text:
        st.caption(detail_text)


def render_detail():
    log_action("page_view", page="detail")
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Detail Analysis</div>
        <div class="page-subtitle">In-depth 16-tool analysis for individual stocks</div>
    </div>
    """, unsafe_allow_html=True)

    data = api_get("/results")
    if not data or not data.get("results"):
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">🔍</div>
            <div class="es-text">No analysis results available.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    tickers = sorted(data["results"].keys())
    selected = st.selectbox(
        "Select Ticker",
        tickers,
        format_func=lambda ticker: format_ticker_label(ticker, "flag_name_code"),
        label_visibility="collapsed",
    )
    if not selected:
        return

    detail = api_get(f"/results/{selected}")
    if not detail:
        summary = data["results"].get(selected, {})
        if not summary:
            st.error(f"Failed to load {selected}")
            return
        detail = {
            "final_signal": summary.get("signal", "?"),
            "composite_score": summary.get("score", 0),
            "confidence": summary.get("confidence", 0),
            "signal_distribution": summary.get("signal_distribution", {}),
            "analyzed_at": summary.get("analyzed_at", ""),
        }
        st.warning("Detail endpoint unavailable — showing summary data only.")

    signal = detail.get("final_signal", "?")
    score = detail.get("composite_score", 0)
    confidence = detail.get("confidence", 0)
    tool_count = detail.get("tool_count", 0)
    dist = detail.get("signal_distribution", {})
    analyzed_at = str(detail.get("analyzed_at", ""))[:19].replace("T", " ")

    badge_class = "buy" if signal == "BUY" else ("sell" if signal == "SELL" else "hold")
    score_color = "var(--buy)" if score > 0 else "var(--sell)" if score < 0 else "var(--outline)"

    st.markdown(f"""
    <div style="margin-bottom:24px;">
        <div style="font-size:10px; color:var(--on-surface-variant); text-transform:uppercase; letter-spacing:1px; margin-bottom:8px;">Signal</div>
        <span class="signal-badge-lg {badge_class}">{signal}</span>
    </div>
    """, unsafe_allow_html=True)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Composite Score", f"{score:+.2f}")
    m2.metric("Confidence", f"{confidence}/10")
    m3.metric("Tools", str(tool_count))
    m4.metric("Buy Votes", str(dist.get("buy", 0)))
    m5.metric("Sell Votes", str(dist.get("sell", 0)))
    m6.metric("Neutral Votes", str(dist.get("neutral", 0)))

    if analyzed_at:
        st.markdown(f'<div class="ts-meta">Analyzed: {analyzed_at}</div>', unsafe_allow_html=True)

    summaries = detail.get("tool_summaries", [])
    if summaries:
        st.markdown(f"""
        <div class="section-header">
            <div class="section-title">Tool Score Overview</div>
            <div class="section-subtitle">{len(summaries)} TOOLS</div>
        </div>
        """, unsafe_allow_html=True)

        names = [s["name"] for s in summaries]
        scores = [s["score"] for s in summaries]
        bar_colors = ["#2BD98A" if s > 0 else "#FF6B6B" if s < 0 else "#2C3745" for s in scores]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=names, x=scores, orientation='h',
            marker=dict(color=bar_colors, line=dict(width=0)),
            text=[f"{s:+.1f}" for s in scores],
            textposition="outside",
            textfont=dict(color="#6A7482", size=11, family="JetBrains Mono"),
        ))
        fig.update_layout(**_plotly_base_layout(
            height=max(400, len(summaries) * 38),
            xaxis=dict(range=[-10, 10], title="", gridcolor="#161C25", zerolinecolor="#161C25"),
            yaxis=dict(
                autorange="reversed", gridcolor="rgba(0,0,0,0)",
                tickfont=dict(family="JetBrains Mono, monospace", size=11, color="#9BA6B5"),
            ),
            margin=dict(l=200, r=60, t=8, b=8),
        ))
        fig.add_vline(x=0, line_color="#1F2733", line_width=1)
        st.plotly_chart(fig, use_container_width=True)

    tool_details = detail.get("tool_details", [])
    if tool_details:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">Detailed Tool Analysis</div>
        </div>
        """, unsafe_allow_html=True)

        for td in tool_details:
            with st.expander(f"**{td.get('name', td.get('tool', '?'))}** — {td.get('signal', '?').upper()} ({td.get('score', 0):+.1f})", expanded=False):
                _render_tool_detail_card(td, selected)

    st.markdown("""
    <div class="section-header">
        <div class="section-title">Chart</div>
    </div>
    """, unsafe_allow_html=True)
    chart_ref = get_chart_url(selected)
    if _USE_LOCAL_ENGINE:
        if chart_ref and os.path.exists(chart_ref):
            st.image(chart_ref, use_container_width=True)
        else:
            st.caption("No chart image available")
    else:
        try:
            resp = httpx.get(chart_ref, timeout=5)
            if resp.status_code == 200:
                st.image(resp.content, use_container_width=True)
            else:
                st.caption("No chart image available")
        except Exception:
            st.caption("Chart load failed")

    llm = detail.get("llm_conclusion", "")
    if llm and not llm.startswith("[오류]") and not llm.startswith("[LLM"):
        st.markdown("""
        <div class="section-header">
            <div class="section-title">LLM Conclusion</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f'<div class="llm-body">\n\n{llm}\n\n</div>', unsafe_allow_html=True)

    # Export 섹션 추가
    st.markdown("""
    <div class="section-header">
        <div class="section-title">📥 Export All Data</div>
    </div>
    """, unsafe_allow_html=True)

    # Export 옵션
    col1, col2 = st.columns(2)
    with col1:
        include_multi = st.checkbox("Include Multi-Agent Analysis", value=True,
                                   help="Multi-Agent 분석 포함 (시간이 더 걸립니다)")

    # Export 버튼들
    export_col1, export_col2, export_col3 = st.columns(3)

    with export_col1:
        if st.button("📄 Export as JSON", use_container_width=True, key="detail_export_json"):
            with st.spinner(f"Collecting all data for {selected}..."):
                export_data = export_comprehensive_data(selected, include_multi)
                json_str = json.dumps(export_data, indent=2, ensure_ascii=False, default=str)

                st.download_button(
                    label="📥 Download JSON",
                    data=json_str,
                    file_name=f"{selected}_comprehensive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                    use_container_width=True
                )
                st.success(f"✅ Data collected! Click 'Download JSON' to save.")

    with export_col2:
        if st.button("📊 Export as CSV", use_container_width=True, key="detail_export_csv"):
            with st.spinner(f"Preparing CSV for {selected}..."):
                export_data = export_comprehensive_data(selected, include_multi)

                # CSV로 변환 (주요 데이터만)
                csv_data = []

                # Single LLM 데이터
                if "single_llm_analysis" in export_data:
                    single = export_data["single_llm_analysis"]
                    csv_data.append({
                        "Type": "Single LLM",
                        "Signal": single.get("final_signal"),
                        "Score": single.get("composite_score"),
                        "Confidence": single.get("confidence"),
                        "Timestamp": single.get("analyzed_at")
                    })

                # Multi-Agent 데이터
                if "multi_agent_analysis" in export_data:
                    multi = export_data["multi_agent_analysis"]
                    if multi.get("agent_results"):
                        for agent in multi["agent_results"]:
                            csv_data.append({
                                "Type": f"Agent: {agent.get('agent')}",
                                "Signal": agent.get("signal"),
                                "Score": agent.get("score", 0),
                                "Confidence": agent.get("confidence"),
                                "Timestamp": multi.get("timestamp")
                            })

                    # Final decision
                    if multi.get("final_decision"):
                        final = multi["final_decision"]
                        csv_data.append({
                            "Type": "Multi-Agent Final",
                            "Signal": final.get("final_signal"),
                            "Score": 0,
                            "Confidence": final.get("final_confidence"),
                            "Timestamp": multi.get("timestamp")
                        })

                if csv_data:
                    df = pd.DataFrame(csv_data)
                    csv_str = df.to_csv(index=False, encoding='utf-8-sig')

                    st.download_button(
                        label="📥 Download CSV",
                        data=csv_str,
                        file_name=f"{selected}_comprehensive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                    st.success(f"✅ CSV prepared! Click 'Download CSV' to save.")
                else:
                    st.warning("No data available for CSV export")

    with export_col3:
        if st.button("📝 Export as Report", use_container_width=True, key="detail_export_report"):
            with st.spinner(f"Generating report for {selected}..."):
                export_data = export_comprehensive_data(selected, include_multi)

                # Markdown 리포트 생성
                report = f"""# 📊 {selected} Comprehensive Analysis Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 1. Single LLM Analysis (V1.0)
"""
                if "single_llm_analysis" in export_data:
                    single = export_data["single_llm_analysis"]
                    report += f"""
- **Final Signal**: {single.get('final_signal')}
- **Composite Score**: {single.get('composite_score')}
- **Confidence**: {single.get('confidence')}/10
- **Analyzed**: {single.get('analyzed_at')}

### Signal Distribution
- Buy votes: {single.get('signal_distribution', {}).get('buy', 0)}
- Sell votes: {single.get('signal_distribution', {}).get('sell', 0)}
- Neutral votes: {single.get('signal_distribution', {}).get('neutral', 0)}
"""

                report += """
## 2. Multi-Agent Analysis (V2.0)
"""
                if "multi_agent_analysis" in export_data:
                    multi = export_data["multi_agent_analysis"]
                    if multi.get("final_decision"):
                        final = multi["final_decision"]
                        report += f"""
### Final Decision
- **Signal**: {final.get('final_signal')}
- **Confidence**: {final.get('final_confidence')}/10
- **Consensus**: {final.get('consensus')}

### Agent Results
"""
                        for agent in multi.get("agent_results", []):
                            report += f"""
#### {agent.get('agent')}
- Signal: {agent.get('signal')}
- Confidence: {agent.get('confidence')}/10
- LLM Provider: {agent.get('llm_provider')}
- Reasoning: {agent.get('reasoning', 'N/A')[:200]}...
"""
                else:
                    report += "\n*Multi-Agent analysis not included or not available*\n"

                report += """
## 3. Backtest Results
"""
                if "backtest" in export_data and export_data["backtest"]:
                    bt = export_data["backtest"]
                    report += f"""
- **Strategy**: Composite
- **Annual Return**: {bt.get('annual_return', 'N/A')}%
- **Sharpe Ratio**: {bt.get('sharpe_ratio', 'N/A')}
- **Max Drawdown**: {bt.get('max_drawdown', 'N/A')}%
"""
                else:
                    report += "\n*Backtest data not available*\n"

                report += """
## 4. ML Prediction
"""
                if "ml_prediction" in export_data and export_data["ml_prediction"]:
                    ml = export_data["ml_prediction"]
                    report += f"""
- **Direction**: {ml.get('ensemble_direction', 'N/A')}
- **Probability**: {ml.get('ensemble_probability', 'N/A')}%
- **Confidence**: {ml.get('ensemble_confidence', 'N/A')}/10
"""
                else:
                    report += "\n*ML prediction not available*\n"

                report += """
---
*Report generated by Stock AI Analysis System v2.0*
"""

                st.download_button(
                    label="📥 Download Report",
                    data=report,
                    file_name=f"{selected}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                    mime="text/markdown",
                    use_container_width=True
                )
                st.success(f"✅ Report generated! Click 'Download Report' to save.")


# ═══════════════════════════════════════════════════════════════
#  스캔 히스토리 페이지
# ═══════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════
#  팩터 랭킹 페이지
# ═══════════════════════════════════════════════════════════════

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




# ═══════════════════════════════════════════════════════════════
#  신호 정확도 페이지 (Sprint 2)
# ═══════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════
#  Virtual Trade 페이지 — 수동 가상 거래 추적
# ═══════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════
#  스캔 로그 (DB) 페이지
# ═══════════════════════════════════════════════════════════════

def render_scan_log():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">Scan Log</div>
        <div class="page-subtitle">Persistent scan result database &amp; analytics</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 통계 요약 ──
    scan_data = api_get("/scan-log?limit=50")
    if not scan_data or scan_data.get("total", 0) == 0:
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">📊</div>
            <div class="es-text">No scan logs yet. Run a scan to start building history.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    total_scans = scan_data.get("total", 0)
    logs = scan_data.get("logs", [])

    # 카드 집계
    buy_cnt = sum(1 for l in logs if l.get("signal") == "BUY")
    sell_cnt = sum(1 for l in logs if l.get("signal") == "SELL")
    hold_cnt = sum(1 for l in logs if l.get("signal") == "HOLD")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Scans", str(total_scans))
    m2.metric("Buy (recent)", str(buy_cnt))
    m3.metric("Sell (recent)", str(sell_cnt))
    m4.metric("Hold (recent)", str(hold_cnt))

    # ── 탭 구성 ──
    tab_overview, tab_weekly, tab_search, tab_ticker = st.tabs(
        ["Overview", "Weekly Summary", "Search / Range", "Ticker History"]
    )

    # ── Overview 탭 ──
    with tab_overview:
        # 최근 스캔 라운드
        latest = api_get("/scan-log/latest")
        latest_logs = latest.get("logs", []) if latest else []
        if latest_logs:
            st.markdown("""
            <div class="section-header">
                <div class="section-title">Latest Scan Round</div>
            </div>
            """, unsafe_allow_html=True)
            lt_rows = []
            for r in latest_logs:
                lt_rows.append({
                    "Ticker": r.get("ticker", "?"),
                    "Signal": r.get("signal", "?"),
                    "Score": r.get("score", 0),
                    "Confidence": r.get("confidence", 0),
                    "Alert": "Yes" if r.get("alert_sent") else "",
                    "Time": str(r.get("scanned_at", ""))[:19].replace("T", " "),
                })
            lt_df = pd.DataFrame(lt_rows)
            st.dataframe(
                lt_df.style.map(
                    lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
                    subset=["Signal"],
                ),
                use_container_width=True, hide_index=True,
            )

        # 전체 최근 로그 테이블
        if logs:
            st.markdown("""
            <div class="section-header">
                <div class="section-title">Recent Scans</div>
                <div class="section-subtitle">LAST 50</div>
            </div>
            """, unsafe_allow_html=True)
            rc_rows = []
            for r in logs:
                rc_rows.append({
                    "ID": r.get("id", 0),
                    "Time": str(r.get("scanned_at", ""))[:19].replace("T", " "),
                    "Ticker": r.get("ticker", "?"),
                    "Signal": r.get("signal", "?"),
                    "Score": r.get("score", 0),
                    "Confidence": r.get("confidence", 0),
                    "BUY": r.get("buy_count", 0),
                    "SELL": r.get("sell_count", 0),
                    "HOLD": r.get("neutral_count", 0),
                })
            rc_df = pd.DataFrame(rc_rows)
            st.dataframe(
                rc_df.style.map(
                    lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
                    subset=["Signal"],
                ),
                use_container_width=True, hide_index=True,
            )

    # ── Weekly Summary 탭 ──
    with tab_weekly:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">Weekly Summary</div>
            <div class="section-subtitle">WEEKLY REPORT</div>
        </div>
        """, unsafe_allow_html=True)

        wt_weeks_ago = st.slider("Weeks Ago (0=this week)", 0, 8, 0, key="wt_weeks_ago")
        weekly_data = api_get(f"/weekly?weeks_ago={wt_weeks_ago}")

        if not weekly_data or weekly_data.get("total_scans", 0) == 0:
            st.info("No scan data for this week.")
        else:
            w1, w2, w3, w4 = st.columns(4)
            w1.metric("Period", f"{weekly_data.get('week_start','')} ~ {weekly_data.get('week_end','')}")
            w2.metric("Total Scans", str(weekly_data.get("total_scans", 0)))
            w3.metric("Alerts", str(weekly_data.get("alert_count", 0)))
            sig_dist = weekly_data.get("signal_distribution", {})
            w4.metric("Signal Ratio", f"B:{sig_dist.get('BUY',0)} S:{sig_dist.get('SELL',0)} H:{sig_dist.get('HOLD',0)}")

            # 종목별 요약 테이블
            tickers_data = weekly_data.get("tickers", [])
            if tickers_data:
                st.markdown("""
                <div class="section-header">
                    <div class="section-title">Per-Ticker Summary</div>
                </div>
                """, unsafe_allow_html=True)
                wt_rows = []
                for t in tickers_data:
                    wt_rows.append({
                        "Ticker": t.get("ticker", "?"),
                        "Scans": t.get("scan_count", 0),
                        "Avg Score": t.get("avg_score", 0),
                        "Avg Conf": t.get("avg_confidence", 0),
                        "BUY": t.get("buy_cnt", 0),
                        "SELL": t.get("sell_cnt", 0),
                        "HOLD": t.get("hold_cnt", 0),
                        "Alerts": t.get("alerts", 0),
                    })
                wt_df = pd.DataFrame(wt_rows)
                st.dataframe(wt_df, use_container_width=True, row_height=44, hide_index=True)

            # Top BUY / Top SELL
            col_buy, col_sell = st.columns(2)
            with col_buy:
                top_buy = weekly_data.get("top_buy", [])
                if top_buy:
                    st.markdown("**Top BUY Signals**")
                    for b in top_buy:
                        st.markdown(f'`{b.get("ticker","?")}` score: **{b.get("best_score",0):+.2f}**')
            with col_sell:
                top_sell = weekly_data.get("top_sell", [])
                if top_sell:
                    st.markdown("**Top SELL Signals**")
                    for s in top_sell:
                        st.markdown(f'`{s.get("ticker","?")}` score: **{s.get("worst_score",0):+.2f}**')

            # 종목별 주간 상세
            st.divider()
            wt_tickers_list = [t.get("ticker", "?") for t in tickers_data] if tickers_data else load_watchlist()
            wt_sel = st.selectbox("Ticker Detail", wt_tickers_list, key="wt_ticker_detail")
            if wt_sel:
                ticker_weekly = api_get(f"/weekly/{wt_sel}?weeks_ago={wt_weeks_ago}")
                if ticker_weekly and ticker_weekly.get("stats", {}).get("scan_count", 0) > 0:
                    tw_stats = ticker_weekly["stats"]
                    tw1, tw2, tw3, tw4 = st.columns(4)
                    tw1.metric("Scans", str(tw_stats.get("scan_count", 0)))
                    tw2.metric("Avg Score", f"{tw_stats.get('avg_score', 0):+.2f}")
                    tw3.metric("Min/Max", f"{tw_stats.get('min_score', 0):+.2f} / {tw_stats.get('max_score', 0):+.2f}")
                    tw4.metric("Alerts", str(tw_stats.get("alert_count", 0)))

                    daily_trend = ticker_weekly.get("daily_trend", [])
                    if daily_trend:
                        dt_df = pd.DataFrame(daily_trend)
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=dt_df["day"], y=dt_df["avg_score"],
                            mode="lines+markers",
                            name="Avg Score",
                            line=dict(color="#6D7CFF", width=3),
                            marker=dict(size=10, color="#6D7CFF"),
                        ))
                        fig.add_hline(y=0, line_color="#1F2733", line_width=1)
                        fig.update_layout(**_plotly_base_layout(
                            height=280,
                            margin=dict(l=40, r=10, t=10, b=40),
                            xaxis=dict(gridcolor="#161C25"),
                            yaxis=dict(title="Score", gridcolor="#161C25"),
                        ))
                        st.plotly_chart(fig, use_container_width=True)

    # ── Search / Range 탭 ──
    with tab_search:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">Search by Date Range</div>
        </div>
        """, unsafe_allow_html=True)

        fc1, fc2 = st.columns(2)
        search_start = fc1.text_input("Start (YYYY-MM-DD)", placeholder="2026-04-07", key="sl_search_start")
        search_end = fc2.text_input("End (YYYY-MM-DD)", placeholder="2026-04-13", key="sl_search_end")

        if st.button("Search Range", type="primary", key="sl_search_btn"):
            if search_start and search_end:
                with st.spinner("Searching..."):
                    result = api_get(f"/scan-log/range?start={search_start.strip()}&end={search_end.strip()}")

                if not result:
                    st.error("Query failed")
                elif result.get("count", 0) == 0:
                    st.info("No records in this date range.")
                else:
                    st.caption(f"Found {result['count']} records")
                    rows = result.get("logs", [])
                    if rows:
                        sr_rows = []
                        for r in rows:
                            sr_rows.append({
                                "ID": r.get("id", 0),
                                "Time": str(r.get("scanned_at", ""))[:19].replace("T", " "),
                                "Ticker": r.get("ticker", "?"),
                                "Signal": r.get("signal", "?"),
                                "Score": r.get("score", 0),
                                "Confidence": r.get("confidence", 0),
                            })
                        sr_df = pd.DataFrame(sr_rows)
                        st.dataframe(
                            sr_df.style.map(
                                lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
                                subset=["Signal"],
                            ),
                            use_container_width=True, hide_index=True,
                        )
            else:
                st.warning("Start and End dates are required.")

    # ── Ticker History 탭 ──
    with tab_ticker:
        st.markdown("""
        <div class="section-header">
            <div class="section-title">Ticker Scan History</div>
        </div>
        """, unsafe_allow_html=True)

        # 종목 선택
        all_tickers = load_watchlist()
        if not all_tickers:
            st.info("No ticker data available.")
        else:
            sel_ticker = st.selectbox("Select Ticker", all_tickers, key="sl_ticker_hist")
            if sel_ticker:
                hist_data = api_get(f"/scan-log/{sel_ticker}?limit=50")
                history = hist_data.get("logs", []) if hist_data else []

                if not history:
                    st.info(f"No scan history for {sel_ticker}")
                else:
                    st.caption(f"{hist_data.get('total', len(history))} total records for {sel_ticker} (showing last 50)")

                    # 점수 시계열 차트
                    h_df = pd.DataFrame(history)
                    h_df["scanned_at"] = pd.to_datetime(h_df["scanned_at"])
                    h_df = h_df.sort_values("scanned_at")

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=h_df["scanned_at"], y=h_df["score"],
                        mode="lines+markers",
                        line=dict(color="#6D7CFF", width=2),
                        marker=dict(
                            size=8,
                            color=[
                                "#2BD98A" if s == "BUY" else "#FF6B6B" if s == "SELL" else "#F5B14C"
                                for s in h_df["signal"]
                            ],
                            line=dict(width=1, color="#06080C"),
                        ),
                        text=[f"{s} ({sc:+.1f})" for s, sc in zip(h_df["signal"], h_df["score"])],
                        hovertemplate="%{text}<br>%{x}<extra></extra>",
                    ))
                    fig.add_hline(y=0, line_color="#1F2733", line_width=1)
                    fig.update_layout(**_plotly_base_layout(
                        height=300,
                        margin=dict(l=50, r=10, t=10, b=40),
                        xaxis=dict(gridcolor="#161C25"),
                        yaxis=dict(title="Score", gridcolor="#161C25"),
                    ))
                    st.plotly_chart(fig, use_container_width=True)

                    # 이력 테이블
                    th_rows = []
                    for r in history:
                        th_rows.append({
                            "ID": r.get("id", 0),
                            "Time": str(r.get("scanned_at", ""))[:19].replace("T", " "),
                            "Signal": r.get("signal", "?"),
                            "Score": r.get("score", 0),
                            "Confidence": r.get("confidence", 0),
                            "BUY": r.get("buy_count", 0),
                            "SELL": r.get("sell_count", 0),
                            "HOLD": r.get("neutral_count", 0),
                            "Alert": "Yes" if r.get("alert_sent") else "",
                        })
                    th_df = pd.DataFrame(th_rows)
                    st.dataframe(
                        th_df.style.map(
                            lambda v: "color: #2BD98A" if v == "BUY" else ("color: #FF6B6B" if v == "SELL" else "color: #F5B14C"),
                            subset=["Signal"],
                        ),
                        use_container_width=True, hide_index=True,
                    )


# ═══════════════════════════════════════════════════════════════
#  라우팅
# ═══════════════════════════════════════════════════════════════

# 커맨드바는 모든 페이지 상단에 고정 — 사이드바에서 분리한 조작 패널이다.
render_command_bar(api_get("/health"), api_get("/"))

if page == "Home":
    render_home()
elif page == "Dashboard":
    render_dashboard()
elif page == "Detail":
    render_detail()
elif page == "Multi-Agent":
    render_multi_agent()
elif page == "Quant Indicators":
    render_quant_indicators()
elif page == "Scan Log":
    render_scan_log()
elif page == "System Monitor":
    render_system_monitor()
elif page == "Signal Accuracy":
    render_signal_accuracy()
elif page == "Screener":
    render_screener()
elif page == "Trading":
    render_trading()
elif page == "Virtual Trade":
    render_virtual_trade()
elif page == "Backtest":
    render_backtest()
elif page == "ML Predict":
    render_ml_predict()
elif page == "Portfolio":
    render_portfolio()
elif page == "Ranking":
    render_ranking()
elif page == "Paper Trade":
    render_paper_trade()
elif page == "History":
    render_history()
