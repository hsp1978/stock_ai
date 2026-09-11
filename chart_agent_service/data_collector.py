"""
데이터 수집 모듈 (경량화 - Mac Studio용)
DATA_SOURCE 환경변수로 yfinance/alpaca/... 스위칭 가능.

배치 프리페치:
  prefetch_ohlcv_batch(tickers) 를 스캔 시작 전에 한 번 호출하면
  yfinance download() 한 번으로 전 종목 데이터를 받아 캐시.
  이후 fetch_ohlcv()는 TTL 캐시를 우선 조회 → 종당 네트워크 왕복 제거.

Step 3: CacheEntry(TTL 메타) + tenacity retry + 다중 소스 fallback 추가.
"""

import logging
import os
import threading
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import (
    ADX_PERIOD,
    ATR_PERIOD,
    BOLLINGER_PERIOD,
    BOLLINGER_STD,
    DEFAULT_HISTORY_PERIOD,
    EMA_PERIODS,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    RSI_PERIOD,
    SMA_PERIODS,
    settings,
)
from data_collector_models import (
    INTRADAY_PERIODS,
    CacheEntry,
    DataStaleError,
)
from data_sources.factory import get_data_source, get_data_source_name
from data_sources.fdr_source import FdrSource
from data_sources.pykrx_source import PykrxSource
from data_sources.yfinance_source import YFinanceSource

logger = logging.getLogger(__name__)

# ─── TTL-aware CacheEntry 저장소 ─────────────────────────────
# key: (ticker.upper(), period)  value: CacheEntry
_entry_cache: dict[tuple, CacheEntry] = {}
_entry_cache_lock = threading.Lock()

# ─── 배치 프리페치용 레거시 캐시 (backward compat) ─────────────
_ohlcv_cache: dict = {}
_ohlcv_cache_lock = threading.Lock()

# ─── 펀더멘털 TTL 캐시 ────────────────────────────────────────
_fundamental_cache: dict[str, dict[str, Any]] = {}
_fundamental_cache_lock = threading.Lock()

_FUNDAMENTAL_FIELDS = [
    "market_cap",
    "pe_ratio",
    "forward_pe",
    "peg_ratio",
    "price_to_book",
    "dividend_yield",
    "eps",
    "revenue_growth",
    "profit_margin",
    "debt_to_equity",
    "free_cash_flow",
    "return_on_equity",
    "beta",
    "52w_high",
    "52w_low",
    "avg_volume",
    "short_ratio",
    "sector",
    "industry",
    "current_price",
]

_FUNDAMENTAL_QUALITY_FIELDS = [
    "market_cap",
    "pe_ratio",
    "eps",
    "beta",
    "sector",
    "industry",
]


# ── 헬퍼 ──────────────────────────────────────────────────────


def _is_korean_ticker(ticker: str) -> bool:
    t = ticker.upper()
    stripped = t.split(".")[0]
    return t.endswith((".KS", ".KQ")) or (stripped.isdigit() and len(stripped) == 6)


def _get_ttl_seconds(period: str) -> float:
    if period in INTRADAY_PERIODS:
        return settings.OHLCV_TTL_INTRADAY_MINUTES * 60.0
    return settings.OHLCV_TTL_EOD_HOURS * 3600.0


def _is_fresh(entry: CacheEntry, period: str) -> bool:
    age = (datetime.now(timezone.utc) - entry.fetched_at).total_seconds()
    return age < _get_ttl_seconds(period)


def _is_fundamental_cache_fresh(entry: dict[str, Any]) -> bool:
    ttl = float(settings.FUNDAMENTAL_TTL_HOURS) * 3600.0
    if ttl <= 0:
        return False
    fetched_at = entry.get("fetched_at")
    if not isinstance(fetched_at, datetime):
        return False
    age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    return age < ttl


def _dedupe_sources(sources: list) -> list:
    seen = set()
    result = []
    for source in sources:
        name = getattr(source, "name", source.__class__.__name__)
        if name in seen:
            continue
        seen.add(name)
        result.append(source)
    return result


# ── tenacity retry 래퍼 ───────────────────────────────────────


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)
def _fetch_with_retry(source: object, ticker: str, period: str) -> pd.DataFrame:
    """단일 소스에서 OHLCV를 최대 3회 재시도로 가져온다."""
    df: pd.DataFrame = source.get_ohlcv(ticker, period=period)  # type: ignore[union-attr]
    if df is None or df.empty:
        raise ConnectionError(f"{source.name} empty data for {ticker}")  # type: ignore[union-attr]
    return df


# ── 다중 소스 fallback (TTL 캐시 포함) ───────────────────────────


