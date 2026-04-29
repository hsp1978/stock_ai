"""
데이터 소스 팩토리 — DATA_SOURCE 환경변수 기반 디스패치.
"""
from __future__ import annotations

import os
from typing import Optional

from data_sources.base import DataSource


VALID_SOURCES = {"yfinance", "alpaca", "polygon", "kis"}


def get_data_source_name() -> str:
    name = os.getenv("DATA_SOURCE", "yfinance").lower()
    if name not in VALID_SOURCES:
        return "yfinance"
    return name


def get_data_source(name: Optional[str] = None) -> DataSource:
    """
    현재 설정된 데이터 소스 인스턴스 반환.

    자격증명이 없는 소스는 yfinance로 자동 폴백.
    """
    name = (name or get_data_source_name()).lower()

    if name == "alpaca":
        from data_sources.alpaca_data_source import AlpacaDataSource
        src = AlpacaDataSource()
        # 자격증명 없으면 폴백
        if not src._credentials_present():
            from data_sources.yfinance_source import YFinanceSource
            return YFinanceSource()
        return src

    if name == "polygon":
        # Phase 2.4에서 구현될 예비 슬롯
        try:
            from data_sources.polygon_source import PolygonSource  # noqa
            return PolygonSource()
        except ImportError:
            pass

    if name == "kis":
        # Phase 2.3에서 구현될 예비 슬롯
        try:
            from data_sources.kis_data_source import KISDataSource  # noqa
            return KISDataSource()
        except ImportError:
            pass

    # 기본: yfinance
    from data_sources.yfinance_source import YFinanceSource
    return YFinanceSource()
