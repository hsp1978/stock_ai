"""
데이터 수집 모듈 (경량화 - Mac Studio용)
yfinance 기반 OHLCV 수집 + 기술 지표 계산
"""
import pandas as pd
import numpy as np
import yfinance as yf
from config import (
    DEFAULT_HISTORY_PERIOD, SMA_PERIODS, EMA_PERIODS,
    RSI_PERIOD, BOLLINGER_PERIOD, BOLLINGER_STD,
    ADX_PERIOD, ATR_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL
)


def fetch_ohlcv(ticker: str, period: str = DEFAULT_HISTORY_PERIOD) -> pd.DataFrame:
    """OHLCV 데이터 수집"""
    t = yf.Ticker(ticker)
    df = t.history(period=period)
    if df.empty:
        raise ValueError(f"{ticker}: 데이터 없음")
    return df


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """기술 지표 일괄 계산"""
    df = df.copy()

    # ── SMA / EMA ──
    for p in SMA_PERIODS:
        df[f'SMA_{p}'] = df['Close'].rolling(window=p, min_periods=p).mean()
    for p in EMA_PERIODS:
        df[f'EMA_{p}'] = df['Close'].ewm(span=p, adjust=False).mean()

    # ── RSI ──
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # ── Bollinger Bands ──
    sma = df['Close'].rolling(window=BOLLINGER_PERIOD).mean()
    std = df['Close'].rolling(window=BOLLINGER_PERIOD).std()
    df[f'BBU_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'] = sma + BOLLINGER_STD * std
    df[f'BBM_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'] = sma
    df[f'BBL_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'] = sma - BOLLINGER_STD * std

    # ── ATR ──
    prev_close = df['Close'].shift(1)
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - prev_close).abs(),
        (df['Low'] - prev_close).abs()
    ], axis=1).max(axis=1)
    df['ATR'] = tr.ewm(span=ATR_PERIOD, adjust=False).mean()

    # ── ADX ──
    plus_dm = df['High'].diff()
    minus_dm = -df['Low'].diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    plus_di = 100 * plus_dm.ewm(span=ADX_PERIOD, adjust=False).mean() / df['ATR']
    minus_di = 100 * minus_dm.ewm(span=ADX_PERIOD, adjust=False).mean() / df['ATR']
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    df[f'ADX_{ADX_PERIOD}'] = dx.ewm(span=ADX_PERIOD, adjust=False).mean()
    df[f'DMP_{ADX_PERIOD}'] = plus_di
    df[f'DMN_{ADX_PERIOD}'] = minus_di

    # ── MACD ──
    ema_fast = df['Close'].ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=MACD_SIGNAL, adjust=False).mean()
    df[f'MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'] = macd_line
    df[f'MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'] = signal_line
    df[f'MACDh_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'] = macd_line - signal_line

    # ── OBV ──
    direction = np.sign(df['Close'].diff())
    df['OBV'] = (df['Volume'] * direction).fillna(0).cumsum()
    df['Volume_SMA_20'] = df['Volume'].rolling(window=20, min_periods=20).mean()

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
        total_call_oi = int(chain.calls['openInterest'].sum()) if 'openInterest' in chain.calls.columns else 0
        total_put_oi = int(chain.puts['openInterest'].sum()) if 'openInterest' in chain.puts.columns else 0
        pcr = round(total_put_oi / total_call_oi, 3) if total_call_oi > 0 else None
        total_call_vol = int(chain.calls['volume'].fillna(0).sum()) if 'volume' in chain.calls.columns else 0
        total_put_vol = int(chain.puts['volume'].fillna(0).sum()) if 'volume' in chain.puts.columns else 0
        pcr_vol = round(total_put_vol / total_call_vol, 3) if total_call_vol > 0 else None
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
            trades.append({
                "date": str(row.get("Start Date", "")),
                "insider": str(row.get("Insider", "")),
                "relation": str(row.get("Relationship", "")),
                "transaction": str(row.get("Transaction", "")),
                "shares": row.get("Shares", 0),
                "value": row.get("Value", 0),
            })
        return trades
    except Exception:
        return []
