"""
차트 분석 에이전트 - 16개 기법을 tool로 제공, LLM이 판단/조합
기술적 분석 6개 + 퀀트 분석 6개 + 리스크/퀀트 확장 4개

사용법:
    agent = ChartAnalysisAgent(ticker, df_indicators)
    result = agent.run(mode="ollama")  # 또는 "gpt4o"
"""
import json
import os
import base64
from datetime import datetime
from typing import Optional

import httpx
import numpy as np
import pandas as pd

import yfinance as yf

from config import (
    OPENAI_API_KEY, OLLAMA_BASE_URL, OLLAMA_MODEL, OUTPUT_DIR,
    BOLLINGER_PERIOD, BOLLINGER_STD, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    ADX_PERIOD, RSI_PERIOD, SMA_PERIODS,
    ATR_STOP_MULTIPLIER, ACCOUNT_SIZE, RISK_PER_TRADE_PCT,
    MAX_POSITION_PCT, TAKE_PROFIT_RR_RATIO, TRADING_STYLE, TIMEFRAME,
    COOLING_OFF_DAYS, DEFAULT_HISTORY_PERIOD,
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    POSITION_TRANCHE_1_PCT, POSITION_TRANCHE_2_PCT, POSITION_TRANCHE_3_PCT,
)


# ═══════════════════════════════════════════════════════════════
#  공통 헬퍼: timezone-aware 시점 비교
# ═══════════════════════════════════════════════════════════════
def _market_now_naive(market: str = "US") -> pd.Timestamp:
    """
    시장 기준 현재 시각을 tz-naive Timestamp로 반환.
    한국 시장(KS/KQ)은 KST, 그 외는 미국 동부(ET) 기준.

    이렇게 하면 yfinance가 제공하는 tz-aware 일자와 비교 시 datetime 오프셋 문제를 줄일 수 있다.
    """
    tz_map = {"KR": "Asia/Seoul", "KS": "Asia/Seoul", "KQ": "Asia/Seoul"}
    tz_name = tz_map.get(market.upper(), "America/New_York")
    return pd.Timestamp.now(tz=tz_name).tz_localize(None)


def _to_naive_ts(ts) -> Optional[pd.Timestamp]:
    """입력값을 tz-naive pd.Timestamp로 변환 (실패 시 None)."""
    try:
        result = pd.Timestamp(ts)
        if result.tzinfo is not None:
            result = result.tz_convert(None) if hasattr(result, 'tz_convert') else result.tz_localize(None)
        return result
    except (ValueError, TypeError):
        return None


def _market_from_ticker(ticker: str) -> str:
    """티커에서 시장 코드(KR/US) 추론."""
    if not ticker:
        return "US"
    t = ticker.upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        return "KR"
    return "US"


# ═══════════════════════════════════════════════════════════════
#  16개 분석 기법 (각각 독립 함수, tool로 LLM에 노출)
# ═══════════════════════════════════════════════════════════════

