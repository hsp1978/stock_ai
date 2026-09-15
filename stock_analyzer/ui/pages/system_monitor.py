"""시스템 모니터 페이지 — 잡 상태·GPU·데이터 신선도.

`webui.py` 분해 — 페이지 단위 (CLAUDE.md §6-10). 분리 후 **렌더 함수를 직접
호출**해 확인한다: ast 파싱·import·HTTP 200 은 화면 결함을 잡지 못한다 (§13.9a).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.api_client import api_get, api_post
from ui.components import _plotly_base_layout


def render_system_monitor():
    st.markdown("""
    <div class="page-header">
        <div class="page-title">System Monitor</div>
        <div class="page-subtitle">LLM routing capacity · signal calibration · paper portfolio snapshot</div>
    </div>
    """, unsafe_allow_html=True)

    data = api_get("/system-monitor", timeout=20)
    if not data:
        st.markdown("""
        <div class="empty-state">
            <div class="es-icon">!</div>
            <div class="es-text">System monitor data unavailable. Check agent API status.</div>
        </div>
        """, unsafe_allow_html=True)
        return

    service = data.get("service", {})
    llm = data.get("llm", {})
    signals = data.get("signals", {})
    paper = data.get("paper", {})
    ops = data.get("ops", {})
    data_health = ops.get("data_health", {}) if isinstance(ops, dict) else {}

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cached Results", f"{service.get('cached_results', 0):,}")
    c2.metric("Scan Count", f"{service.get('scan_count', 0):,}")
    c3.metric("Scheduler", "RUNNING" if service.get("scheduler_running") else "OFF")
    c4.metric("Data Health", str(data_health.get("status", "unknown")).upper())
    c5.metric("Generated", str(data.get("generated_at", ""))[:19].replace("T", " "))

    st.divider()

    tab_nodes, tab_agents, tab_jobs, tab_data, tab_signals, tab_paper = st.tabs(
        ["LLM Nodes", "Agent Runtime", "Ops Jobs", "Data Freshness", "Signal Quality", "Paper Portfolio"]
    )

    with tab_nodes:
        nodes = llm.get("nodes", {}) if isinstance(llm, dict) else {}
        if nodes:
            node_rows = []
            for node, metrics in nodes.items():
                capacity = metrics.get("capacity", 0) or 0
                inflight = metrics.get("inflight", 0) or 0
                usage_pct = (inflight / capacity * 100) if capacity else 0
                node_rows.append({
                    "Node": node,
                    "Inflight": inflight,
                    "Capacity": capacity,
                    "Available": metrics.get("available_slots", 0),
                    "Usage %": round(usage_pct, 1),
                    "Overloads": metrics.get("overload_count", 0),
                    "URL": metrics.get("url", ""),
                })
            st.dataframe(node_rows, use_container_width=True, row_height=44, hide_index=True)

            chart_df = pd.DataFrame(node_rows)
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=chart_df["Node"],
                y=chart_df["Inflight"],
                name="Inflight",
                marker_color="#38bdf8",
            ))
            fig.add_trace(go.Bar(
                x=chart_df["Node"],
                y=chart_df["Available"],
                name="Available",
                marker_color="#10b981",
            ))
            fig.update_layout(**_plotly_base_layout(
                height=320,
                barmode="stack",
                yaxis_title="Requests",
                margin=dict(l=35, r=20, t=30, b=35),
            ))
            st.plotly_chart(fig, use_container_width=True)

            mac_health = llm.get("mac_studio_health", {})
            if mac_health:
                h1, h2, h3 = st.columns(3)
                h1.metric("Mac Studio", "ONLINE" if mac_health.get("available") else "OFFLINE")
                h2.metric("Failures", str(mac_health.get("failures", 0)))
                h3.metric("Last Status", str(mac_health.get("last_status") or "n/a"))

                # 도달성만 보면 CPU 폴백 노드를 ONLINE 으로 읽는다 (2026-09-14:
                # 5일간 32B 모델이 CPU 에서 0.5 tok/s 로 돌았다). 가속기 상태를 같이 띄운다.
                runtime = mac_health.get("runtime")
                if runtime == "cpu_fallback":
                    st.error(
                        "Mac Studio 가 **CPU 폴백** 중입니다 — GPU 미적재: "
                        f"{', '.join(mac_health.get('cpu_only_models') or [])}. "
                        "라우팅에서 제외됩니다 (RTX 단독). Ollama 재기동이 필요합니다."
                    )
                elif runtime == "idle":
                    st.caption("Runtime: idle — 적재된 모델이 없어 가속기 상태는 판정 불가")
                elif runtime:
                    st.caption(f"Runtime: {runtime}")

                if mac_health.get("last_error"):
                    st.caption(f"Last error: {mac_health.get('last_error')}")
        else:
            st.info(llm.get("error") or "No LLM node metrics yet.")

    with tab_agents:
        perf = ((llm.get("agent_performance") or {}).get("agent_performance") or {})
        if perf:
            rows = []
            for agent, metrics in perf.items():
                rows.append({
                    "Agent": agent,
                    "Runs": metrics.get("count", 0),
                    "Avg Seconds": round(metrics.get("avg_time", 0), 2),
                    "Node Usage": ", ".join(
                        f"{node}:{count}" for node, count in (metrics.get("node_usage") or {}).items()
                    ),
                })
            perf_df = pd.DataFrame(rows).sort_values("Avg Seconds", ascending=False)
            st.dataframe(perf_df, use_container_width=True, row_height=44, hide_index=True)

            fig = go.Figure(go.Bar(
                x=perf_df["Avg Seconds"],
                y=perf_df["Agent"],
                orientation="h",
                marker_color="#f59e0b",
            ))
            fig.update_layout(**_plotly_base_layout(
                height=max(320, 42 * len(perf_df)),
                xaxis_title="Avg seconds",
                yaxis_title="",
                margin=dict(l=120, r=20, t=25, b=35),
            ))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No agent runtime samples yet. Run a multi-agent analysis to populate this view.")

    with tab_jobs:
        scheduler = ops.get("scheduler", {}) if isinstance(ops, dict) else {}
        jobs = ops.get("jobs", []) if isinstance(ops, dict) else []

        j1, j2, j3, j4 = st.columns(4)
        j1.metric("Scheduler", "RUNNING" if scheduler.get("running") else "OFF")
        j2.metric("Registered Jobs", f"{len(scheduler.get('jobs') or []):,}")
        j3.metric("Tracked Jobs", f"{len(jobs):,}")
        j4.metric("Job Errors", f"{sum(int(j.get('error_count', 0) or 0) for j in jobs):,}")

        action_1, action_2, action_3 = st.columns([1, 1, 2])
        with action_1:
            if st.button("Run Data Check", use_container_width=True):
                result = api_post("/ops/jobs/data_health_check/run", timeout=90)
                if result and not result.get("error"):
                    st.success(f"Data check: {result.get('status', 'completed')}")
                else:
                    st.error((result or {}).get("error") or "Data check failed")
        with action_2:
            if st.button("Run Corp Actions", use_container_width=True):
                result = api_post("/ops/jobs/corporate_actions/run?force=true", timeout=120)
                if result and not result.get("error"):
                    st.success(
                        f"Checked {result.get('checked', 0)} · Applied {result.get('applied', 0)}"
                    )
                else:
                    st.error((result or {}).get("error") or "Corporate action check failed")
        with action_3:
            if st.button("Refresh Monitor", use_container_width=True):
                st.cache_data.clear() if hasattr(st, "cache_data") else None
                st.rerun()

        if jobs:
            job_rows = []
            for job in jobs:
                job_rows.append({
                    "Job": job.get("label") or job.get("job_id"),
                    "Status": str(job.get("status", "unknown")).upper(),
                    "Runs": job.get("run_count", 0),
                    "Errors": job.get("error_count", 0),
                    "Last Started": str(job.get("last_started_at") or "")[:19].replace("T", " "),
                    "Last Finished": str(job.get("last_finished_at") or "")[:19].replace("T", " "),
                    "Duration Sec": job.get("last_duration_sec"),
                    "Last Error": job.get("last_error") or "",
                })
            st.dataframe(job_rows, use_container_width=True, row_height=44, hide_index=True)
        else:
            st.info("No ops job state yet.")

        sched_jobs = scheduler.get("jobs") or []
        if sched_jobs:
            st.markdown("#### Scheduler Queue")
            st.dataframe(
                [{
                    "Job": item.get("id"),
                    "Trigger": item.get("trigger"),
                    "Next Run": str(item.get("next_run_time") or "")[:19].replace("T", " "),
                } for item in sched_jobs],
                use_container_width=True,
                hide_index=True,
            )

    with tab_data:
        if data_health:
            d1, d2, d3, d4, d5 = st.columns(5)
            d1.metric("Status", str(data_health.get("status", "unknown")).upper())
            d2.metric("Tickers", f"{data_health.get('ticker_count', 0):,}")
            d3.metric("Stale", f"{data_health.get('stale_count', 0):,}")
            d4.metric("Degraded", f"{data_health.get('degraded_count', 0):,}")
            d5.metric("Warming", f"{data_health.get('warming_count', 0):,}")

            warmup = data_health.get("warmup") or {}
            if warmup.get("warming"):
                st.info(
                    f"기동 {warmup.get('uptime_sec', 0) / 60:.0f}분 — OHLCV·뉴스 캐시는 "
                    "인메모리라 첫 스캔 전까지 비어 있다. 미수집은 장애가 아니다."
                )

            # 점검 범위를 화면에도 적는다 — 무엇을 안 보고 있는지가 보이지 않으면
            # 'OK' 가 '괜찮다'인지 '안 봤다'인지 구분할 수 없다.
            scope = data_health.get("scope") or {}
            if scope:
                counts = scope.get("counts") or {}
                label = " · ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "없음"
                st.caption(
                    f"점검 범위: {label}"
                    f" · 최근 분석 창 {scope.get('recent_analysis_window_days', 0):g}일"
                    f" · 제외 {scope.get('excluded_count', 0)}건"
                )
                excluded = scope.get("excluded") or []
                if excluded:
                    with st.expander(f"범위 밖 {len(excluded)}종목 (사유 포함)", expanded=False):
                        st.dataframe(
                            pd.DataFrame([{
                                "Ticker": r.get("ticker"),
                                "Reason": r.get("reason"),
                                "Days Ago": r.get("last_analyzed_days_ago"),
                            } for r in excluded]),
                            use_container_width=True, row_height=44, hide_index=True,
                        )

            rows = data_health.get("rows") or []
            if rows:
                freshness_rows = []
                for row in rows:
                    freshness_rows.append({
                        "Ticker": row.get("ticker"),
                        "Scope": row.get("scope") or "",
                        "Severity": str(row.get("severity", "")).upper(),
                        "Reasons": ", ".join(row.get("reasons") or []),
                        "OHLCV Source": row.get("ohlcv_source") or "",
                        "OHLCV Age H": round((row.get("ohlcv_age_sec") or 0) / 3600, 2)
                        if row.get("ohlcv_age_sec") is not None else None,
                        "Latest Bar": row.get("ohlcv_latest_bar") or "",
                        "Fund Source": row.get("fundamental_source") or "",
                        "Fund Quality": row.get("fundamental_quality") or "",
                        "Fund Age H": round((row.get("fundamental_age_sec") or 0) / 3600, 2)
                        if row.get("fundamental_age_sec") is not None else None,
                        "News Cached": bool(row.get("news_present")),
                        "News Fresh": bool(row.get("news_fresh")),
                    })
                df_fresh = pd.DataFrame(freshness_rows)
                severity_order = {"STALE": 0, "DEGRADED": 1, "OK": 2}
                df_fresh["_order"] = df_fresh["Severity"].map(severity_order).fillna(9)
                df_fresh = df_fresh.sort_values(["_order", "Ticker"]).drop(columns=["_order"])
                st.dataframe(df_fresh, use_container_width=True, row_height=44, hide_index=True)

                chart_df = df_fresh.groupby("Severity").size().reset_index(name="Count")
                fig = go.Figure(go.Bar(
                    x=chart_df["Severity"],
                    y=chart_df["Count"],
                    marker_color=["#ef4444" if s == "STALE" else "#f59e0b" if s == "DEGRADED" else "#10b981"
                                  for s in chart_df["Severity"]],
                ))
                fig.update_layout(**_plotly_base_layout(
                    height=280,
                    yaxis_title="Tickers",
                    xaxis_title="Data state",
                    margin=dict(l=35, r=20, t=25, b=35),
                ))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data freshness rows yet.")
        else:
            st.info("Data health snapshot unavailable.")

    with tab_signals:
        accuracy = (
            signals.get("accuracy_primary") or signals.get("accuracy_7d") or {}
            if isinstance(signals, dict) else {}
        )
        if accuracy and not accuracy.get("error"):
            # 평가 기간은 매매 스타일의 의도 보유기간에서 파생된다 — 라벨을 고정
            # 문자열("7D")로 두면 실제 horizon 과 어긋난다.
            hz = accuracy.get("horizon_days", 7)
            a1, a2, a3, a4 = st.columns(4)
            a1.metric(f"{hz}D Evaluated", f"{accuracy.get('total_evaluated', 0):,}")
            a2.metric(
                f"{hz}D 방향 적중률",
                f"{accuracy.get('direction_hit_rate_pct', 0):.1f}%",
            )
            # 방향 보정본을 쓴다 — 원시 평균은 매도가 맞을수록 내려간다.
            a3.metric("방향보정 기대값", f"{accuracy.get('avg_signed_return_pct', 0):+.2f}%")
            a4.metric("Samples", f"{accuracy.get('sample_size', 0):,}")

            bands = [b for b in accuracy.get("by_confidence_band", []) if b.get("total", 0) > 0]
            if bands:
                band_df = pd.DataFrame(bands)
                fig = go.Figure(go.Bar(
                    x=band_df["band"],
                    y=band_df["direction_hit_rate_pct"],
                    text=[f"n={n}" for n in band_df["total"]],
                    marker_color="#10b981",
                ))
                fig.add_hline(y=50, line_dash="dash", line_color="#6A7482")
                fig.update_layout(**_plotly_base_layout(
                    height=330,
                    yaxis_title="Win rate %",
                    xaxis_title="Confidence band",
                    yaxis=dict(range=[0, 100]),
                    margin=dict(l=35, r=20, t=30, b=35),
                ))
                st.plotly_chart(fig, use_container_width=True)

            calib = signals.get("calibrator") or {}
            v1, v2, v3 = st.columns(3)
            v1.metric("Calibrator", "ON" if calib.get("active") else "OFF")
            v2.metric("Calibration Samples", f"{calib.get('total_samples', 0):,}")
            v3.metric("Last Refit", str(calib.get("last_refit") or "never")[:19])
        else:
            st.info((signals or {}).get("error") or "No evaluated signal data yet.")

    with tab_paper:
        if paper and not paper.get("error"):
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Equity", f"${paper.get('total_equity', 0):,.2f}")
            p2.metric("PnL", f"${paper.get('total_pnl', 0):+,.2f}",
                      delta=f"{paper.get('total_pnl_pct', 0):+.2f}%")
            p3.metric("Open Positions", f"{paper.get('open_positions', 0)}")
            p4.metric("Win Rate", f"{paper.get('win_rate_pct', 0):.1f}%")
            q1, q2 = st.columns(2)
            q1.metric("Cash", f"${paper.get('cash', 0):,.2f}")
            q2.metric("Position Value", f"${paper.get('position_value', 0):,.2f}")
        else:
            st.info((paper or {}).get("error") or "Paper trading status unavailable.")
