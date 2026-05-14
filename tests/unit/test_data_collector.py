"""
OHLCV 캐시 freshness + retry + 다중 소스 fallback 단위 테스트 (Step 3)

테스트 시나리오:
- yfinance 정상 → CacheEntry 정상 생성
- yfinance 3회 실패 → FDR fallback
- 모든 소스 실패 → DataStaleError raise
- 한국 ticker (005930.KS) → pykrx 우선 호출
- 캐시 TTL 미만료 → 캐시 반환 (소스 호출 안 함)
- 캐시 TTL 만료 후 재호출 → 새 fetch
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from data_collector_models import CacheEntry, DataStaleError  # noqa: E402


# ── 공통 픽스처 ───────────────────────────────────────────────────────


def _make_df(rows: int = 50) -> pd.DataFrame:
    """더미 OHLCV DataFrame 생성."""
    idx = pd.date_range("2025-01-01", periods=rows, freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "Open": [100.0] * rows,
            "High": [105.0] * rows,
            "Low": [95.0] * rows,
            "Close": [102.0] * rows,
            "Volume": [1_000_000] * rows,
        },
        index=idx,
    )


@pytest.fixture(autouse=True)
def clear_cache():
    """각 테스트 전후 캐시 초기화."""
    import data_collector as dc

    dc._entry_cache.clear()
    dc._ohlcv_cache.clear()
    yield
    dc._entry_cache.clear()
    dc._ohlcv_cache.clear()


# ── CacheEntry.build ─────────────────────────────────────────────────


def test_cache_entry_build():
    """CacheEntry.build → 메타 정확히 채워짐."""
    df = _make_df()
    entry = CacheEntry.build("AAPL", df, "yfinance")
    assert entry.ticker == "AAPL"
    assert entry.source == "yfinance"
    assert entry.row_count == 50
    assert entry.data_hash  # non-empty
    assert entry.fetched_at.tzinfo is not None  # timezone-aware


# ── yfinance 정상 → CacheEntry 생성 ─────────────────────────────────


def test_fetch_normal_returns_dataframe():
    """yfinance 정상 응답 시 fetch_ohlcv가 DataFrame을 반환한다."""
    mock_source = MagicMock()
    mock_source.name = "yfinance"
    mock_source.get_ohlcv.return_value = _make_df()

    import data_collector as dc

    with (
        patch("data_collector.YFinanceSource", return_value=mock_source),
        patch("data_collector.FdrSource", return_value=MagicMock()),
        patch("data_collector._is_korean_ticker", return_value=False),
    ):
        df = dc.fetch_ohlcv("AAPL", "2y")

    assert isinstance(df, pd.DataFrame)
    assert not df.empty


def test_fetch_meta_caches_entry():
    """fetch_ohlcv_with_meta 호출 후 _entry_cache에 저장됨."""
    mock_source = MagicMock()
    mock_source.name = "yfinance"
    mock_source.get_ohlcv.return_value = _make_df()

    import data_collector as dc

    with (
        patch("data_collector.YFinanceSource", return_value=mock_source),
        patch("data_collector.FdrSource", return_value=MagicMock()),
        patch("data_collector._is_korean_ticker", return_value=False),
    ):
        entry = dc.fetch_ohlcv_with_meta("AAPL", "2y")

    assert isinstance(entry, CacheEntry)
    assert ("AAPL", "2y") in dc._entry_cache


# ── yfinance 실패 → FDR fallback ─────────────────────────────────────


def test_yfinance_failure_falls_back_to_fdr():
    """yfinance가 ConnectionError를 내면 FDR로 fallback."""
    yf_mock = MagicMock()
    yf_mock.name = "yfinance"
    yf_mock.get_ohlcv.side_effect = ConnectionError("timeout")

    fdr_mock = MagicMock()
    fdr_mock.name = "fdr"
    fdr_mock.get_ohlcv.return_value = _make_df()

    import data_collector as dc

    with (
        patch("data_collector.YFinanceSource", return_value=yf_mock),
        patch("data_collector.FdrSource", return_value=fdr_mock),
        patch("data_collector._is_korean_ticker", return_value=False),
        # tenacity retry를 1회로 단축 (대기 없음)
        patch(
            "data_collector._fetch_with_retry",
            side_effect=dc._fetch_with_retry.__wrapped__,
        ),
    ):
        # yfinance가 실패하면 FDR이 호출돼야 함
        entry = dc.fetch_ohlcv_with_meta("AAPL", "2y")

    assert entry.source == "fdr"


# ── 모든 소스 실패 → DataStaleError ──────────────────────────────────


def test_all_sources_fail_raises_data_stale_error():
    """모든 소스 실패 시 DataStaleError 발생."""
    yf_mock = MagicMock()
    yf_mock.name = "yfinance"
    yf_mock.get_ohlcv.side_effect = ConnectionError("fail")

    fdr_mock = MagicMock()
    fdr_mock.name = "fdr"
    fdr_mock.get_ohlcv.side_effect = ConnectionError("fail")

    import data_collector as dc

    with (
        patch("data_collector.YFinanceSource", return_value=yf_mock),
        patch("data_collector.FdrSource", return_value=fdr_mock),
        patch("data_collector._is_korean_ticker", return_value=False),
        patch(
            "data_collector._fetch_with_retry",
            side_effect=dc._fetch_with_retry.__wrapped__,
        ),
    ):
        with pytest.raises(DataStaleError):
            dc.fetch_ohlcv_with_meta("AAPL", "2y")


# ── 한국 ticker → pykrx 우선 호출 ───────────────────────────────────


def test_korean_ticker_uses_pykrx_first():
    """005930.KS → 소스 순서가 pykrx > fdr > yfinance."""
    pykrx_mock = MagicMock()
    pykrx_mock.name = "pykrx"
    pykrx_mock.get_ohlcv.return_value = _make_df()

    fdr_mock = MagicMock()
    fdr_mock.name = "fdr"
    yf_mock = MagicMock()
    yf_mock.name = "yfinance"

    import data_collector as dc

    with (
        patch("data_collector.PykrxSource", return_value=pykrx_mock),
        patch("data_collector.FdrSource", return_value=fdr_mock),
        patch("data_collector.YFinanceSource", return_value=yf_mock),
        patch("data_collector._is_korean_ticker", return_value=True),
    ):
        entry = dc.fetch_ohlcv_with_meta("005930.KS", "2y")

    assert entry.source == "pykrx"
    fdr_mock.get_ohlcv.assert_not_called()
    yf_mock.get_ohlcv.assert_not_called()


# ── TTL 미만료 → 캐시 반환 ───────────────────────────────────────────


def test_cache_hit_no_source_call():
    """TTL 이내 캐시 존재 시 소스를 다시 호출하지 않는다."""
    import data_collector as dc

    fresh_entry = CacheEntry.build("AAPL", _make_df(), "yfinance")
    dc._entry_cache[("AAPL", "2y")] = fresh_entry

    yf_mock = MagicMock()
    yf_mock.name = "yfinance"

    with patch("data_collector.YFinanceSource", return_value=yf_mock):
        result = dc.fetch_ohlcv_with_meta("AAPL", "2y")

    assert result is fresh_entry  # 동일 객체 반환
    yf_mock.get_ohlcv.assert_not_called()


# ── TTL 만료 → 새 fetch ──────────────────────────────────────────────


def test_expired_cache_triggers_new_fetch():
    """TTL 만료된 캐시는 무시하고 소스를 새로 호출한다."""
    import data_collector as dc

    stale_entry = CacheEntry.build("AAPL", _make_df(20), "yfinance")
    # fetched_at을 48시간 전으로 강제 설정
    object.__setattr__(
        stale_entry,
        "fetched_at",
        datetime.now(timezone.utc) - timedelta(hours=48),
    )
    dc._entry_cache[("AAPL", "2y")] = stale_entry

    fresh_df = _make_df(50)
    yf_mock = MagicMock()
    yf_mock.name = "yfinance"
    yf_mock.get_ohlcv.return_value = fresh_df

    with (
        patch("data_collector.YFinanceSource", return_value=yf_mock),
        patch("data_collector.FdrSource", return_value=MagicMock()),
        patch("data_collector._is_korean_ticker", return_value=False),
    ):
        new_entry = dc.fetch_ohlcv_with_meta("AAPL", "2y")

    assert new_entry.row_count == 50  # 새 데이터
    yf_mock.get_ohlcv.assert_called_once()


# ── _is_korean_ticker ─────────────────────────────────────────────────


def test_is_korean_ticker():
    import data_collector as dc

    assert dc._is_korean_ticker("005930.KS") is True
    assert dc._is_korean_ticker("035720.KQ") is True
    assert dc._is_korean_ticker("005930") is True  # 6-digit code
    assert dc._is_korean_ticker("AAPL") is False
    assert dc._is_korean_ticker("SPY") is False
    assert dc._is_korean_ticker("TSLA") is False
