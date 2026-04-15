"""
섹터/산업 비교 분석 모듈
- yfinance로 섹터/산업 정보 조회
- 동종 피어 그룹과 밸류에이션·모멘텀·변동성 비교
"""
from datetime import datetime, timezone
from typing import List, Dict, Optional
import json
import os

import numpy as np
import yfinance as yf


# ── 피어 그룹 매핑 ────────────────────────────────────────────────

def _load_sector_peers() -> Dict[str, List[str]]:
    """JSON 파일에서 섹터/산업별 종목 리스트 로드"""
    json_path = os.path.join(os.path.dirname(__file__), "sector_tickers.json")

    # JSON 파일이 없으면 기본값 사용
    if not os.path.exists(json_path):
        return {
            "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA"],
            "Financials": ["JPM", "BAC", "WFC", "GS", "MS"],
            "Healthcare": ["JNJ", "UNH", "PFE", "MRK", "ABBV"],
        }

    try:
        with open(json_path, "r") as f:
            data = json.load(f)
            # sectors와 industries를 합쳐서 반환
            result = {}
            if "sectors" in data:
                result.update(data["sectors"])
            if "industries" in data:
                result.update(data["industries"])
            return result
    except Exception as e:
        print(f"Warning: Failed to load sector_tickers.json: {e}")
        # 파일 로드 실패시 기본값 반환
        return {
            "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA"],
            "Financials": ["JPM", "BAC", "WFC", "GS", "MS"],
            "Healthcare": ["JNJ", "UNH", "PFE", "MRK", "ABBV"],
        }

SECTOR_PEERS = _load_sector_peers()


def _safe_float(val) -> Optional[float]:
    try:
        v = float(val)
        return None if (v != v or abs(v) > 1e12) else round(v, 4)  # NaN/Inf 체크
    except (TypeError, ValueError):
        return None


def _get_momentum(ticker: str, period_days: int = 21) -> Optional[float]:
    """단순 수익률 (%)."""
    try:
        hist = yf.Ticker(ticker).history(period=f"{period_days + 5}d")
        if len(hist) < 2:
            return None
        pct = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
        return round(float(pct), 2)
    except Exception:
        return None


def _get_beta(ticker: str) -> Optional[float]:
    try:
        info = yf.Ticker(ticker).info
        return _safe_float(info.get("beta"))
    except Exception:
        return None


def _get_pe(ticker: str) -> Optional[float]:
    try:
        info = yf.Ticker(ticker).info
        return _safe_float(info.get("trailingPE") or info.get("forwardPE"))
    except Exception:
        return None


def _percentile(value: float, values: List[float]) -> int:
    """value가 values 목록에서 몇 퍼센타일인지 반환."""
    if not values or value is None:
        return 50
    arr = sorted(v for v in values if v is not None)
    if not arr:
        return 50
    below = sum(1 for v in arr if v < value)
    return round(below / len(arr) * 100)


# ── 메인 함수 ────────────────────────────────────────────────────

def compare_sector(ticker: str) -> Dict:
    """섹터 내 상대 위치 분석."""
    ticker = ticker.upper()

    # 기본 정보 조회
    info = {}
    try:
        info = yf.Ticker(ticker).info
    except Exception:
        pass

    sector = info.get("sector", "Technology")
    industry = info.get("industry", "Unknown")

    # 피어 결정: 산업 내 피어 > 섹터 피어
    peers_pool = SECTOR_PEERS.get(industry, SECTOR_PEERS.get(sector, []))
    peers = [p for p in peers_pool if p != ticker][:6]  # 최대 6개 피어

    # 타겟 종목 지표
    target_pe = _safe_float(info.get("trailingPE") or info.get("forwardPE"))
    target_beta = _safe_float(info.get("beta"))
    target_mom = _get_momentum(ticker, 21)

    # 피어 지표 수집
    peer_pes, peer_betas, peer_moms = [], [], []
    for p in peers:
        pe = _get_pe(p)
        beta = _get_beta(p)
        mom = _get_momentum(p, 21)
        if pe is not None:
            peer_pes.append(pe)
        if beta is not None:
            peer_betas.append(beta)
        if mom is not None:
            peer_moms.append(mom)

    # 섹터 평균
    def safe_avg(lst):
        valid = [v for v in lst if v is not None]
        return round(sum(valid) / len(valid), 2) if valid else None

    sector_pe_avg = safe_avg(peer_pes)
    sector_beta_avg = safe_avg(peer_betas)
    sector_mom_avg = safe_avg(peer_moms)

    all_pes = ([target_pe] if target_pe else []) + peer_pes
    all_betas = ([target_beta] if target_beta else []) + peer_betas
    all_moms = ([target_mom] if target_mom else []) + peer_moms

    # 상대 강도 (1M 모멘텀 기준)
    relative_strength = None
    if target_mom is not None and sector_mom_avg and sector_mom_avg != 0:
        relative_strength = round(target_mom / sector_mom_avg, 2)

    sector_trend = "neutral"
    if sector_mom_avg is not None:
        if sector_mom_avg > 3:
            sector_trend = "outperforming"
        elif sector_mom_avg < -3:
            sector_trend = "underperforming"

    return {
        "ticker": ticker,
        "sector": sector,
        "industry": industry,
        "peers": peers,
        "comparison": {
            "pe_ratio": {
                "value": target_pe,
                "sector_avg": sector_pe_avg,
                "percentile": _percentile(target_pe, all_pes) if target_pe is not None else None,
            },
            "momentum_1m": {
                "value": target_mom,
                "sector_avg": sector_mom_avg,
                "percentile": _percentile(target_mom, all_moms) if target_mom is not None else None,
            },
            "beta": {
                "value": target_beta,
                "sector_avg": sector_beta_avg,
                "percentile": _percentile(target_beta, all_betas) if target_beta is not None else None,
            },
        },
        "sector_trend": sector_trend,
        "relative_strength": relative_strength,
        "analyzed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