class AnalysisTools:
    """16개 분석 기법. 각 메서드는 dict를 반환한다."""

    def __init__(self, ticker: str, df: pd.DataFrame):
        self.ticker = ticker
        self.df = df.copy()
        self.close = df['Close']
        self.high = df['High']
        self.low = df['Low']
        self.volume = df['Volume']
        self.latest = df.iloc[-1]

        # [P1 개선] 진입가 검증
        self.entry_price_warnings = []
        current_price = float(self.latest['Close'])
        day_high = float(self.latest['High'])
        day_low = float(self.latest['Low'])
        _cur = "₩" if _market_from_ticker(ticker) == "KR" else "$"
        _pfmt = (lambda v: f"{_cur}{v:,.0f}") if _cur == "₩" else (lambda v: f"{_cur}{v:.2f}")

        if current_price > day_high:
            self.entry_price_warnings.append(f"진입가 {_pfmt(current_price)} > 당일 고가 {_pfmt(day_high)}")
        elif current_price < day_low:
            self.entry_price_warnings.append(f"진입가 {_pfmt(current_price)} < 당일 저가 {_pfmt(day_low)}")

        # 52주 고가 대비 하락률 계산
        if len(df) >= 252:
            week52_high = float(df['High'].tail(252).max())
            self.week52_high = week52_high
            self.week52_decline = (week52_high - current_price) / week52_high * 100
        else:
            self.week52_high = None
            self.week52_decline = None

    # ── 기술적 분석 6개 ──────────────────────────────────────

    def trend_ma_analysis(self) -> dict:
        """[기술1] 이동평균선 배열 분석 - 골든/데드크로스, 정배열/역배열, 급등돌파"""
        result = {"tool": "trend_ma_analysis", "name": "이동평균선 배열 분석"}
        sma_vals = {}
        for p in [20, 50, 200]:
            col = f'SMA_{p}'
            if col in self.df.columns and not pd.isna(self.latest[col]):
                sma_vals[p] = float(self.latest[col])

        if not sma_vals:
            result["signal"] = "neutral"
            result["score"] = 0
            result["detail"] = "이동평균선 데이터 부족"
            return result

        price = float(self.latest['Close'])
        above_count = sum(1 for v in sma_vals.values() if price > v)

        # 정배열/역배열 판단
        sorted_periods = sorted(sma_vals.keys())
        sorted_vals = [sma_vals[p] for p in sorted_periods]
        is_bullish_aligned = all(sorted_vals[i] >= sorted_vals[i+1] for i in range(len(sorted_vals)-1))
        is_bearish_aligned = all(sorted_vals[i] <= sorted_vals[i+1] for i in range(len(sorted_vals)-1))

        # 급등 돌파 상태 감지: 가격이 모든 MA 위에서 일정기간 유지 + 거래량 체크
        is_breakout = False
        breakout_type = None

        if above_count == len(sma_vals):  # 모든 MA 위에 있을 때
            # 최근 10봉 내 MA 위 유지 기간 확인
            lookback = min(10, len(self.df))
            recent_df = self.df.iloc[-lookback:]
            breakout_bars = 0
            for i in range(len(recent_df)):
                row = recent_df.iloc[i]
                if all(row['Close'] > row[f'SMA_{p}'] for p in sorted_periods if f'SMA_{p}' in row and not pd.isna(row[f'SMA_{p}'])):
                    breakout_bars += 1

            # [개선 #1] MA breakout + 거래량 체크 강화
            volume_ratio = 1.0
            volume_warning = None
            if 'Volume_SMA_20' in self.df.columns and not pd.isna(self.latest.get('Volume_SMA_20')):
                vol = float(self.latest['Volume'])
                vol_avg = float(self.latest['Volume_SMA_20'])
                volume_ratio = vol / vol_avg if vol_avg > 0 else 1.0

                # 거래량 1.5배 미만 시 경고
                if volume_ratio < 1.5:
                    volume_warning = f"거래량 부족 {volume_ratio:.1f}x < 1.5x 기준"

            # 돌파 판정: 8봉 이상 MA 위 유지 + 거래량 1.5배 이상
            if breakout_bars >= 8:
                if volume_ratio >= 1.5:  # 1.5배 이상 거래량 필수
                    is_breakout = True
                    breakout_type = "breakout_bullish"  # 거래량 동반 강한 돌파
                else:
                    # 거래량 부족 시 돌파 무효
                    is_breakout = False
                    breakout_type = None

        # 골든/데드크로스 (SMA20 vs SMA50)
        cross_signal = "none"
        if 20 in sma_vals and 50 in sma_vals:
            sma20_series = self.df['SMA_20'].dropna()
            sma50_series = self.df['SMA_50'].dropna()
            if len(sma20_series) >= 2 and len(sma50_series) >= 2:
                prev_diff = float(sma20_series.iloc[-2] - sma50_series.iloc[-2])
                curr_diff = float(sma20_series.iloc[-1] - sma50_series.iloc[-1])
                if prev_diff < 0 and curr_diff > 0:
                    cross_signal = "golden_cross"
                elif prev_diff > 0 and curr_diff < 0:
                    cross_signal = "dead_cross"

        # 점수 계산 (-10 ~ +10) - 돌파 유형별 처리
        score = 0
        if is_breakout:
            if breakout_type == "breakout_bullish":
                # 거래량 동반 강한 돌파
                score += 5
                # RSI 과열 체크
                if 'RSI' in self.df.columns and not pd.isna(self.latest['RSI']):
                    rsi = float(self.latest['RSI'])
                    if rsi > 70:
                        score -= 2  # 과열시 일부 차감
            elif breakout_type == "breakout_weak":
                # 거래량 미동반 약한 돌파 - 중립
                score += 0  # 신호 없음
        elif is_bullish_aligned:
            score += 4
        elif is_bearish_aligned:
            score -= 4
        else:
            # Mixed alignment
            score += (above_count - len(sma_vals) / 2) * 2

        if cross_signal == "golden_cross":
            score += 3
        elif cross_signal == "dead_cross":
            score -= 3

        # 거래량 검증을 score에 반영 (거짓 강세 신호 방지)
        # 평균 대비 거래량이 극도로 낮은 경우 신호 신뢰성 저하
        if 'Volume_SMA_20' in self.df.columns and not pd.isna(self.latest.get('Volume_SMA_20')):
            try:
                vol_now = float(self.latest['Volume'])
                vol_avg = float(self.latest['Volume_SMA_20'])
                if vol_avg > 0:
                    vol_ratio = vol_now / vol_avg
                    # 거래량 극도 부족 (0.3x 미만)이면 강한 buy/sell 신호 약화
                    if vol_ratio < 0.3 and abs(score) >= 4:
                        score = score * 0.4  # 60% 감점
                    elif vol_ratio < 0.5 and abs(score) >= 4:
                        score = score * 0.6  # 40% 감점
            except (ValueError, TypeError, KeyError):
                pass

        score = max(-10, min(10, score))

        # 신호 결정 - breakout_weak는 중립 처리
        if breakout_type == "breakout_weak":
            signal = "neutral"
        else:
            signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        # alignment 상태 결정
        if is_breakout:
            alignment = breakout_type  # "breakout_bullish" or "breakout_weak"
        elif is_bullish_aligned:
            alignment = "bullish"
        elif is_bearish_aligned:
            alignment = "bearish"
        else:
            alignment = "mixed"

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "sma_values": sma_vals,
            "price_vs_sma": {f"SMA_{p}": "above" if price > v else "below" for p, v in sma_vals.items()},
            "alignment": alignment,
            "is_breakout": is_breakout,
            "cross_signal": cross_signal,
            "volume_ratio": round(volume_ratio, 2) if 'volume_ratio' in locals() else None,
            "volume_warning": volume_warning if 'volume_warning' in locals() else None,
            "detail": f"가격 ${price:.2f}, 배열={alignment}, 크로스={cross_signal}" +
                      (f", 거래량 {volume_ratio:.1f}x" if 'volume_ratio' in locals() else "") +
                      (f" [{volume_warning}]" if 'volume_warning' in locals() and volume_warning else "")
        })
        return result

    def rsi_divergence_analysis(self) -> dict:
        """[기술2] RSI 다이버전스 분석 - 일반/히든 다이버전스 탐지"""
        result = {"tool": "rsi_divergence_analysis", "name": "RSI 다이버전스 분석"}

        if 'RSI' not in self.df.columns:
            result.update({"signal": "neutral", "score": 0, "detail": "RSI 데이터 없음"})
            return result

        rsi = self.df['RSI'].dropna()
        close = self.close.loc[rsi.index]

        if len(rsi) < 20:
            result.update({"signal": "neutral", "score": 0, "detail": "데이터 부족"})
            return result

        current_rsi = float(rsi.iloc[-1])

        # 최근 20봉 내 피봇 포인트 탐색
        lookback = min(30, len(rsi))
        recent_close = close.iloc[-lookback:]
        recent_rsi = rsi.iloc[-lookback:]

        # 일반 다이버전스: 가격 신고가 but RSI 하락 → bearish
        # 일반 다이버전스: 가격 신저가 but RSI 상승 → bullish
        mid = lookback // 2
        price_first_half_high = float(recent_close.iloc[:mid].max())
        price_second_half_high = float(recent_close.iloc[mid:].max())
        rsi_first_half_high = float(recent_rsi.iloc[:mid].max())
        rsi_second_half_high = float(recent_rsi.iloc[mid:].max())

        price_first_half_low = float(recent_close.iloc[:mid].min())
        price_second_half_low = float(recent_close.iloc[mid:].min())
        rsi_first_half_low = float(recent_rsi.iloc[:mid].min())
        rsi_second_half_low = float(recent_rsi.iloc[mid:].min())

        divergence = "none"
        if price_second_half_high > price_first_half_high and rsi_second_half_high < rsi_first_half_high:
            divergence = "bearish_regular"
        elif price_second_half_low < price_first_half_low and rsi_second_half_low > rsi_first_half_low:
            divergence = "bullish_regular"
        elif price_second_half_low > price_first_half_low and rsi_second_half_low < rsi_first_half_low:
            divergence = "bullish_hidden"
        elif price_second_half_high < price_first_half_high and rsi_second_half_high > rsi_first_half_high:
            divergence = "bearish_hidden"

        # Regime-aware RSI 임계값:
        # 강한 추세(ADX > 25)에서는 표준 30/70이 너무 빨리 신호를 발생시킴.
        # → 추세장에서 80/20, 평이한 시장에서는 표준 70/30 사용.
        rsi_overbought = RSI_OVERBOUGHT
        rsi_oversold = RSI_OVERSOLD
        regime_adjust = "standard"
        if 'ADX' in self.df.columns and not pd.isna(self.latest.get('ADX')):
            try:
                adx_val = float(self.latest['ADX'])
                if adx_val > 25:
                    rsi_overbought = 80
                    rsi_oversold = 20
                    regime_adjust = "trending"
            except (ValueError, TypeError):
                pass

        score = 0
        if current_rsi > rsi_overbought:
            score -= 3
        elif current_rsi < rsi_oversold:
            score += 3
        elif current_rsi > 60:
            score -= 1
        elif current_rsi < 40:
            score += 1

        if "bullish" in divergence:
            score += 4
        elif "bearish" in divergence:
            score -= 4

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "current_rsi": round(current_rsi, 2),
            "rsi_zone": "overbought" if current_rsi > rsi_overbought else ("oversold" if current_rsi < rsi_oversold else "neutral"),
            "rsi_thresholds": {"overbought": rsi_overbought, "oversold": rsi_oversold, "regime": regime_adjust},
            "divergence": divergence,
            "detail": f"RSI={current_rsi:.1f} (임계값 {rsi_oversold}/{rsi_overbought}, {regime_adjust}), 다이버전스={divergence}"
        })
        return result

    def bollinger_squeeze_analysis(self) -> dict:
        """[기술3] 볼린저밴드 스퀴즈/확장 분석"""
        result = {"tool": "bollinger_squeeze_analysis", "name": "볼린저밴드 스퀴즈 분석"}

        bbu = f'BBU_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'
        bbl = f'BBL_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'
        bbm = f'BBM_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'

        if bbu not in self.df.columns:
            result.update({"signal": "neutral", "score": 0, "detail": "볼린저밴드 데이터 없음"})
            return result

        price = float(self.latest['Close'])
        upper = float(self.latest[bbu])
        lower = float(self.latest[bbl])
        middle = float(self.latest[bbm])
        bb_width = (upper - lower) / middle * 100

        # 최근 20봉 밴드폭 비교
        bb_widths = ((self.df[bbu] - self.df[bbl]) / self.df[bbm] * 100).dropna()
        avg_width = float(bb_widths.tail(50).mean()) if len(bb_widths) >= 50 else float(bb_widths.mean())
        min_width_20 = float(bb_widths.tail(20).min())

        is_squeeze = bb_width < avg_width * 0.6
        is_expanding = bb_width > avg_width * 1.4
        pct_b = (price - lower) / (upper - lower) if upper != lower else 0.5

        score = 0
        if is_squeeze:
            score += 2  # 스퀴즈 = 큰 움직임 예고, 방향은 중립
        if pct_b > 0.8:
            score -= 2  # 상단 밴드 근접 = 과매수
        elif pct_b < 0.2:
            score += 2  # 하단 밴드 근접 = 과매도
        if price > upper:
            score -= 3  # 상단 돌파 = 과열
        elif price < lower:
            score += 3  # 하단 이탈 = 반등 가능

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "bb_upper": round(upper, 2),
            "bb_lower": round(lower, 2),
            "bb_width_pct": round(bb_width, 2),
            "avg_width_pct": round(avg_width, 2),
            "pct_b": round(pct_b, 3),
            "squeeze": is_squeeze,
            "expanding": is_expanding,
            "detail": f"밴드폭={bb_width:.1f}% (평균 {avg_width:.1f}%), %B={pct_b:.2f}, 스퀴즈={'Yes' if is_squeeze else 'No'}"
        })
        return result

    def macd_momentum_analysis(self) -> dict:
        """[기술4] MACD 모멘텀 분석 - 크로스, 히스토그램 가속/감속"""
        result = {"tool": "macd_momentum_analysis", "name": "MACD 모멘텀 분석"}

        macd_col = f'MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        sig_col = f'MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        hist_col = f'MACDh_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'

        if macd_col not in self.df.columns:
            result.update({"signal": "neutral", "score": 0, "detail": "MACD 데이터 없음"})
            return result

        macd_val = float(self.latest[macd_col])
        sig_val = float(self.latest[sig_col])
        hist_val = float(self.latest[hist_col])

        # 크로스 감지
        macd_s = self.df[macd_col].dropna()
        sig_s = self.df[sig_col].dropna()
        cross = "none"
        if len(macd_s) >= 2 and len(sig_s) >= 2:
            prev_diff = float(macd_s.iloc[-2] - sig_s.iloc[-2])
            curr_diff = float(macd_s.iloc[-1] - sig_s.iloc[-1])
            if prev_diff < 0 and curr_diff > 0:
                cross = "bullish_cross"
            elif prev_diff > 0 and curr_diff < 0:
                cross = "bearish_cross"

        # 히스토그램 가속/감속
        hist_s = self.df[hist_col].dropna()
        hist_accel = "stable"
        if len(hist_s) >= 3:
            h1, h2, h3 = float(hist_s.iloc[-3]), float(hist_s.iloc[-2]), float(hist_s.iloc[-1])
            if h3 > h2 > h1:
                hist_accel = "accelerating_up"
            elif h3 < h2 < h1:
                hist_accel = "accelerating_down"
            elif abs(h3) < abs(h2):
                hist_accel = "decelerating"

        # 제로라인 위치
        zero_position = "above" if macd_val > 0 else "below"

        score = 0
        if cross == "bullish_cross":
            score += 4
        elif cross == "bearish_cross":
            score -= 4
        if hist_val > 0:
            score += 1
        else:
            score -= 1
        if hist_accel == "accelerating_up":
            score += 2
        elif hist_accel == "accelerating_down":
            score -= 2

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "macd": round(macd_val, 4),
            "signal_line": round(sig_val, 4),
            "histogram": round(hist_val, 4),
            "cross": cross,
            "histogram_acceleration": hist_accel,
            "zero_position": zero_position,
            "detail": f"MACD={macd_val:.4f}, 크로스={cross}, 히스토그램={hist_accel}"
        })
        return result

    def adx_trend_strength_analysis(self) -> dict:
        """[기술5] ADX 추세 강도 분석 - 추세 유무 및 방향"""
        result = {"tool": "adx_trend_strength_analysis", "name": "ADX 추세 강도 분석"}

        adx_col = f'ADX_{ADX_PERIOD}'
        dmp_col = f'DMP_{ADX_PERIOD}'
        dmn_col = f'DMN_{ADX_PERIOD}'

        if adx_col not in self.df.columns:
            result.update({"signal": "neutral", "score": 0, "detail": "ADX 데이터 없음"})
            return result

        adx = float(self.latest[adx_col])
        dmp = float(self.latest[dmp_col]) if dmp_col in self.df.columns else 0
        dmn = float(self.latest[dmn_col]) if dmn_col in self.df.columns else 0

        # 추세 강도 분류
        if adx > 40:
            strength = "very_strong"
        elif adx > 25:
            strength = "strong"
        elif adx > 20:
            strength = "weak"
        else:
            strength = "no_trend"

        # 방향
        direction = "bullish" if dmp > dmn else "bearish"

        # DI 크로스
        di_cross = "none"
        dmp_s = self.df.get(dmp_col, pd.Series(dtype=float)).dropna()
        dmn_s = self.df.get(dmn_col, pd.Series(dtype=float)).dropna()
        if len(dmp_s) >= 2 and len(dmn_s) >= 2:
            prev = float(dmp_s.iloc[-2] - dmn_s.iloc[-2])
            curr = float(dmp_s.iloc[-1] - dmn_s.iloc[-1])
            if prev < 0 and curr > 0:
                di_cross = "bullish_di_cross"
            elif prev > 0 and curr < 0:
                di_cross = "bearish_di_cross"

        score = 0
        if strength in ("strong", "very_strong"):
            score += 3 if direction == "bullish" else -3
        if di_cross == "bullish_di_cross":
            score += 3
        elif di_cross == "bearish_di_cross":
            score -= 3

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "adx": round(adx, 2),
            "plus_di": round(dmp, 2),
            "minus_di": round(dmn, 2),
            "trend_strength": strength,
            "trend_direction": direction,
            "di_cross": di_cross,
            "detail": f"ADX={adx:.1f} ({strength}), 방향={direction}, DI크로스={di_cross}"
        })
        return result

    def volume_profile_analysis(self) -> dict:
        """[기술6] 거래량 프로파일 분석 - OBV, 거래량 이상, 매집/분산, 급변 감지"""
        result = {"tool": "volume_profile_analysis", "name": "거래량 프로파일 분석"}

        if 'OBV' not in self.df.columns:
            result.update({"signal": "neutral", "score": 0, "detail": "OBV 데이터 없음"})
            return result

        vol = float(self.latest['Volume'])
        vol_sma = float(self.latest.get('Volume_SMA_20', vol))
        vol_ratio = vol / vol_sma if vol_sma > 0 else 1.0

        # 거래량 급변 감지 (1시간/4시간 단위)
        volume_change_warning = None
        volume_change_rate = 0.0
        if len(self.df) >= 5:
            # 최근 5봉 거래량 비율 추이
            recent_vol_ratios = []
            for i in range(-5, 0):
                v = float(self.df['Volume'].iloc[i])
                v_sma = float(self.df.get('Volume_SMA_20', pd.Series([v])).iloc[i] if 'Volume_SMA_20' in self.df.columns else v)
                recent_vol_ratios.append(v / v_sma if v_sma > 0 else 1.0)

            # 급변 감지: 직전 봉 대비 50% 이상 변동
            if len(recent_vol_ratios) >= 2:
                prev_ratio = recent_vol_ratios[-2]
                curr_ratio = vol_ratio
                if prev_ratio > 0:
                    volume_change_rate = abs(curr_ratio - prev_ratio) / prev_ratio
                    if volume_change_rate > 0.5:
                        if curr_ratio < prev_ratio:
                            volume_change_warning = "volume_sudden_drop"
                        else:
                            volume_change_warning = "volume_sudden_spike"

        obv = self.df['OBV'].dropna()
        obv_trend = "flat"
        if len(obv) >= 10:
            obv_sma5 = obv.rolling(5).mean()
            obv_sma20 = obv.rolling(20).mean()
            if len(obv_sma5.dropna()) >= 1 and len(obv_sma20.dropna()) >= 1:
                if float(obv_sma5.iloc[-1]) > float(obv_sma20.iloc[-1]):
                    obv_trend = "rising"
                else:
                    obv_trend = "falling"

        # 가격-거래량 괴리 (매집/분산)
        price_change = float(self.close.iloc[-1] / self.close.iloc[-10] - 1) if len(self.close) >= 10 else 0
        obv_change = float(obv.iloc[-1] - obv.iloc[-10]) if len(obv) >= 10 else 0

        accumulation = "neutral"
        if price_change < 0 and obv_change > 0:
            accumulation = "accumulation"  # 가격 하락 but 거래량 유입
        elif price_change > 0 and obv_change < 0:
            accumulation = "distribution"  # 가격 상승 but 거래량 유출

        score = 0
        if obv_trend == "rising":
            score += 2
        elif obv_trend == "falling":
            score -= 2
        if accumulation == "accumulation":
            score += 3
        elif accumulation == "distribution":
            score -= 3
        if vol_ratio > 2.0:
            score += 1 if price_change > 0 else -1

        # 거래량 급변 시 점수 조정
        if volume_change_warning == "volume_sudden_drop":
            score -= 2  # 거래량 급감은 추세 약화 신호
        elif volume_change_warning == "volume_sudden_spike":
            score += 1 if price_change > 0 else -1  # 방향성에 따라

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        detail_text = f"거래량비={vol_ratio:.2f}x, OBV추세={obv_trend}, 매집분산={accumulation}"
        if volume_change_warning:
            detail_text += f", ⚠️{volume_change_warning} ({volume_change_rate:.0%} 변동)"

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "current_volume": int(vol),
            "volume_ratio": round(vol_ratio, 2),
            "volume_sma_period": 20,  # [개선 #6] 시간프레임 명시
            "volume_change_lookback": 5,  # 최근 5봉 비교
            "volume_change_warning": volume_change_warning,
            "volume_change_rate": round(volume_change_rate, 2) if volume_change_rate else 0.0,
            "obv_trend": obv_trend,
            "obv_trend_periods": {"short": 5, "long": 20},  # OBV 비교 기간
            "price_volume_divergence_period": 10,  # 가격-거래량 괴리 분석 기간
            "accumulation_distribution": accumulation,
            "timeframe": "daily",  # 일봉 기준
            "detail": detail_text + " (일봉 기준, SMA20 대비)"  # 시간프레임 명시
        })
        return result

    # ── 퀀트 분석 6개 ────────────────────────────────────────

    def fibonacci_retracement_analysis(self) -> dict:
        """[퀀트1] 피보나치 되돌림 분석"""
        result = {"tool": "fibonacci_retracement_analysis", "name": "피보나치 되돌림 분석"}

        lookback = min(120, len(self.df))
        recent = self.df.tail(lookback)
        high_price = float(recent['High'].max())
        low_price = float(recent['Low'].min())
        price = float(self.latest['Close'])

        diff = high_price - low_price
        if diff == 0:
            result.update({"signal": "neutral", "score": 0, "detail": "가격 변동 없음"})
            return result

        levels = {
            "0.0": high_price,
            "0.236": high_price - diff * 0.236,
            "0.382": high_price - diff * 0.382,
            "0.500": high_price - diff * 0.500,
            "0.618": high_price - diff * 0.618,
            "0.786": high_price - diff * 0.786,
            "1.0": low_price,
        }

        # 현재가가 어느 레벨 구간에 있는지
        retracement_pct = (high_price - price) / diff
        nearest_level = min(levels.keys(), key=lambda k: abs(float(k) - retracement_pct))

        # 지지/저항 판단
        support_levels = {k: v for k, v in levels.items() if v < price}
        resistance_levels = {k: v for k, v in levels.items() if v > price}
        nearest_support = max(support_levels.values()) if support_levels else low_price
        nearest_resistance = min(resistance_levels.values()) if resistance_levels else high_price

        score = 0
        # 핵심 레벨(0.382, 0.500, 0.618) 근처면 반등 가능성
        for key_level in [0.382, 0.500, 0.618]:
            level_price = high_price - diff * key_level
            if abs(price - level_price) / price < 0.02:  # 2% 이내
                score += 2  # 지지 레벨 근접 = 매수 기회
                break

        if retracement_pct < 0.236:
            score += 2  # 고점 근처 = 강세
        elif retracement_pct > 0.786:
            score += 3  # 저점 근처 = 반등 기대
        elif retracement_pct > 0.618:
            score += 1

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "levels": {k: round(v, 2) for k, v in levels.items()},
            "current_retracement": round(retracement_pct, 3),
            "nearest_level": nearest_level,
            "nearest_support": round(nearest_support, 2),
            "nearest_resistance": round(nearest_resistance, 2),
            "detail": f"되돌림={retracement_pct:.1%}, 가까운 레벨={nearest_level}, 지지=${nearest_support:.2f}"
        })
        return result

    def volatility_regime_analysis(self) -> dict:
        """[퀀트2] 변동성 체제 분석 - ATR 기반 체제 판단"""
        result = {"tool": "volatility_regime_analysis", "name": "변동성 체제 분석"}

        if 'ATR' not in self.df.columns:
            result.update({"signal": "neutral", "score": 0, "detail": "ATR 데이터 없음"})
            return result

        atr = self.df['ATR'].dropna()
        if len(atr) < 50:
            result.update({"signal": "neutral", "score": 0, "detail": "ATR 데이터 부족"})
            return result

        current_atr = float(atr.iloc[-1])
        price = float(self.latest['Close'])
        atr_pct = current_atr / price * 100

        # 연환산 변동성 — 단일 정의: 일간 수익률 표준편차 기반 (통계적으로 더 정확)
        # ATR 기반 변동성은 atr_pct로 별도 보고
        returns = self.close.pct_change().dropna()
        if len(returns) >= 20:
            daily_vol_pct = float(returns.tail(20).std()) * 100  # %
        else:
            daily_vol_pct = atr_pct  # 표본 부족 시 ATR%로 폴백
        annualized_vol = daily_vol_pct * np.sqrt(252)  # 단일 진실 값

        # 변동성 라벨 (S&P 500 평균 15-20% 기준) — 위 단일 값 기준으로 결정
        if annualized_vol > 60:
            vol_label = "극도 고변동성"
        elif annualized_vol > 40:
            vol_label = "고변동성"
        elif annualized_vol > 25:
            vol_label = "평균 이상"
        elif annualized_vol > 15:
            vol_label = "정상"
        else:
            vol_label = "저변동성"

        # 히스토리컬 퍼센타일
        atr_pcts = (atr / self.close.loc[atr.index]) * 100
        percentile = float((atr_pcts < atr_pct).sum() / len(atr_pcts) * 100)

        # 체제 분류
        if percentile > 80:
            regime = "high_volatility"
        elif percentile > 60:
            regime = "above_average"
        elif percentile > 40:
            regime = "normal"
        elif percentile > 20:
            regime = "below_average"
        else:
            regime = "low_volatility"

        # 변동성 추이
        atr_5 = float(atr.tail(5).mean())
        atr_20 = float(atr.tail(20).mean())
        vol_trend = "expanding" if atr_5 > atr_20 * 1.1 else ("contracting" if atr_5 < atr_20 * 0.9 else "stable")

        score = 0
        if regime == "low_volatility" and vol_trend == "contracting":
            score += 2  # 저변동성 수축 = 폭발 예고
        elif regime == "high_volatility":
            score -= 2  # 고변동성 = 위험

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "current_atr": round(current_atr, 2),
            "atr_pct": round(atr_pct, 2),
            "percentile": round(percentile, 1),
            "regime": regime,
            "vol_trend": vol_trend,
            "annualized_volatility": round(annualized_vol, 2),
            "daily_volatility": round(daily_vol_pct, 4),
            "vol_label": vol_label,
            "detail": f"ATR%={atr_pct:.2f}%, 연환산={annualized_vol:.1f}% ({vol_label}), 체제={regime}, 추이={vol_trend}"
        })
        return result

    def mean_reversion_analysis(self) -> dict:
        """[퀀트3] 평균 회귀 분석 - Z-Score 기반 (실적 후 모드 포함)"""
        result = {"tool": "mean_reversion_analysis", "name": "평균 회귀 분석"}

        if len(self.close) < 50:
            result.update({"signal": "neutral", "score": 0, "detail": "데이터 부족"})
            return result

        price = float(self.latest['Close'])

        # 실적 발표 후 여부 체크
        post_earnings_mode = False
        mean_reversion_confidence = "normal"  # 신뢰도 수준
        weight_multiplier = 1.0  # 점수 가중치

        try:
            # 실적 발표일 체크 (event_driven_analysis와 연동)
            from datetime import datetime, timedelta
            t = yf.Ticker(self.ticker)
            cal = t.calendar

            if cal is not None:
                earnings_dates = []
                if isinstance(cal, dict):
                    ed = cal.get("Earnings Date")
                    if ed:
                        earnings_dates = [ed] if not isinstance(ed, list) else ed
                elif hasattr(cal, 'index') and "Earnings Date" in cal.index:
                    ed = cal.loc["Earnings Date"]
                    earnings_dates = [d for d in ed.values if pd.notna(d)]

                # 최근 3일 이내 실적 발표 확인 (시장 시간대 기준)
                market = _market_from_ticker(self.ticker)
                now_naive = _market_now_naive(market)
                for ed in earnings_dates:
                    try:
                        ed_dt = _to_naive_ts(ed)
                        if ed_dt is None:
                            continue
                        days_since = (now_naive - ed_dt).days
                        if 0 <= days_since <= 3:
                            post_earnings_mode = True
                            mean_reversion_confidence = "low"
                            # 실적 후 점수 가중치 감소 (임계값 조정 대신)
                            weight_multiplier = 0.5
                            break
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass  # 실적 정보 없으면 기본 모드

        # 다중 기간 Z-Score
        z_scores = {}
        for period in [20, 50]:
            sma = float(self.close.tail(period).mean())
            std = float(self.close.tail(period).std())
            if std > 0:
                z_scores[f"z_{period}"] = round((price - sma) / std, 3)

        if not z_scores:
            result.update({"signal": "neutral", "score": 0, "detail": "표준편차 0"})
            return result

        avg_z = np.mean(list(z_scores.values()))

        # 평균 회귀 확률 (Z-Score 기반)
        from scipy import stats as scipy_stats
        reversion_prob = 1 - scipy_stats.norm.cdf(abs(avg_z))
        reversion_prob *= 2  # 양측

        # 고정 임계값 사용 (조정 없음)
        high_threshold = 2.0
        mid_threshold = 1.5

        score = 0
        if avg_z > high_threshold:
            score -= 5  # 극단적 고평가
        elif avg_z > mid_threshold:
            score -= 3
        elif avg_z < -high_threshold:
            score += 5  # 극단적 저평가
        elif avg_z < -mid_threshold:
            score += 3
        elif abs(avg_z) < 0.5:
            score += 1  # 평균 근처 = 안정

        # 실적 후 모드에서 점수 가중치 적용
        if post_earnings_mode:
            score = score * weight_multiplier

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        detail_text = f"평균Z={avg_z:.2f}, 회귀확률={reversion_prob:.1%}"
        if post_earnings_mode:
            detail_text += f" [실적후: 신뢰도 {mean_reversion_confidence}, 가중치 {weight_multiplier}]"

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "z_scores": z_scores,
            "avg_z_score": round(avg_z, 3),
            "reversion_probability": round(reversion_prob, 4),
            "post_earnings_mode": post_earnings_mode,
            "confidence_level": mean_reversion_confidence,
            "weight_multiplier": weight_multiplier,
            "detail": detail_text
        })
        return result

    def momentum_rank_analysis(self) -> dict:
        """[퀀트4] 모멘텀 순위 분석 - 다기간 수익률 종합"""
        result = {"tool": "momentum_rank_analysis", "name": "모멘텀 순위 분석"}

        if len(self.close) < 60:
            result.update({"signal": "neutral", "score": 0, "detail": "데이터 부족"})
            return result

        price = float(self.latest['Close'])
        returns = {}
        for period, label in [(5, "1w"), (21, "1m"), (63, "3m")]:
            if len(self.close) > period:
                ret = float(self.close.iloc[-1] / self.close.iloc[-period - 1] - 1) * 100
                returns[label] = round(ret, 2)

        # 모멘텀 점수: 단기 + 중기 + 장기 가중 평균
        weights = {"1w": 0.2, "1m": 0.3, "3m": 0.5}
        weighted_return = sum(returns.get(k, 0) * w for k, w in weights.items())

        # 가속도 (단기 vs 장기)
        acceleration = "neutral"
        if "1w" in returns and "3m" in returns:
            weekly_annualized = returns["1w"] * 52
            quarterly = returns["3m"]
            if weekly_annualized > quarterly * 1.5:
                acceleration = "accelerating"
            elif weekly_annualized < quarterly * 0.5:
                acceleration = "decelerating"

        score = 0
        if weighted_return > 10:
            score += 4
        elif weighted_return > 5:
            score += 2
        elif weighted_return < -10:
            score -= 4
        elif weighted_return < -5:
            score -= 2

        if acceleration == "accelerating":
            score += 2
        elif acceleration == "decelerating":
            score -= 2

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "returns": returns,
            "weighted_return": round(weighted_return, 2),
            "acceleration": acceleration,
            "detail": f"가중수익률={weighted_return:.1f}%, 가속={acceleration}"
        })
        return result

    def support_resistance_analysis(self) -> dict:
        """[퀀트5] 지지/저항선 분석 - 피봇포인트 + 가격 클러스터"""
        result = {"tool": "support_resistance_analysis", "name": "지지/저항선 분석"}

        if len(self.df) < 20:
            result.update({"signal": "neutral", "score": 0, "detail": "데이터 부족"})
            return result

        price = float(self.latest['Close'])
        high = float(self.latest['High'])
        low = float(self.latest['Low'])

        # 클래식 피봇포인트
        pivot = (high + low + price) / 3
        r1 = 2 * pivot - low
        s1 = 2 * pivot - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)

        # 최근 고점/저점 기반 지지저항
        lookback = min(60, len(self.df))
        recent = self.df.tail(lookback)
        swing_highs = []
        swing_lows = []
        for i in range(2, len(recent) - 2):
            if (float(recent['High'].iloc[i]) > float(recent['High'].iloc[i-1]) and
                float(recent['High'].iloc[i]) > float(recent['High'].iloc[i-2]) and
                float(recent['High'].iloc[i]) > float(recent['High'].iloc[i+1]) and
                float(recent['High'].iloc[i]) > float(recent['High'].iloc[i+2])):
                swing_highs.append(float(recent['High'].iloc[i]))
            if (float(recent['Low'].iloc[i]) < float(recent['Low'].iloc[i-1]) and
                float(recent['Low'].iloc[i]) < float(recent['Low'].iloc[i-2]) and
                float(recent['Low'].iloc[i]) < float(recent['Low'].iloc[i+1]) and
                float(recent['Low'].iloc[i]) < float(recent['Low'].iloc[i+2])):
                swing_lows.append(float(recent['Low'].iloc[i]))

        nearest_resistance = min([h for h in swing_highs if h > price], default=r1)
        nearest_support = max([l for l in swing_lows if l < price], default=s1)

        upside_pct = (nearest_resistance - price) / price * 100
        downside_pct = (price - nearest_support) / price * 100
        risk_reward = upside_pct / downside_pct if downside_pct > 0 else 0

        score = 0
        if risk_reward > 2:
            score += 3
        elif risk_reward > 1.5:
            score += 2
        elif risk_reward < 0.5:
            score -= 3
        elif risk_reward < 1:
            score -= 1

        # 지지선 근접 = 매수, 저항선 근접 = 매도
        if downside_pct < 1:
            score += 2  # 지지선 바로 위
        if upside_pct < 1:
            score -= 2  # 저항선 바로 아래

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "pivot": round(pivot, 2),
            "resistance": {"R1": round(r1, 2), "R2": round(r2, 2), "swing": round(nearest_resistance, 2)},
            "support": {"S1": round(s1, 2), "S2": round(s2, 2), "swing": round(nearest_support, 2)},
            "upside_pct": round(upside_pct, 2),
            "downside_pct": round(downside_pct, 2),
            "risk_reward_ratio": round(risk_reward, 2),
            "detail": f"R/R={risk_reward:.1f}, 저항=${nearest_resistance:.2f}(+{upside_pct:.1f}%), 지지=${nearest_support:.2f}(-{downside_pct:.1f}%)"
        })
        return result

    def correlation_regime_analysis(self) -> dict:
        """[퀀트6] 수익률 자기상관 분석 - 추세 지속성 판단"""
        result = {"tool": "correlation_regime_analysis", "name": "수익률 자기상관 분석"}

        returns = self.close.pct_change().dropna()
        if len(returns) < 60:
            result.update({"signal": "neutral", "score": 0, "detail": "데이터 부족"})
            return result

        # 자기상관 (lag 1~5)
        autocorrs = {}
        for lag in range(1, 6):
            corr = float(returns.autocorr(lag=lag))
            autocorrs[f"lag_{lag}"] = round(corr, 4)

        avg_autocorr = np.mean(list(autocorrs.values()))

        # Hurst Exponent 근사 (R/S 분석 간소화)
        n = len(returns)
        max_k = min(int(np.log2(n)), 8)
        rs_list = []
        for k in range(2, max_k + 1):
            size = 2 ** k
            if size > n:
                break
            num_blocks = n // size
            rs_vals = []
            for i in range(num_blocks):
                block = returns.iloc[i*size:(i+1)*size].values
                mean_block = np.mean(block)
                cumdev = np.cumsum(block - mean_block)
                r = np.max(cumdev) - np.min(cumdev)
                s = np.std(block, ddof=1) if np.std(block, ddof=1) > 0 else 1e-10
                rs_vals.append(r / s)
            rs_list.append((np.log(size), np.log(np.mean(rs_vals)) if rs_vals else 0))

        hurst = 0.5
        if len(rs_list) >= 2:
            x = [p[0] for p in rs_list]
            y = [p[1] for p in rs_list]
            if len(x) >= 2:
                slope = np.polyfit(x, y, 1)[0]
                hurst = float(slope)

        # 해석
        if hurst > 0.6:
            regime = "trending"  # 추세 지속
        elif hurst < 0.4:
            regime = "mean_reverting"  # 평균 회귀
        else:
            regime = "random_walk"

        score = 0
        if regime == "trending" and avg_autocorr > 0:
            score += 3  # 양의 추세 지속
        elif regime == "trending" and avg_autocorr < 0:
            score -= 3  # 음의 추세 지속
        elif regime == "mean_reverting":
            # 평균 회귀 환경에서는 최근 방향 반대로
            recent_return = float(returns.tail(5).sum())
            score += 2 if recent_return < 0 else -2

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "autocorrelations": autocorrs,
            "avg_autocorrelation": round(avg_autocorr, 4),
            "hurst_exponent": round(hurst, 3),
            "regime": regime,
            "detail": f"Hurst={hurst:.3f} ({regime}), 평균자기상관={avg_autocorr:.4f}"
        })
        return result

    def risk_position_sizing(self) -> dict:
        """[리스크] 포지션 사이징 및 손절/익절 산출 (ATR + 지지저항 기반)"""
        result = {"tool": "risk_position_sizing", "name": "포지션 사이징 / 리스크 관리"}

        if 'ATR' not in self.df.columns:
            result.update({"signal": "neutral", "score": 0, "detail": "ATR 데이터 없음"})
            return result

        price = float(self.latest['Close'])
        atr_series = self.df['ATR'].dropna()
        if atr_series.empty:
            result.update({"signal": "neutral", "score": 0, "detail": "ATR 유효값 없음"})
            return result
        atr = float(atr_series.iloc[-1])

        # 1. ATR 기반 R/R 계산 (호가단위 반올림)
        from tick_size import round_to_tick
        stop_distance = atr * ATR_STOP_MULTIPLIER
        # 손절은 아래로(매수 포지션), 익절은 위로 — 실제 호가단위로 정합
        stop_loss_atr = round_to_tick(price - stop_distance, self.ticker, side="down")
        take_profit_atr = round_to_tick(price + stop_distance * TAKE_PROFIT_RR_RATIO, self.ticker, side="up")
        rr_ratio_atr = TAKE_PROFIT_RR_RATIO

        # 2. 지지저항 기반 R/R 계산
        # support_resistance_analysis와 유사한 로직 사용
        lookback = min(60, len(self.df))
        recent = self.df.tail(lookback)
        swing_highs = []
        swing_lows = []

        for i in range(2, min(len(recent) - 2, lookback - 2)):
            if (float(recent['High'].iloc[i]) > float(recent['High'].iloc[i-1]) and
                float(recent['High'].iloc[i]) > float(recent['High'].iloc[i-2]) and
                float(recent['High'].iloc[i]) > float(recent['High'].iloc[i+1]) and
                float(recent['High'].iloc[i]) > float(recent['High'].iloc[i+2])):
                swing_highs.append(float(recent['High'].iloc[i]))
            if (float(recent['Low'].iloc[i]) < float(recent['Low'].iloc[i-1]) and
                float(recent['Low'].iloc[i]) < float(recent['Low'].iloc[i-2]) and
                float(recent['Low'].iloc[i]) < float(recent['Low'].iloc[i+1]) and
                float(recent['Low'].iloc[i]) < float(recent['Low'].iloc[i+2])):
                swing_lows.append(float(recent['Low'].iloc[i]))

        # 피봇 포인트 계산
        high = float(self.latest['High'])
        low = float(self.latest['Low'])
        pivot = (high + low + price) / 3
        r1 = 2 * pivot - low
        s1 = 2 * pivot - high

        nearest_resistance_sr = min([h for h in swing_highs if h > price], default=r1)
        nearest_support_sr = max([l for l in swing_lows if l < price], default=s1)

        # 호가단위로 반올림하여 실제 주문 가능한 값으로 출력
        stop_loss_sr = round_to_tick(nearest_support_sr, self.ticker, side="down")
        take_profit_sr = round_to_tick(nearest_resistance_sr, self.ticker, side="up")

        upside_pct = (nearest_resistance_sr - price) / price * 100 if price > 0 else 0
        downside_pct = (price - nearest_support_sr) / price * 100 if price > 0 else 0
        rr_ratio_sr = upside_pct / downside_pct if downside_pct > 0 else 0

        # 최종 손절/익절 결정 (진정한 보수적 선택)
        stop_loss_final = min(stop_loss_atr, stop_loss_sr)  # 더 가까운(보수적) 손절
        take_profit_final = take_profit_atr  # ATR 기반 익절 사용

        # [P0 개선] 켈리 기준 먼저 가져오기
        kelly_result = self.kelly_criterion_analysis()
        kelly_optimal_pct = kelly_result.get('optimal_position_pct', 10.0)  # 켈리 권장 비중

        # 포지션 사이징 계산
        stop_distance_final = price - stop_loss_final
        risk_amount = ACCOUNT_SIZE * (RISK_PER_TRADE_PCT / 100)
        qty = int(risk_amount / stop_distance_final) if stop_distance_final > 0 else 0
        position_value = qty * price
        position_pct = (position_value / ACCOUNT_SIZE * 100) if ACCOUNT_SIZE > 0 else 0

        # [P0 켈리 하드캡] 켈리 권장 비중으로 제한
        if position_pct > kelly_optimal_pct and kelly_optimal_pct > 0:
            warnings_pre = []
            warnings_pre.append(f"켈리 하드캡 적용: {position_pct:.1f}% → {kelly_optimal_pct:.1f}%")
            position_pct = kelly_optimal_pct
            position_value = ACCOUNT_SIZE * (position_pct / 100)
            qty = int(position_value / price)
            position_value = qty * price  # 정수 주식수로 재계산
            position_pct = (position_value / ACCOUNT_SIZE * 100)

        # [개선 #2] R/R min() 적용 및 일관성 유지
        effective_rr = min(rr_ratio_atr, rr_ratio_sr)  # 보수적 선택
        rr_method = "ATR" if rr_ratio_atr <= rr_ratio_sr else "S/R"

        warnings = []
        # 켈리 하드캡 경고 추가
        if 'warnings_pre' in locals():
            warnings.extend(warnings_pre)

        # R/R 단계별 경고
        if effective_rr < 1.0:
            warnings.append(f"R/R 불리 ({effective_rr:.2f} < 1.0): 손실이 수익보다 큼")
            # 포지션 50% 자동 축소
            qty = int(qty * 0.5)
            position_value = qty * price
            position_pct = position_value / ACCOUNT_SIZE * 100
        elif effective_rr < 2.0:
            warnings.append(f"R/R 미흡 ({effective_rr:.2f} < 2.0): 권장 기준 미달")

        if position_pct > MAX_POSITION_PCT:
            max_qty = int(ACCOUNT_SIZE * MAX_POSITION_PCT / 100 / price)
            warnings.append(f"비중 초과({position_pct:.1f}%>{MAX_POSITION_PCT}%), 최대 {max_qty}주로 제한")
            qty = max_qty
            position_value = qty * price
            position_pct = position_value / ACCOUNT_SIZE * 100
        if position_value > ACCOUNT_SIZE:
            warnings.append("잔고 부족")
            qty = int(ACCOUNT_SIZE / price)
            position_value = qty * price
            position_pct = position_value / ACCOUNT_SIZE * 100
        if stop_distance_final / price > 0.10:
            warnings.append(f"손절가 이격 과다({stop_distance_final / price:.1%})")

        pct1 = POSITION_TRANCHE_1_PCT / 100
        pct2 = POSITION_TRANCHE_2_PCT / 100
        pct3 = POSITION_TRANCHE_3_PCT / 100

        split_entry = [
            {"tranche": 1, "pct": POSITION_TRANCHE_1_PCT, "qty": int(qty * pct1), "note": "1차 진입"},
            {"tranche": 2, "pct": POSITION_TRANCHE_2_PCT, "qty": int(qty * pct2), "note": "확인 후 추가"},
            {"tranche": 3, "pct": POSITION_TRANCHE_3_PCT, "qty": qty - int(qty * pct1) - int(qty * pct2), "note": "최종 진입"},
        ]

        # [P0 신호 중립 고정] 포지션 사이징은 방향 판단이 아닌 실행 파라미터
        # 점수는 실행 타이밍의 적절성만 평가 (항상 중립 신호)
        score = 0
        if effective_rr >= 2.0 and not warnings:
            score = 5  # 좋은 실행 조건
        elif effective_rr >= 1.5:
            score = 3  # 보통 실행 조건
        elif effective_rr < 1.0:
            score = -3  # 나쁜 실행 조건
        if warnings:
            score -= min(len(warnings), 3)  # 최대 -3점 차감
        score = max(-10, min(10, score))
        signal = "neutral"  # 항상 중립 - 방향 판단 제외

        _d_cur = "₩" if _market_from_ticker(self.ticker) == "KR" else "$"
        _d_fmt = (lambda v: f"{_d_cur}{v:,.0f}") if _d_cur == "₩" else (lambda v: f"{_d_cur}{v:.2f}")
        _detail_str = (f"진입={_d_fmt(price)}, ATR손절={_d_fmt(stop_loss_atr)}(RR {rr_ratio_atr:.1f}), "
                       f"SR손절={_d_fmt(stop_loss_sr)}(RR {rr_ratio_sr:.1f}), "
                       f"수량={qty}주({_d_fmt(position_value)}, {position_pct:.1f}%)")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "entry_price": price,
            # ATR 기반 레벨
            "atr_based": {
                "stop_loss": stop_loss_atr,
                "take_profit": take_profit_atr,
                "risk_reward_ratio": round(rr_ratio_atr, 2),
                "stop_distance": round(stop_distance, 2),
                "stop_pct": round(stop_distance / price * 100, 2),
            },
            # 지지저항 기반 레벨
            "sr_based": {
                "stop_loss": stop_loss_sr,
                "take_profit": take_profit_sr,
                "risk_reward_ratio": round(rr_ratio_sr, 2),
                "upside_pct": round(upside_pct, 2),
                "downside_pct": round(downside_pct, 2),
            },
            # 최종 권장값
            "final_levels": {
                "stop_loss": stop_loss_final,
                "take_profit": take_profit_final,
                "effective_rr": round(effective_rr, 2),  # min(ATR_RR, SR_RR)
                "rr_method": rr_method,  # 적용된 방법
                "method": "conservative",  # 보수적 선택
            },
            "atr": round(atr, 2),
            "atr_multiplier": ATR_STOP_MULTIPLIER,
            "account_size": ACCOUNT_SIZE,
            "risk_per_trade_pct": RISK_PER_TRADE_PCT,
            "risk_amount": round(risk_amount, 2),
            "recommended_qty": qty,
            "position_value": round(position_value, 2),
            "position_pct": round(position_pct, 2),
            "kelly_optimal_pct": round(kelly_optimal_pct, 2),  # 켈리 권장 비중
            "split_entry": split_entry,
            "trading_style": TRADING_STYLE,
            "warnings": warnings,
            "detail": _detail_str,
        })
        return result

    def entry_plan_analysis(self, signal: str = "buy", confidence: float = 7.0,
                            other_results: Optional[list] = None) -> dict:
        """
        [실전] 진입 계획 생성 — 매매 시점/분할진입/손절익절/보유기간.

        다른 도구들의 결과를 종합하여 "언제/얼마에/몇 번에 나눠 매수할지" 결정.
        사용법: 다른 도구들을 먼저 실행한 후 results 리스트를 전달.

        Args:
            signal: 현재 종합 신호 (buy/sell/neutral)
            confidence: 0-10 신뢰도
            other_results: 다른 도구 실행 결과 리스트. None이면 risk_position_sizing만 재실행.
        """
        from entry_plan import build_entry_plan, format_entry_plan_text

        result = {"tool": "entry_plan_analysis", "name": "진입 계획 (매매 시점/분할/손절익절)"}

        current_price = float(self.latest['Close'])
        tool_results = other_results or []

        # 최소 필수: risk_position_sizing이 결과에 없으면 직접 실행
        if not any(r.get("tool") == "risk_position_sizing" for r in tool_results):
            tool_results = list(tool_results) + [self.risk_position_sizing()]
        # volatility_regime도 ATR 풀백 계산에 유용하므로 없으면 실행
        if not any(r.get("tool") == "volatility_regime_analysis" for r in tool_results):
            try:
                tool_results.append(self.volatility_regime_analysis())
            except Exception:
                pass

        plan = build_entry_plan(
            ticker=self.ticker,
            signal=signal,
            confidence=confidence,
            current_price=current_price,
            tool_results=tool_results,
            trading_style=TRADING_STYLE,
            week52_high=self.week52_high,
        )

        currency = "₩" if _market_from_ticker(self.ticker) == "KR" else "$"
        _ep_fmt = (lambda v: f"{currency}{v:,.0f}") if currency == "₩" else (lambda v: f"{currency}{v:.2f}")
        result.update({
            "signal": "neutral",  # 이 도구는 방향성 판단이 아님
            "score": 0,
            "entry_plan": plan,
            "formatted": format_entry_plan_text(plan, currency=currency),
            "detail": f"{plan['entry_timing']} · {plan['order_type']}"
                     + (f" @ {_ep_fmt(plan['limit_price'])}" if plan.get('limit_price') else "")
                     + f" · 보유 {plan['expected_holding_days']}일"
        })
        return result

    def kelly_criterion_analysis(self) -> dict:
        """[퀀트7] 켈리 기준 최적 배팅 비율 산출"""
        result = {"tool": "kelly_criterion_analysis", "name": "켈리 기준 배팅 분석"}

        returns = self.close.pct_change().dropna()
        if len(returns) < 60:
            result.update({"signal": "neutral", "score": 0, "detail": "데이터 부족"})
            return result

        wins = returns[returns > 0]
        losses = returns[returns < 0]

        if len(wins) == 0 or len(losses) == 0:
            result.update({"signal": "neutral", "score": 0, "detail": "승/패 데이터 부족"})
            return result

        win_rate = len(wins) / len(returns)
        avg_win = float(wins.mean())
        avg_loss = float(abs(losses.mean()))
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

        kelly_full = win_rate - (1 - win_rate) / win_loss_ratio if win_loss_ratio > 0 else 0
        kelly_half = kelly_full / 2
        kelly_quarter = kelly_full / 4

        # Sharpe Ratio (무위험 수익률 옵션 적용 - 항목 #9 참조)
        # ANNUAL_RISK_FREE_RATE 환경변수로 조정 가능 (기본 0 = naive Sharpe)
        rf_annual = float(os.getenv("ANNUAL_RISK_FREE_RATE", "0.0"))
        rf_daily = rf_annual / 252
        excess_returns = returns - rf_daily
        sharpe = float(excess_returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

        # [개선 #3] 켈리 50% 이내 규칙 엄격 적용
        kelly_half = kelly_full / 2  # 켈리의 50%
        kelly_cap = MAX_POSITION_PCT / 2  # MAX_POSITION_PCT의 50% (10%)

        # 켈리 50% 규칙과 절대 상한 적용
        optimal_pct_raw = kelly_half * 100
        optimal_pct = min(optimal_pct_raw, kelly_cap)  # 10% 상한

        # 경고 메시지들
        warnings = []
        no_trade_warning = None

        # 켈리가 극단적으로 낮을 때
        if kelly_half < 0.01:  # 1% 미만
            no_trade_warning = f"켈리 < 1% ({kelly_half*100:.2f}%): 엣지 부족, 진입 비권장"
            optimal_pct = 0  # 포지션 없음
            signal_override = "no_trade"
        # 켈리가 상한을 초과할 때
        elif optimal_pct_raw > kelly_cap:
            warnings.append(f"Kelly {optimal_pct_raw:.1f}% → {kelly_cap:.1f}% 상한 적용")
            signal_override = None
        else:
            signal_override = None

        score = 0
        if kelly_full > 0.15:
            score += 4
        elif kelly_full > 0.05:
            score += 2
        elif kelly_full < -0.05:
            score -= 3
        elif kelly_full < 0:
            score -= 1

        if win_rate > 0.55:
            score += 1
        elif win_rate < 0.40:
            score -= 1

        # Sharpe ratio 점수 반영 (이전엔 계산만 하고 미사용)
        if sharpe > 1.5:
            score += 2  # 우수한 위험조정 수익
        elif sharpe > 0.8:
            score += 1
        elif sharpe < -0.5:
            score -= 2  # 열악한 위험조정 수익

        score = max(-10, min(10, score))

        # 신호 결정 (no_trade 우선)
        if signal_override == "no_trade":
            signal = "neutral"  # no_trade를 neutral로 매핑
        else:
            signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "win_rate": round(win_rate, 4),
            "avg_win_pct": round(avg_win * 100, 3),
            "avg_loss_pct": round(avg_loss * 100, 3),
            "win_loss_ratio": round(win_loss_ratio, 3),
            "kelly_full_pct": round(kelly_full * 100, 2),
            "kelly_half_pct": round(kelly_half * 100, 2),
            "kelly_quarter_pct": round(kelly_quarter * 100, 2),
            "kelly_raw_pct": round(optimal_pct_raw, 2),  # 상한 적용 전 값
            "optimal_position_pct": round(optimal_pct, 2),
            "kelly_cap_pct": round(kelly_cap, 2),  # 적용된 상한
            "sharpe_ratio": round(sharpe, 3),
            "no_trade_warning": no_trade_warning,
            "warnings": warnings if warnings else None,
            "detail": f"승률={win_rate:.1%}, W/L비={win_loss_ratio:.2f}, "
                       f"켈리={kelly_full:.1%}, 권장비중={optimal_pct:.1f}%" +
                       (f" (상한 {kelly_cap:.1f}%)" if optimal_pct_raw > kelly_cap else "") +
                       (f" [{no_trade_warning}]" if no_trade_warning else "")
        })
        return result

    def beta_correlation_analysis(self) -> dict:
        """[퀀트8] 베타/상관관계 분석 - SPY 대비 베타, 알파, 상관계수"""
        result = {"tool": "beta_correlation_analysis", "name": "베타/상관관계 분석"}

        try:
            spy = yf.Ticker("SPY").history(period=DEFAULT_HISTORY_PERIOD)
            if spy.empty:
                result.update({"signal": "neutral", "score": 0, "detail": "SPY 데이터 없음"})
                return result
        except Exception as e:
            result.update({"signal": "neutral", "score": 0, "detail": f"SPY 수집 실패: {e}"})
            return result

        common_idx = self.df.index.intersection(spy.index)
        if len(common_idx) < 60:
            result.update({"signal": "neutral", "score": 0, "detail": "공통 기간 부족"})
            return result

        stock_ret = self.close.loc[common_idx].pct_change().dropna()
        spy_ret = spy["Close"].loc[common_idx].pct_change().dropna()
        common_ret_idx = stock_ret.index.intersection(spy_ret.index)
        stock_ret = stock_ret.loc[common_ret_idx]
        spy_ret = spy_ret.loc[common_ret_idx]

        if len(stock_ret) < 30:
            result.update({"signal": "neutral", "score": 0, "detail": "수익률 데이터 부족"})
            return result

        cov = float(stock_ret.cov(spy_ret))
        var_spy = float(spy_ret.var())
        beta = cov / var_spy if var_spy > 0 else 1.0
        alpha_daily = float(stock_ret.mean() - beta * spy_ret.mean())
        alpha_annual = alpha_daily * 252
        correlation = float(stock_ret.corr(spy_ret))
        r_squared = correlation ** 2
        tracking_error = float((stock_ret - beta * spy_ret).std() * np.sqrt(252))

        info_ratio = alpha_annual / tracking_error if tracking_error > 0 else 0

        beta_60d = beta
        if len(stock_ret) >= 120:
            sr_60 = stock_ret.tail(60)
            sp_60 = spy_ret.loc[sr_60.index]
            cov_60 = float(sr_60.cov(sp_60))
            var_60 = float(sp_60.var())
            beta_60d = cov_60 / var_60 if var_60 > 0 else beta

        score = 0
        if alpha_annual > 0.10:
            score += 3
        elif alpha_annual > 0.05:
            score += 1
        elif alpha_annual < -0.10:
            score -= 3
        elif alpha_annual < -0.05:
            score -= 1

        if beta < 0.8:
            score += 1
        elif beta > 1.5:
            score -= 1

        if info_ratio > 0.5:
            score += 1

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        result.update({
            "signal": signal,
            "score": round(score, 1),
            "beta": round(beta, 3),
            "beta_60d": round(beta_60d, 3),
            "alpha_annual_pct": round(alpha_annual * 100, 2),
            "correlation": round(correlation, 3),
            "r_squared": round(r_squared, 3),
            "tracking_error_pct": round(tracking_error * 100, 2),
            "information_ratio": round(info_ratio, 3),
            "benchmark": "SPY",
            "detail": f"β={beta:.2f}(60d:{beta_60d:.2f}), α={alpha_annual:.1%}, "
                       f"상관={correlation:.2f}, IR={info_ratio:.2f}"
        })
        return result

    def event_driven_analysis(self) -> dict:
        """[퀀트9] 이벤트 드리븐 분석 - 실적발표, 배당락, 52주 신고/저가"""
        result = {"tool": "event_driven_analysis", "name": "이벤트 드리븐 분석"}

        try:
            t = yf.Ticker(self.ticker)
            info = t.info or {}
        except Exception as e:
            result.update({"signal": "neutral", "score": 0, "detail": f"데이터 수집 실패: {e}"})
            return result

        events = []
        score = 0

        earnings_dates = []
        try:
            cal = t.calendar
            if cal is not None:
                if isinstance(cal, dict):
                    ed = cal.get("Earnings Date")
                    if ed:
                        earnings_dates = [str(d) for d in (ed if isinstance(ed, list) else [ed])]
                elif isinstance(cal, pd.DataFrame) and not cal.empty:
                    if "Earnings Date" in cal.index:
                        ed = cal.loc["Earnings Date"]
                        earnings_dates = [str(d) for d in ed.values if pd.notna(d)]
        except Exception:
            pass

        if earnings_dates:
            events.append({"type": "earnings", "dates": earnings_dates})
            market = _market_from_ticker(self.ticker)
            now_naive = _market_now_naive(market)
            for ed_str in earnings_dates:
                try:
                    ed_dt = _to_naive_ts(ed_str)
                    if ed_dt is None:
                        continue
                    days_until = (ed_dt - now_naive).days
                    if 0 <= days_until <= 7:
                        events.append({"type": "earnings_imminent", "days": days_until})
                        score -= 1
                    elif 7 < days_until <= 30:
                        events.append({"type": "earnings_upcoming", "days": days_until})
                except Exception:
                    pass

        price = float(self.latest["Close"])
        high_52w = info.get("fiftyTwoWeekHigh")
        low_52w = info.get("fiftyTwoWeekLow")

        if high_52w and price >= high_52w * 0.97:
            events.append({"type": "near_52w_high", "pct_from_high": round((price / high_52w - 1) * 100, 2)})
            score += 2
        if low_52w and price <= low_52w * 1.03:
            events.append({"type": "near_52w_low", "pct_from_low": round((price / low_52w - 1) * 100, 2)})
            score += 3

        ex_div_date = info.get("exDividendDate")
        if ex_div_date:
            try:
                ex_dt_raw = pd.Timestamp(ex_div_date, unit="s") if isinstance(ex_div_date, (int, float)) else pd.Timestamp(ex_div_date)
                ex_dt = _to_naive_ts(ex_dt_raw)
                if ex_dt is None:
                    raise ValueError("invalid ex_div_date")
                market = _market_from_ticker(self.ticker)
                days_to_ex = (ex_dt - _market_now_naive(market)).days
                if 0 < days_to_ex <= 14:
                    events.append({"type": "ex_dividend_soon", "date": str(ex_dt.date()), "days": days_to_ex})
                    div_yield = info.get("dividendYield", 0) or 0
                    if div_yield > 0.03:
                        score += 1
            except Exception:
                pass

        if len(self.close) >= 20:
            vol_10d = float(self.close.pct_change().tail(10).std())
            vol_60d = float(self.close.pct_change().tail(60).std()) if len(self.close) >= 60 else vol_10d
            if vol_10d > vol_60d * 2:
                events.append({"type": "volatility_spike", "ratio": round(vol_10d / vol_60d, 2)})
                score -= 1

        if len(self.volume) >= 20:
            vol_today = float(self.volume.iloc[-1])
            vol_avg = float(self.volume.tail(20).mean())
            if vol_avg > 0 and vol_today > vol_avg * 3:
                events.append({"type": "volume_spike", "ratio": round(vol_today / vol_avg, 2)})

        rec = info.get("recommendationKey", "")
        rec_map = {"strong_buy": 2, "buy": 1, "hold": 0, "sell": -1, "strong_sell": -2}
        if rec in rec_map:
            events.append({"type": "analyst_consensus", "recommendation": rec})
            score += rec_map[rec]

        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

        event_summary = ", ".join(e["type"] for e in events) if events else "특이 이벤트 없음"
        result.update({
            "signal": signal,
            "score": round(score, 1),
            "events": events,
            "event_count": len(events),
            "earnings_dates": earnings_dates,
            "52w_high": high_52w,
            "52w_low": low_52w,
            "analyst_recommendation": rec or "N/A",
            "detail": f"이벤트 {len(events)}건: {event_summary}"
        })
        return result

    def insider_trading_analysis(self) -> dict:
        """[퀀트10] 내부자 거래 분석 - CEO/CFO 매수/매도 패턴"""
        result = {"tool": "insider_trading_analysis", "name": "내부자 거래 분석"}

        try:
            # 내부자 거래 분석기 임포트
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from stock_analyzer.insider_trading import InsiderTradingAnalyzer

            analyzer = InsiderTradingAnalyzer()
            current_price = float(self.latest["Close"])
            analysis = analyzer.analyze(self.ticker, current_price)

            result.update(analysis)

        except Exception as e:
            # 폴백: 기본 yfinance 내부자 거래 체크
            try:
                t = yf.Ticker(self.ticker)
                insider = t.insider_trades

                score = 0
                detail_parts = []

                if insider is not None and not insider.empty:
                    # 최근 3개월 거래 필터링
                    recent_date = pd.Timestamp.now() - pd.Timedelta(days=90)
                    recent_trades = insider[insider.index >= recent_date] if not insider.empty else pd.DataFrame()

                    if not recent_trades.empty:
                        # 매수/매도 카운트
                        buy_trades = recent_trades[recent_trades['Shares'] > 0] if 'Shares' in recent_trades.columns else pd.DataFrame()
                        sell_trades = recent_trades[recent_trades['Shares'] < 0] if 'Shares' in recent_trades.columns else pd.DataFrame()

                        buy_count = len(buy_trades)
                        sell_count = len(sell_trades)

                        # 점수 계산
                        if sell_count > buy_count * 2:
                            score -= 4
                            detail_parts.append(f"내부자 매도 압도적 ({sell_count}건)")
                        elif sell_count > buy_count:
                            score -= 2
                            detail_parts.append(f"내부자 매도 우세 ({sell_count}건)")
                        elif buy_count > sell_count * 2:
                            score += 4
                            detail_parts.append(f"내부자 매수 압도적 ({buy_count}건)")
                        elif buy_count > sell_count:
                            score += 2
                            detail_parts.append(f"내부자 매수 우세 ({buy_count}건)")
                        else:
                            detail_parts.append(f"내부자 거래 중립 (매수 {buy_count}, 매도 {sell_count})")
                    else:
                        detail_parts.append("최근 내부자 거래 없음")
                else:
                    detail_parts.append("내부자 거래 데이터 없음")

                signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")

                result.update({
                    "signal": signal,
                    "score": round(score, 1),
                    "detail": " / ".join(detail_parts)
                })

            except Exception as fallback_error:
                result.update({
                    "signal": "neutral",
                    "score": 0,
                    "detail": f"내부자 거래 분석 실패: {str(fallback_error)[:50]}"
                })

        return result

    # ── P2: Piotroski F-Score / Altman Z-Score ───────────────────

    @staticmethod
    def _safe_get(
        stmt: "pd.DataFrame | None",
        keys: "str | list[str]",
        col: int = 0,
        default: float = 0.0,
    ) -> float:
        """재무제표 DataFrame에서 안전하게 값을 추출한다. 여러 키 이름 시도."""
        if stmt is None or stmt.empty:
            return default
        key_list = [keys] if isinstance(keys, str) else keys
        for k in key_list:
            if k in stmt.index:
                try:
                    val = stmt.loc[k].iloc[col]
                    if pd.notna(val):
                        return float(val)
                except Exception:
                    pass
        return default

    def piotroski_fscore_analysis(self) -> dict:
        """[P2-A] Piotroski F-Score — 재무 건전성 0–9점.

        9 신호: 수익성 4 + 레버리지/유동성 3 + 운영 효율 2.
        score ≥7: BUY, score ≤2: SELL, 나머지: NEUTRAL.
        """
        result = {"tool": "piotroski_fscore_analysis", "name": "Piotroski F-Score 분석"}
        try:
            import yfinance as yf

            t = yf.Ticker(self.ticker)
            bs = t.balance_sheet
            inc = t.financials
            cf = t.cashflow

            if bs is None or bs.empty or inc is None or inc.empty:
                result.update({"signal": "neutral", "score": 0, "detail": "재무제표 없음"})
                return result
            if bs.shape[1] < 2:
                result.update({"signal": "neutral", "score": 0, "detail": "데이터 1년치만 있음"})
                return result

            _g = self._safe_get
            # ── 자산/순이익/현금흐름 ───────────────────────────────────
            ta0 = _g(bs, ["Total Assets"], 0)
            ta1 = _g(bs, ["Total Assets"], 1)
            avg_ta = (ta0 + ta1) / 2 if ta0 and ta1 else (ta0 or ta1 or 1)

            ni0 = _g(inc, ["Net Income", "Net Income Common Stockholders"], 0)
            ni1 = _g(inc, ["Net Income", "Net Income Common Stockholders"], 1)
            ocf0 = _g(
                cf,
                ["Operating Cash Flow", "Total Cash From Operating Activities",
                 "Cash From Operating Activities"],
                0,
            )
            roa0 = ni0 / avg_ta if avg_ta else 0
            roa1 = ni1 / ta1 if ta1 else 0

            # ── F1~F4 수익성 ─────────────────────────────────────────
            f1 = int(roa0 > 0)
            f2 = int(ocf0 > 0)
            f3 = int(roa0 > roa1)
            f4 = int(avg_ta > 0 and (ocf0 / avg_ta) > roa0)

            # ── F5~F7 레버리지/유동성 ────────────────────────────────
            ltd0 = _g(bs, ["Long Term Debt", "Long-Term Debt", "LongTermDebt"], 0)
            ltd1 = _g(bs, ["Long Term Debt", "Long-Term Debt", "LongTermDebt"], 1)
            ca0 = _g(bs, ["Current Assets", "Total Current Assets"], 0)
            ca1 = _g(bs, ["Current Assets", "Total Current Assets"], 1)
            cl0 = _g(bs, ["Current Liabilities", "Total Current Liabilities"], 0)
            cl1 = _g(bs, ["Current Liabilities", "Total Current Liabilities"], 1)

            lev0 = ltd0 / ta0 if ta0 else 0
            lev1 = ltd1 / ta1 if ta1 else 0
            f5 = int(lev0 < lev1)

            cr0 = ca0 / cl0 if cl0 else 0
            cr1 = ca1 / cl1 if cl1 else 0
            f6 = int(cr0 > cr1)

            # F7: 주식 수 미희석 (info 기반 근사값 — 더 정확한 검증은 P3)
            f7 = 1  # 보수적으로 1로 설정 (API 한계)

            # ── F8~F9 운영 효율 ──────────────────────────────────────
            rev0 = _g(inc, ["Total Revenue", "Revenue"], 0)
            rev1 = _g(inc, ["Total Revenue", "Revenue"], 1)
            gp0 = _g(inc, ["Gross Profit"], 0)
            gp1 = _g(inc, ["Gross Profit"], 1)

            gm0 = gp0 / rev0 if rev0 else 0
            gm1 = gp1 / rev1 if rev1 else 0
            f8 = int(gm0 > gm1)

            at0 = rev0 / avg_ta if avg_ta else 0
            at1 = rev1 / ta1 if ta1 else 0
            f9 = int(at0 > at1)

            fscore = f1 + f2 + f3 + f4 + f5 + f6 + f7 + f8 + f9

            # score –10 ~ +10 매핑: 중앙 4.5점
            tool_score = round((fscore - 4.5) * (10 / 4.5), 1)
            tool_score = max(-10.0, min(10.0, tool_score))

            if fscore >= 7:
                signal, grade = "buy", "STRONG(7-9)"
            elif fscore <= 2:
                signal, grade = "sell", "WEAK(0-2)"
            else:
                signal, grade = "neutral", "MEDIUM(3-6)"

            result.update({
                "signal": signal,
                "score": tool_score,
                "fscore": fscore,
                "grade": grade,
                "components": {
                    "F1_ROA_positive": bool(f1),
                    "F2_OCF_positive": bool(f2),
                    "F3_ROA_improving": bool(f3),
                    "F4_accrual_quality": bool(f4),
                    "F5_leverage_down": bool(f5),
                    "F6_liquidity_up": bool(f6),
                    "F7_no_dilution": True,
                    "F8_margin_improving": bool(f8),
                    "F9_turnover_improving": bool(f9),
                },
                "detail": f"F-Score={fscore}/9 ({grade}), ROA={roa0:.3f}, OCF/TA={ocf0/avg_ta:.3f}",
            })
        except Exception as exc:
            result.update({
                "signal": "neutral", "score": 0,
                "detail": f"F-Score 계산 실패: {str(exc)[:100]}",
            })
        return result

    def altman_zscore_analysis(self) -> dict:
        """[P2-B] Altman Z-Score — 도산 위험도 분석.

        상장 미국 기업: Z = 1.2X1+1.4X2+3.3X3+0.6X4+1.0X5
        한국/비상장: Z' = 0.717X1+0.847X2+3.107X3+0.420X4+0.998X5
        """
        result = {"tool": "altman_zscore_analysis", "name": "Altman Z-Score 도산 분석"}
        try:
            import yfinance as yf

            t = yf.Ticker(self.ticker)
            bs = t.balance_sheet
            inc = t.financials
            info = t.info or {}

            if bs is None or bs.empty or inc is None or inc.empty:
                result.update({"signal": "neutral", "score": 0, "detail": "재무제표 없음"})
                return result

            _g = self._safe_get
            ta = _g(bs, ["Total Assets"], 0) or 1.0

            # X1: Working Capital / Total Assets
            ca = _g(bs, ["Current Assets", "Total Current Assets"], 0)
            cl = _g(bs, ["Current Liabilities", "Total Current Liabilities"], 0)
            x1 = (ca - cl) / ta

            # X2: Retained Earnings / Total Assets
            re = _g(bs, ["Retained Earnings", "RetainedEarnings"], 0)
            x2 = re / ta

            # X3: EBIT / Total Assets
            ebit = _g(inc, ["Operating Income", "EBIT", "Ebit"], 0)
            x3 = ebit / ta

            # X4: Market Cap / Total Liabilities
            mktcap = float(info.get("marketCap") or 0)
            total_liab = _g(
                bs,
                ["Total Liabilities Net Minority Interest", "Total Liab",
                 "Total Liabilities", "TotalLiabilitiesNetMinorityInterest"],
                0,
            )
            x4 = mktcap / total_liab if total_liab else 0

            # X5: Revenue / Total Assets
            rev = _g(inc, ["Total Revenue", "Revenue"], 0)
            x5 = rev / ta

            # 모델 선택: 한국 or 시총 미조회 → Z'-Score
            is_korean = _market_from_ticker(self.ticker) == "KR"
            use_prime = is_korean or (mktcap == 0)

            if use_prime:
                zscore = 0.717*x1 + 0.847*x2 + 3.107*x3 + 0.420*x4 + 0.998*x5
                model = "Z'-Score(비상장/KR)"
                safe_th, distress_th = 2.9, 1.23
            else:
                zscore = 1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5
                model = "Z-Score(상장)"
                safe_th, distress_th = 2.99, 1.81

            if zscore >= safe_th:
                zone, signal = "safe", "buy"
                tool_score = min(10.0, (zscore - safe_th) * 2 + 5)
            elif zscore >= distress_th:
                zone, signal = "grey", "neutral"
                tool_score = 0.0
            else:
                zone, signal = "distress", "sell"
                tool_score = max(-10.0, -(distress_th - zscore) * 3 - 3)

            result.update({
                "signal": signal,
                "score": round(tool_score, 1),
                "zscore": round(zscore, 3),
                "zone": zone,
                "model": model,
                "components": {
                    "X1_working_capital": round(x1, 4),
                    "X2_retained_earnings": round(x2, 4),
                    "X3_ebit": round(x3, 4),
                    "X4_market_book": round(x4, 4),
                    "X5_asset_turnover": round(x5, 4),
                },
                "detail": (
                    f"Altman {model} Z={zscore:.3f} | {zone.upper()} "
                    f"(safe>{safe_th}, distress<{distress_th})"
                ),
            })
        except Exception as exc:
            result.update({
                "signal": "neutral", "score": 0,
                "detail": f"Z-Score 계산 실패: {str(exc)[:100]}",
            })
        return result

    # ── Step 5: MFI 도구 (16→18개) ──────────────────────────────

    @staticmethod
    def _compute_mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Money Flow Index (14-period 표준 공식)."""
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        rmf = tp * df["Volume"]
        direction = np.where(
            tp > tp.shift(1), 1, np.where(tp < tp.shift(1), -1, 0)
        )
        pos = pd.Series(rmf.where(direction > 0, 0), index=df.index).rolling(period).sum()
        neg = pd.Series(rmf.where(direction < 0, 0), index=df.index).rolling(period).sum()
        # neg=0 이면 MFI=100 (전부 양봉), neg=NaN이면 전파
        mfi = np.where(
            neg == 0,
            100.0,
            100.0 - 100.0 / (1.0 + pos / neg.replace(0, np.nan)),
        )
        return pd.Series(mfi, index=df.index)

    @staticmethod
    def _detect_divergence(price: pd.Series, indicator: pd.Series, lookback: int = 30) -> str:
        """가격-지표 다이버전스 감지 (bullish/bearish/none)."""
        n = min(lookback, len(price), len(indicator))
        if n < 10:
            return "none"
        mid = n // 2
        p = price.iloc[-n:]
        ind = indicator.iloc[-n:]
        p1_low, p2_low = float(p.iloc[:mid].min()), float(p.iloc[mid:].min())
        i1_low, i2_low = float(ind.iloc[:mid].min()), float(ind.iloc[mid:].min())
        p1_high, p2_high = float(p.iloc[:mid].max()), float(p.iloc[mid:].max())
        i1_high, i2_high = float(ind.iloc[:mid].max()), float(ind.iloc[mid:].max())
        if p2_low < p1_low and i2_low > i1_low:
            return "bullish"
        if p2_high > p1_high and i2_high < i1_high:
            return "bearish"
        return "none"

    def money_flow_index_analysis(self) -> dict:
        """[Step5-A] MFI 단독 도구 — 거래량 가중 과매수/과매도 (score ±3)."""
        result = {"tool": "money_flow_index_analysis", "name": "MFI(자금흐름지수) 분석"}
        if len(self.df) < 16:
            result.update({"signal": "neutral", "score": 0, "detail": "데이터 부족"})
            return result
        mfi = self._compute_mfi(self.df)
        last = float(mfi.iloc[-1])
        if np.isnan(last):
            result.update({"signal": "neutral", "score": 0, "detail": "MFI NaN"})
            return result
        score, flags = 0, []
        if last > 80:
            score = -3
            flags.append("MFI_OVERBOUGHT")
        elif last < 20:
            score = 3
            flags.append("MFI_OVERSOLD")
        signal = "buy" if score > 0 else ("sell" if score < 0 else "neutral")
        result.update({
            "signal": signal, "score": score, "mfi": round(last, 2),
            "flags": flags, "detail": f"MFI={last:.1f}, {', '.join(flags) or '중립'}",
        })
        return result

    def rsi_mfi_combined_analysis(self) -> dict:
        """[Step5-B] RSI+MFI 조합 — 합치 과매수/매도, 이중 다이버전스, 거짓 돌파 감지 (score ±6)."""
        result = {"tool": "rsi_mfi_combined_analysis", "name": "RSI+MFI 조합 분석"}
        if "RSI" not in self.df.columns or len(self.df) < 20:
            result.update({"signal": "neutral", "score": 0, "detail": "데이터 부족"})
            return result
        rsi = self.df["RSI"].dropna()
        mfi = self._compute_mfi(self.df).dropna()
        if len(rsi) == 0 or len(mfi) == 0:
            result.update({"signal": "neutral", "score": 0, "detail": "RSI/MFI 없음"})
            return result
        last_rsi, last_mfi = float(rsi.iloc[-1]), float(mfi.iloc[-1])
        score, flags = 0, []
        # 합치 과매수/과매도
        if last_rsi > 70 and last_mfi > 80:
            score = -5
            flags.append("CONFIRMED_OVERBOUGHT")
        elif last_rsi < 30 and last_mfi < 20:
            score = 5
            flags.append("CONFIRMED_OVERSOLD")
        # 이중 다이버전스
        close = self.close.loc[rsi.index]
        close_m = self.close.loc[mfi.index]
        price_div = self._detect_divergence(close, rsi, 30)
        volume_div = self._detect_divergence(close_m, mfi, 30)
        if price_div == "bearish" and volume_div == "bearish":
            score -= 6
            flags.append("DOUBLE_BEARISH_DIVERGENCE")
        elif price_div == "bullish" and volume_div == "bullish":
            score += 6
            flags.append("DOUBLE_BULLISH_DIVERGENCE")
        # 거짓 돌파
        if last_rsi > 70 and last_mfi < 60:
            score -= 4
            flags.append("VOLUME_DIVERGENCE_BEARISH")
        elif last_rsi < 30 and last_mfi > 40:
            score += 4
            flags.append("VOLUME_DIVERGENCE_BULLISH")
        score = max(-10, min(10, score))
        signal = "buy" if score > 2 else ("sell" if score < -2 else "neutral")
        result.update({
            "signal": signal, "score": round(score, 1),
            "rsi": round(last_rsi, 2), "mfi": round(last_mfi, 2),
            "flags": flags, "detail": f"RSI={last_rsi:.1f}, MFI={last_mfi:.1f}, flags={flags}",
        })
        return result

    # ── Step 6: MACD+RSI cross-signal (18→19개) ──────────────────

    def macd_rsi_cross_analysis(self) -> dict:
        """[Step6] MACD 크로스 + RSI 동시 조건 — STRONG confirmation (score ±7)."""
        result = {"tool": "macd_rsi_cross_analysis", "name": "MACD+RSI 크로스 시그널"}
        macd_col = f"MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}"
        sig_col = f"MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}"
        if macd_col not in self.df.columns or "RSI" not in self.df.columns:
            result.update({"signal": "neutral", "score": 0, "detail": "데이터 없음"})
            return result
        macd_s = self.df[macd_col].dropna()
        sig_s = self.df[sig_col].dropna()
        rsi = self.df["RSI"].dropna()
        if len(macd_s) < 2 or len(rsi) == 0:
            result.update({"signal": "neutral", "score": 0, "detail": "데이터 부족"})
            return result
        bearish_cross = (
            float(macd_s.iloc[-2]) > float(sig_s.iloc[-2])
            and float(macd_s.iloc[-1]) < float(sig_s.iloc[-1])
        )
        bullish_cross = (
            float(macd_s.iloc[-2]) < float(sig_s.iloc[-2])
            and float(macd_s.iloc[-1]) > float(sig_s.iloc[-1])
        )
        last_rsi = float(rsi.iloc[-1])
        score, flags = 0, []
        if bearish_cross:
            flags.append("MACD_BEARISH_CROSS")
            if last_rsi > 70:
                score = -7
                flags.append("STRONG_BEARISH_CONFIRMATION")
            else:
                score = -3
        elif bullish_cross:
            flags.append("MACD_BULLISH_CROSS")
            if last_rsi < 30:
                score = 7
                flags.append("STRONG_BULLISH_CONFIRMATION")
            else:
                score = 3
        signal = "buy" if score > 0 else ("sell" if score < 0 else "neutral")
        result.update({
            "signal": signal, "score": score,
            "macd": round(float(macd_s.iloc[-1]), 4),
            "signal_line": round(float(sig_s.iloc[-1]), 4),
            "rsi": round(last_rsi, 2),
            "flags": flags, "detail": f"MACD cross={'bearish' if bearish_cross else 'bullish' if bullish_cross else 'none'}, RSI={last_rsi:.1f}, flags={flags}",
        })
        return result


# ═══════════════════════════════════════════════════════════════
#  Tool 정의 (LLM에 제공할 스키마)
# ═══════════════════════════════════════════════════════════════

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "trend_ma_analysis",
            "description": "이동평균선 배열 분석. 골든크로스/데드크로스, 정배열/역배열 판단. 추세 방향 파악에 사용.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rsi_divergence_analysis",
            "description": "RSI 다이버전스 분석. 과매수/과매도 + 가격-RSI 괴리(다이버전스) 탐지. 반전 시점 포착에 유용.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bollinger_squeeze_analysis",
            "description": "볼린저밴드 스퀴즈 분석. 밴드폭 수축/확장으로 변동성 폭발 예측. %B로 과매수/과매도 판단.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "macd_momentum_analysis",
            "description": "MACD 모멘텀 분석. 시그널 크로스, 히스토그램 가속/감속으로 모멘텀 변화 감지.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "adx_trend_strength_analysis",
            "description": "ADX 추세 강도 분석. 현재 추세의 강도와 방향(+DI/-DI) 판단. 추세 전략 vs 회귀 전략 선택에 필수.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "volume_profile_analysis",
            "description": "거래량 프로파일 분석. OBV 추세, 매집/분산 판단, 거래량 이상 감지. 가격 움직임의 신뢰도 확인.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fibonacci_retracement_analysis",
            "description": "피보나치 되돌림 분석. 주요 되돌림 레벨(0.382, 0.5, 0.618)에서 지지/저항 판단.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "volatility_regime_analysis",
            "description": "변동성 체제 분석. ATR 퍼센타일로 현재 변동성 수준 판단. 포지션 크기 조절에 활용.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mean_reversion_analysis",
            "description": "평균 회귀 분석. Z-Score로 현재 가격이 평균 대비 얼마나 벗어났는지 판단. 극단 구간에서 반전 포착.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "momentum_rank_analysis",
            "description": "모멘텀 순위 분석. 1주/1개월/3개월 수익률 가중합산. 모멘텀 가속/감속 판단.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "support_resistance_analysis",
            "description": "지지/저항선 분석. 피봇포인트 + 스윙 고저점 기반. 진입/청산 가격대와 Risk:Reward 비율 계산.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "correlation_regime_analysis",
            "description": "수익률 자기상관 분석. Hurst 지수로 추세 지속/평균 회귀/랜덤워크 체제 판단. 전략 선택 근거.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "risk_position_sizing",
            "description": "포지션 사이징/리스크 관리. ATR 기반 손절/익절가, 권장 매수 수량, 분할 진입 계획, 비중 경고를 산출.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kelly_criterion_analysis",
            "description": "켈리 기준 배팅 분석. 과거 승률/손익비로 최적 투자 비중 산출. 풀켈리/하프켈리/쿼터켈리 제공.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "beta_correlation_analysis",
            "description": "베타/상관관계 분석. SPY 대비 베타, 알파, 상관계수, 정보비율. 시장 대비 초과수익 판단.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "event_driven_analysis",
            "description": "이벤트 드리븐 분석. 실적발표 일정, 52주 고저, 배당락, 변동성 스파이크, 애널리스트 컨센서스.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "insider_trading_analysis",
            "description": "내부자 거래 분석. CEO/CFO/임원 매수매도 패턴, C-Suite 거래 집중도, 최근 30일 거래 동향 분석.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "money_flow_index_analysis",
            "description": "MFI(자금흐름지수) 분석. 거래량 가중 과매수(>80)/과매도(<20) 탐지. 저유동성 거짓 돌파 보완.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rsi_mfi_combined_analysis",
            "description": "RSI+MFI 조합 분석. 합치 과매수/매도, 이중 다이버전스, 거짓 돌파(거래량 확인 없는 RSI 극단) 감지.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "macd_rsi_cross_analysis",
            "description": "MACD 크로스+RSI 동시 조건. MACD bearish cross ∧ RSI>70 → score=-7(STRONG_BEARISH), bullish cross ∧ RSI<30 → score=+7(STRONG_BULLISH).",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "piotroski_fscore_analysis",
            "description": "Piotroski F-Score(0-9): 수익성·레버리지·운영효율 9 신호 기반 재무 건전성. 7-9 BUY, 0-2 SELL.",
        }
    },
    {
        "type": "function",
        "function": {
            "name": "altman_zscore_analysis",
            "description": "Altman Z-Score 도산 위험 분석. safe(BUY)/grey(NEUTRAL)/distress(SELL). 상장사 Z, 비상장/한국 Z'-Score.",
        }
    },
]

# Ollama용 간소화 tool 이름 목록
TOOL_NAMES = [t["function"]["name"] for t in TOOL_DEFINITIONS]


# ═══════════════════════════════════════════════════════════════
#  차트 분석 에이전트 (LLM 오케스트레이션)
# ═══════════════════════════════════════════════════════════════

class ChartAnalysisAgent:
    """LLM이 22개 tool 중 필요한 것을 선택하여 분석을 수행하는 에이전트 (P2: F-Score/Z-Score 추가)"""

    MAX_ITERATIONS = 5  # tool call 최대 반복 횟수

    def __init__(self, ticker: str, df: pd.DataFrame):
        self.ticker = ticker
        self.df = df
        self.tools = AnalysisTools(ticker, df)
        self.tool_results = []  # 실행된 tool 결과 누적
        self._tool_map = {
            "trend_ma_analysis": self.tools.trend_ma_analysis,
            "rsi_divergence_analysis": self.tools.rsi_divergence_analysis,
            "bollinger_squeeze_analysis": self.tools.bollinger_squeeze_analysis,
            "macd_momentum_analysis": self.tools.macd_momentum_analysis,
            "adx_trend_strength_analysis": self.tools.adx_trend_strength_analysis,
            "volume_profile_analysis": self.tools.volume_profile_analysis,
            "fibonacci_retracement_analysis": self.tools.fibonacci_retracement_analysis,
            "volatility_regime_analysis": self.tools.volatility_regime_analysis,
            "mean_reversion_analysis": self.tools.mean_reversion_analysis,
            "momentum_rank_analysis": self.tools.momentum_rank_analysis,
            "support_resistance_analysis": self.tools.support_resistance_analysis,
            "correlation_regime_analysis": self.tools.correlation_regime_analysis,
            "risk_position_sizing": self.tools.risk_position_sizing,
            "kelly_criterion_analysis": self.tools.kelly_criterion_analysis,
            "beta_correlation_analysis": self.tools.beta_correlation_analysis,
            "event_driven_analysis": self.tools.event_driven_analysis,
            "entry_plan_analysis": self.tools.entry_plan_analysis,
            # Step 5+6: 신규 도구
            "money_flow_index_analysis": self.tools.money_flow_index_analysis,
            "rsi_mfi_combined_analysis": self.tools.rsi_mfi_combined_analysis,
            "macd_rsi_cross_analysis": self.tools.macd_rsi_cross_analysis,
            # P2: 펀더멘털 점수 도구
            "piotroski_fscore_analysis": self.tools.piotroski_fscore_analysis,
            "altman_zscore_analysis": self.tools.altman_zscore_analysis,
        }

    def _execute_tool(self, name: str) -> dict:
        """tool 이름으로 분석 실행"""
        fn = self._tool_map.get(name)
        if fn:
            return fn()
        return {"tool": name, "error": f"Unknown tool: {name}"}

    def run_all_tools(self) -> list:
        """전체 tool 실행 (LLM 없이 전수 분석).

        entry_plan_analysis는 다른 도구 결과를 입력으로 받기 때문에 마지막에 실행.
        """
        results = []
        for name, fn in self._tool_map.items():
            if name == "entry_plan_analysis":
                continue  # 마지막 단계에서 별도 실행
            try:
                results.append(fn())
            except Exception as e:
                results.append({"tool": name, "error": str(e), "signal": "neutral", "score": 0})

        # 종합 score 기반으로 임시 signal/confidence를 산출하여 entry_plan에 전달
        avg_score = 0
        valid_scores = [r.get("score", 0) for r in results if isinstance(r.get("score"), (int, float))]
        if valid_scores:
            avg_score = sum(valid_scores) / len(valid_scores)
        composite_signal = "buy" if avg_score > 2 else ("sell" if avg_score < -2 else "neutral")
        composite_confidence = min(10.0, abs(avg_score) + 3.0) if valid_scores else 5.0

        try:
            entry_result = self.tools.entry_plan_analysis(
                signal=composite_signal,
                confidence=composite_confidence,
                other_results=results,
            )
            results.append(entry_result)
        except Exception as e:
            results.append({
                "tool": "entry_plan_analysis",
                "error": str(e),
                "signal": "neutral",
                "score": 0,
            })

        self.tool_results = results
        return results

    def compute_composite_score(self) -> dict:
        """전체 결과를 종합하여 최종 스코어 산출"""
        if not self.tool_results:
            self.run_all_tools()

        scores = []
        signals = {"buy": 0, "sell": 0, "neutral": 0}
        tool_summaries = []

        for r in self.tool_results:
            score = r.get("score", 0)
            signal = r.get("signal", "neutral")
            scores.append(score)
            signals[signal] = signals.get(signal, 0) + 1
            tool_summaries.append({
                "tool": r.get("tool", "unknown"),
                "name": r.get("name", ""),
                "signal": signal,
                "score": score,
                "detail": r.get("detail", ""),
            })

        avg_score = float(np.mean(scores))
        total = len(self.tool_results)

        if avg_score > 2:
            final_signal = "BUY"
        elif avg_score < -2:
            final_signal = "SELL"
        else:
            final_signal = "HOLD"

        # 신뢰도 (의견 일치도 기반)
        max_agreement = max(signals.values())
        confidence = round(max_agreement / total * 10, 1) if total > 0 else 0

        return {
            "ticker": self.ticker,
            "analysis_date": datetime.now().isoformat(),
            "final_signal": final_signal,
            "composite_score": round(avg_score, 2),
            "confidence": confidence,
            "signal_distribution": signals,
            "tool_count": total,
            "tool_summaries": tool_summaries,
            "tool_details": self.tool_results,
        }

    # ── LLM 에이전트 모드 ────────────────────────────────────

    def run(self, mode: str = "ollama") -> dict:
        """
        LLM 에이전트 모드 실행
        1) LLM에 tool 목록 제공
        2) LLM이 필요한 tool 선택
        3) tool 실행 → 결과를 LLM에 피드백
        4) LLM이 최종 판단
        """
        if mode == "gpt4o":
            return self._run_gpt4o_agent()
        elif mode == "ollama":
            return self._run_ollama_agent()
        else:
            # LLM 없이 전수 분석
            return self.compute_composite_score()

    def _build_agent_system_prompt(self) -> str:
        return f"""당신은 주식 차트 분석 전문 에이전트다.

