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

## Validation

- `pytest tests/unit -q`
- `python3 -m py_compile chart_agent_service/config.py chart_agent_service/data_collector.py chart_agent_service/news_analyzer.py chart_agent_service/paper_trader.py chart_agent_service/service.py stock_analyzer/dual_node_config.py stock_analyzer/local_engine.py stock_analyzer/multi_agent.py stock_analyzer/webui.py`

