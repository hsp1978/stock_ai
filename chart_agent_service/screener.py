"""
한국 주식 기술적 스크리너 (V1).

파이프라인:
  [KOSPI+KOSDAQ 전체]
    → [시총 2,000억+ 필터]         약 280개
    → [배치 OHLCV 다운로드]
    → [지표 계산 (data_collector 재사용)]
    → [기술적 점수 0~100 계산]
    → [감점 적용]
    → [정규화 + 등급 부여]
    → [상위 N개 반환]

설계 원칙:
- 기존 analysis_tools.py 도구를 재구현하지 않음 (지표 계산만 데이터 레벨에서 사용)
- Watchlist에 자동 등록하지 않음 (SSOT 정책 준수)
- scan_log / signal_outcomes 테이블과 완전 분리 (screener_results 별도)
- pykrx 없어도 yfinance 폴백으로 부분 동작
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from decision_context import (
    build_multi_agent_context,
    build_screener_context,
    compare_decision_contexts,
)


# ─────────────────────────────────────────────────────────
#  설정 (환경변수로 조정 가능)
# ─────────────────────────────────────────────────────────
import os as _os

MIN_MARKET_CAP_KRW = float(_os.getenv("SCREENER_MIN_MARKET_CAP_KRW", "200_000_000_000"))  # 2천억
TOP_N_RESULTS = int(_os.getenv("SCREENER_TOP_N", "20"))
OHLCV_PERIOD_DAYS = int(_os.getenv("SCREENER_OHLCV_DAYS", "200"))


# ─────────────────────────────────────────────────────────
#  점수 체계 (가중치는 환경변수로 튜닝 가능)
# ─────────────────────────────────────────────────────────
SCORE_WEIGHTS = {
    "macd_cross":      30,  # 최근 10봉 이내 MACD 골든크로스
    "ma_alignment":    20,  # MA5 > MA20 > MA60 정배열
    "rsi_momentum":    20,  # RSI > 50 + 상승 기울기
    "volume_bullish":  15,  # 최근 3일 중 2일 이상 거래량↑ + 양봉
    "ma20_support":     5,  # 20일선 지지 확인
    "vwap_support":    10,  # VWAP20 지지/상향 추세 확인
}
# 최대 100점

PENALTY_WEIGHTS = {
    "macd_deadcross":     20,  # 데드크로스 발생 중
    "rsi_overbought":     15,  # RSI > 78 과매수
    "volume_declining":   10,  # 5일 연속 거래량 감소
    "vwap_breakdown":     10,  # VWAP20 하향 이탈
    "below_ma120":        10,  # 종가 < MA120 (장기 역행)
    "high_volatility":    15,  # 연환산 변동성 60%+ (극고변동성)
    "extreme_volatility": 25,  # 연환산 변동성 100%+ (비정상 변동성)
}

# 펀더멘털 필터 — 두 조건 모두 충족 시 자동 실격
# (PBR 단독 고평가는 성장주로 허용, 적자 + 고PBR 조합만 걸러냄)
FUNDAMENTAL_DISQUALIFY_EPS_MAX = 0        # EPS < 0 (적자)
FUNDAMENTAL_DISQUALIFY_PBR_MIN = 5.0      # P/B > 5.0 (동종업계 평균의 5배+)


# ─────────────────────────────────────────────────────────
#  데이터 수집 (유니버스 + 시총)
# ─────────────────────────────────────────────────────────
NAVER_MARKET_SUM_URL = "https://finance.naver.com/sise/sise_market_sum.naver"


def _parse_int_text(value: object) -> Optional[int]:
    text = str(value or "").strip().replace(",", "")
    if not text or not re.fullmatch(r"-?\d+", text):
        return None
    return int(text)


def _parse_naver_last_page(soup) -> int:
    last_page = 1
    for selector in ("td.pgRR a", "table.Nnavi a"):
        for link in soup.select(selector):
            href = link.get("href") or ""
            match = re.search(r"[?&]page=(\d+)", href)
            if match:
                last_page = max(last_page, int(match.group(1)))
    return last_page


def _parse_naver_market_sum_page(
    html: str,
    market_name: str,
    suffix: str,
    min_market_cap: float,
) -> Tuple[List[Dict], int]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict] = []

    for tr in soup.select("table.type_2 tr"):
        link = tr.select_one("a[href*='code=']")
        if not link:
            continue

        href = link.get("href") or ""
        match = re.search(r"code=(\d{6})", href)
        if not match:
            continue

        cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
        if len(cells) < 7:
            continue

        cap_100m = _parse_int_text(cells[6])
        if cap_100m is None:
            continue

        market_cap = float(cap_100m * 100_000_000)
        if market_cap < min_market_cap:
            continue

        code = match.group(1)
        rows.append({
            "ticker": f"{code}{suffix}",
            "name": link.get_text(" ", strip=True) or code,
            "market": market_name,
            "market_cap": market_cap,
        })

    return rows, _parse_naver_last_page(soup)


def _load_kr_universe_from_naver(min_market_cap: float) -> pd.DataFrame:
    import requests

    headers = {"User-Agent": "Mozilla/5.0"}
    rows: List[Dict] = []
    seen = set()

    for sosok, market_name, suffix in [(0, "KOSPI", ".KS"), (1, "KOSDAQ", ".KQ")]:
        page = 1
        last_page = 1

        while page <= last_page:
            resp = requests.get(
                NAVER_MARKET_SUM_URL,
                params={"sosok": sosok, "page": page},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            resp.encoding = "euc-kr"

            page_rows, parsed_last_page = _parse_naver_market_sum_page(
                resp.text,
                market_name=market_name,
                suffix=suffix,
                min_market_cap=min_market_cap,
            )
            last_page = max(last_page, parsed_last_page)

            for row in page_rows:
                if row["ticker"] in seen:
                    continue
                seen.add(row["ticker"])
                rows.append(row)

            # 네이버 시총 페이지는 내림차순이다. 해당 페이지에 기준 이상 종목이
            # 하나도 없으면 이후 페이지도 기준 미달로 보고 중단한다.
            if page > 1 and not page_rows:
                break

            page += 1

    return pd.DataFrame(rows)


def load_kr_universe(min_market_cap: float = MIN_MARKET_CAP_KRW) -> pd.DataFrame:
    """
    KOSPI + KOSDAQ 종목 중 시총 기준 이상만 반환.

    Returns:
        DataFrame with columns: ticker, name, market, market_cap
        ticker는 yfinance 형식 (예: 005930.KS / 136480.KS)
    """
    # 1순위: pykrx (가장 정확한 KRX 공식 데이터)
    try:
        from pykrx import stock
        today = datetime.now().strftime("%Y%m%d")

        rows = []
        for market_name, suffix in [("KOSPI", ".KS"), ("KOSDAQ", ".KQ")]:
            try:
                caps = stock.get_market_cap(today, market=market_name)
                if caps is None or caps.empty:
                    # 오늘 휴장이면 영업일 조회
                    bd = stock.get_nearest_business_day_in_a_week(today)
                    caps = stock.get_market_cap(bd, market=market_name)
            except Exception:
                continue

            if caps is None or caps.empty:
                continue

            # 컬럼: '시가총액', '거래량', '거래대금', '상장주식수' (pykrx)
            filtered = caps[caps['시가총액'] >= min_market_cap]
            for code, row in filtered.iterrows():
                try:
                    name = stock.get_market_ticker_name(code) or code
                except Exception:
                    name = code
                rows.append({
                    "ticker": f"{code}{suffix}",
                    "name": name,
                    "market": market_name,
                    "market_cap": float(row['시가총액']),
                })

        if rows:
            return pd.DataFrame(rows)
    except ImportError:
        pass
    except Exception as e:
        print(f"[screener] pykrx 오류, FDR로 폴백: {e}")

    # 2순위: FinanceDataReader
    try:
        import FinanceDataReader as fdr
        krx = fdr.StockListing('KRX')

        sym_col = 'Code' if 'Code' in krx.columns else 'Symbol'
        name_col = None
        for c in ('Name', '종목명', 'CompanyName'):
            if c in krx.columns:
                name_col = c
                break
        market_col = 'Market' if 'Market' in krx.columns else None
        cap_col = None
        for c in ('Marcap', 'MarketCap', '시가총액'):
            if c in krx.columns:
                cap_col = c
                break

        if not cap_col:
            print("[screener] FDR에 시총 컬럼 없음 — pykrx 설치 필요")
            return pd.DataFrame()

        filtered = krx[krx[cap_col] >= min_market_cap]
        rows = []
        for _, row in filtered.iterrows():
            code = str(row[sym_col])
            market = str(row.get(market_col, 'KOSPI'))
            suffix = '.KQ' if 'KOSDAQ' in market.upper() else '.KS'
            rows.append({
                "ticker": f"{code}{suffix}",
                "name": row.get(name_col, code) if name_col else code,
                "market": 'KOSDAQ' if suffix == '.KQ' else 'KOSPI',
                "market_cap": float(row[cap_col]),
            })
        return pd.DataFrame(rows)
    except ImportError:
        pass
    except Exception as e:
        print(f"[screener] FDR 오류: {e}")

    # 3순위: Naver Finance 시가총액 페이지
    try:
        naver = _load_kr_universe_from_naver(min_market_cap)
        if not naver.empty:
            print(f"[screener] Naver 시총 fallback 사용: {len(naver)}개")
            return naver
    except ImportError:
        pass
    except Exception as e:
        print(f"[screener] Naver 시총 fallback 오류: {e}")

    return pd.DataFrame()


# ─────────────────────────────────────────────────────────
#  지표 계산 (data_collector 재사용)
# ─────────────────────────────────────────────────────────
def _calc_indicators_lite(df: pd.DataFrame) -> pd.DataFrame:
    """
    스크리너 전용 경량 지표 계산.
    data_collector.calculate_indicators는 너무 많은 지표를 계산 (느림).
    스크리너는 필요한 것만 빠르게 계산.
    """
    df = df.copy()
    close = df['Close']
    volume = df['Volume']

    # 이동평균
    df['MA5'] = close.rolling(5, min_periods=5).mean()
    df['MA20'] = close.rolling(20, min_periods=20).mean()
    df['MA60'] = close.rolling(60, min_periods=60).mean()
    df['MA120'] = close.rolling(120, min_periods=120).mean()

    # RSI (Wilder's): 손실이 없는 강한 상승 구간은 RSI=100, 변동 없는 구간은 50
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    df['RSI'] = rsi

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']

    # 거래량 평균
    df['VOL_MA20'] = volume.rolling(20, min_periods=20).mean()

    # Rolling VWAP: 일봉 데이터 기준 20/60봉 거래량 가중 평균가
    typical_price = (df['High'] + df['Low'] + close) / 3
    volume_filled = volume.fillna(0)
    tpv = typical_price * volume_filled
    for period in (20, 60):
        vol_sum = volume_filled.rolling(period, min_periods=period).sum().replace(0, np.nan)
        vwap = tpv.rolling(period, min_periods=period).sum() / vol_sum
        df[f'VWAP_{period}'] = vwap
        df[f'VWAP_DIST_{period}'] = (close / vwap - 1) * 100
    df['VWAP_SLOPE_20'] = df['VWAP_20'].pct_change(5) * 100

    return df


# ─────────────────────────────────────────────────────────
#  점수 계산 (개별 항목)
# ─────────────────────────────────────────────────────────
def _score_macd_cross(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """
    MACD 골든크로스 점수.
    최근 10봉 이내 발생: 30점 만점
    현재 MACD > Signal (유지): 15점
    데드크로스 or 하락: 0점
    """
    if len(df) < 30 or df['MACD'].isna().iloc[-1]:
        return 0, None

    recent = df.tail(15)
    macd = recent['MACD'].values
    sig = recent['MACD_signal'].values

    # 최근 10봉 안에서 크로스 발생 여부
    for i in range(1, min(11, len(macd))):
        # i봉 전에 MACD <= Signal이었다가 i-1봉 전에 MACD > Signal
        idx_prev = len(macd) - i - 1
        idx_curr = len(macd) - i
        if idx_prev >= 0 and idx_curr >= 0:
            if macd[idx_prev] <= sig[idx_prev] and macd[idx_curr] > sig[idx_curr]:
                # 크로스 발생 — 최근일수록 높은 점수 (1봉 전 30점 → 10봉 전 20점)
                freshness_score = SCORE_WEIGHTS["macd_cross"] - (i - 1) * (10 / 9)
                return freshness_score, f"골든크로스 {i}봉 전 발생"

    # 유지 중인 경우
    if macd[-1] > sig[-1]:
        return SCORE_WEIGHTS["macd_cross"] * 0.5, "MACD > Signal 유지"

    return 0, None


def _score_ma_alignment(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """MA5 > MA20 > MA60 정배열 확인."""
    if len(df) < 60 or df[['MA5', 'MA20', 'MA60']].iloc[-1].isna().any():
        return 0, None

    last = df.iloc[-1]
    if last['MA5'] > last['MA20'] > last['MA60']:
        return SCORE_WEIGHTS["ma_alignment"], "MA 정배열"
    # 부분 정배열
    if last['MA5'] > last['MA20']:
        return SCORE_WEIGHTS["ma_alignment"] * 0.5, "MA5>MA20만 충족"
    return 0, None


def _score_rsi_momentum(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """RSI > 50 + 상승 기울기."""
    if len(df) < 20 or df['RSI'].tail(3).isna().any():
        return 0, None

    rsi = df['RSI'].iloc[-1]
    if rsi <= 50:
        return 0, None

    # 3봉 기울기 (최근 3일 연속 상승?)
    r = df['RSI'].tail(3).values
    slope_up = r[-1] > r[-2] > r[-3]

    if slope_up:
        return SCORE_WEIGHTS["rsi_momentum"], f"RSI {rsi:.1f}↑ (상승 모멘텀)"
    if rsi > 55:
        return SCORE_WEIGHTS["rsi_momentum"] * 0.5, f"RSI {rsi:.1f} (상승 영역)"
    return 0, None


def _score_volume_bullish(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """최근 3일 중 2일 이상: 거래량↑ + 양봉."""
    if len(df) < 20 or df['VOL_MA20'].isna().iloc[-1]:
        return 0, None

    recent3 = df.tail(3)
    bullish_count = 0
    for _, row in recent3.iterrows():
        is_bullish = row['Close'] > row['Open']
        vol_up = row['Volume'] > row['VOL_MA20']
        if is_bullish and vol_up:
            bullish_count += 1

    if bullish_count >= 2:
        return SCORE_WEIGHTS["volume_bullish"], f"거래량+양봉 {bullish_count}/3일"
    if bullish_count == 1:
        return SCORE_WEIGHTS["volume_bullish"] * 0.3, "거래량+양봉 1/3일"
    return 0, None


def _score_ma20_support(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """20일선 지지 확인 (현재가가 MA20 근처 위로)."""
    if len(df) < 20 or df['MA20'].isna().iloc[-1]:
        return 0, None

    price = df['Close'].iloc[-1]
    ma20 = df['MA20'].iloc[-1]
    if ma20 <= 0:
        return 0, None

    ratio = price / ma20

    # 98%~105% 구간: 20일선 근처
    if 0.98 <= ratio <= 1.05:
        return SCORE_WEIGHTS["ma20_support"], f"MA20 지지 ({ratio*100:.1f}%)"
    # 105~115%: 정상 상승 구간
    if 1.05 < ratio <= 1.15:
        return SCORE_WEIGHTS["ma20_support"] * 0.5, f"MA20 위 {ratio*100:.1f}%"
    return 0, None


def _score_vwap_support(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """VWAP20 지지 또는 상향 VWAP 구간 확인."""
    if len(df) < 25 or 'VWAP_20' not in df.columns or pd.isna(df['VWAP_20'].iloc[-1]):
        return 0, None

    last = df.iloc[-1]
    price = float(last['Close'])
    vwap = float(last['VWAP_20'])
    if vwap <= 0:
        return 0, None

    dist_pct = float(last.get('VWAP_DIST_20', (price / vwap - 1) * 100))
    slope_raw = last.get('VWAP_SLOPE_20')
    slope_pct = 0.0 if pd.isna(slope_raw) else float(slope_raw)
    prev_close = float(df['Close'].iloc[-2]) if len(df) >= 2 else price

    if 0 <= dist_pct <= 3 and slope_pct >= 0:
        return (
            SCORE_WEIGHTS["vwap_support"],
            f"VWAP20 지지 ({dist_pct:+.1f}%, 기울기 {slope_pct:+.1f}%)",
        )
    if 3 < dist_pct <= 8 and slope_pct > 0:
        return (
            SCORE_WEIGHTS["vwap_support"] * 0.5,
            f"VWAP20 상단 추세 ({dist_pct:+.1f}%)",
        )
    if -1 <= dist_pct < 0 and price > prev_close:
        return (
            SCORE_WEIGHTS["vwap_support"] * 0.5,
            f"VWAP20 재돌파 근접 ({dist_pct:+.1f}%)",
        )
    return 0, None


# ─────────────────────────────────────────────────────────
#  감점 계산
# ─────────────────────────────────────────────────────────
def _penalty_macd_deadcross(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """MACD 데드크로스 발생 중."""
    if len(df) < 15 or df['MACD'].isna().iloc[-1]:
        return 0, None
    recent = df.tail(11)
    macd = recent['MACD'].values
    sig = recent['MACD_signal'].values
    for i in range(1, min(11, len(macd))):
        idx_prev = len(macd) - i - 1
        idx_curr = len(macd) - i
        if idx_prev >= 0 and macd[idx_prev] >= sig[idx_prev] and macd[idx_curr] < sig[idx_curr]:
            return -PENALTY_WEIGHTS["macd_deadcross"], f"데드크로스 {i}봉 전 발생"
    return 0, None


def _penalty_rsi_overbought(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """RSI > 78 과매수."""
    if df['RSI'].isna().iloc[-1]:
        return 0, None
    rsi = df['RSI'].iloc[-1]
    if rsi > 78:
        return -PENALTY_WEIGHTS["rsi_overbought"], f"RSI {rsi:.1f} 과매수"
    return 0, None


def _penalty_volume_declining(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """5일 연속 거래량 감소."""
    if len(df) < 5:
        return 0, None
    v = df['Volume'].tail(5).values
    if all(v[i] < v[i-1] for i in range(1, 5)):
        return -PENALTY_WEIGHTS["volume_declining"], "5일 연속 거래량↓"
    return 0, None


def _penalty_vwap_breakdown(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """VWAP20을 의미 있게 하향 이탈하고 VWAP도 꺾인 구간."""
    if len(df) < 25 or 'VWAP_20' not in df.columns or pd.isna(df['VWAP_20'].iloc[-1]):
        return 0, None

    last = df.iloc[-1]
    price = float(last['Close'])
    vwap = float(last['VWAP_20'])
    if vwap <= 0:
        return 0, None

    dist_pct = float(last.get('VWAP_DIST_20', (price / vwap - 1) * 100))
    slope_raw = last.get('VWAP_SLOPE_20')
    slope_pct = 0.0 if pd.isna(slope_raw) else float(slope_raw)

    if price < vwap * 0.97 and slope_pct <= 0:
        return (
            -PENALTY_WEIGHTS["vwap_breakdown"],
            f"VWAP20 하회 ({dist_pct:+.1f}%, 기울기 {slope_pct:+.1f}%)",
        )
    return 0, None


def _penalty_below_ma120(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """종가 < MA120 (장기 추세 역행)."""
    if len(df) < 120 or df['MA120'].isna().iloc[-1]:
        return 0, None
    if df['Close'].iloc[-1] < df['MA120'].iloc[-1]:
        return -PENALTY_WEIGHTS["below_ma120"], "종가 < MA120"
    return 0, None


def _penalty_high_volatility(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """연환산 변동성 60%+ 감점 — 변동성 29% 일간은 연 ~460%에 해당하므로 단계별 처리."""
    if len(df) < 20:
        return 0, None
    daily_returns = df['Close'].pct_change().dropna()
    if len(daily_returns) < 10:
        return 0, None
    daily_vol = float(daily_returns.tail(20).std())
    annual_vol = daily_vol * (252 ** 0.5) * 100  # 연환산 %
    if annual_vol >= 100:
        return -PENALTY_WEIGHTS["extreme_volatility"], f"연환산변동성 {annual_vol:.0f}% (비정상)"
    if annual_vol >= 60:
        return -PENALTY_WEIGHTS["high_volatility"], f"연환산변동성 {annual_vol:.0f}% (극고변동성)"
    return 0, None


# ─────────────────────────────────────────────────────────
#  종합 점수 계산
# ─────────────────────────────────────────────────────────
def calculate_score(df: pd.DataFrame) -> Dict:
    """
    단일 종목 OHLCV DataFrame에서 점수 계산.

    Returns:
        {score: float, grade: str, breakdown: dict, penalties: list}
    """
    if df is None or df.empty or len(df) < 60:
        return {
            "score": 0.0,
            "grade": "D",
            "breakdown": {},
            "penalties": [],
            "reason": "데이터 부족 (60일 미만)",
        }

    df = _calc_indicators_lite(df)

    # 기본 점수
    breakdown = {}
    positive_score = 0.0
    score_fns = [
        ("macd_cross",    _score_macd_cross),
        ("ma_alignment",  _score_ma_alignment),
        ("rsi_momentum",  _score_rsi_momentum),
        ("volume_bullish", _score_volume_bullish),
        ("ma20_support",  _score_ma20_support),
        ("vwap_support",  _score_vwap_support),
    ]
    for name, fn in score_fns:
        try:
            points, reason = fn(df)
        except Exception:
            points, reason = 0, None
        if points > 0:
            breakdown[name] = {"points": round(points, 1), "reason": reason}
            positive_score += points

    # 감점
    penalties = []
    penalty_score = 0.0
    penalty_fns = [
        ("macd_deadcross",    _penalty_macd_deadcross),
        ("rsi_overbought",    _penalty_rsi_overbought),
        ("volume_declining",  _penalty_volume_declining),
        ("vwap_breakdown",    _penalty_vwap_breakdown),
        ("below_ma120",       _penalty_below_ma120),
        ("high_volatility",   _penalty_high_volatility),
    ]
    for name, fn in penalty_fns:
        try:
            points, reason = fn(df)
        except Exception:
            points, reason = 0, None
        if points < 0:
            penalties.append({"name": name, "points": round(points, 1), "reason": reason})
            penalty_score += points

    raw_score = positive_score + penalty_score
    # 최종 점수: 0~100 범위 (감점으로 음수 될 경우 0으로 clip)
    final_score = max(0.0, min(100.0, raw_score))
    grade = score_to_grade(final_score)

    return {
        "score": round(final_score, 1),
        "grade": grade,
        "breakdown": breakdown,
        "penalties": penalties,
        "positive_score": round(positive_score, 1),
        "penalty_score": round(penalty_score, 1),
    }


def score_to_grade(score: float) -> str:
    """점수 → 등급 변환."""
    if score >= 85:
        return "S"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


# ─────────────────────────────────────────────────────────
#  메인 파이프라인
# ─────────────────────────────────────────────────────────
def run_screener(
    min_market_cap: float = MIN_MARKET_CAP_KRW,
    top_n: int = TOP_N_RESULTS,
    save_db: bool = True,
) -> Dict:
    """
    한국 주식 스크리너 실행.

    Returns:
        {run_id, scanned_at, universe_size, results: [...상위 N], ...}
    """
    t_start = datetime.now()
    run_id = t_start.strftime("%Y%m%d_%H%M%S_%f")

    print(f"[screener] 실행 {run_id} 시작")

    # 1. 유니버스 로드
    universe = load_kr_universe(min_market_cap)
    if universe.empty:
        return {
            "run_id": run_id,
            "scanned_at": t_start.isoformat(),
            "error": "유니버스 로드 실패 (pykrx/FDR/Naver Finance 데이터 소스 조회 실패)",
            "universe_size": 0,
            "results": [],
        }
    print(f"[screener] 유니버스: {len(universe)}개 (시총 {min_market_cap/1e8:.0f}억+)")

    # 2. OHLCV 준비
    tickers = universe['ticker'].tolist()
    from data_collector import prefetch_ohlcv_batch, clear_ohlcv_cache, fetch_ohlcv
    clear_ohlcv_cache()
    us_batch_tickers = [
        t for t in tickers
        if not str(t).upper().endswith((".KS", ".KQ"))
    ]
    if us_batch_tickers:
        prefetch_ohlcv_batch(us_batch_tickers, period="1y")
    if len(us_batch_tickers) != len(tickers):
        print("[screener] 한국 종목 OHLCV는 pykrx/FDR 우선순위 보존을 위해 개별 조회")

    # 3. 각 종목 점수 계산
    scored = []
    failed = 0
    for _, row in universe.iterrows():
        ticker = row['ticker']
        try:
            df = fetch_ohlcv(ticker, period="1y")
        except Exception:
            failed += 1
            continue

        if df is None or df.empty:
            failed += 1
            continue

        result = calculate_score(df)
        decision_context = build_screener_context(
            score=result["score"],
            grade=result["grade"],
            breakdown=result.get("breakdown", {}),
            penalties=result.get("penalties", []),
        )
        scored.append({
            "ticker": ticker,
            "name": row['name'],
            "market": row['market'],
            "market_cap": row['market_cap'],
            "current_price": float(df['Close'].iloc[-1]),
            "screener_signal": decision_context["signal"],
            "screener_confidence": decision_context["confidence"],
            "horizon_days": decision_context["horizon_days"],
            "decision_context": decision_context,
            **result,
        })

    clear_ohlcv_cache()

    # 4. 펀더멘털 필터 — 상위 후보만 yfinance로 확인 (속도 고려)
    #    EPS < 0 AND P/B > 5 조합: 적자 기업 고평가 → 점수 0으로 강제
    _disqualified = 0
    _top_candidates = sorted(scored, key=lambda x: x['score'], reverse=True)[:top_n * 2]
    for item in _top_candidates:
        try:
            import yfinance as yf
            _info = yf.Ticker(item['ticker']).info
            _eps = _info.get('trailingEps') or _info.get('epsTrailingTwelveMonths')
            _pbr = _info.get('priceToBook')
            if (_eps is not None and _pbr is not None
                    and _eps < FUNDAMENTAL_DISQUALIFY_EPS_MAX
                    and _pbr > FUNDAMENTAL_DISQUALIFY_PBR_MIN):
                item['score'] = 0.0
                item['grade'] = 'D'
                item['disqualified'] = True
                item['disqualify_reason'] = (
                    f"적자(EPS {_eps:.1f}) + 고PBR({_pbr:.1f}x) — 펀더멘털 실격"
                )
                item['penalties'].append({
                    "name": "fundamental_disqualify",
                    "points": -100,
                    "reason": item['disqualify_reason'],
                })
                _disqualified += 1
        except Exception:
            pass

    if _disqualified:
        print(f"[screener] 펀더멘털 실격: {_disqualified}개 (적자+고PBR)")

    # 5. 정렬 + 상위 N
    scored.sort(key=lambda x: x['score'], reverse=True)
    top = scored[:top_n]
    for i, item in enumerate(top, 1):
        item['rank'] = i

    elapsed = (datetime.now() - t_start).total_seconds()
    print(f"[screener] 완료: {len(scored)}종목 분석 / 실패 {failed} / {elapsed:.1f}s")

    # 5. DB 저장
    if save_db and top:
        try:
            from db import insert_screener_results
            insert_screener_results(run_id, top)
            print(f"[screener] DB 저장 완료: screener_results")
        except Exception as e:
            print(f"[screener] DB 저장 실패: {e}")

    return {
        "run_id": run_id,
        "scanned_at": t_start.isoformat(),
        "universe_size": len(universe),
        "analyzed_count": len(scored),
        "failed_count": failed,
        "elapsed_seconds": round(elapsed, 1),
        "min_market_cap": min_market_cap,
        "top_n": top_n,
        "results": top,
    }


# ─────────────────────────────────────────────────────────
#  스크리너 → Multi-Agent 파이프라인
# ─────────────────────────────────────────────────────────
def _score_floor_for_grade(screener_grade: str) -> float:
    return {"S": 90.0, "A": 80.0, "B": 70.0, "C": 55.0, "D": 30.0}.get(
        str(screener_grade or "D").upper(),
        30.0,
    )


def _determine_agreement(
    screener_grade: str,
    ma_signal: str,
    ma_confidence: float,
    screener_score: Optional[float] = None,
    ma_decision: Optional[Dict] = None,
    screener_row: Optional[Dict] = None,
) -> Dict:
    """
    스크리너 등급과 Multi-Agent 결과의 일치도 판정.

    Returns:
        {level: str, label: str, emoji: str, description: str}
    """
    score = screener_score if screener_score is not None else _score_floor_for_grade(screener_grade)
    primary = build_screener_context(
        score=score,
        grade=screener_grade,
        breakdown=(screener_row or {}).get("breakdown") or (screener_row or {}).get("screener_breakdown"),
        penalties=(screener_row or {}).get("penalties") or (screener_row or {}).get("screener_penalties"),
    )
    fd = dict(ma_decision or {})
    fd.setdefault("final_signal", ma_signal)
    fd.setdefault("final_confidence", ma_confidence)
    secondary = build_multi_agent_context(fd, horizon_days=primary["horizon_days"])
    return compare_decision_contexts(
        primary,
        secondary,
        secondary_decision=fd,
        screener_row=screener_row,
    )


def run_screener_with_multiagent(
    min_market_cap: float = MIN_MARKET_CAP_KRW,
    top_n: int = TOP_N_RESULTS,
    analyze_top: int = 5,
    save_db: bool = True,
) -> Dict:
    """
    스크리너 → Multi-Agent 자동 파이프라인.

    Args:
        min_market_cap: 최소 시총 (원)
        top_n: 스크리너 상위 몇 개
        analyze_top: 그 중 Multi-Agent로 자동 심층 분석할 상위 개수 (기본 5개)
        save_db: DB 저장 여부

    Returns:
        {screener_result, multi_agent_results, combined_view, ...}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from db import worker_connection_scope

    # ── 1단계: 스크리너 ──────────────────────
    print(f"\n[파이프라인] 1단계: 스크리너 실행")
    screener_result = run_screener(
        min_market_cap=min_market_cap,
        top_n=top_n,
        save_db=save_db,
    )
    candidates = screener_result.get("results", [])
    if not candidates:
        return {
            **screener_result,
            "multi_agent_results": {},
            "combined_view": [],
            "pipeline_stage": "failed_at_screener",
        }

    analyze_top = min(analyze_top, len(candidates))
    to_analyze = candidates[:analyze_top]
    print(f"[파이프라인] 2단계: Multi-Agent 심층 분석 상위 {analyze_top}개 병렬 실행")

    # ── 2단계: Multi-Agent 병렬 분석 ──────────
    ma_results = {}
    t_ma_start = datetime.now()

    def _run_ma(candidate):
        ticker = candidate["ticker"]
        with worker_connection_scope():
            try:
                # 기존 analyze_ticker 또는 Multi-Agent 경로
                # multi_agent.MultiAgentOrchestrator 사용
                import sys as _sys, os as _os
                proj = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
                analyzer = _os.path.join(proj, "stock_analyzer")
                if analyzer not in _sys.path:
                    _sys.path.insert(0, analyzer)

                from multi_agent import MultiAgentOrchestrator
                orchestrator = MultiAgentOrchestrator()
                ma_result = orchestrator.analyze(ticker)
                return ticker, ma_result
            except Exception as e:
                return ticker, {"error": f"Multi-Agent 실행 실패: {str(e)[:100]}"}

    # 병렬 실행 (max_workers는 Ollama 병렬 수와 맞춤)
    max_workers = int(_os.getenv("SCAN_PARALLEL_WORKERS", "2"))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_ma, c): c["ticker"] for c in to_analyze}
        for future in as_completed(futures):
            try:
                ticker, result = future.result()
                ma_results[ticker] = result
            except Exception as e:
                ma_results[futures[future]] = {"error": str(e)}

    ma_elapsed = (datetime.now() - t_ma_start).total_seconds()
    print(f"[파이프라인] Multi-Agent 완료: {len(ma_results)}개 / {ma_elapsed:.1f}s")

    # ── 3단계: 합의도 분석 (combined view) ────
    combined_view = []
    for cand in candidates:
        ticker = cand["ticker"]
        entry = {
            "rank": cand["rank"],
            "ticker": ticker,
            "name": cand.get("name"),
            "market": cand.get("market"),
            "market_cap": cand.get("market_cap"),
            "current_price": cand.get("current_price"),
            "screener_score": cand["score"],
            "screener_grade": cand["grade"],
            "screener_signal": cand.get("screener_signal", "neutral"),
            "screener_confidence": cand.get("screener_confidence", 0.0),
            "horizon_days": cand.get("horizon_days"),
            "decision_context": cand.get("decision_context"),
            "screener_breakdown": cand.get("breakdown", {}),
            "screener_penalties": cand.get("penalties", []),
        }

        ma = ma_results.get(ticker)
        if ma and "error" not in ma:
            fd = ma.get("final_decision", {})
            ma_signal = fd.get("final_signal", "neutral")
            ma_conf = float(fd.get("final_confidence", 0))
            ma_context = build_multi_agent_context(fd, horizon_days=entry.get("horizon_days"))
            agreement = _determine_agreement(
                cand["grade"],
                ma_signal,
                ma_conf,
                screener_score=cand["score"],
                ma_decision=fd,
                screener_row=cand,
            )
            entry.update({
                "multi_agent_analyzed": True,
                "multi_agent_signal": ma_signal,
                "multi_agent_confidence": ma_conf,
                "multi_agent_context": ma_context,
                "multi_agent_consensus": fd.get("consensus", ""),
                "multi_agent_reasoning": (fd.get("reasoning") or "")[:200],
                "entry_plan": fd.get("entry_plan"),
                "agreement": agreement,
                "decision_divergence": agreement,
            })
        elif ma and "error" in ma:
            entry.update({
                "multi_agent_analyzed": False,
                "multi_agent_error": ma["error"],
                "agreement": {
                    "level": "error", "label": "분석 실패", "emoji": "❌",
                    "description": ma["error"][:80],
                },
            })
        else:
            # Multi-Agent 분석 안 한 종목 (analyze_top 초과)
            entry.update({
                "multi_agent_analyzed": False,
                "agreement": {
                    "level": "pending", "label": "미분석", "emoji": "⏳",
                    "description": "Multi-Agent 분석 대기 중 (상위 N개 범위 밖)",
                },
            })
        combined_view.append(entry)

    # 합의도 통계
    agreement_stats = {}
    for e in combined_view:
        lvl = e.get("agreement", {}).get("level", "unknown")
        agreement_stats[lvl] = agreement_stats.get(lvl, 0) + 1

    total_elapsed = (datetime.now() - datetime.fromisoformat(screener_result["scanned_at"])).total_seconds()

    return {
        **screener_result,
        "pipeline_stage": "completed",
        "analyzed_top": analyze_top,
        "multi_agent_elapsed_seconds": round(ma_elapsed, 1),
        "total_elapsed_seconds": round(total_elapsed, 1),
        "multi_agent_results": ma_results,
        "combined_view": combined_view,
        "agreement_stats": agreement_stats,
    }


if __name__ == "__main__":
    # 수동 실행 테스트
    result = run_screener(top_n=10, save_db=False)
    print()
    print("=" * 70)
    print(f"스크리너 실행: {result['run_id']}")
    print(f"유니버스: {result.get('universe_size', 0)}개")
    print(f"소요: {result.get('elapsed_seconds', 0)}s")
    print("=" * 70)
    print()
    print(f"{'순위':<4} {'종목':<20} {'점수':<6} {'등급':<4} {'시총(억)':<12} {'현재가':<10}")
    print("-" * 70)
    for r in result.get("results", []):
        cap_bn = r['market_cap'] / 1e8
        print(f"{r['rank']:<4} {r['name'][:15]:<20} {r['score']:<6.1f} {r['grade']:<4} "
              f"{cap_bn:>10,.0f} ₩{r['current_price']:>8,.0f}")