역할:
- {self.ticker} 종목에 대해 제공된 분석 도구(tool)를 사용하여 종합 판단을 내린다.
- 16개의 분석 도구가 있다. 상황에 따라 필요한 도구를 선택하여 호출한다.
- 최소 8개 이상의 도구를 사용해야 한다.
- 각 도구의 결과를 종합하여 최종 매수/매도/관망 판단을 내린다.

분석 도구 목록:
1. trend_ma_analysis - 이동평균선 배열 (골든/데드크로스)
2. rsi_divergence_analysis - RSI 다이버전스
3. bollinger_squeeze_analysis - 볼린저밴드 스퀴즈
4. macd_momentum_analysis - MACD 모멘텀
5. adx_trend_strength_analysis - ADX 추세 강도
6. volume_profile_analysis - 거래량 프로파일
7. fibonacci_retracement_analysis - 피보나치 되돌림
8. volatility_regime_analysis - 변동성 체제
9. mean_reversion_analysis - 평균 회귀 (Z-Score)
10. momentum_rank_analysis - 모멘텀 순위
11. support_resistance_analysis - 지지/저항선
12. correlation_regime_analysis - 수익률 자기상관
13. risk_position_sizing - 포지션 사이징/리스크 관리 (ATR 손절, 매수 수량, 분할 진입)
14. kelly_criterion_analysis - 켈리 기준 배팅 (승률/손익비 → 최적 비중)
15. beta_correlation_analysis - 베타/상관관계 (SPY 대비 베타, 알파, 정보비율)
16. event_driven_analysis - 이벤트 드리븐 (실적발표, 배당락, 52주 고저, 애널리스트)

