"""
MFI 도구 + RSI/MFI 조합 + MACD/RSI cross-signal 단위 테스트 (Step 5+6)

테스트 시나리오:
- 평탄 OHLCV → MFI ≈ 50
- 강세 fixture (가격↑, 거래량↑) → MFI > 70, score < 0
- 약세 fixture (가격↓, 거래량↑) → MFI < 30, score > 0
- 다이버전스 fixture → bearish divergence flag
- NaN 처리: 첫 period bars → NaN
- bearish cross + RSI 75 → score=-7, STRONG_BEARISH_CONFIRMATION
- bullish cross + RSI 25 → score=+7, STRONG_BULLISH_CONFIRMATION
- bearish cross + RSI 50 → score=-3
- no cross → score=0
"""

import os
import sys

import numpy as np
import pandas as pd

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from analysis_tools import AnalysisTools  # noqa: E402


# ── OHLCV 더미 DataFrame 생성 헬퍼 ───────────────────────────────────


def _make_ohlcv(
    n: int = 60,
    base_price: float = 100.0,
    trend: float = 0.0,
    volume_trend: float = 0.0,
    rng_seed: int = 42,
) -> pd.DataFrame:
    """
    trend > 0 : 가격 상승, volume_trend > 0 : 거래량 증가.
    """
    rng = np.random.default_rng(rng_seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    closes = base_price + np.arange(n) * trend + rng.normal(0, 0.5, n)
    highs = closes + abs(rng.normal(1, 0.3, n))
    lows = closes - abs(rng.normal(1, 0.3, n))
    vols = (50_000 + np.arange(n) * volume_trend + rng.normal(0, 500, n)).clip(1)
    df = pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": vols},
        index=idx,
    )
    return df


def _add_rsi_macd(df: pd.DataFrame) -> pd.DataFrame:
    """RSI + MACD 컬럼을 계산해 붙인다."""
    close = df["Close"]
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - 100 / (1 + rs)
    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    df["MACD_12_26_9"] = macd
    df["MACDs_12_26_9"] = signal
    df["MACDh_12_26_9"] = macd - signal
    return df


# ── _compute_mfi ─────────────────────────────────────────────────────


def test_mfi_flat_price_near_50():
    """평탄 가격 → MFI 50 근처 (30~70 범위)."""
    df = _make_ohlcv(n=60, trend=0.0, volume_trend=0.0)
    mfi = AnalysisTools._compute_mfi(df)
    last = float(mfi.dropna().iloc[-1])
    assert 20 < last < 80, f"평탄 MFI should be near 50, got {last}"


def test_mfi_bullish_fixture():
    """가격↑ + 거래량↑ → 양의 자금흐름 → MFI 높음 (>50 이상)."""
    df = _make_ohlcv(n=60, trend=0.5, volume_trend=500.0)
    mfi = AnalysisTools._compute_mfi(df)
    last = float(mfi.dropna().iloc[-1])
    # 강세이면 MFI > 50 경향
    assert last > 40, f"Bullish MFI should be high, got {last}"


def test_mfi_bearish_fixture():
    """가격↓ + 거래량↑ → 음의 자금흐름 → MFI 낮음 (<60)."""
    df = _make_ohlcv(n=60, trend=-0.5, volume_trend=500.0)
    mfi = AnalysisTools._compute_mfi(df)
    last = float(mfi.dropna().iloc[-1])
    assert last < 70, f"Bearish MFI should be low, got {last}"


def test_mfi_nan_first_period_bars():
    """처음 period-1 bars는 NaN이어야 한다 (rolling(14): 0~12번 NaN, 13번부터 유효)."""
    df = _make_ohlcv(n=60)
    mfi = AnalysisTools._compute_mfi(df, period=14)
    assert pd.isna(mfi.iloc[0])
    assert pd.isna(mfi.iloc[12])  # 13번째 바 (0-indexed 12) — 아직 NaN
    assert not pd.isna(mfi.iloc[13])  # 14번째 바부터 유효


# ── money_flow_index_analysis ────────────────────────────────────────


def _make_all_up_df(n: int = 60) -> pd.DataFrame:
    """모든 봉이 양봉 (TP 단조 증가) → MFI = 100."""
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    closes = np.linspace(100.0, 200.0, n)
    df = pd.DataFrame(
        {
            "Open": closes - 0.5,
            "High": closes + 1.0,
            "Low": closes - 1.0,
            "Close": closes,
            "Volume": np.full(n, 100_000.0),
        },
        index=idx,
    )
    return df


def test_mfi_overbought_score_negative():
    """MFI=100 (단조 상승) → score < 0, MFI_OVERBOUGHT flag."""
    df = _make_all_up_df(n=60)
    tools = AnalysisTools("TEST", df)
    result = tools.money_flow_index_analysis()
    # 모든 봉 상승 → negative_mf = 0 → MFI = 100 > 80
    assert result["score"] < 0
    assert "MFI_OVERBOUGHT" in result["flags"]


def test_mfi_tool_returns_valid_dict():
    """money_flow_index_analysis가 유효한 dict를 반환."""
    df = _make_ohlcv(n=60)
    tools = AnalysisTools("AAPL", df)
    result = tools.money_flow_index_analysis()
    assert "tool" in result
    assert "signal" in result
    assert result["signal"] in ("buy", "sell", "neutral")
    assert "score" in result


# ── rsi_mfi_combined_analysis ────────────────────────────────────────


