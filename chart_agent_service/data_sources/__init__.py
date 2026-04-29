"""
데이터 소스 어댑터 (Phase 2.2+).

DATA_SOURCE 환경변수로 스위칭:
  yfinance (기본, 15분 지연)
  alpaca   (REST + WebSocket 실시간 — Phase 2.2)
  polygon  (Phase 2.4 예비)
  kis      (Phase 2.3 예비)
"""
from data_sources.base import DataSource, OHLCVBar, Quote
from data_sources.factory import get_data_source, get_data_source_name

__all__ = [
    "DataSource",
    "OHLCVBar",
    "Quote",
    "get_data_source",
    "get_data_source_name",
]
