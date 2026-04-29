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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf


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
    "volume_bullish":  20,  # 최근 3일 중 2일 이상 거래량↑ + 양봉
    "ma20_support":    10,  # 20일선 지지 확인
}
# 최대 100점

PENALTY_WEIGHTS = {
    "macd_deadcross":     20,  # 데드크로스 발생 중
    "rsi_overbought":     15,  # RSI > 78 과매수
    "volume_declining":   10,  # 5일 연속 거래량 감소
    "below_ma120":        10,  # 종가 < MA120 (장기 역행)
}


# ─────────────────────────────────────────────────────────
#  데이터 수집 (유니버스 + 시총)
# ─────────────────────────────────────────────────────────
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

    # RSI (Wilder's)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']

    # 거래량 평균
    df['VOL_MA20'] = volume.rolling(20, min_periods=20).mean()

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
                # 크로스 발생 — 최근일수록 높은 점수 (30→20 선형)
                fresh_bonus = (11 - i) / 10  # i=1일 때 1.0, i=10일 때 0.1
                return SCORE_WEIGHTS["macd_cross"] * fresh_bonus, f"골든크로스 {i}봉 전 발생"

    # 유지 중인 경우
    if macd[-1] > sig[-1]:
        return SCORE_WEIGHTS["macd_cross"] * 0.5, "MACD > Signal 유지"

    return 0, None


def _score_ma_alignment(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """MA5 > MA20 > MA60 정배열 확인."""
    if len(df) < 60 or df[['MA5', 'MA20', 'MA60']].isna().any().any():
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


def _penalty_below_ma120(df: pd.DataFrame) -> Tuple[float, Optional[str]]:
    """종가 < MA120 (장기 추세 역행)."""
    if len(df) < 120 or df['MA120'].isna().iloc[-1]:
        return 0, None
    if df['Close'].iloc[-1] < df['MA120'].iloc[-1]:
        return -PENALTY_WEIGHTS["below_ma120"], "종가 < MA120"
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
        ("below_ma120",       _penalty_below_ma120),
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
    run_id = t_start.strftime("%Y%m%d_%H%M")

    print(f"[screener] 실행 {run_id} 시작")

    # 1. 유니버스 로드
    universe = load_kr_universe(min_market_cap)
    if universe.empty:
        return {
            "run_id": run_id,
            "scanned_at": t_start.isoformat(),
            "error": "유니버스 로드 실패 (pykrx 또는 FDR 설치 필요)",
            "universe_size": 0,
            "results": [],
        }
    print(f"[screener] 유니버스: {len(universe)}개 (시총 {min_market_cap/1e8:.0f}억+)")

    # 2. 배치 OHLCV 다운로드
    tickers = universe['ticker'].tolist()
    from data_collector import prefetch_ohlcv_batch, clear_ohlcv_cache, fetch_ohlcv
    clear_ohlcv_cache()
    # 스크리너는 1y (200일+) 필요 — data_collector 기본값
    prefetch_ohlcv_batch(tickers, period="1y")

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
        scored.append({
            "ticker": ticker,
            "name": row['name'],
            "market": row['market'],
            "market_cap": row['market_cap'],
            "current_price": float(df['Close'].iloc[-1]),
            **result,
        })

    clear_ohlcv_cache()

    # 4. 정렬 + 상위 N
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
def _determine_agreement(screener_grade: str, ma_signal: str, ma_confidence: float) -> Dict:
    """
    스크리너 등급과 Multi-Agent 결과의 일치도 판정.

    Returns:
        {level: str, label: str, emoji: str, description: str}
    """
    grade_tier = {"S": 3, "A": 2, "B": 1, "C": 0, "D": -1}.get(screener_grade or "D", -1)
    sig = (ma_signal or "").lower()

    # 강한 일치: 스크리너 S/A + MA buy + 신뢰도 ≥ 6
    if grade_tier >= 2 and sig == "buy" and ma_confidence >= 6:
        return {
            "level": "strong_match", "label": "강한 일치", "emoji": "🟢🟢",
            "description": "스크리너 상위 + Multi-Agent 매수 확증 — 1순위 후보",
        }
    # 부분 일치: 스크리너 S/A + MA buy 낮은 신뢰도 or MA neutral
    if grade_tier >= 2 and (sig == "buy" or sig == "neutral"):
        return {
            "level": "partial_match", "label": "부분 일치", "emoji": "🟢",
            "description": "스크리너 강세지만 Multi-Agent는 보수적 — 추가 관찰 필요",
        }
    # 충돌: 스크리너 A/S인데 MA sell
    if grade_tier >= 2 and sig == "sell":
        return {
            "level": "conflict", "label": "신호 충돌", "emoji": "⚠️",
            "description": "스크리너는 매수 후보인데 Multi-Agent 매도 — 재검토 필요",
        }
    # 뜻밖의 매수: 스크리너 C/D인데 MA buy
    if grade_tier < 1 and sig == "buy":
        return {
            "level": "unexpected_buy", "label": "이례적 매수", "emoji": "🟡",
            "description": "스크리너 약한 후보인데 Multi-Agent는 매수 — Multi-Agent 근거 확인",
        }
    # 동반 약세
    if grade_tier < 1 and sig in ("sell", "neutral"):
        return {
            "level": "aligned_weak", "label": "동반 약세", "emoji": "⚪",
            "description": "스크리너와 Multi-Agent 모두 약한 후보 — 관망",
        }
    # 기본
    return {
        "level": "neutral", "label": "일치도 보통", "emoji": "🔵",
        "description": "스크리너와 Multi-Agent 신호 보통 수준",
    }


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
            "screener_breakdown": cand.get("breakdown", {}),
            "screener_penalties": cand.get("penalties", []),
        }

        ma = ma_results.get(ticker)
        if ma and "error" not in ma:
            fd = ma.get("final_decision", {})
            ma_signal = fd.get("final_signal", "neutral")
            ma_conf = float(fd.get("final_confidence", 0))
            entry.update({
                "multi_agent_analyzed": True,
                "multi_agent_signal": ma_signal,
                "multi_agent_confidence": ma_conf,
                "multi_agent_consensus": fd.get("consensus", ""),
                "multi_agent_reasoning": (fd.get("reasoning") or "")[:200],
                "entry_plan": fd.get("entry_plan"),
                "agreement": _determine_agreement(cand["grade"], ma_signal, ma_conf),
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
