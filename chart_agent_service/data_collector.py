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
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd
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
    if _is_korean_ticker(ticker):
        sources: list = [PykrxSource(), FdrSource(), YFinanceSource()]
    else:
        sources = [YFinanceSource(), FdrSource()]

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
    1. 배치 프리페치 레거시 캐시 (prefetch_ohlcv_batch 호출 시)
    2. TTL-aware CacheEntry → 다중 소스 fallback
    """
    key = (ticker.upper(), period)

    # 1. 배치 캐시 (구형, 스캔 시 프리페치로 채워짐)
    with _ohlcv_cache_lock:
        legacy = _ohlcv_cache.get(key)
    if legacy is not None and not legacy.empty:
        return legacy.copy()

    # 2. TTL 캐시 + 다중 소스 fallback
    entry = fetch_ohlcv_with_meta(ticker, period)
    return entry.data.copy()


def prefetch_ohlcv_batch(tickers: list, period: str = DEFAULT_HISTORY_PERIOD) -> None:
    """
    전 종목 OHLCV를 yfinance 배치 다운로드로 한 번에 수집해 캐시.

    순차 스캔에서 종목당 5~10초 절약 가능.
    스캔 시작 직전에 호출.
    """
    if not tickers:
        return
    try:
        logger.info("[배치] %d개 종목 데이터 사전 다운로드 중...", len(tickers))
        raw = yf.download(
            tickers,
            period=period,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if raw.empty:
            return

        if isinstance(raw.columns, pd.MultiIndex):
            for t in tickers:
                t_up = t.upper()
                try:
                    df_t = raw.xs(t, level=1, axis=1).copy()
                    if not df_t.empty:
                        with _ohlcv_cache_lock:
                            _ohlcv_cache[(t_up, period)] = df_t
                except KeyError:
                    pass
        else:
            t_up = tickers[0].upper()
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


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """기술 지표 일괄 계산"""
    df = df.copy()

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

    return df


def fetch_fundamentals(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    info = t.info or {}
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
        "beta": info.get("beta"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "avg_volume": info.get("averageVolume"),
        "short_ratio": info.get("shortRatio"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
    }


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