def fetch_ohlcv_with_meta(
    ticker: str, period: str = DEFAULT_HISTORY_PERIOD
) -> CacheEntry:
    """
    TTL 캐시 → 다중 소스 fallback 순으로 OHLCV를 가져온다.

    한국: pykrx > FDR > yfinance
    미국: yfinance > FDR

    실패 시 DataStaleError.
    """
    key = (ticker.upper(), period)

    # 1. TTL 캐시 확인
    with _entry_cache_lock:
        cached = _entry_cache.get(key)
    if cached is not None and _is_fresh(cached, period):
        return cached

    # 2. 소스 우선순위 결정
    configured_source_name = get_data_source_name()
    if _is_korean_ticker(ticker):
        sources: list = [PykrxSource(), FdrSource(), YFinanceSource()]
    else:
        sources = [YFinanceSource(), FdrSource()]
    if configured_source_name != "yfinance":
        sources = _dedupe_sources([get_data_source(configured_source_name)] + sources)

    last_exc: Exception | None = None
    for source in sources:
        try:
            df = _fetch_with_retry(source, ticker, period)
            entry = CacheEntry.build(ticker, df, source.name)  # type: ignore[arg-type]
            with _entry_cache_lock:
                _entry_cache[key] = entry
            logger.info(
                "[%s] %s fetch OK via %s (%d rows)",
                ticker,
                period,
                source.name,
                entry.row_count,
            )
            return entry
        except Exception as exc:
            last_exc = exc
            logger.warning("[%s] %s failed: %s", source.name, ticker, exc)

    raise DataStaleError(f"All sources exhausted for {ticker}", last_exc)


def fetch_ohlcv(ticker: str, period: str = DEFAULT_HISTORY_PERIOD) -> pd.DataFrame:
    """
    OHLCV DataFrame 반환 (backward-compatible).

    조회 순서:
    1. 배치 프리페치 레거시 캐시 (prefetch_ohlcv_batch 호출 시, yfinance/미국 종목만)
    2. TTL-aware CacheEntry → 다중 소스 fallback
    """
    key = (ticker.upper(), period)

    # 1. 배치 캐시 (구형, 스캔 시 프리페치로 채워짐)
    with _ohlcv_cache_lock:
        legacy = _ohlcv_cache.get(key)
    if (
        legacy is not None
        and not legacy.empty
        and get_data_source_name() == "yfinance"
        and not _is_korean_ticker(ticker)
    ):
        return legacy.copy()

    # 2. TTL 캐시 + 다중 소스 fallback
    entry = fetch_ohlcv_with_meta(ticker, period)
    return entry.data.copy()


