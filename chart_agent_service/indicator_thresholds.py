"""지표 해석 임계값 — 단일 출처.

2026-09 사후검증에서 **같은 숫자를 도구와 에이전트가 다르게 읽는** 사례가 반복됐다.

| 사례 | 도구 출력 | 에이전트 서술 |
|---|---|---|
| DB손해보험 | RSI 64.57 (`rsi_zone=neutral`) | "과매수 진입" (기준 70 미달) |
| DB손해보험 | 연환산 변동성 64.0% (`vol_label=매우 높음`) | "안정적" (S&P 평균의 3~4배) |
| 영원무역 | 거래량 0.47x | "경고 수준 1.5배 미만에 해당하지 않음" (임계 방향 반대) |

도구는 이미 라벨(`rsi_zone`·`vol_label`·`trend_strength`)을 내고 있었다. 문제는 그
기준이 각 도구에 흩어져 있어 **프롬프트에 실리지 않았다**는 것이다. 여기 모아서
도구와 에이전트 프롬프트가 같은 표를 보게 한다.

RSI 과매수/과매도는 `config.RSI_OVERBOUGHT/RSI_OVERSOLD`(운영자가 .env 로 조정)를
그대로 따른다 — 여기서 다시 정의하면 진실이 둘이 된다.
"""

from __future__ import annotations

try:
    from config import RSI_OVERBOUGHT, RSI_OVERSOLD
except Exception:  # config 없이 import 되는 환경(테스트 등)
    RSI_OVERBOUGHT, RSI_OVERSOLD = 70, 30

# RSI — 과매수/과매도는 config 값, 중간 구간만 여기서 정의한다.
RSI_BULLISH = 55      # 이상이면 강세 쪽 중립
RSI_BEARISH = 45      # 이하면 약세 쪽 중립

# ADX — 추세 강도 (Wilder 기준)
ADX_VERY_STRONG = 50
ADX_STRONG = 40
ADX_MODERATE = 25     # 25 미만은 '추세 없음'으로 본다

# 연환산 변동성(%) — 절대 기준. S&P500 장기 평균이 15~20% 수준이다.
VOL_EXTREME = 60
VOL_HIGH = 40
VOL_ABOVE_AVERAGE = 25
VOL_NORMAL = 15

# 거래량 배수 — 평균 대비. 1.5배 이상을 '급증'으로 본다.
VOLUME_SURGE = 1.5
VOLUME_DRY = 0.7      # 이하면 '거래 위축'


def rsi_label(rsi: float | None) -> str:
    if rsi is None:
        return "데이터 없음"
    if rsi > RSI_OVERBOUGHT:
        return f"과매수(>{RSI_OVERBOUGHT})"
    if rsi < RSI_OVERSOLD:
        return f"과매도(<{RSI_OVERSOLD})"
    if rsi >= RSI_BULLISH:
        return f"중립-강세({RSI_BULLISH}~{RSI_OVERBOUGHT})"
    if rsi <= RSI_BEARISH:
        return f"중립-약세({RSI_BEARISH}↓)"
    return f"중립({RSI_BEARISH}~{RSI_BULLISH})"


def adx_label(adx: float | None) -> str:
    if adx is None:
        return "데이터 없음"
    if adx >= ADX_VERY_STRONG:
        return f"매우 강한 추세(>={ADX_VERY_STRONG})"
    if adx >= ADX_STRONG:
        return f"강한 추세(>={ADX_STRONG})"
    if adx >= ADX_MODERATE:
        return f"추세 형성(>={ADX_MODERATE})"
    return f"추세 없음(<{ADX_MODERATE})"


def volatility_label(annualized_pct: float | None) -> str:
    if annualized_pct is None:
        return "데이터 없음"
    if annualized_pct > VOL_EXTREME:
        return f"매우 높음(>{VOL_EXTREME}%)"
    if annualized_pct > VOL_HIGH:
        return f"높음(>{VOL_HIGH}%)"
    if annualized_pct > VOL_ABOVE_AVERAGE:
        return f"평균 이상(>{VOL_ABOVE_AVERAGE}%)"
    if annualized_pct > VOL_NORMAL:
        return f"보통(>{VOL_NORMAL}%)"
    return f"낮음(<={VOL_NORMAL}%)"


def volume_label(ratio: float | None) -> str:
    if ratio is None:
        return "데이터 없음"
    if ratio >= VOLUME_SURGE:
        return f"급증(>={VOLUME_SURGE}x)"
    if ratio <= VOLUME_DRY:
        return f"위축(<={VOLUME_DRY}x)"
    return "보통"


def prompt_threshold_table() -> str:
    """에이전트 프롬프트에 그대로 싣는 임계 기준표.

    프롬프트와 도구가 다른 기준을 쓰면 리포트가 스스로와 모순된다.
    """
    return (
        "## 지표 해석 기준 (이 기준을 벗어난 서술은 하지 마세요)\n"
        f"- RSI: 과매수 > {RSI_OVERBOUGHT} / 과매도 < {RSI_OVERSOLD} / "
        f"중립 {RSI_OVERSOLD}~{RSI_OVERBOUGHT} "
        f"(그 안에서 {RSI_BULLISH} 이상은 강세 쪽, {RSI_BEARISH} 이하는 약세 쪽 중립)\n"
        f"- ADX: >= {ADX_VERY_STRONG} 매우 강함 / >= {ADX_STRONG} 강함 / "
        f">= {ADX_MODERATE} 추세 형성 / < {ADX_MODERATE} 추세 없음\n"
        f"- 연환산 변동성: > {VOL_EXTREME}% 매우 높음 / > {VOL_HIGH}% 높음 / "
        f"> {VOL_ABOVE_AVERAGE}% 평균 이상 / > {VOL_NORMAL}% 보통 / <= {VOL_NORMAL}% 낮음 "
        "(S&P500 장기 평균 15~20%)\n"
        f"- 거래량 배수: >= {VOLUME_SURGE}x 급증 / <= {VOLUME_DRY}x 위축\n"
        "- reversion_probability = 평균 회귀가 **발생할** 확률이다. "
        "낮으면(<10%) 회귀하지 않는다는 뜻이므로 추세 지속이 우세하고, "
        "높으면(>60%) 되돌림을 경계해야 한다. Z-score 의 크기와 혼동하지 말 것 — "
        "Z 가 커도 회귀확률이 낮으면 추세가 우세하다."
    )