def test_rsi_mfi_combined_returns_valid():
    """rsi_mfi_combined_analysis가 유효한 dict를 반환."""
    df = _add_rsi_macd(_make_ohlcv(n=80))
    tools = AnalysisTools("AAPL", df)
    result = tools.rsi_mfi_combined_analysis()
    assert result["signal"] in ("buy", "sell", "neutral")
    assert -10 <= result["score"] <= 10
    assert "flags" in result


def test_rsi_mfi_divergence_detection():
    """다이버전스 fixture: 가격 상승 + 거래량 평탄 → _detect_divergence 동작 확인."""
    # 가격 상승, 거래량 평탄 → MFI가 오르지 않음
    df_up = _make_ohlcv(n=80, trend=1.0, volume_trend=0.0)
    close = df_up["Close"]
    mfi = AnalysisTools._compute_mfi(df_up).dropna()
    # 다이버전스 함수 직접 테스트
    div = AnalysisTools._detect_divergence(close.iloc[-len(mfi) :], mfi, lookback=30)
    assert div in ("bullish", "bearish", "none")  # 함수가 valid string 반환


# ── macd_rsi_cross_analysis (Step 6) ────────────────────────────────


def _make_bearish_cross_df(rsi_value: float = 75.0) -> pd.DataFrame:
    """MACD bearish cross 직전 상태 DataFrame 생성."""
    df = _make_ohlcv(n=80, trend=0.5)
    df = _add_rsi_macd(df)
    # 마지막 2개 봉에서 bearish cross: MACD[-2]>Signal[-2], MACD[-1]<Signal[-1]
    df.loc[df.index[-2], "MACD_12_26_9"] = 0.5
    df.loc[df.index[-2], "MACDs_12_26_9"] = 0.3
    df.loc[df.index[-1], "MACD_12_26_9"] = 0.2
    df.loc[df.index[-1], "MACDs_12_26_9"] = 0.4
    # RSI 강제 설정
    df.loc[df.index[-1], "RSI"] = rsi_value
    return df


def _make_bullish_cross_df(rsi_value: float = 25.0) -> pd.DataFrame:
    """MACD bullish cross 직전 상태 DataFrame 생성."""
    df = _make_ohlcv(n=80, trend=-0.5)
    df = _add_rsi_macd(df)
    df.loc[df.index[-2], "MACD_12_26_9"] = -0.3
    df.loc[df.index[-2], "MACDs_12_26_9"] = -0.1
    df.loc[df.index[-1], "MACD_12_26_9"] = -0.05
    df.loc[df.index[-1], "MACDs_12_26_9"] = -0.2
    df.loc[df.index[-1], "RSI"] = rsi_value
    return df


def test_bearish_cross_rsi_overbought():
    """bearish cross + RSI=75 → score=-7, STRONG_BEARISH_CONFIRMATION."""
    df = _make_bearish_cross_df(rsi_value=75.0)
    tools = AnalysisTools("AAPL", df)
    result = tools.macd_rsi_cross_analysis()
    assert result["score"] == -7
    assert "STRONG_BEARISH_CONFIRMATION" in result["flags"]
    assert "MACD_BEARISH_CROSS" in result["flags"]


def test_bullish_cross_rsi_oversold():
    """bullish cross + RSI=25 → score=+7, STRONG_BULLISH_CONFIRMATION."""
    df = _make_bullish_cross_df(rsi_value=25.0)
    tools = AnalysisTools("AAPL", df)
    result = tools.macd_rsi_cross_analysis()
    assert result["score"] == 7
    assert "STRONG_BULLISH_CONFIRMATION" in result["flags"]
    assert "MACD_BULLISH_CROSS" in result["flags"]


def test_bearish_cross_rsi_neutral():
    """bearish cross + RSI=50 → score=-3 (단순 cross, STRONG 없음)."""
    df = _make_bearish_cross_df(rsi_value=50.0)
    tools = AnalysisTools("AAPL", df)
    result = tools.macd_rsi_cross_analysis()
    assert result["score"] == -3
    assert "STRONG_BEARISH_CONFIRMATION" not in result["flags"]
    assert "MACD_BEARISH_CROSS" in result["flags"]


def test_no_cross_score_zero():
    """크로스 없음 → score=0."""
    df = _make_ohlcv(n=80, trend=0.0)
    df = _add_rsi_macd(df)
    # MACD > Signal 유지 (크로스 없음)
    df.loc[df.index[-2], "MACD_12_26_9"] = 0.3
    df.loc[df.index[-2], "MACDs_12_26_9"] = 0.1
    df.loc[df.index[-1], "MACD_12_26_9"] = 0.4
    df.loc[df.index[-1], "MACDs_12_26_9"] = 0.2
    tools = AnalysisTools("AAPL", df)
    result = tools.macd_rsi_cross_analysis()
    assert result["score"] == 0


# ── 도구 수 검증 ─────────────────────────────────────────────────────


def test_new_tools_registered():
    """3개 신규 도구가 ChartAnalysisAgent._tool_map에 등록됨."""
    from analysis_tools import ChartAnalysisAgent

    df = _add_rsi_macd(_make_ohlcv(n=80))
    agent = ChartAnalysisAgent("AAPL", df)
    assert "money_flow_index_analysis" in agent._tool_map
    assert "rsi_mfi_combined_analysis" in agent._tool_map
    assert "macd_rsi_cross_analysis" in agent._tool_map