def prefetch_ohlcv_batch(tickers: list, period: str = DEFAULT_HISTORY_PERIOD) -> None:
    """
    미국 종목 OHLCV를 yfinance 배치 다운로드로 한 번에 수집해 캐시.

    순차 스캔에서 종목당 5~10초 절약 가능.
    스캔 시작 직전에 호출.
    한국 종목은 pykrx/FDR 우선순위를 보존하기 위해 배치 캐시에 넣지 않는다.
    """
    if not tickers:
        return
    if get_data_source_name() != "yfinance":
        logger.info("[배치] DATA_SOURCE=%s 이므로 yfinance 배치 프리페치 생략", get_data_source_name())
        return

    batch_tickers = [t for t in tickers if not _is_korean_ticker(t)]
    if not batch_tickers:
        logger.info("[배치] yfinance 배치 대상 미국 종목 없음")
        return

    try:
        skipped = len(tickers) - len(batch_tickers)
        logger.info(
            "[배치] %d개 미국 종목 데이터 사전 다운로드 중... (한국 종목 %d개 제외)",
            len(batch_tickers),
            skipped,
        )
        raw = yf.download(
            batch_tickers,
            period=period,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if raw.empty:
            return

        if isinstance(raw.columns, pd.MultiIndex):
            for t in batch_tickers:
                t_up = t.upper()
                try:
                    df_t = raw.xs(t, level=1, axis=1).copy()
                    if not df_t.empty:
                        with _ohlcv_cache_lock:
                            _ohlcv_cache[(t_up, period)] = df_t
                except KeyError:
                    pass
        else:
            t_up = batch_tickers[0].upper()
            with _ohlcv_cache_lock:
                _ohlcv_cache[(t_up, period)] = raw.copy()

        cached = sum(1 for k in _ohlcv_cache if k[1] == period)
        logger.info("[배치] 완료: %d개 캐시 저장", cached)
    except Exception as exc:
        logger.warning("[배치] 사전 다운로드 실패 (개별 조회로 폴백): %s", exc)


def clear_ohlcv_cache() -> None:
    """두 캐시 모두 초기화 (다음 스캔 시작 전 호출)."""
    with _ohlcv_cache_lock:
        _ohlcv_cache.clear()
    with _entry_cache_lock:
        _entry_cache.clear()


def clear_fundamental_cache() -> None:
    """펀더멘털 TTL 캐시 초기화 (테스트/수동 복구용)."""
    with _fundamental_cache_lock:
        _fundamental_cache.clear()


def _age_seconds(fetched_at: datetime | None) -> float | None:
    if not isinstance(fetched_at, datetime):
        return None
    return max(0.0, (datetime.now(timezone.utc) - fetched_at).total_seconds())


# ═══════════════════════════════════════════════════════════════════
#  가격 소스 교차검증
# ═══════════════════════════════════════════════════════════════════
#
# 다중 소스 폴백은 '한 소스가 죽었을 때 다른 소스로 넘어가는' 장치일 뿐,
# **두 소스가 서로 다른 값을 줄 때를 잡지 못한다.** 가격이 틀리면 Z-score·ATR·
# 지지저항·R/R 이 전부 무의미해지므로, 최신 종가만 교차 확인한다.
#
# 2026-09 사후검증에서 나온 불일치 사례:
#   DB손해보험  공식 IR ₩68,400(9/3) vs 외부 위젯 ₩202,000(9/2) — 약 3배
#   PLTR       시스템 진입가 $147.12 vs 당일 실제 범위 $139.53~$146.50
#
# 설계 선택:
#   - 전체 히스토리가 아니라 **최신 종가 1개**만 비교한다 (호출 비용 최소화).
#   - 같은 거래일(latest_bar_date)일 때만 가격을 비교한다. 날짜가 다르면 가격
#     차이가 아니라 **소스 지연**이므로 따로 보고한다 (장중 시점 차이 포함).
#   - 불일치는 예외로 올리지 않는다. 분석 전체를 죽이면 데이터 소스 딸꾹질이
#     운영 중단이 된다 — 대신 상태로 보고해 게이트가 판단하게 한다.
#   - 결과는 OHLCV 와 같은 TTL 로 캐시한다 (스캔마다 재검증하지 않는다).

_verification_cache: dict[str, tuple[datetime, "PriceVerification"]] = {}
_verification_lock = threading.Lock()

# 같은 거래일 종가가 이 비율 이상 어긋나면 불일치로 본다.
PRICE_MISMATCH_PCT = 2.0


@dataclass(frozen=True)
class PriceVerification:
    """최신 종가 교차검증 결과."""

    ticker: str
    status: str          # ok | mismatch | bar_date_mismatch | single_source | unavailable
    primary_source: Optional[str] = None
    primary_close: Optional[float] = None
    primary_bar_date: Optional[str] = None
    secondary_source: Optional[str] = None
    secondary_close: Optional[float] = None
    secondary_bar_date: Optional[str] = None
    compared_bar_date: Optional[str] = None   # 실제로 비교한 공통 거래일
    diff_pct: Optional[float] = None
    detail: str = ""

    @property
    def is_mismatch(self) -> bool:
        return self.status in ("mismatch", "bar_date_mismatch")


def _secondary_sources(ticker: str, primary_name: str) -> list:
    """1차 소스를 제외한 검증용 소스 목록 (같은 체인 순서)."""
    if _is_korean_ticker(ticker):
        candidates = [PykrxSource(), FdrSource(), YFinanceSource()]
    else:
        candidates = [YFinanceSource(), FdrSource()]
    return [
        src
        for src in _dedupe_sources(candidates)
        if getattr(src, "name", "") != primary_name
    ]


def _close_by_date(df: "pd.DataFrame") -> dict[str, float]:
    """{ISO 날짜: 종가}. 소스 간 '같은 거래일'을 맞추기 위한 인덱스."""
    if df is None or df.empty or "Close" not in df.columns:
        return {}
    out: dict[str, float] = {}
    for idx, value in df["Close"].items():
        key = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _latest_close_and_date(df: "pd.DataFrame") -> tuple[Optional[float], Optional[str]]:
    if df is None or df.empty or "Close" not in df.columns:
        return None, None
    try:
        close = float(df["Close"].iloc[-1])
    except (TypeError, ValueError):
        return None, None
    last_idx = df.index[-1]
    bar_date = (
        last_idx.date().isoformat()
        if hasattr(last_idx, "date")
        else str(last_idx)[:10]
    )
    return close, bar_date


def verify_latest_close(
    ticker: str, period: str = DEFAULT_HISTORY_PERIOD, use_cache: bool = True
) -> PriceVerification:
    """1차 소스의 최신 종가를 다른 소스와 비교한다.

    네트워크를 타므로 TTL 캐시를 쓴다. 검증 불가는 'ok' 로 적지 않는다.
    """
    key = f"{ticker.upper()}|{period}"
    ttl = _get_ttl_seconds(period)
    now = datetime.now(timezone.utc)
    if use_cache:
        with _verification_lock:
            cached = _verification_cache.get(key)
        if cached and (now - cached[0]).total_seconds() < ttl:
            return cached[1]

    try:
        primary = fetch_ohlcv_with_meta(ticker, period)
    except Exception as exc:
        result = PriceVerification(
            ticker=ticker.upper(),
            status="unavailable",
            detail=f"1차 소스 조회 실패 — 검증 불가 ({type(exc).__name__}: {exc})",
        )
        _store_verification(key, now, result)
        return result

    p_close, p_date = _latest_close_and_date(primary.data)
    base = {
        "ticker": ticker.upper(),
        "primary_source": primary.source,
        "primary_close": p_close,
        "primary_bar_date": p_date,
    }
    if p_close is None:
        result = PriceVerification(
            **base, status="unavailable", detail="1차 소스 종가 없음 — 검증 불가"
        )
        _store_verification(key, now, result)
        return result

    failures: list[str] = []
    for source in _secondary_sources(ticker, primary.source):
        name = getattr(source, "name", source.__class__.__name__)
        try:
            df = _fetch_with_retry(source, ticker, period)
        except Exception as exc:
            failures.append(f"{name}({type(exc).__name__})")
            continue
        s_close, s_date = _latest_close_and_date(df)
        if s_close is None:
            failures.append(f"{name}(종가없음)")
            continue

        # '최신 vs 최신'을 비교하면 안 된다. 실측(2026-09-11): 미국 종목에서 Toss 는
        # KST 날짜(09-11), yfinance 는 미국장 날짜(09-10)로 최신 봉을 라벨링한다.
        # 그대로 비교하면 **모든 미국 종목이 매일 불일치**로 잡혀 경고가 상시 켜진다.
        # 두 소스에 공통으로 있는 가장 최근 거래일의 종가를 맞춰서 본다.
        primary_by_date = _close_by_date(primary.data)
        secondary_by_date = _close_by_date(df)
        common = sorted(set(primary_by_date) & set(secondary_by_date))
        if not common:
            result = PriceVerification(
                **base,
                status="bar_date_mismatch",
                secondary_source=name,
                secondary_close=s_close,
                secondary_bar_date=s_date,
                detail=(
                    f"공통 거래일 없음: {primary.source} 최신 {p_date} vs {name} 최신 {s_date} "
                    "— 가격 비교 불가"
                ),
            )
            _store_verification(key, now, result)
            return result

        compared = common[-1]
        p_cmp = primary_by_date[compared]
        s_cmp = secondary_by_date[compared]
        lag_note = ""
        if p_date != s_date:
            lag_note = f", 최신봉 {primary.source} {p_date}/{name} {s_date}"

        diff_pct = abs(p_cmp - s_cmp) / s_cmp * 100 if s_cmp else None
        status = (
            "mismatch"
            if diff_pct is not None and diff_pct > PRICE_MISMATCH_PCT
            else "ok"
        )
        detail = (
            f"{compared} 종가 비교: {primary.source} {p_cmp:,.2f} vs {name} {s_cmp:,.2f} "
            f"(차이 {diff_pct:.2f}%){lag_note}"
        )
        if status == "mismatch":
            detail += f" — 임계 {PRICE_MISMATCH_PCT}% 초과, 가격 기반 지표 신뢰 불가"
        result = PriceVerification(
            **base,
            status=status,
            secondary_source=name,
            secondary_close=s_cmp,
            secondary_bar_date=s_date,
            compared_bar_date=compared,
            diff_pct=round(diff_pct, 3) if diff_pct is not None else None,
            detail=detail,
        )
        _store_verification(key, now, result)
        return result

    # 2차 소스가 하나도 응답하지 않았다 — '일치'가 아니라 '미검증'이다.
    result = PriceVerification(
        **base,
        status="single_source",
        detail=(
            f"{primary.source} 단일 소스 — 교차검증 불가"
            + (f" (실패: {', '.join(failures)})" if failures else "")
        ),
    )
    _store_verification(key, now, result)
    return result


def _store_verification(key: str, now: datetime, result: "PriceVerification") -> None:
    with _verification_lock:
        _verification_cache[key] = (now, result)


def clear_price_verification_cache() -> None:
    with _verification_lock:
        _verification_cache.clear()


def get_data_cache_status(
    tickers: list[str] | None = None,
    period: str = DEFAULT_HISTORY_PERIOD,
) -> dict[str, Any]:
    """
    OHLCV/fundamental TTL 캐시의 freshness 메타데이터를 반환한다.

    네트워크를 호출하지 않는 관측용 함수다. 스케줄러/대시보드가 현재
    캐시 상태를 읽고 stale/missing 여부를 판단할 때 사용한다.
    """
    with _entry_cache_lock:
        entry_snapshot = dict(_entry_cache)
    with _ohlcv_cache_lock:
        legacy_snapshot = dict(_ohlcv_cache)
    with _fundamental_cache_lock:
        fundamental_snapshot = dict(_fundamental_cache)

    if tickers:
        ticker_list = [t.upper().strip() for t in tickers if t and t.strip()]
    else:
        found = {key[0] for key in entry_snapshot if len(key) >= 2 and key[1] == period}
        found.update(key[0] for key in legacy_snapshot if len(key) >= 2 and key[1] == period)
        found.update(fundamental_snapshot.keys())
        ticker_list = sorted(found)

    ohlcv_ttl = _get_ttl_seconds(period)
    fundamental_ttl = float(settings.FUNDAMENTAL_TTL_HOURS) * 3600.0
    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "ohlcv_ttl_sec": ohlcv_ttl,
        "fundamental_ttl_sec": fundamental_ttl,
        "tickers": {},
    }

    for ticker in ticker_list:
        key = (ticker, period)
        entry = entry_snapshot.get(key)
        legacy_df = legacy_snapshot.get(key)
        fundamental = fundamental_snapshot.get(ticker)

        ohlcv_status: dict[str, Any]
        if entry is not None:
            age = _age_seconds(entry.fetched_at)
            ohlcv_status = {
                "present": True,
                "source": entry.source,
                "fetched_at": entry.fetched_at.isoformat(),
                "age_sec": age,
                "fresh": bool(age is not None and age < ohlcv_ttl),
                "row_count": entry.row_count,
                "latest_bar_date": entry.latest_bar_date.isoformat(),
                "data_hash": entry.data_hash,
            }
        elif legacy_df is not None:
            latest_bar = None
            try:
                latest_idx = legacy_df.index[-1]
                latest_bar = (
                    latest_idx.date().isoformat()
                    if hasattr(latest_idx, "date")
                    else str(latest_idx)[:10]
                )
            except Exception:
                pass
            ohlcv_status = {
                "present": True,
                "source": "yfinance_batch",
                "fetched_at": None,
                "age_sec": None,
                "fresh": None,
                "row_count": int(len(legacy_df)),
                "latest_bar_date": latest_bar,
                "data_hash": None,
            }
        else:
            ohlcv_status = {
                "present": False,
                "source": None,
                "fetched_at": None,
                "age_sec": None,
                "fresh": False,
                "row_count": 0,
                "latest_bar_date": None,
                "data_hash": None,
            }

        fundamental_status: dict[str, Any]
        if fundamental is not None:
            fetched_at = fundamental.get("fetched_at")
            data = fundamental.get("data") or {}
            age = _age_seconds(fetched_at)
            fundamental_status = {
                "present": True,
                "source": data.get("_source"),
                "sources_attempted": data.get("_sources_attempted") or [],
                "errors": data.get("_errors") or [],
                "fetched_at": fetched_at.isoformat() if isinstance(fetched_at, datetime) else None,
                "age_sec": age,
                "fresh": bool(age is not None and age < fundamental_ttl),
                "data_quality": data.get("data_quality", "unknown"),
            }
        else:
            fundamental_status = {
                "present": False,
                "source": None,
                "sources_attempted": [],
                "errors": [],
                "fetched_at": None,
                "age_sec": None,
                "fresh": False,
                "data_quality": "missing",
            }

        result["tickers"][ticker] = {
            "ohlcv": ohlcv_status,
            "fundamentals": fundamental_status,
        }

    return result


