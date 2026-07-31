"""
매크로 경제 컨텍스트 모듈
- yfinance로 VIX, 미국채 수익률, DXY, WTI 유가 등 수집
- 시장 전반 분위기(regime) 판단
"""

from datetime import datetime, timezone
from typing import Dict, Optional

import yfinance as yf


# ── 지표 수집 ─────────────────────────────────────────────────────

MACRO_TICKERS = {
    "vix": "^VIX",
    "us10y": "^TNX",
    "dxy": "DX-Y.NYB",
    "oil_wti": "CL=F",
    "sp500": "^GSPC",
    "gold": "GC=F",
    # 한국 지수 — 2026-07-30 감사에서 누락 확인. 미국 지표만 보고 있어
    # KOSPI 폭락장(7/28 -10.84%, 7/29 -5.98%, 월중 8,303→5,594 = -32.6%)에도
    # 국내 종목 분석의 macro 기여가 0이었다.
    "kospi": "^KS11",
    "kosdaq": "^KQ11",
}


def _fetch_indicator(symbol: str, period: str = "1mo") -> Optional[Dict]:
    """종가 기준 현재값·1개월 트렌드 반환."""
    try:
        hist = yf.Ticker(symbol).history(period=period)
        if hist.empty or len(hist) < 5:
            return None
        close = hist["Close"].dropna()
        current = float(close.iloc[-1])
        month_ago = float(close.iloc[0])
        week_ago = float(close.iloc[-5]) if len(close) >= 5 else month_ago
        pct_1m = round((current / month_ago - 1) * 100, 2)
        pct_1w = round((current / week_ago - 1) * 100, 2)
        # 일간 변동률 — 급락은 1개월 추세에 묻힌다. -10%대 하루가
        # pct_1m 기준으로는 'stable'로 보일 수 있다.
        prev = float(close.iloc[-2]) if len(close) >= 2 else current
        pct_1d = round((current / prev - 1) * 100, 2) if prev else 0.0
        return {
            "value": round(current, 2),
            "pct_1d": pct_1d,
            "pct_1w": pct_1w,
            "pct_1m": pct_1m,
        }
    except Exception:
        return None


def _trend_label(pct: Optional[float], threshold: float = 2.0) -> str:
    if pct is None:
        return "unknown"
    if pct > threshold:
        return "rising"
    if pct < -threshold:
        return "falling"
    return "stable"


# ── 신호 판단 ─────────────────────────────────────────────────────


def _vix_signal(value: float, trend: str) -> str:
    if value < 15:
        return "risk_on"
    if value > 25:
        return "risk_off"
    return "risk_on" if trend == "falling" else "neutral"


def _us10y_signal(value: float, trend: str) -> str:
    if value > 4.5:
        return "headwind"
    if value < 3.5:
        return "tailwind"
    return "headwind" if trend == "rising" else "neutral"


def _dxy_signal(trend: str) -> str:
    if trend == "rising":
        return "headwind"  # 달러 강세 → EM·원자재 불리
    if trend == "falling":
        return "tailwind"
    return "neutral"


def compute_vhf(close, period: int = 28) -> float:  # type: ignore[annotation-unchecked]
    """Vertical Horizontal Filter — 추세 강도 지표 (Step 7)."""
    import numpy as np

    if len(close) < period + 1:
        return 0.35
    rolling_max = close.rolling(period).max()
    rolling_min = close.rolling(period).min()
    abs_changes = close.diff().abs().rolling(period).sum()
    numerator = float((rolling_max - rolling_min).iloc[-1])
    denominator = float(abs_changes.iloc[-1])
    if denominator == 0 or np.isnan(denominator):
        return 0.35
    return numerator / denominator


def _oil_signal(trend: str) -> str:
    if trend == "rising":
        return "inflationary"
    if trend == "falling":
        return "deflationary"
    return "neutral"


def _sp500_trend(pct_1m: Optional[float]) -> str:
    if pct_1m is None:
        return "neutral"
    if pct_1m > 3:
        return "bullish"
    if pct_1m < -3:
        return "bearish"
    return "neutral"


def _kr_market_stress(
    pct_1d: Optional[float],
    pct_1w: Optional[float],
    pct_1m: Optional[float] = None,
) -> str:
    """국내 지수 스트레스 판정.

    KRX 서킷브레이커 1단계가 -8%(1분 이상 지속)이므로 일간 -8%를 crash 기준으로
    쓴다. 주간/월간 낙폭은 며칠에 걸친 붕괴를 잡는다.

    스트레스 판정이 melt_up보다 우선한다 — 급락장의 반등일에 melt_up으로 읽으면
    가장 위험한 날에 경고가 사라진다 (2026-07-31: 일간 +13.95%였지만 월간 -24.8%).
    일간 ±8%는 방향과 무관하게 정상 국면이 아니다.
    """
    if pct_1d is None and pct_1w is None and pct_1m is None:
        return "unknown"
    d = pct_1d if pct_1d is not None else 0.0
    w = pct_1w if pct_1w is not None else 0.0
    m = pct_1m if pct_1m is not None else 0.0

    if d <= -8.0 or w <= -15.0 or m <= -20.0 or abs(d) >= 12.0:
        return "crash"
    if d <= -3.0 or w <= -7.0 or m <= -10.0 or abs(d) >= 8.0:
        return "stressed"
    if d >= 3.0 or w >= 7.0:
        return "melt_up"
    return "normal"