규칙:
1. 먼저 기본 도구(1~6)를 실행하고, 결과를 보고 필요한 퀀트 도구(7~12)를 추가 실행한다.
2. 각 도구는 인자 없이 호출한다.
3. 모든 도구 실행이 끝나면 종합 판단을 한국어로 작성한다.
4. 감정 없이 데이터 기반으로만 판단한다."""

    def _run_gpt4o_agent(self) -> dict:
        """GPT-4o function calling + vision 기반 에이전트"""
        if not OPENAI_API_KEY:
            print("  [경고] OPENAI_API_KEY 없음. 전수 분석 모드로 전환.")
            return self.compute_composite_score()

        messages = [
            {"role": "system", "content": self._build_agent_system_prompt()},
            {"role": "user", "content": f"{self.ticker} 종목을 분석해라. 필요한 도구를 선택하여 호출하라."},
        ]

        all_tool_results = []

        for iteration in range(self.MAX_ITERATIONS):
            try:
                resp = httpx.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o",
                        "messages": messages,
                        "tools": TOOL_DEFINITIONS,
                        "tool_choice": "auto",
                        "temperature": 0.2,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]
                msg = choice["message"]
                messages.append(msg)

                if not msg.get("tool_calls"):
                    llm_conclusion = msg.get("content", "")
                    break

                for tc in msg["tool_calls"]:
                    fn_name = tc["function"]["name"]
                    print(f"    → tool: {fn_name}")
                    tool_result = self._execute_tool(fn_name)
                    all_tool_results.append(tool_result)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })

            except Exception as e:
                print(f"  [GPT-4o 에이전트 오류] {e}")
                llm_conclusion = f"[오류] {e}"
                break
        else:
            llm_conclusion = "최대 반복 횟수 초과"

        self.tool_results = all_tool_results
        composite = self.compute_composite_score()

        chart_path = generate_agent_chart(self.ticker, self.df, composite)
        if chart_path and os.path.exists(chart_path):
            composite["chart_path"] = chart_path
            try:
                print("    [Vision] 차트 이미지를 GPT-4o에 전달하여 패턴 분석...")
                with open(chart_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode("utf-8")
                vision_resp = httpx.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o",
                        "messages": [
                            {"role": "system", "content": "당신은 주식 차트 패턴 분석 전문가다. 차트 이미지를 보고 기술적 패턴(헤드앤숄더, 더블탑/바텀, 삼각수렴, 채널, 깃발 등)을 식별하고 한국어로 분석하라."},
                            {"role": "user", "content": [
                                {"type": "text", "text": f"{self.ticker} 차트를 분석하라. 가격 패턴, 이동평균선 배열, 거래량 특성, RSI/MACD 상태를 종합하여 기술적 소견을 작성하라."},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"}},
                            ]},
                        ],
                        "max_tokens": 1500,
                        "temperature": 0.2,
                    },
                    timeout=90,
                )
                vision_resp.raise_for_status()
                vision_text = vision_resp.json()["choices"][0]["message"]["content"]
                llm_conclusion = f"{llm_conclusion}\n\n## 차트 패턴 분석 (Vision)\n{vision_text}"
                print("    [Vision] 차트 패턴 분석 완료")
            except Exception as e:
                print(f"    [Vision 오류] {e}")

        composite["llm_conclusion"] = llm_conclusion
        composite["agent_mode"] = "gpt4o"
        return composite

    def _run_ollama_agent(self) -> dict:
        """Ollama 기반 에이전트 (2단계: tool 선택 → 종합 판단)"""
        try:
            resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
            if resp.status_code != 200:
                raise ConnectionError("Ollama 서버 응답 없음")
        except Exception:
            print("  [경고] Ollama 서버 연결 실패. 전수 분석 모드로 전환.")
            return self.compute_composite_score()

        # Step 1: 전체 tool 실행 (Ollama는 function calling 미지원 모델이 많으므로)
        print("    [Step 1] 16개 분석 도구 실행...")
        self.run_all_tools()

        for r in self.tool_results:
            print(f"      ✓ {r.get('name', r.get('tool', '?'))}: {r.get('signal', '?')} (점수: {r.get('score', 0)})")

        # Step 2: 결과를 Ollama에 전달하여 종합 판단 요청
        composite = self.compute_composite_score()
        summary_text = self._format_tool_results_for_llm()

        prompt = f"""{self._build_agent_system_prompt()}