def _stabilize_latest_indicator_row(
    df: pd.DataFrame,
    indicator_cols: list[str],
) -> pd.DataFrame:
    """Keep latest OHLC live, but freeze indicator columns at the prior bar."""
    if len(df) < 2 or not indicator_cols:
        df.attrs["indicator_mode"] = "confirmed"
        df.attrs["indicator_asof"] = None
        return df

    latest_idx = df.index[-1]
    confirmed_idx = df.index[-2]

    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in df.columns:
            df[f"Live_{col}"] = df[col]

    df.loc[latest_idx, indicator_cols] = df.loc[confirmed_idx, indicator_cols]
    df["Indicator_Mode"] = "confirmed"
    df["Indicator_AsOf"] = None
    df.loc[latest_idx, "Indicator_AsOf"] = (
        confirmed_idx.isoformat() if hasattr(confirmed_idx, "isoformat") else str(confirmed_idx)
    )
    df.attrs["indicator_mode"] = "confirmed"
    df.attrs["indicator_asof"] = df.loc[latest_idx, "Indicator_AsOf"]

    live_close = float(df.loc[latest_idx, "Live_Close"]) if "Live_Close" in df.columns else None
    if live_close and live_close > 0:
        for col in indicator_cols:
            is_price_level = (
                col.startswith(("SMA_", "EMA_"))
                or (col.startswith("VWAP_") and col.removeprefix("VWAP_").isdigit())
            )
            if (
                is_price_level
                and not pd.isna(df.loc[latest_idx, col])
                and float(df.loc[latest_idx, col]) != 0
            ):
                df.loc[latest_idx, f"Live_Dist_{col}"] = (
                    live_close / float(df.loc[latest_idx, col]) - 1
                ) * 100
    return df


