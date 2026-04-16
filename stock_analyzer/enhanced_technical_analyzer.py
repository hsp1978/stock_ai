#!/usr/bin/env python3
"""
Enhanced Technical Analysis Module
- Indicator conflict resolution
- Volume-price divergence detection
- Support/Resistance analysis
- Event risk integration
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import yfinance as yf
from dataclasses import dataclass
from enum import Enum


class SignalType(Enum):
    """Signal classification"""
    TREND_FOLLOWING = "trend"      # MA, RSI, ADX, Momentum
    MEAN_REVERSION = "reversion"   # Fibonacci, Support/Resistance, Bollinger
    VOLUME_BASED = "volume"         # Volume Profile, OBV
    VOLATILITY = "volatility"       # Bollinger Bands, ATR


@dataclass
class TechnicalSignal:
    """Individual technical signal"""
    indicator: str
    signal: str  # 'BUY', 'SELL', 'NEUTRAL'
    strength: float  # 0-1
    signal_type: SignalType
    reasoning: str
    price_level: Optional[float] = None


@dataclass
class MarketContext:
    """Market context for analysis"""
    trend: str  # 'UPTREND', 'DOWNTREND', 'SIDEWAYS'
    volatility: str  # 'HIGH', 'MEDIUM', 'LOW'
    volume_trend: str  # 'INCREASING', 'DECREASING', 'STABLE'
    upcoming_events: List[Dict]
    support_levels: List[float]
    resistance_levels: List[float]


class EnhancedTechnicalAnalyzer:
    """Advanced technical analysis with conflict resolution"""

    def __init__(self):
        self.weights = {
            # Trend following has higher weight in trending markets
            SignalType.TREND_FOLLOWING: 1.5,
            SignalType.MEAN_REVERSION: 1.0,
            SignalType.VOLUME_BASED: 1.3,
            SignalType.VOLATILITY: 0.8
        }

    def analyze(self, ticker: str, period: str = "3mo") -> Dict:
        """
        Complete technical analysis with conflict resolution

        Returns:
            {
                'recommendation': 'BUY/SELL/HOLD',
                'confidence': 0-10,
                'signals': [...],
                'context': MarketContext,
                'conflicts': [...],
                'risk_factors': [...]
            }
        """
        # Fetch data
        df = self._fetch_data(ticker, period)
        if df is None or df.empty:
            return self._error_response("Failed to fetch data")

        # Calculate all indicators
        signals = self._calculate_all_indicators(df)

        # Analyze market context
        context = self._analyze_context(df, ticker)

        # Detect conflicts
        conflicts = self._detect_conflicts(signals)

        # Resolve conflicts with context-aware weighting
        recommendation, confidence = self._resolve_conflicts(
            signals, context, conflicts
        )

        # Check risk factors
        risk_factors = self._assess_risks(context, df)

        return {
            'ticker': ticker,
            'recommendation': recommendation,
            'confidence': round(confidence, 1),
            'signals': [self._signal_to_dict(s) for s in signals],
            'context': self._context_to_dict(context),
            'conflicts': conflicts,
            'risk_factors': risk_factors,
            'analysis_time': datetime.now().isoformat()
        }

    def _fetch_data(self, ticker: str, period: str) -> Optional[pd.DataFrame]:
        """Fetch stock data"""
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period)

            # Add volume moving average
            df['Volume_MA'] = df['Volume'].rolling(window=20).mean()

            # Add price rate of change
            df['ROC'] = df['Close'].pct_change(periods=10) * 100

            return df
        except Exception as e:
            print(f"Error fetching data: {e}")
            return None

    def _calculate_all_indicators(self, df: pd.DataFrame) -> List[TechnicalSignal]:
        """Calculate all technical indicators"""
        signals = []

        # Moving Averages (Trend Following)
        signals.append(self._calculate_ma_signal(df))

        # RSI (Trend Following)
        signals.append(self._calculate_rsi_signal(df))

        # MACD (Trend Following)
        signals.append(self._calculate_macd_signal(df))

        # Volume Analysis (Volume Based)
        signals.append(self._calculate_volume_signal(df))

        # Bollinger Bands (Mean Reversion/Volatility)
        signals.append(self._calculate_bollinger_signal(df))

        # Support/Resistance (Mean Reversion)
        signals.append(self._calculate_support_resistance_signal(df))

        # Fibonacci (Mean Reversion)
        signals.append(self._calculate_fibonacci_signal(df))

        # ADX (Trend Strength)
        signals.append(self._calculate_adx_signal(df))

        return [s for s in signals if s is not None]

    def _calculate_ma_signal(self, df: pd.DataFrame) -> Optional[TechnicalSignal]:
        """Moving Average analysis"""
        try:
            df['MA_50'] = df['Close'].rolling(window=50).mean()
            df['MA_200'] = df['Close'].rolling(window=200).mean()

            current_price = df['Close'].iloc[-1]
            ma_50 = df['MA_50'].iloc[-1]
            ma_200 = df['MA_200'].iloc[-1]

            # Skip if not enough data
            if pd.isna(ma_200):
                return None

            # Golden/Death cross
            if ma_50 > ma_200 and current_price > ma_50:
                signal = 'BUY'
                strength = min(1.0, (current_price - ma_200) / ma_200 * 10)
                reasoning = f"Golden cross: Price ${current_price:.2f} above MA50 ${ma_50:.2f} and MA200 ${ma_200:.2f}"
            elif ma_50 < ma_200 and current_price < ma_50:
                signal = 'SELL'
                strength = min(1.0, (ma_200 - current_price) / ma_200 * 10)
                reasoning = f"Death cross: Price ${current_price:.2f} below MA50 ${ma_50:.2f} and MA200 ${ma_200:.2f}"
            else:
                signal = 'NEUTRAL'
                strength = 0.5
                reasoning = "Mixed MA signals"

            return TechnicalSignal(
                indicator="Moving Averages",
                signal=signal,
                strength=abs(strength),
                signal_type=SignalType.TREND_FOLLOWING,
                reasoning=reasoning
            )
        except Exception as e:
            print(f"MA calculation error: {e}")
            return None

    def _calculate_rsi_signal(self, df: pd.DataFrame) -> Optional[TechnicalSignal]:
        """RSI calculation with divergence detection"""
        try:
            # Calculate RSI
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['RSI'] = 100 - (100 / (1 + rs))

            rsi = df['RSI'].iloc[-1]
            rsi_prev = df['RSI'].iloc[-5:-1].mean()

            # Check for divergence
            price_trend = (df['Close'].iloc[-1] - df['Close'].iloc[-5]) / df['Close'].iloc[-5]
            rsi_trend = (rsi - rsi_prev) / rsi_prev if rsi_prev != 0 else 0

            divergence = False
            if abs(price_trend) > 0.02 and abs(rsi_trend) > 0.05:
                if price_trend > 0 and rsi_trend < 0:
                    divergence = True  # Bearish divergence
                elif price_trend < 0 and rsi_trend > 0:
                    divergence = True  # Bullish divergence

            if rsi < 30:
                signal = 'BUY'
                strength = (30 - rsi) / 30
                reasoning = f"RSI oversold at {rsi:.1f}"
            elif rsi > 70:
                signal = 'SELL'
                strength = (rsi - 70) / 30
                reasoning = f"RSI overbought at {rsi:.1f}"
            elif divergence:
                signal = 'SELL' if price_trend > 0 else 'BUY'
                strength = 0.7
                reasoning = f"RSI divergence detected: {'Bearish' if price_trend > 0 else 'Bullish'}"
            else:
                signal = 'NEUTRAL'
                strength = 0.5
                reasoning = f"RSI neutral at {rsi:.1f}"

            return TechnicalSignal(
                indicator="RSI",
                signal=signal,
                strength=min(1.0, abs(strength)),
                signal_type=SignalType.TREND_FOLLOWING,
                reasoning=reasoning
            )
        except Exception as e:
            print(f"RSI calculation error: {e}")
            return None

    def _calculate_volume_signal(self, df: pd.DataFrame) -> Optional[TechnicalSignal]:
        """Volume analysis with price correlation"""
        try:
            current_volume = df['Volume'].iloc[-1]
            avg_volume = df['Volume'].rolling(window=20).mean().iloc[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

            # Check volume-price correlation
            price_change = (df['Close'].iloc[-1] - df['Close'].iloc[-2]) / df['Close'].iloc[-2]

            # Volume divergence detection
            recent_price_trend = (df['Close'].iloc[-1] - df['Close'].iloc[-5]) / df['Close'].iloc[-5]
            recent_volume_trend = (df['Volume'].iloc[-5:].mean() - df['Volume'].iloc[-10:-5].mean()) / df['Volume'].iloc[-10:-5].mean()

            if volume_ratio > 1.5 and price_change > 0:
                signal = 'BUY'
                strength = min(1.0, volume_ratio / 2)
                reasoning = f"Strong volume {volume_ratio:.2f}x average with price rise"
            elif volume_ratio > 1.5 and price_change < 0:
                signal = 'SELL'
                strength = min(1.0, volume_ratio / 2)
                reasoning = f"High volume {volume_ratio:.2f}x average with price drop"
            elif volume_ratio < 0.5:
                signal = 'NEUTRAL'
                strength = 0.3
                reasoning = f"Low volume {volume_ratio:.2f}x average - weak conviction"
            elif recent_price_trend > 0 and recent_volume_trend < -0.2:
                signal = 'SELL'
                strength = 0.6
                reasoning = "Volume-price divergence: Rising price on declining volume"
            else:
                signal = 'NEUTRAL'
                strength = 0.5
                reasoning = f"Normal volume at {volume_ratio:.2f}x average"

            return TechnicalSignal(
                indicator="Volume Profile",
                signal=signal,
                strength=strength,
                signal_type=SignalType.VOLUME_BASED,
                reasoning=reasoning
            )
        except Exception as e:
            print(f"Volume calculation error: {e}")
            return None

    def _calculate_support_resistance_signal(self, df: pd.DataFrame) -> Optional[TechnicalSignal]:
        """Support and Resistance levels"""
        try:
            current_price = df['Close'].iloc[-1]

            # Find recent highs and lows
            recent_high = df['High'].rolling(window=20).max().iloc[-1]
            recent_low = df['Low'].rolling(window=20).min().iloc[-1]

            # Calculate pivot points
            pivot = (recent_high + recent_low + df['Close'].iloc[-1]) / 3
            r1 = 2 * pivot - recent_low
            s1 = 2 * pivot - recent_high

            # Distance from support/resistance
            dist_to_support = (current_price - s1) / current_price
            dist_to_resistance = (r1 - current_price) / current_price

            if dist_to_support < 0.02:  # Within 2% of support
                signal = 'BUY'
                strength = 0.7
                reasoning = f"Near support at ${s1:.2f} (current: ${current_price:.2f})"
                price_level = s1
            elif dist_to_resistance < 0.02:  # Within 2% of resistance
                signal = 'SELL'
                strength = 0.7
                reasoning = f"Near resistance at ${r1:.2f} (current: ${current_price:.2f})"
                price_level = r1
            else:
                signal = 'NEUTRAL'
                strength = 0.5
                reasoning = f"Between S1 ${s1:.2f} and R1 ${r1:.2f}"
                price_level = pivot

            return TechnicalSignal(
                indicator="Support/Resistance",
                signal=signal,
                strength=strength,
                signal_type=SignalType.MEAN_REVERSION,
                reasoning=reasoning,
                price_level=price_level
            )
        except Exception as e:
            print(f"S/R calculation error: {e}")
            return None

    def _calculate_macd_signal(self, df: pd.DataFrame) -> Optional[TechnicalSignal]:
        """MACD calculation"""
        try:
            df['EMA_12'] = df['Close'].ewm(span=12, adjust=False).mean()
            df['EMA_26'] = df['Close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = df['EMA_12'] - df['EMA_26']
            df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
            df['MACD_Histogram'] = df['MACD'] - df['Signal_Line']

            macd = df['MACD'].iloc[-1]
            signal_line = df['Signal_Line'].iloc[-1]
            histogram = df['MACD_Histogram'].iloc[-1]
            prev_histogram = df['MACD_Histogram'].iloc[-2]

            # Check for crossover
            if macd > signal_line and histogram > 0 and prev_histogram <= 0:
                signal = 'BUY'
                strength = 0.8
                reasoning = "MACD bullish crossover"
            elif macd < signal_line and histogram < 0 and prev_histogram >= 0:
                signal = 'SELL'
                strength = 0.8
                reasoning = "MACD bearish crossover"
            elif histogram > 0 and histogram > prev_histogram:
                signal = 'BUY'
                strength = 0.6
                reasoning = "MACD momentum increasing"
            elif histogram < 0 and histogram < prev_histogram:
                signal = 'SELL'
                strength = 0.6
                reasoning = "MACD momentum decreasing"
            else:
                signal = 'NEUTRAL'
                strength = 0.5
                reasoning = "MACD neutral"

            return TechnicalSignal(
                indicator="MACD",
                signal=signal,
                strength=strength,
                signal_type=SignalType.TREND_FOLLOWING,
                reasoning=reasoning
            )
        except Exception as e:
            print(f"MACD calculation error: {e}")
            return None

    def _calculate_bollinger_signal(self, df: pd.DataFrame) -> Optional[TechnicalSignal]:
        """Bollinger Bands with squeeze detection"""
        try:
            df['BB_Middle'] = df['Close'].rolling(window=20).mean()
            df['BB_Std'] = df['Close'].rolling(window=20).std()
            df['BB_Upper'] = df['BB_Middle'] + (df['BB_Std'] * 2)
            df['BB_Lower'] = df['BB_Middle'] - (df['BB_Std'] * 2)

            current_price = df['Close'].iloc[-1]
            upper_band = df['BB_Upper'].iloc[-1]
            lower_band = df['BB_Lower'].iloc[-1]
            middle_band = df['BB_Middle'].iloc[-1]

            # Calculate bandwidth for squeeze detection
            bandwidth = (upper_band - lower_band) / middle_band
            avg_bandwidth = ((df['BB_Upper'] - df['BB_Lower']) / df['BB_Middle']).rolling(window=50).mean().iloc[-1]

            # Position within bands
            position = (current_price - lower_band) / (upper_band - lower_band) if upper_band != lower_band else 0.5

            if bandwidth < avg_bandwidth * 0.7:
                signal = 'NEUTRAL'
                strength = 0.8
                reasoning = f"Bollinger Squeeze detected - breakout pending (bandwidth: {bandwidth:.3f})"
            elif position < 0.2:
                signal = 'BUY'
                strength = 0.7
                reasoning = f"Near lower Bollinger Band at ${lower_band:.2f}"
            elif position > 0.8:
                signal = 'SELL'
                strength = 0.7
                reasoning = f"Near upper Bollinger Band at ${upper_band:.2f}"
            else:
                signal = 'NEUTRAL'
                strength = 0.5
                reasoning = f"Within Bollinger Bands (position: {position:.2f})"

            return TechnicalSignal(
                indicator="Bollinger Bands",
                signal=signal,
                strength=strength,
                signal_type=SignalType.VOLATILITY,
                reasoning=reasoning
            )
        except Exception as e:
            print(f"Bollinger calculation error: {e}")
            return None

    def _calculate_fibonacci_signal(self, df: pd.DataFrame) -> Optional[TechnicalSignal]:
        """Fibonacci retracement levels"""
        try:
            # Find recent high and low
            recent_period = 50
            recent_high = df['High'].iloc[-recent_period:].max()
            recent_low = df['Low'].iloc[-recent_period:].min()

            # Calculate Fibonacci levels
            diff = recent_high - recent_low
            fib_levels = {
                '0.0%': recent_high,
                '23.6%': recent_high - diff * 0.236,
                '38.2%': recent_high - diff * 0.382,
                '50.0%': recent_high - diff * 0.500,
                '61.8%': recent_high - diff * 0.618,
                '100.0%': recent_low
            }

            current_price = df['Close'].iloc[-1]

            # Find nearest Fibonacci level
            nearest_level = None
            nearest_distance = float('inf')
            for level_name, level_price in fib_levels.items():
                distance = abs(current_price - level_price) / current_price
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest_level = (level_name, level_price)

            if nearest_distance < 0.02:  # Within 2% of a Fib level
                if nearest_level[0] in ['61.8%', '100.0%']:
                    signal = 'BUY'
                    strength = 0.7
                    reasoning = f"At Fibonacci support {nearest_level[0]} (${nearest_level[1]:.2f})"
                elif nearest_level[0] in ['0.0%', '23.6%']:
                    signal = 'SELL'
                    strength = 0.7
                    reasoning = f"At Fibonacci resistance {nearest_level[0]} (${nearest_level[1]:.2f})"
                else:
                    signal = 'NEUTRAL'
                    strength = 0.5
                    reasoning = f"At Fibonacci level {nearest_level[0]} (${nearest_level[1]:.2f})"
            else:
                signal = 'NEUTRAL'
                strength = 0.4
                reasoning = "Not near significant Fibonacci level"

            return TechnicalSignal(
                indicator="Fibonacci",
                signal=signal,
                strength=strength,
                signal_type=SignalType.MEAN_REVERSION,
                reasoning=reasoning,
                price_level=nearest_level[1] if nearest_level else None
            )
        except Exception as e:
            print(f"Fibonacci calculation error: {e}")
            return None

    def _calculate_adx_signal(self, df: pd.DataFrame) -> Optional[TechnicalSignal]:
        """ADX trend strength indicator"""
        try:
            # Calculate True Range
            df['H-L'] = df['High'] - df['Low']
            df['H-PC'] = abs(df['High'] - df['Close'].shift(1))
            df['L-PC'] = abs(df['Low'] - df['Close'].shift(1))
            df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)

            # Calculate directional movement
            df['DMplus'] = np.where((df['High'] - df['High'].shift(1)) > (df['Low'].shift(1) - df['Low']),
                                    np.maximum(df['High'] - df['High'].shift(1), 0), 0)
            df['DMminus'] = np.where((df['Low'].shift(1) - df['Low']) > (df['High'] - df['High'].shift(1)),
                                     np.maximum(df['Low'].shift(1) - df['Low'], 0), 0)

            # Smooth the indicators
            period = 14
            df['TR_smooth'] = df['TR'].rolling(window=period).mean()
            df['DMplus_smooth'] = df['DMplus'].rolling(window=period).mean()
            df['DMminus_smooth'] = df['DMminus'].rolling(window=period).mean()

            # Calculate DI
            df['DIplus'] = 100 * (df['DMplus_smooth'] / df['TR_smooth'])
            df['DIminus'] = 100 * (df['DMminus_smooth'] / df['TR_smooth'])

            # Calculate ADX
            df['DX'] = 100 * abs(df['DIplus'] - df['DIminus']) / (df['DIplus'] + df['DIminus'])
            df['ADX'] = df['DX'].rolling(window=period).mean()

            adx = df['ADX'].iloc[-1]
            di_plus = df['DIplus'].iloc[-1]
            di_minus = df['DIminus'].iloc[-1]

            if adx > 25:
                if di_plus > di_minus:
                    signal = 'BUY'
                    strength = min(1.0, adx / 50)
                    reasoning = f"Strong uptrend: ADX={adx:.1f}, DI+={di_plus:.1f} > DI-={di_minus:.1f}"
                else:
                    signal = 'SELL'
                    strength = min(1.0, adx / 50)
                    reasoning = f"Strong downtrend: ADX={adx:.1f}, DI-={di_minus:.1f} > DI+={di_plus:.1f}"
            else:
                signal = 'NEUTRAL'
                strength = 0.3
                reasoning = f"Weak trend: ADX={adx:.1f} < 25"

            return TechnicalSignal(
                indicator="ADX",
                signal=signal,
                strength=strength,
                signal_type=SignalType.TREND_FOLLOWING,
                reasoning=reasoning
            )
        except Exception as e:
            print(f"ADX calculation error: {e}")
            return None

    def _analyze_context(self, df: pd.DataFrame, ticker: str) -> MarketContext:
        """Analyze overall market context"""
        try:
            # Determine trend
            ma_50 = df['Close'].rolling(window=50).mean().iloc[-1]
            ma_200 = df['Close'].rolling(window=200).mean().iloc[-1]
            current_price = df['Close'].iloc[-1]

            if pd.notna(ma_200):
                if current_price > ma_50 > ma_200:
                    trend = 'UPTREND'
                elif current_price < ma_50 < ma_200:
                    trend = 'DOWNTREND'
                else:
                    trend = 'SIDEWAYS'
            else:
                trend = 'SIDEWAYS'

            # Determine volatility
            volatility_ratio = df['Close'].pct_change().std() * np.sqrt(252)
            if volatility_ratio > 0.4:
                volatility = 'HIGH'
            elif volatility_ratio > 0.2:
                volatility = 'MEDIUM'
            else:
                volatility = 'LOW'

            # Volume trend
            recent_volume = df['Volume'].iloc[-10:].mean()
            prev_volume = df['Volume'].iloc[-20:-10].mean()
            if recent_volume > prev_volume * 1.2:
                volume_trend = 'INCREASING'
            elif recent_volume < prev_volume * 0.8:
                volume_trend = 'DECREASING'
            else:
                volume_trend = 'STABLE'

            # Get upcoming events
            events = self._get_upcoming_events(ticker)

            # Calculate support/resistance levels
            support_levels = self._calculate_support_levels(df)
            resistance_levels = self._calculate_resistance_levels(df)

            return MarketContext(
                trend=trend,
                volatility=volatility,
                volume_trend=volume_trend,
                upcoming_events=events,
                support_levels=support_levels,
                resistance_levels=resistance_levels
            )
        except Exception as e:
            print(f"Context analysis error: {e}")
            return MarketContext(
                trend='SIDEWAYS',
                volatility='MEDIUM',
                volume_trend='STABLE',
                upcoming_events=[],
                support_levels=[],
                resistance_levels=[]
            )

    def _get_upcoming_events(self, ticker: str) -> List[Dict]:
        """Get upcoming events (earnings, dividends, etc.)"""
        try:
            stock = yf.Ticker(ticker)
            calendar = stock.calendar

            events = []
            if calendar is not None and len(calendar) > 0:
                # Extract earnings date if available
                if 'Earnings Date' in calendar:
                    earnings_dates = calendar['Earnings Date']
                    if isinstance(earnings_dates, pd.Series) and len(earnings_dates) > 0:
                        next_earnings = earnings_dates.iloc[0]
                        if pd.notna(next_earnings):
                            events.append({
                                'type': 'earnings',
                                'date': next_earnings.strftime('%Y-%m-%d') if hasattr(next_earnings, 'strftime') else str(next_earnings),
                                'description': 'Earnings Report'
                            })

                # Add ex-dividend date if available
                if 'Ex-Dividend Date' in calendar:
                    ex_div = calendar['Ex-Dividend Date']
                    if pd.notna(ex_div):
                        events.append({
                            'type': 'dividend',
                            'date': ex_div.strftime('%Y-%m-%d') if hasattr(ex_div, 'strftime') else str(ex_div),
                            'description': 'Ex-Dividend Date'
                        })

            return events
        except Exception as e:
            print(f"Event fetch error: {e}")
            return []

    def _calculate_support_levels(self, df: pd.DataFrame) -> List[float]:
        """Calculate support levels"""
        try:
            lows = df['Low'].iloc[-50:]

            # Find local minima
            support_levels = []
            for i in range(2, len(lows) - 2):
                if lows.iloc[i] < lows.iloc[i-1] and lows.iloc[i] < lows.iloc[i-2] and \
                   lows.iloc[i] < lows.iloc[i+1] and lows.iloc[i] < lows.iloc[i+2]:
                    support_levels.append(lows.iloc[i])

            # Remove duplicates and sort
            support_levels = sorted(list(set([round(s, 2) for s in support_levels])))

            return support_levels[-3:] if len(support_levels) > 3 else support_levels
        except:
            return []

    def _calculate_resistance_levels(self, df: pd.DataFrame) -> List[float]:
        """Calculate resistance levels"""
        try:
            highs = df['High'].iloc[-50:]

            # Find local maxima
            resistance_levels = []
            for i in range(2, len(highs) - 2):
                if highs.iloc[i] > highs.iloc[i-1] and highs.iloc[i] > highs.iloc[i-2] and \
                   highs.iloc[i] > highs.iloc[i+1] and highs.iloc[i] > highs.iloc[i+2]:
                    resistance_levels.append(highs.iloc[i])

            # Remove duplicates and sort
            resistance_levels = sorted(list(set([round(r, 2) for r in resistance_levels])))

            return resistance_levels[:3] if len(resistance_levels) > 3 else resistance_levels
        except:
            return []

    def _detect_conflicts(self, signals: List[TechnicalSignal]) -> List[Dict]:
        """Detect conflicting signals"""
        conflicts = []

        # Group signals by type
        trend_signals = [s for s in signals if s.signal_type == SignalType.TREND_FOLLOWING]
        reversion_signals = [s for s in signals if s.signal_type == SignalType.MEAN_REVERSION]

        # Check trend vs mean reversion conflicts
        trend_direction = self._get_consensus(trend_signals)
        reversion_direction = self._get_consensus(reversion_signals)

        if trend_direction and reversion_direction and trend_direction != reversion_direction:
            conflicts.append({
                'type': 'trend_vs_reversion',
                'trend_signal': trend_direction,
                'reversion_signal': reversion_direction,
                'description': f"Trend indicators suggest {trend_direction} while mean reversion suggests {reversion_direction}"
            })

        # Check volume confirmation
        volume_signals = [s for s in signals if s.signal_type == SignalType.VOLUME_BASED]
        if volume_signals:
            volume_direction = volume_signals[0].signal
            if trend_direction and volume_direction != trend_direction and volume_direction != 'NEUTRAL':
                conflicts.append({
                    'type': 'volume_divergence',
                    'price_signal': trend_direction,
                    'volume_signal': volume_direction,
                    'description': "Volume not confirming price action"
                })

        return conflicts

    def _get_consensus(self, signals: List[TechnicalSignal]) -> Optional[str]:
        """Get consensus from a list of signals"""
        if not signals:
            return None

        buy_weight = sum(s.strength for s in signals if s.signal == 'BUY')
        sell_weight = sum(s.strength for s in signals if s.signal == 'SELL')

        if buy_weight > sell_weight * 1.2:
            return 'BUY'
        elif sell_weight > buy_weight * 1.2:
            return 'SELL'
        else:
            return 'NEUTRAL'

    def _resolve_conflicts(self, signals: List[TechnicalSignal],
                          context: MarketContext,
                          conflicts: List[Dict]) -> Tuple[str, float]:
        """Resolve conflicts using context-aware weighting"""

        # Adjust weights based on market context
        adjusted_weights = self.weights.copy()

        if context.trend in ['UPTREND', 'DOWNTREND']:
            # In trending market, give more weight to trend following
            adjusted_weights[SignalType.TREND_FOLLOWING] *= 1.5
            adjusted_weights[SignalType.MEAN_REVERSION] *= 0.7
        else:
            # In sideways market, give more weight to mean reversion
            adjusted_weights[SignalType.MEAN_REVERSION] *= 1.3
            adjusted_weights[SignalType.TREND_FOLLOWING] *= 0.8

        if context.volatility == 'HIGH':
            # In high volatility, reduce all weights slightly
            for key in adjusted_weights:
                adjusted_weights[key] *= 0.9

        if context.volume_trend == 'DECREASING':
            # Low volume reduces confidence
            adjusted_weights[SignalType.VOLUME_BASED] *= 0.7

        # Calculate weighted scores
        buy_score = 0
        sell_score = 0
        total_weight = 0

        for signal in signals:
            weight = adjusted_weights[signal.signal_type] * signal.strength

            if signal.signal == 'BUY':
                buy_score += weight
            elif signal.signal == 'SELL':
                sell_score += weight

            total_weight += weight

        # Normalize scores
        if total_weight > 0:
            buy_score /= total_weight
            sell_score /= total_weight

        # Apply penalty for conflicts
        if conflicts:
            confidence_penalty = 0.1 * len(conflicts)
        else:
            confidence_penalty = 0

        # Determine recommendation
        score_diff = buy_score - sell_score

        if score_diff > 0.15:
            recommendation = 'BUY'
            confidence = min(10, (score_diff * 20) - confidence_penalty)
        elif score_diff < -0.15:
            recommendation = 'SELL'
            confidence = min(10, (-score_diff * 20) - confidence_penalty)
        else:
            recommendation = 'HOLD'
            confidence = max(3, 5 - confidence_penalty)

        # Reduce confidence if near important events
        if context.upcoming_events:
            for event in context.upcoming_events:
                if event['type'] == 'earnings':
                    try:
                        event_date = datetime.strptime(event['date'], '%Y-%m-%d')
                        if (event_date - datetime.now()).days <= 5:
                            confidence *= 0.7
                    except:
                        pass

        return recommendation, max(1, confidence)

    def _assess_risks(self, context: MarketContext, df: pd.DataFrame) -> List[str]:
        """Assess risk factors"""
        risks = []

        # Event risk
        for event in context.upcoming_events:
            if event['type'] == 'earnings':
                risks.append(f"Earnings report on {event['date']} - increased volatility expected")

        # Volatility risk
        if context.volatility == 'HIGH':
            risks.append("High volatility environment - wider stops recommended")

        # Volume risk
        if context.volume_trend == 'DECREASING':
            risks.append("Declining volume - potential false breakout risk")

        # Support/Resistance risk
        current_price = df['Close'].iloc[-1]
        if context.support_levels:
            nearest_support = min(context.support_levels, key=lambda x: abs(x - current_price))
            if (current_price - nearest_support) / current_price < 0.03:
                risks.append(f"Near support at ${nearest_support:.2f}")

        if context.resistance_levels:
            nearest_resistance = min(context.resistance_levels, key=lambda x: abs(x - current_price) if x > current_price else float('inf'))
            if nearest_resistance != float('inf') and (nearest_resistance - current_price) / current_price < 0.03:
                risks.append(f"Near resistance at ${nearest_resistance:.2f}")

        return risks

    def _signal_to_dict(self, signal: TechnicalSignal) -> Dict:
        """Convert signal to dictionary"""
        return {
            'indicator': signal.indicator,
            'signal': signal.signal,
            'strength': signal.strength,
            'type': signal.signal_type.value,
            'reasoning': signal.reasoning,
            'price_level': signal.price_level
        }

    def _context_to_dict(self, context: MarketContext) -> Dict:
        """Convert context to dictionary"""
        return {
            'trend': context.trend,
            'volatility': context.volatility,
            'volume_trend': context.volume_trend,
            'upcoming_events': context.upcoming_events,
            'support_levels': context.support_levels,
            'resistance_levels': context.resistance_levels
        }

    def _error_response(self, message: str) -> Dict:
        """Generate error response"""
        return {
            'error': True,
            'message': message,
            'recommendation': 'HOLD',
            'confidence': 0
        }


# Example usage
if __name__ == "__main__":
    analyzer = EnhancedTechnicalAnalyzer()

    # Test with IBM
    result = analyzer.analyze("IBM")

    print("\n=== Enhanced Technical Analysis: IBM ===")
    print(f"Recommendation: {result['recommendation']}")
    print(f"Confidence: {result['confidence']}/10")

    print("\n--- Signals ---")
    for signal in result['signals']:
        print(f"{signal['indicator']:20} | {signal['signal']:6} | Strength: {signal['strength']:.2f} | {signal['reasoning']}")

    print("\n--- Market Context ---")
    ctx = result['context']
    print(f"Trend: {ctx['trend']}")
    print(f"Volatility: {ctx['volatility']}")
    print(f"Volume: {ctx['volume_trend']}")

    if ctx['support_levels']:
        print(f"Support: {ctx['support_levels']}")
    if ctx['resistance_levels']:
        print(f"Resistance: {ctx['resistance_levels']}")

    if result['conflicts']:
        print("\n--- Conflicts Detected ---")
        for conflict in result['conflicts']:
            print(f"• {conflict['description']}")

    if result['risk_factors']:
        print("\n--- Risk Factors ---")
        for risk in result['risk_factors']:
            print(f"• {risk}")