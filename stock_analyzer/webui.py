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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 로깅은 UI 를 그리기 전에 설정한다 — 그 전에 난 로그는 사라진다.
# agent-api 와 같은 설정을 공유하므로 비밀값 마스킹도 함께 적용된다.
from app_logging import configure_logging, get_logger  # noqa: E402

configure_logging()
logger = get_logger("stock_auto.webui")

# ── UI 공용 모듈 (webui.py 점진 분리 — CLAUDE.md §6-10) ──
from ui.api_client import (  # noqa: E402
    AGENT_API_URL, api_get, api_post, get_chart_url, log_action,
)
from ui.export import export_comprehensive_data  # noqa: E402
from ui.format import (  # noqa: E402
    _fmt_num, _fmt_price, _get_currency_symbol, _is_korean_stock,
)
from ui.components import (  # noqa: E402
    _css_key, _plotly_base_layout, _quant_signal_style, _signal_pill_html,
    ticker_chip_html,
)
from ui.pages.backtest import render_backtest  # noqa: E402
from ui.pages.home import (  # noqa: E402
    render_home, render_index_chart, render_market_ticker_bar,
    render_stat_row,
)
from ui.pages.dashboard import render_dashboard  # noqa: E402
from ui.pages.detail import render_detail  # noqa: E402
from ui.pages.history import render_history  # noqa: E402
from ui.pages.scan_log import render_scan_log  # noqa: E402
from ui.pages.ml_predict import render_ml_predict  # noqa: E402
from ui.pages.multi_agent import render_multi_agent  # noqa: E402
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
    _INDEX_PERIODS, KRW_CROSS, MARKET_INDICES, _krw_cross_series,
    fetch_index_history, fetch_market_indices,
)
from ui.theme import inject_theme  # noqa: E402
from ui.tickers import (  # noqa: E402
    WATCHLIST_PATH, resolve_ticker, _is_korean_ticker, _looks_broken_name, _market_code,
    _market_flag, add_to_watchlist, clear_watchlist, format_ticker_label,
    get_ticker_display_name, load_watchlist, remove_from_watchlist,
    save_watchlist, validate_ticker_webui,
)


st.set_page_config(
    page_title="Stock AI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Kinetic Terminal Design System CSS ──────────────────────────
# ── Kinetic Terminal Design System CSS (stock_analyzer/ui/theme.py) ──
inject_theme()


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