def calculate_indicators(df: pd.DataFrame, mode: str = "confirmed") -> pd.DataFrame:
    """기술 지표 일괄 계산.

    mode="confirmed" (default): latest row keeps live OHLC values, while indicator
    columns are frozen to the prior confirmed bar to avoid intraday repaint.
    mode="live": preserve legacy behavior and include the latest row in indicators.
    """
    if mode not in {"confirmed", "live"}:
        raise ValueError("mode must be 'confirmed' or 'live'")
    df = df.copy()
    original_cols = set(df.columns)

    # ── SMA / EMA ──
    for p in SMA_PERIODS:
        df[f"SMA_{p}"] = df["Close"].rolling(window=p, min_periods=p).mean()
    for p in EMA_PERIODS:
        df[f"EMA_{p}"] = df["Close"].ewm(span=p, adjust=False).mean()

    # ── RSI ──
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # ── Bollinger Bands ──
    sma = df["Close"].rolling(window=BOLLINGER_PERIOD).mean()
    std = df["Close"].rolling(window=BOLLINGER_PERIOD).std()
    df[f"BBU_{BOLLINGER_PERIOD}_{BOLLINGER_STD}"] = sma + BOLLINGER_STD * std
    df[f"BBM_{BOLLINGER_PERIOD}_{BOLLINGER_STD}"] = sma
    df[f"BBL_{BOLLINGER_PERIOD}_{BOLLINGER_STD}"] = sma - BOLLINGER_STD * std

    # ── ATR ──
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["ATR"] = tr.ewm(span=ATR_PERIOD, adjust=False).mean()

    # ── ADX ──
    plus_dm = df["High"].diff()
    minus_dm = -df["Low"].diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    plus_di = 100 * plus_dm.ewm(span=ADX_PERIOD, adjust=False).mean() / df["ATR"]
    minus_di = 100 * minus_dm.ewm(span=ADX_PERIOD, adjust=False).mean() / df["ATR"]
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    df[f"ADX_{ADX_PERIOD}"] = dx.ewm(span=ADX_PERIOD, adjust=False).mean()
    df[f"DMP_{ADX_PERIOD}"] = plus_di
    df[f"DMN_{ADX_PERIOD}"] = minus_di

    # ── MACD ──
    ema_fast = df["Close"].ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    df[f"MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}"] = macd_line
    df[f"MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}"] = signal_line
    df[f"MACDh_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}"] = macd_line - signal_line

    # ── OBV ──
    direction = np.sign(df["Close"].diff())
    df["OBV"] = (df["Volume"] * direction).fillna(0).cumsum()
    df["Volume_SMA_20"] = df["Volume"].rolling(window=20, min_periods=20).mean()

    # ── Rolling VWAP ──
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    volume = df["Volume"].fillna(0)
    tpv = typical_price * volume
    for p in (20, 60):
        vol_sum = volume.rolling(window=p, min_periods=p).sum().replace(0, np.nan)
        vwap = tpv.rolling(window=p, min_periods=p).sum() / vol_sum
        df[f"VWAP_{p}"] = vwap
        df[f"VWAP_DIST_{p}"] = (df["Close"] / vwap - 1) * 100
    df["VWAP_SLOPE_20"] = df["VWAP_20"].pct_change(5) * 100

    indicator_cols = [c for c in df.columns if c not in original_cols]
    if mode == "confirmed":
        df = _stabilize_latest_indicator_row(df, indicator_cols)
    else:
        df["Indicator_Mode"] = "live"
        df["Indicator_AsOf"] = None
        df.attrs["indicator_mode"] = "live"
        df.attrs["indicator_asof"] = (
            df.index[-1].isoformat() if len(df.index) and hasattr(df.index[-1], "isoformat")
            else str(df.index[-1]) if len(df.index) else None
        )

    return df