def _market_regime(vix_sig: str, us10y_sig: str, sp500_tr: str) -> str:
    if vix_sig == "risk_on" and sp500_tr == "bullish":
        return "risk_on"
    if vix_sig == "risk_off" or sp500_tr == "bearish":
        return "risk_off"
    return "neutral"


def _build_summary(
    vix_val, vix_sig, us10y_val, us10y_sig, dxy_sig, oil_sig, regime,
    kr_stress: str = "unknown", kospi_1d: Optional[float] = None,
) -> str:
    parts = []
    if vix_val:
        parts.append(f"VIX {vix_val:.1f}({'하락' if vix_sig == 'risk_on' else '상승'})")
    if us10y_val:
        parts.append(
            f"미국채10년 {us10y_val:.2f}%({'상승' if us10y_sig == 'headwind' else '안정'})"
        )
    if dxy_sig != "neutral":
        parts.append(f"달러({'강세' if dxy_sig == 'headwind' else '약세'})")
    if oil_sig != "neutral":
        parts.append(f"유가({'상승압력' if oil_sig == 'inflationary' else '하락'})")

    if kospi_1d is not None:
        parts.append(f"KOSPI {kospi_1d:+.2f}%(일간)")

    if regime == "risk_on":
        mood = "위험자산 선호 환경. 주식·성장주 유리."
    elif regime == "risk_off":
        mood = "위험 회피 환경. 방어주·채권 유리."
    else:
        mood = "중립적 환경. 종목별 선별 대응 필요."

    # 국내 지수 스트레스는 미국 기반 regime과 별개로 명시한다 —
    # 한국 종목 판단에서 이게 빠지면 폭락장에서 매수 신호가 나온다.
    kr_note = {
        "crash": " ⚠️ 국내 증시 급락 국면(서킷브레이커 수준). 국내 종목 신규 매수 부적합.",
        "stressed": " ⚠️ 국내 증시 약세 국면. 국내 종목 진입 신중.",
        "melt_up": " 국내 증시 급등 국면. 추격 매수 주의.",
    }.get(kr_stress, "")

    prefix = ", ".join(parts)
    body = f"{prefix}. {mood}" if prefix else mood
    return body + kr_note


# ── 메인 함수 ────────────────────────────────────────────────────


def fetch_macro_context() -> Dict:
    """주요 매크로 지표 수집 및 시장 분위기 판단."""
    raw = {}
    for key, sym in MACRO_TICKERS.items():
        raw[key] = _fetch_indicator(sym)

    def _extract(key):
        d = raw.get(key)
        return (d["value"] if d else None, d["pct_1m"] if d else None)

    def _extract_full(key):
        d = raw.get(key) or {}
        return (d.get("value"), d.get("pct_1d"), d.get("pct_1w"), d.get("pct_1m"))

    vix_val, vix_pct = _extract("vix")
    us10y_val, us10y_pct = _extract("us10y")
    dxy_val, dxy_pct = _extract("dxy")
    oil_val, oil_pct = _extract("oil_wti")
    sp500_val, sp500_pct = _extract("sp500")
    gold_val, gold_pct = _extract("gold")

    vix_trend = _trend_label(vix_pct, threshold=5.0)
    us10y_trend = _trend_label(us10y_pct, threshold=3.0)
    dxy_trend = _trend_label(dxy_pct, threshold=1.5)
    oil_trend = _trend_label(oil_pct, threshold=3.0)

    vix_sig = _vix_signal(vix_val or 20, vix_trend)
    us10y_sig = _us10y_signal(us10y_val or 4.0, us10y_trend)
    dxy_sig = _dxy_signal(dxy_trend)
    oil_sig = _oil_signal(oil_trend)
    sp500_tr = _sp500_trend(sp500_pct)
    regime = _market_regime(vix_sig, us10y_sig, sp500_tr)

    kospi_val, kospi_1d, kospi_1w, kospi_1m = _extract_full("kospi")
    kosdaq_val, kosdaq_1d, kosdaq_1w, kosdaq_1m = _extract_full("kosdaq")
    kr_stress = _kr_market_stress(kospi_1d, kospi_1w, kospi_1m)

    return {
        "vix": {
            "value": vix_val,
            "trend": vix_trend,
            "signal": vix_sig,
            "pct_1m": vix_pct,
        },
        "us10y": {
            "value": us10y_val,
            "trend": us10y_trend,
            "signal": us10y_sig,
            "pct_1m": us10y_pct,
        },
        "dxy": {
            "value": dxy_val,
            "trend": dxy_trend,
            "signal": dxy_sig,
            "pct_1m": dxy_pct,
        },
        "oil_wti": {
            "value": oil_val,
            "trend": oil_trend,
            "signal": oil_sig,
            "pct_1m": oil_pct,
        },
        "sp500": {
            "value": sp500_val,
            "trend": sp500_tr,
            "pct_1m": sp500_pct,
        },
        "gold": {
            "value": gold_val,
            "pct_1m": gold_pct,
        },
        "kospi": {
            "value": kospi_val,
            "pct_1d": kospi_1d,
            "pct_1w": kospi_1w,
            "pct_1m": kospi_1m,
        },
        "kosdaq": {
            "value": kosdaq_val,
            "pct_1d": kosdaq_1d,
            "pct_1w": kosdaq_1w,
            "pct_1m": kosdaq_1m,
        },
        "kr_market_stress": kr_stress,
        "sp500_trend": sp500_tr,
        "market_regime": regime,
        "summary": _build_summary(
            vix_val, vix_sig, us10y_val, us10y_sig, dxy_sig, oil_sig, regime,
            kr_stress=kr_stress, kospi_1d=kospi_1d,
        ),
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
