"""
기술 지표 계산 모듈
pandas-ta 의존성 제거 → numpy/pandas 직접 구현
원본 보고서의 지표 + 보완 지표 포함
"""
import pandas as pd
import numpy as np
from config.settings import (
    SMA_PERIODS, EMA_PERIODS, RSI_PERIOD, BOLLINGER_PERIOD, BOLLINGER_STD,
    ADX_PERIOD, ATR_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    STOCHASTIC_K, STOCHASTIC_D, STOCHASTIC_SMOOTH,
    ICHIMOKU_TENKAN, ICHIMOKU_KIJUN, ICHIMOKU_SENKOU_B,
    WILLIAMS_R_PERIOD, CMF_PERIOD,
)


class TechnicalIndicators:
    """기술 지표 계산 및 해석 (자체 구현)"""

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()

    def calculate_all(self) -> pd.DataFrame:
        """모든 기술 지표 계산"""
        self._add_trend_indicators()
        self._add_momentum_indicators()
        self._add_volatility_indicators()
        self._add_volume_indicators()
        self._add_extra_indicators()
        return self.df

    # ── 기본 계산 함수 ───────────────────────────────────────

    @staticmethod
    def _sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period, min_periods=period).mean()

    @staticmethod
    def _ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _rsi(series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()

    # ── 추세 지표 ────────────────────────────────────────────

    def _add_trend_indicators(self):
        for p in SMA_PERIODS:
            self.df[f'SMA_{p}'] = self._sma(self.df['Close'], p)
        for p in EMA_PERIODS:
            self.df[f'EMA_{p}'] = self._ema(self.df['Close'], p)

        # ADX
        self._calculate_adx()

        # MACD
        ema_fast = self._ema(self.df['Close'], MACD_FAST)
        ema_slow = self._ema(self.df['Close'], MACD_SLOW)
        macd_line = ema_fast - ema_slow
        signal_line = self._ema(macd_line, MACD_SIGNAL)
        histogram = macd_line - signal_line
        self.df[f'MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'] = macd_line
        self.df[f'MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'] = signal_line
        self.df[f'MACDh_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'] = histogram

    def _calculate_adx(self):
        high, low, close = self.df['High'], self.df['Low'], self.df['Close']
        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        atr = self._atr(high, low, close, ADX_PERIOD)

        plus_di = 100 * self._ema(plus_dm, ADX_PERIOD) / atr
        minus_di = 100 * self._ema(minus_dm, ADX_PERIOD) / atr

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        adx = self._ema(dx, ADX_PERIOD)

        self.df[f'ADX_{ADX_PERIOD}'] = adx
        self.df[f'DMP_{ADX_PERIOD}'] = plus_di
        self.df[f'DMN_{ADX_PERIOD}'] = minus_di

    # ── 모멘텀 지표 ──────────────────────────────────────────

    def _add_momentum_indicators(self):
        self.df['RSI'] = self._rsi(self.df['Close'], RSI_PERIOD)

    # ── 변동성 지표 ──────────────────────────────────────────

    def _add_volatility_indicators(self):
        sma = self._sma(self.df['Close'], BOLLINGER_PERIOD)
        std = self.df['Close'].rolling(window=BOLLINGER_PERIOD).std()
        self.df[f'BBU_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'] = sma + BOLLINGER_STD * std
        self.df[f'BBM_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'] = sma
        self.df[f'BBL_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'] = sma - BOLLINGER_STD * std

        self.df['ATR'] = self._atr(self.df['High'], self.df['Low'], self.df['Close'], ATR_PERIOD)

    # ── 거래량 지표 ──────────────────────────────────────────

    def _add_volume_indicators(self):
        # OBV
        direction = np.sign(self.df['Close'].diff())
        self.df['OBV'] = (self.df['Volume'] * direction).fillna(0).cumsum()

        self.df['Volume_SMA_20'] = self._sma(self.df['Volume'], 20)

    # ── 추가 지표 (Stochastic, Ichimoku, Williams %R, CMF) ──

    def _add_extra_indicators(self):
        """확장 기술 지표 계산"""
        self._calculate_stochastic()
        self._calculate_ichimoku()
        self._calculate_williams_r()
        self._calculate_cmf()

    def _calculate_stochastic(self):
        """Stochastic Oscillator (%K, %D)"""
        high, low, close = self.df['High'], self.df['Low'], self.df['Close']
        lowest_low = low.rolling(window=STOCHASTIC_K, min_periods=STOCHASTIC_K).min()
        highest_high = high.rolling(window=STOCHASTIC_K, min_periods=STOCHASTIC_K).max()
        denom = highest_high - lowest_low
        denom = denom.replace(0, np.nan)

        fast_k = 100 * (close - lowest_low) / denom
        # Slow %K = Fast %K를 STOCHASTIC_SMOOTH 기간으로 평활
        slow_k = fast_k.rolling(window=STOCHASTIC_SMOOTH, min_periods=1).mean()
        slow_d = slow_k.rolling(window=STOCHASTIC_D, min_periods=1).mean()

        self.df['STOCH_K'] = slow_k
        self.df['STOCH_D'] = slow_d

    def _calculate_ichimoku(self):
        """Ichimoku Cloud (일목균형표)"""
        high, low, close = self.df['High'], self.df['Low'], self.df['Close']

        # 전환선 (Tenkan-sen): (최고+최저)/2 over tenkan 기간
        tenkan_high = high.rolling(window=ICHIMOKU_TENKAN, min_periods=ICHIMOKU_TENKAN).max()
        tenkan_low = low.rolling(window=ICHIMOKU_TENKAN, min_periods=ICHIMOKU_TENKAN).min()
        self.df['ICHI_TENKAN'] = (tenkan_high + tenkan_low) / 2

        # 기준선 (Kijun-sen)
        kijun_high = high.rolling(window=ICHIMOKU_KIJUN, min_periods=ICHIMOKU_KIJUN).max()
        kijun_low = low.rolling(window=ICHIMOKU_KIJUN, min_periods=ICHIMOKU_KIJUN).min()
        self.df['ICHI_KIJUN'] = (kijun_high + kijun_low) / 2

        # 선행스팬 A (Senkou Span A): (전환선+기준선)/2 를 kijun 기간 앞으로 이동
        self.df['ICHI_SENKOU_A'] = ((self.df['ICHI_TENKAN'] + self.df['ICHI_KIJUN']) / 2).shift(ICHIMOKU_KIJUN)

        # 선행스팬 B (Senkou Span B): (최고+최저)/2 over senkou_b 기간을 kijun 앞으로 이동
        senkou_high = high.rolling(window=ICHIMOKU_SENKOU_B, min_periods=ICHIMOKU_SENKOU_B).max()
        senkou_low = low.rolling(window=ICHIMOKU_SENKOU_B, min_periods=ICHIMOKU_SENKOU_B).min()
        self.df['ICHI_SENKOU_B'] = ((senkou_high + senkou_low) / 2).shift(ICHIMOKU_KIJUN)

        # 후행스팬 (Chikou Span): 종가를 kijun 기간 뒤로 이동
        self.df['ICHI_CHIKOU'] = close.shift(-ICHIMOKU_KIJUN)

    def _calculate_williams_r(self):
        """Williams %R"""
        high, low, close = self.df['High'], self.df['Low'], self.df['Close']
        highest_high = high.rolling(window=WILLIAMS_R_PERIOD, min_periods=WILLIAMS_R_PERIOD).max()
        lowest_low = low.rolling(window=WILLIAMS_R_PERIOD, min_periods=WILLIAMS_R_PERIOD).min()
        denom = highest_high - lowest_low
        denom = denom.replace(0, np.nan)
        self.df['WILLIAMS_R'] = -100 * (highest_high - close) / denom

    def _calculate_cmf(self):
        """Chaikin Money Flow (CMF)"""
        high, low, close, volume = self.df['High'], self.df['Low'], self.df['Close'], self.df['Volume']
        denom = high - low
        denom = denom.replace(0, np.nan)
        mf_multiplier = ((close - low) - (high - close)) / denom
        mf_volume = mf_multiplier * volume

        vol_sum = volume.rolling(window=CMF_PERIOD, min_periods=CMF_PERIOD).sum()
        vol_sum = vol_sum.replace(0, np.nan)
        self.df['CMF'] = mf_volume.rolling(window=CMF_PERIOD, min_periods=CMF_PERIOD).sum() / vol_sum

    # ── 현재 상태 요약 ───────────────────────────────────────

    def get_latest_summary(self) -> dict:
        """최신 지표 값 요약 (AI 입력용)"""
        latest = self.df.iloc[-1]
        prev = self.df.iloc[-2] if len(self.df) > 1 else latest

        vol_sma = latest.get('Volume_SMA_20', 0)
        summary = {
            "price": {
                "close": round(float(latest['Close']), 2),
                "change_pct": round(float((latest['Close'] / prev['Close'] - 1) * 100), 2),
                "volume": int(latest['Volume']),
                "volume_vs_avg": round(float(latest['Volume'] / vol_sma), 2) if vol_sma and vol_sma > 0 else 1.0,
            },
            "trend": {},
            "momentum": {},
            "volatility": {},
        }

        # 추세
        for p in SMA_PERIODS:
            col = f'SMA_{p}'
            if col in latest.index and not pd.isna(latest[col]):
                summary["trend"][col] = round(float(latest[col]), 2)
                summary["trend"][f"price_vs_{col}"] = "above" if latest['Close'] > latest[col] else "below"

        adx_col = f'ADX_{ADX_PERIOD}'
        if adx_col in latest.index and not pd.isna(latest[adx_col]):
            adx_val = float(latest[adx_col])
            summary["trend"]["ADX"] = round(adx_val, 2)
            if adx_val > 40:
                summary["trend"]["trend_strength"] = "very_strong"
            elif adx_val > 25:
                summary["trend"]["trend_strength"] = "strong"
            elif adx_val > 20:
                summary["trend"]["trend_strength"] = "weak"
            else:
                summary["trend"]["trend_strength"] = "no_trend"

        macd_col = f'MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        macd_sig = f'MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        macd_hist = f'MACDh_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        if macd_col in latest.index and not pd.isna(latest[macd_col]):
            summary["trend"]["MACD"] = round(float(latest[macd_col]), 4)
            summary["trend"]["MACD_signal"] = round(float(latest.get(macd_sig, 0)), 4)
            summary["trend"]["MACD_histogram"] = round(float(latest.get(macd_hist, 0)), 4)

        # 모멘텀
        if 'RSI' in latest.index and not pd.isna(latest['RSI']):
            rsi = float(latest['RSI'])
            summary["momentum"]["RSI"] = round(rsi, 2)
            if rsi > 70:
                summary["momentum"]["RSI_signal"] = "overbought"
            elif rsi < 30:
                summary["momentum"]["RSI_signal"] = "oversold"
            else:
                summary["momentum"]["RSI_signal"] = "neutral"

        # 변동성
        if 'ATR' in latest.index and not pd.isna(latest['ATR']):
            atr_val = float(latest['ATR'])
            summary["volatility"]["ATR"] = round(atr_val, 2)
            summary["volatility"]["ATR_pct"] = round(atr_val / float(latest['Close']) * 100, 2)

        bbu = f'BBU_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'
        bbl = f'BBL_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'
        if bbu in latest.index and not pd.isna(latest[bbu]):
            summary["volatility"]["BB_upper"] = round(float(latest[bbu]), 2)
            summary["volatility"]["BB_lower"] = round(float(latest[bbl]), 2)
            bb_width = float((latest[bbu] - latest[bbl]) / latest['Close'] * 100)
            summary["volatility"]["BB_width_pct"] = round(bb_width, 2)
            if latest['Close'] > latest[bbu]:
                summary["volatility"]["BB_position"] = "above_upper"
            elif latest['Close'] < latest[bbl]:
                summary["volatility"]["BB_position"] = "below_lower"
            else:
                summary["volatility"]["BB_position"] = "inside"

        return summary