def _safe_float(value: Any, multiplier: float = 1.0) -> float | None:
    if value in (None, "", "None", "N/A", "-"):
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        parsed = float(value) * multiplier
        if pd.isna(parsed):
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, multiplier: float = 1.0) -> int | None:
    parsed = _safe_float(value, multiplier=multiplier)
    return int(parsed) if parsed is not None else None


def _empty_fundamentals() -> dict[str, Any]:
    return {field: None for field in _FUNDAMENTAL_FIELDS}


def _fundamental_quality(data: dict[str, Any]) -> str:
    present = sum(1 for key in _FUNDAMENTAL_QUALITY_FIELDS if data.get(key) is not None)
    if present >= 5:
        return "full"
    if present >= 2:
        return "partial"
    if any(data.get(key) is not None for key in _FUNDAMENTAL_FIELDS):
        return "sparse"
    return "empty"


def _merge_fundamentals(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key in _FUNDAMENTAL_FIELDS:
        if merged.get(key) is None and incoming.get(key) is not None:
            merged[key] = incoming[key]
    return merged


def _normalize_yfinance_fundamentals(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio"),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": info.get("dividendYield"),
        "eps": info.get("trailingEps"),
        "revenue_growth": info.get("revenueGrowth"),
        "profit_margin": info.get("profitMargins"),
        "debt_to_equity": info.get("debtToEquity"),
        "free_cash_flow": info.get("freeCashflow"),
        "return_on_equity": info.get("returnOnEquity"),
        "beta": info.get("beta"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "avg_volume": info.get("averageVolume"),
        "short_ratio": info.get("shortRatio"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
    }


def _fetch_yfinance_fundamentals(ticker: str) -> dict[str, Any]:
    t = yf.Ticker(ticker)
    info = t.info or {}
    if not info:
        return {}
    return _normalize_yfinance_fundamentals(info)


def _request_json(url: str, params: dict[str, Any], timeout: float = 8.0) -> Any:
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _fetch_finnhub_fundamentals(ticker: str) -> dict[str, Any]:
    token = settings.FINNHUB_API_KEY or os.getenv("FINNHUB_API_KEY", "")
    if not token:
        return {}
    payload = _request_json(
        "https://finnhub.io/api/v1/stock/metric",
        {"symbol": ticker.upper(), "metric": "all", "token": token},
    )
    metric = payload.get("metric") if isinstance(payload, dict) else {}
    if not metric:
        return {}
    return {
        "market_cap": _safe_int(metric.get("marketCapitalization"), 1_000_000),
        "pe_ratio": _safe_float(metric.get("peTTM")),
        "forward_pe": _safe_float(metric.get("forwardPEAnnual")),
        "price_to_book": _safe_float(metric.get("pbAnnual")),
        "dividend_yield": _safe_float(metric.get("dividendYieldIndicatedAnnual"), 0.01),
        "eps": _safe_float(metric.get("epsTTM")),
        "revenue_growth": _safe_float(metric.get("revenueGrowthTTMYoy"), 0.01),
        "profit_margin": _safe_float(metric.get("netProfitMarginTTM"), 0.01),
        "debt_to_equity": _safe_float(metric.get("totalDebt/totalEquityAnnual")),
        "return_on_equity": _safe_float(metric.get("roeTTM"), 0.01),
        "beta": _safe_float(metric.get("beta")),
        "52w_high": _safe_float(metric.get("52WeekHigh")),
        "52w_low": _safe_float(metric.get("52WeekLow")),
        "avg_volume": _safe_int(metric.get("10DayAverageTradingVolume"), 1_000_000),
    }


def _fetch_alphavantage_fundamentals(ticker: str) -> dict[str, Any]:
    api_key = (
        settings.ALPHAVANTAGE_API_KEY
        or os.getenv("ALPHAVANTAGE_API_KEY", "")
        or os.getenv("ALPHA_VANTAGE_API_KEY", "")
    )
    if not api_key:
        return {}
    payload = _request_json(
        "https://www.alphavantage.co/query",
        {"function": "OVERVIEW", "symbol": ticker.upper(), "apikey": api_key},
    )
    if not isinstance(payload, dict) or not payload.get("Symbol"):
        return {}
    return {
        "market_cap": _safe_int(payload.get("MarketCapitalization")),
        "pe_ratio": _safe_float(payload.get("TrailingPE")),
        "forward_pe": _safe_float(payload.get("ForwardPE")),
        "peg_ratio": _safe_float(payload.get("PEGRatio")),
        "price_to_book": _safe_float(payload.get("PriceToBookRatio")),
        "dividend_yield": _safe_float(payload.get("DividendYield")),
        "eps": _safe_float(payload.get("EPS")),
        "revenue_growth": _safe_float(payload.get("QuarterlyRevenueGrowthYOY")),
        "profit_margin": _safe_float(payload.get("ProfitMargin")),
        "return_on_equity": _safe_float(payload.get("ReturnOnEquityTTM")),
        "beta": _safe_float(payload.get("Beta")),
        "52w_high": _safe_float(payload.get("52WeekHigh")),
        "52w_low": _safe_float(payload.get("52WeekLow")),
        "sector": payload.get("Sector"),
        "industry": payload.get("Industry"),
    }


def _fetch_fmp_fundamentals(ticker: str) -> dict[str, Any]:
    api_key = settings.FMP_API_KEY or os.getenv("FMP_API_KEY", "")
    if not api_key:
        return {}

    result: dict[str, Any] = {}
    profile_payload = _request_json(
        f"https://financialmodelingprep.com/api/v3/profile/{ticker.upper()}",
        {"apikey": api_key},
    )
    profile = profile_payload[0] if isinstance(profile_payload, list) and profile_payload else {}
    if isinstance(profile, dict):
        result.update(
            {
                "market_cap": _safe_int(profile.get("mktCap")),
                "dividend_yield": _safe_float(profile.get("lastDiv")),
                "beta": _safe_float(profile.get("beta")),
                "avg_volume": _safe_int(profile.get("volAvg")),
                "sector": profile.get("sector"),
                "industry": profile.get("industry"),
                "current_price": _safe_float(profile.get("price")),
            }
        )

    ratios_payload = _request_json(
        f"https://financialmodelingprep.com/api/v3/ratios-ttm/{ticker.upper()}",
        {"apikey": api_key},
    )
    ratios = ratios_payload[0] if isinstance(ratios_payload, list) and ratios_payload else {}
    if isinstance(ratios, dict):
        result.update(
            {
                "pe_ratio": _safe_float(ratios.get("peRatioTTM")),
                "peg_ratio": _safe_float(ratios.get("pegRatioTTM")),
                "price_to_book": _safe_float(ratios.get("priceToBookRatioTTM")),
                "dividend_yield": result.get("dividend_yield")
                or _safe_float(ratios.get("dividendYielTTM")),
                "profit_margin": _safe_float(ratios.get("netProfitMarginTTM")),
                "return_on_equity": _safe_float(ratios.get("returnOnEquityTTM")),
                "debt_to_equity": _safe_float(ratios.get("debtEquityRatioTTM")),
            }
        )
    return result


def _fetch_naver_fundamentals(ticker: str) -> dict[str, Any]:
    if not _is_korean_ticker(ticker):
        return {}
    code = ticker.upper().split(".")[0]
    response = requests.get(
        f"https://finance.naver.com/item/main.naver?code={code}",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=8,
    )
    response.raise_for_status()
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return {}

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    result: dict[str, Any] = {}

    marker_map = {
        "PER": "pe_ratio",
        "PBR": "price_to_book",
        "EPS": "eps",
        "배당수익률": "dividend_yield",
    }
    parts = text.replace("l", " ").split()
    for idx, token in enumerate(parts):
        key = marker_map.get(token)
        if not key:
            continue
        for candidate in parts[idx + 1: idx + 5]:
            parsed = _safe_float(candidate)
            if parsed is not None:
                result[key] = parsed / 100.0 if key == "dividend_yield" else parsed
                break

    market_sum = soup.select_one("#_market_sum")
    if market_sum:
        unit = market_sum.find_next(string=lambda value: value and "억원" in value)
        market_cap_100m = _safe_float(market_sum.get_text(strip=True))
        if market_cap_100m is not None:
            result["market_cap"] = int(market_cap_100m * 100_000_000)
        elif unit:
            result["market_cap"] = None
    return result


def fetch_fundamentals(ticker: str) -> dict:
    ticker = ticker.upper().strip()
    now = datetime.now(timezone.utc)

    with _fundamental_cache_lock:
        cached = _fundamental_cache.get(ticker)
    if cached is not None and _is_fundamental_cache_fresh(cached):
        result = dict(cached["data"])
        result["_cache_hit"] = True
        return result

    source_fns = [
        ("naver", _fetch_naver_fundamentals),
        ("yfinance", _fetch_yfinance_fundamentals),
        ("finnhub", _fetch_finnhub_fundamentals),
        ("alphavantage", _fetch_alphavantage_fundamentals),
        ("fmp", _fetch_fmp_fundamentals),
    ] if _is_korean_ticker(ticker) else [
        ("yfinance", _fetch_yfinance_fundamentals),
        ("finnhub", _fetch_finnhub_fundamentals),
        ("alphavantage", _fetch_alphavantage_fundamentals),
        ("fmp", _fetch_fmp_fundamentals),
    ]

    merged = _empty_fundamentals()
    attempted: list[str] = []
    used: list[str] = []
    errors: list[str] = []

    for source_name, fetcher in source_fns:
        attempted.append(source_name)
        try:
            data = fetcher(ticker)
            normalized = {field: data.get(field) for field in _FUNDAMENTAL_FIELDS}
            if _fundamental_quality(normalized) == "empty":
                continue
            merged = _merge_fundamentals(merged, normalized)
            used.append(source_name)
            if _fundamental_quality(merged) == "full":
                break
        except Exception as exc:
            errors.append(f"{source_name}: {str(exc)[:160]}")
            logger.warning("[%s] fundamentals failed via %s: %s", ticker, source_name, exc)

    quality = _fundamental_quality(merged)
    result = {
        **merged,
        "_source": "+".join(used) if used else "none",
        "_sources_attempted": attempted,
        "_errors": errors,
        "_fetched_at": now.isoformat(),
        "_cache_hit": False,
        "data_quality": quality,
    }

    with _fundamental_cache_lock:
        _fundamental_cache[ticker] = {"fetched_at": now, "data": dict(result)}
    return result


def fetch_options_pcr(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    try:
        expirations = t.options
        if not expirations:
            return {"put_call_ratio": None, "error": "No options data"}
        nearest_exp = expirations[0]
        chain = t.option_chain(nearest_exp)
        total_call_oi = (
            int(chain.calls["openInterest"].sum())
            if "openInterest" in chain.calls.columns
            else 0
        )
        total_put_oi = (
            int(chain.puts["openInterest"].sum())
            if "openInterest" in chain.puts.columns
            else 0
        )
        pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else None
        total_call_vol = (
            int(chain.calls["volume"].fillna(0).sum())
            if "volume" in chain.calls.columns
            else 0
        )
        total_put_vol = (
            int(chain.puts["volume"].fillna(0).sum())
            if "volume" in chain.puts.columns
            else 0
        )
        pcr_vol = (
            round(total_put_vol / total_call_vol, 3) if total_call_vol > 0 else None
        )
        return {
            "expiration": nearest_exp,
            "call_oi": total_call_oi,
            "put_oi": total_put_oi,
            "put_call_ratio_oi": pcr,
            "call_volume": total_call_vol,
            "put_volume": total_put_vol,
            "put_call_ratio_vol": pcr_vol,
        }
    except Exception as e:
        return {"put_call_ratio": None, "error": str(e)}


def fetch_insider_trades(ticker: str) -> list:
    t = yf.Ticker(ticker)
    try:
        insiders = t.insider_transactions
        if insiders is None or insiders.empty:
            return []
        recent = insiders.head(10)
        trades = []
        for _, row in recent.iterrows():
            trades.append(
                {
                    "date": str(row.get("Start Date", "")),
                    "insider": str(row.get("Insider", "")),
                    "relation": str(row.get("Relationship", "")),
                    "transaction": str(row.get("Transaction", "")),
                    "shares": row.get("Shares", 0),
                    "value": row.get("Value", 0),
                }
            )
        return trades
    except Exception:
        return []
