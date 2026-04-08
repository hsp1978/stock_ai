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