## {self.ticker} 분석 도구 실행 결과

{summary_text}

## 종합 스코어
- 평균 점수: {composite['composite_score']} / 10
- 신호 분포: 매수 {composite['signal_distribution']['buy']}개, 매도 {composite['signal_distribution']['sell']}개, 중립 {composite['signal_distribution']['neutral']}개
- 시스템 판단: {composite['final_signal']}

위 16개 도구의 분석 결과를 종합하여 최종 판단을 한국어로 작성하라.
다음 형식을 따르라:

## 종합 판단
[매수/매도/관망] (신뢰도: X/10)

## 기술적 분석 요약
[6개 기술 도구 결과 종합]

## 퀀트 분석 요약
[6개 퀀트 도구 결과 종합]

## 핵심 근거
[판단의 핵심 근거 3~5개]

## 리스크 요인
[주의사항 2~3개]

## 매매 전략
[포지션 사이징 결과 기반 진입/손절/익절 가격, 분할 매수 계획, 경고 사항]"""

        try:
            print("    [Step 2] LLM 종합 판단 요청 중...")
            resp = httpx.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 4096},
                },
                timeout=180,
            )
            resp.raise_for_status()
            llm_conclusion = resp.json().get("response", "[응답 없음]")
        except Exception as e:
            print(f"  [Ollama 종합 판단 오류] {e}")
            llm_conclusion = f"[LLM 오류] {e}\n\n시스템 자동 판단: {composite['final_signal']} (점수: {composite['composite_score']})"

        composite["llm_conclusion"] = llm_conclusion
        composite["agent_mode"] = "ollama"
        return composite

    def _format_tool_results_for_llm(self) -> str:
        """tool 결과를 LLM 입력용 텍스트로 포매팅"""
        lines = []
        for i, r in enumerate(self.tool_results, 1):
            lines.append(f"### {i}. {r.get('name', r.get('tool', '?'))}")
            lines.append(f"- 신호: {r.get('signal', '?')}")
            lines.append(f"- 점수: {r.get('score', 0)} / 10")
            lines.append(f"- 요약: {r.get('detail', '')}")
            # 주요 수치 포함
            for k, v in r.items():
                if k not in ('tool', 'name', 'signal', 'score', 'detail') and not isinstance(v, (dict, list)):
                    lines.append(f"- {k}: {v}")
            lines.append("")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  차트 이미지 생성 (에이전트 결과용)
# ═══════════════════════════════════════════════════════════════

def generate_agent_chart(ticker: str, df: pd.DataFrame, composite: dict, save_path: str = None) -> Optional[str]:
    """4패널 에이전트 차트: 가격+MA / 거래량 / RSI / MACD"""
    if save_path is None:
        save_path = os.path.join(OUTPUT_DIR, f"{ticker}_agent_analysis.png")

    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec

        BG = '#0b0e14'
        CARD = '#1d2026'
        GRID = '#32353c'
        TEXT = '#e1e2eb'
        GREEN = '#02d4a1'
        RED = '#fd526f'
        GOLD = '#ffb347'

        display_df = df.tail(120).copy()
        fig = plt.figure(figsize=(18, 14), facecolor=BG)
        gs = GridSpec(4, 1, height_ratios=[3, 1, 1, 1], hspace=0.08, figure=fig)

        signal_color = {'BUY': GREEN, 'SELL': RED, 'HOLD': GOLD}.get(
            composite.get('final_signal', 'HOLD'), GOLD)

        risk_info = ""
        for td in composite.get("tool_details", []):
            if td.get("tool") == "risk_position_sizing":
                sl = td.get("stop_loss", "")
                tp = td.get("take_profit", "")
                qty = td.get("recommended_qty", "")
                risk_info = f"  |  SL: ${sl}  TP: ${tp}  Qty: {qty}"
                break

        # ── Panel 1: Price + MA ──
        ax1 = fig.add_subplot(gs[0])
        ax1.set_facecolor(CARD)
        ax1.plot(display_df.index, display_df['Close'], color=TEXT, linewidth=1.3, label='Close')

        ma_colors = {}
        for p in SMA_PERIODS:
            col = f'SMA_{p}'
            if col in display_df.columns:
                c = {'5': '#aec6ff', '20': '#FFD700', '50': '#FF8C00', '120': '#aec6ff', '200': '#FF1493'}.get(str(p), '#aec6ff')
                ma_colors[col] = c
                ax1.plot(display_df.index, display_df[col], color=c, linewidth=0.8, alpha=0.7, label=col)

        bbu = f'BBU_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'
        bbl = f'BBL_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'
        if bbu in display_df.columns:
            ax1.fill_between(display_df.index, display_df[bbu], display_df[bbl], alpha=0.08, color='#aec6ff')

        ax1.set_title(
            f"{ticker}  |  {composite.get('final_signal', '?')} ({composite.get('composite_score', 0):+.2f})"
            f"  |  Confidence: {composite.get('confidence', 0)}/10  |  Style: {TRADING_STYLE}{risk_info}",
            color=signal_color, fontsize=13, fontweight='bold', loc='left', pad=10
        )
        ax1.legend(loc='upper left', fontsize=7, facecolor=CARD, edgecolor=GRID, labelcolor=TEXT)
        ax1.tick_params(colors=TEXT, labelsize=8)
        ax1.set_ylabel('Price', color=TEXT, fontsize=9)
        ax1.grid(True, color=GRID, alpha=0.3, linewidth=0.5)
        for spine in ax1.spines.values():
            spine.set_color(GRID)
        ax1.set_xticklabels([])

        # ── Panel 2: Volume ──
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax2.set_facecolor(CARD)
        vol_colors = [GREEN if display_df['Close'].iloc[i] >= display_df['Close'].iloc[max(0, i-1)]
                      else RED for i in range(len(display_df))]
        ax2.bar(display_df.index, display_df['Volume'], color=vol_colors, alpha=0.6, width=0.8)
        if 'Volume_SMA_20' in display_df.columns:
            ax2.plot(display_df.index, display_df['Volume_SMA_20'], color=GOLD, linewidth=0.8, label='Vol MA20')
        ax2.set_ylabel('Volume', color=TEXT, fontsize=9)
        ax2.tick_params(colors=TEXT, labelsize=8)
        ax2.grid(True, color=GRID, alpha=0.3, linewidth=0.5)
        ax2.legend(loc='upper left', fontsize=7, facecolor=CARD, edgecolor=GRID, labelcolor=TEXT)
        for spine in ax2.spines.values():
            spine.set_color(GRID)
        ax2.set_xticklabels([])

        # ── Panel 3: RSI ──
        ax3 = fig.add_subplot(gs[2], sharex=ax1)
        ax3.set_facecolor(CARD)
        if 'RSI' in display_df.columns:
            rsi = display_df['RSI']
            ax3.plot(display_df.index, rsi, color='#aec6ff', linewidth=1.0)
            ax3.axhline(RSI_OVERBOUGHT, color=RED, linewidth=0.6, linestyle='--', alpha=0.7)
            ax3.axhline(RSI_OVERSOLD, color=GREEN, linewidth=0.6, linestyle='--', alpha=0.7)
            ax3.axhline(50, color=GRID, linewidth=0.4, linestyle=':')
            ax3.fill_between(display_df.index, rsi, RSI_OVERBOUGHT, where=(rsi >= RSI_OVERBOUGHT), alpha=0.15, color=RED)
            ax3.fill_between(display_df.index, rsi, RSI_OVERSOLD, where=(rsi <= RSI_OVERSOLD), alpha=0.15, color=GREEN)
            ax3.set_ylim(10, 90)
        ax3.set_ylabel('RSI', color=TEXT, fontsize=9)
        ax3.tick_params(colors=TEXT, labelsize=8)
        ax3.grid(True, color=GRID, alpha=0.3, linewidth=0.5)
        for spine in ax3.spines.values():
            spine.set_color(GRID)
        ax3.set_xticklabels([])

        # ── Panel 4: MACD ──
        macd_col = f'MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        sig_col = f'MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        hist_col = f'MACDh_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'

        ax4 = fig.add_subplot(gs[3], sharex=ax1)
        ax4.set_facecolor(CARD)
        if macd_col in display_df.columns:
            ax4.plot(display_df.index, display_df[macd_col], color='#aec6ff', linewidth=1.0, label='MACD')
            ax4.plot(display_df.index, display_df[sig_col], color=GOLD, linewidth=0.8, label='Signal')
            hist = display_df[hist_col]
            hist_colors = [GREEN if v >= 0 else RED for v in hist]
            ax4.bar(display_df.index, hist, color=hist_colors, alpha=0.5, width=0.8)
            ax4.axhline(0, color=GRID, linewidth=0.4)
        ax4.set_ylabel('MACD', color=TEXT, fontsize=9)
        ax4.tick_params(colors=TEXT, labelsize=8)
        ax4.grid(True, color=GRID, alpha=0.3, linewidth=0.5)
        ax4.legend(loc='upper left', fontsize=7, facecolor=CARD, edgecolor=GRID, labelcolor=TEXT)
        for spine in ax4.spines.values():
            spine.set_color(GRID)

        plt.xticks(rotation=30, ha='right')

        fig.savefig(save_path, dpi=150, facecolor=BG, bbox_inches='tight')
        plt.close(fig)
        return save_path

    except Exception as e:
        print(f"  [에이전트 차트 생성 오류] {e}")
        return None
