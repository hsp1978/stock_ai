# Phase 5: Observability & Resilience

## Summary

Phase 5 adds runtime visibility and external data resilience without changing the core analysis workflow.

## Changes

- Added TTL-cached fundamental fallback collection with source metadata and data-quality flags.
- Added TTL-cached news collection with headline-only mode and Naver/Alpha Vantage fallback support.
- Routed multi-agent headline context through the centralized news collector instead of direct yfinance news calls.
- Added `/system-monitor` for service, LLM node, signal accuracy, calibrator, and paper portfolio snapshots.
- Added a Streamlit `System Monitor` page.
- Added paper trading corporate-action adjustment for stock splits and dividends with idempotent event tracking.
- Added an automation control plane for scheduler jobs, manual job execution, and persisted job status.
- Added data freshness SLO snapshots for OHLCV, fundamentals, and news cache state.
- Added deduplicated operations alerts for job failures and stale/degraded data freshness.
- Extended `System Monitor` with `Ops Jobs` and `Data Freshness` tabs.

## Automation Control Plane

The service now tracks these operational jobs:

- `watchlist_scan`: scheduled watchlist scan
- `daily_signal_validation`: signal outcome validation and calibrator refit
- `corporate_actions`: paper portfolio split/dividend adjustment
- `data_health_check`: cache freshness and data quality check

The control plane is exposed through:

- `GET /ops/jobs`
- `GET /ops/data-health`
- `POST /ops/jobs/{job_id}/run`

Job state is persisted in `app_state`, including last start/end time, duration, run count, error count, last error, and compact result summary.

## Data Freshness SLO

`data_health_check` reads cache metadata without making new external API calls. It reports:

- OHLCV cache source, age, row count, latest bar date, and freshness
- Fundamental cache source, attempted sources, data quality, errors, and freshness
- News cache source list, article count, sentiment mode, and freshness

The system marks a ticker as `stale` when OHLCV is missing or older than the configured stale threshold, and `degraded` when fundamentals are missing, empty, or expired.

## Validation

- `pytest tests/unit -q`
- `python3 -m py_compile chart_agent_service/config.py chart_agent_service/data_collector.py chart_agent_service/news_analyzer.py chart_agent_service/paper_trader.py chart_agent_service/service.py stock_analyzer/dual_node_config.py stock_analyzer/local_engine.py stock_analyzer/multi_agent.py stock_analyzer/webui.py`
