"""
차트 패턴 인식 모듈 (알고리즘 기반)
- scipy.signal로 로컬 극값 탐지
- 헤드앤숄더, 더블탑/바텀, 삼각수렴, 채널, 깃발, 쐐기 등 감지
"""
from datetime import datetime, timezone
from typing import List, Dict, Optional

import numpy as np
from scipy.signal import argrelextrema


# ── 패턴 정의 ────────────────────────────────────────────────────

PATTERN_META = {
    "double_top":             ("더블탑",           "bearish"),
    "double_bottom":          ("더블바텀",          "bullish"),
    "head_and_shoulders":     ("헤드앤숄더",        "bearish"),
    "inverse_head_shoulders": ("역헤드앤숄더",      "bullish"),
    "ascending_triangle":     ("상승 삼각형",       "bullish"),
    "descending_triangle":    ("하락 삼각형",       "bearish"),
    "symmetrical_triangle":   ("대칭 삼각형",       "neutral"),
    "bullish_flag":           ("상승 깃발",         "bullish"),
    "bearish_flag":           ("하락 깃발",         "bearish"),
    "rising_wedge":           ("상승 쐐기 (반전)",   "bearish"),
    "falling_wedge":          ("하락 쐐기 (반전)",   "bullish"),
}


def _get_extrema(prices: np.ndarray, order: int = 5):
    highs_idx = argrelextrema(prices, np.greater, order=order)[0]
    lows_idx = argrelextrema(prices, np.less, order=order)[0]
    return highs_idx, lows_idx


def _pct_diff(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return abs(a - b) / b


def _linear_slope(idx: np.ndarray, vals: np.ndarray) -> float:
    """최소제곱 기울기. 양수=상승, 음수=하락."""
    if len(idx) < 2:
        return 0.0
    x = np.array(idx, dtype=float)
    y = np.array(vals, dtype=float)
    return float(np.polyfit(x, y, 1)[0])


# ── 개별 패턴 탐지 ───────────────────────────────────────────────

def _detect_double_top(highs_idx, highs_val, current_price: float) -> Optional[Dict]:
    if len(highs_idx) < 2:
        return None
    h1, h2 = highs_val[-2], highs_val[-1]
    if _pct_diff(h1, h2) < 0.03:  # 두 고점이 3% 이내
        neck = current_price
        target = neck - (max(h1, h2) - neck)
        return {
            "name": "double_top",
            "confidence": round(0.5 + (0.03 - _pct_diff(h1, h2)) * 10, 2),
            "target_price": round(target, 2),
            "invalidation_price": round(max(h1, h2) * 1.01, 2),
            "description": f"두 고점({h1:.2f}, {h2:.2f})이 유사한 수준. 넥라인 하향 돌파 시 하락 가속.",
        }
    return None


def _detect_double_bottom(lows_idx, lows_val, current_price: float) -> Optional[Dict]:
    if len(lows_idx) < 2:
        return None
    l1, l2 = lows_val[-2], lows_val[-1]
    if _pct_diff(l1, l2) < 0.03:
        neck = current_price
        target = neck + (neck - min(l1, l2))
        return {
            "name": "double_bottom",
            "confidence": round(0.5 + (0.03 - _pct_diff(l1, l2)) * 10, 2),
            "target_price": round(target, 2),
            "invalidation_price": round(min(l1, l2) * 0.99, 2),
            "description": f"두 저점({l1:.2f}, {l2:.2f})이 유사한 수준. 넥라인 상향 돌파 시 상승 가속.",
        }
    return None


def _detect_head_and_shoulders(highs_idx, highs_val, lows_val) -> Optional[Dict]:
    if len(highs_idx) < 3:
        return None
    l, h, r = highs_val[-3], highs_val[-2], highs_val[-1]
    if h > l and h > r and _pct_diff(l, r) < 0.05:
        neck = min(lows_val[-3:]) if len(lows_val) >= 3 else r * 0.95
        target = round(neck - (h - neck), 2)
        return {
            "name": "head_and_shoulders",
            "confidence": round(min(0.85, 0.6 + (1 - _pct_diff(l, r)) * 0.5), 2),
            "target_price": target,
            "invalidation_price": round(h * 1.01, 2),
            "description": f"왼어깨({l:.2f}), 머리({h:.2f}), 오른어깨({r:.2f}). 넥라인 이탈 시 하락 전환.",
        }
    return None


def _detect_inverse_head_shoulders(lows_idx, lows_val, highs_val) -> Optional[Dict]:
    if len(lows_idx) < 3:
        return None
    l, h, r = lows_val[-3], lows_val[-2], lows_val[-1]
    if h < l and h < r and _pct_diff(l, r) < 0.05:
        neck = max(highs_val[-3:]) if len(highs_val) >= 3 else r * 1.05
        target = round(neck + (neck - h), 2)
        return {
            "name": "inverse_head_shoulders",
            "confidence": round(min(0.85, 0.6 + (1 - _pct_diff(l, r)) * 0.5), 2),
            "target_price": target,
            "invalidation_price": round(h * 0.99, 2),
            "description": f"역헤드({h:.2f}), 양쪽 어깨({l:.2f}, {r:.2f}). 넥라인 돌파 시 상승 전환.",
        }
    return None


def _detect_triangles(highs_idx, highs_val, lows_idx, lows_val, current_price: float) -> List[Dict]:
    results = []
    if len(highs_idx) < 3 or len(lows_idx) < 3:
        return results

    high_slope = _linear_slope(highs_idx[-3:], highs_val[-3:])
    low_slope = _linear_slope(lows_idx[-3:], lows_val[-3:])

    apex_price = (highs_val[-1] + lows_val[-1]) / 2
    target_up = round(apex_price + (highs_val[-3] - lows_val[-3]) * 0.8, 2)
    target_dn = round(apex_price - (highs_val[-3] - lows_val[-3]) * 0.8, 2)

    # 상승 삼각형: 고점 수평 + 저점 상승
    if abs(high_slope) < 0.02 and low_slope > 0.01:
        results.append({
            "name": "ascending_triangle",
            "confidence": 0.70,
            "target_price": target_up,
            "invalidation_price": round(lows_val[-1] * 0.98, 2),
            "description": "저점이 높아지며 수평 저항선에 수렴. 상방 돌파 시 강한 상승 기대.",
        })

    # 하락 삼각형: 고점 하락 + 저점 수평
    if high_slope < -0.01 and abs(low_slope) < 0.02:
        results.append({
            "name": "descending_triangle",
            "confidence": 0.70,
            "target_price": target_dn,
            "invalidation_price": round(highs_val[-1] * 1.02, 2),
            "description": "고점이 낮아지며 수평 지지선에 수렴. 하방 이탈 시 강한 하락 기대.",
        })

    # 대칭 삼각형: 고점 하락 + 저점 상승
    if high_slope < -0.01 and low_slope > 0.01:
        results.append({
            "name": "symmetrical_triangle",
            "confidence": 0.60,
            "target_price": target_up if current_price > apex_price else target_dn,
            "invalidation_price": round(lows_val[-1] * 0.97, 2),
            "description": "고점 하락, 저점 상승으로 수렴. 돌파 방향으로 추세 결정.",
        })

    return results


def _detect_flags(prices: np.ndarray, highs_val, lows_val, current_price: float) -> List[Dict]:
    results = []
    if len(prices) < 30:
        return results

    # 최근 20봉 기울기 vs 이전 10봉 기울기로 깃발 판단
    prev_10 = prices[-30:-20]
    recent_20 = prices[-20:]
    prev_slope = float(np.polyfit(range(len(prev_10)), prev_10, 1)[0])
    recent_slope = float(np.polyfit(range(len(recent_20)), recent_20, 1)[0])

    flagpole = abs(prev_slope)
    if flagpole < 0.1:
        return results

    # 상승 깃발: 이전 급등 + 최근 완만한 하락
    if prev_slope > 0.5 and -prev_slope * 0.5 < recent_slope < 0:
        target = round(current_price + (prices[-30] - prices[-20]), 2)
        results.append({
            "name": "bullish_flag",
            "confidence": 0.65,
            "target_price": target,
            "invalidation_price": round(min(recent_20) * 0.98, 2),
            "description": "급등 이후 완만한 조정(깃발). 상방 돌파 시 추가 상승 기대.",
        })

    # 하락 깃발: 이전 급락 + 최근 완만한 상승
    if prev_slope < -0.5 and 0 < recent_slope < abs(prev_slope) * 0.5:
        target = round(current_price - (prices[-20] - prices[-30]), 2)
        results.append({
            "name": "bearish_flag",
            "confidence": 0.65,
            "target_price": target,
            "invalidation_price": round(max(recent_20) * 1.02, 2),
            "description": "급락 이후 완만한 반등(깃발). 하방 이탈 시 추가 하락 기대.",
        })

    return results


def _detect_wedges(highs_idx, highs_val, lows_idx, lows_val) -> List[Dict]:
    results = []
    if len(highs_idx) < 3 or len(lows_idx) < 3:
        return results

    high_slope = _linear_slope(highs_idx[-3:], highs_val[-3:])
    low_slope = _linear_slope(lows_idx[-3:], lows_val[-3:])

    # 상승 쐐기: 두 추세선 모두 상승, 저점 추세선이 더 가파름
    if high_slope > 0.01 and low_slope > high_slope:
        results.append({
            "name": "rising_wedge",
            "confidence": 0.65,
            "target_price": round(lows_val[-3] * 0.95, 2),
            "invalidation_price": round(highs_val[-1] * 1.02, 2),
            "description": "고점·저점 모두 상승하나 수렴 중. 하방 이탈 시 급락 전환 가능.",
        })

    # 하락 쐐기: 두 추세선 모두 하락, 고점 추세선이 더 가파름
    if high_slope < -0.01 and low_slope < high_slope:
        results.append({
            "name": "falling_wedge",
            "confidence": 0.65,
            "target_price": round(highs_val[-3] * 1.05, 2),
            "invalidation_price": round(lows_val[-1] * 0.98, 2),
            "description": "고점·저점 모두 하락하나 수렴 중. 상방 돌파 시 강한 반등 기대.",
        })

    return results


# ── 메인 함수 ────────────────────────────────────────────────────

def detect_chart_patterns(ticker: str, df, chart_path: Optional[str] = None) -> Dict:
    """OHLCV DataFrame으로 차트 패턴 감지."""
    close = df["Close"].values.astype(float)
    high = df["High"].values.astype(float)
    low = df["Low"].values.astype(float)
    current_price = float(close[-1])

    order = max(3, len(close) // 40)
    highs_idx, lows_idx = _get_extrema(close, order=order)

    highs_val = close[highs_idx] if len(highs_idx) else np.array([current_price])
    lows_val = close[lows_idx] if len(lows_idx) else np.array([current_price])

    detected = []

    # 더블탑/바텀
    dt = _detect_double_top(highs_idx, highs_val, current_price)
    if dt:
        detected.append(dt)

    db = _detect_double_bottom(lows_idx, lows_val, current_price)
    if db:
        detected.append(db)

    # 헤드앤숄더
    hs = _detect_head_and_shoulders(highs_idx, highs_val, lows_val)
    if hs:
        detected.append(hs)

    ihs = _detect_inverse_head_shoulders(lows_idx, lows_val, highs_val)
    if ihs:
        detected.append(ihs)

    # 삼각형
    detected.extend(_detect_triangles(highs_idx, highs_val, lows_idx, lows_val, current_price))

    # 깃발
    detected.extend(_detect_flags(close, highs_val, lows_val, current_price))

    # 쐐기
    detected.extend(_detect_wedges(highs_idx, highs_val, lows_idx, lows_val))

    # 메타 정보 병합
    patterns = []
    for p in detected:
        name = p.pop("name")
        kr_name, direction = PATTERN_META.get(name, (name, "neutral"))
        patterns.append({
            "name": name,
            "name_kr": kr_name,
            "confidence": min(1.0, p.get("confidence", 0.5)),
            "direction": direction,
            "description": p.get("description", ""),
            "target_price": p.get("target_price"),
            "invalidation_price": p.get("invalidation_price"),
        })

    # 신뢰도 높은 순 정렬
    patterns.sort(key=lambda x: x["confidence"], reverse=True)

    return {
        "ticker": ticker,
        "current_price": current_price,
        "patterns": patterns,
        "pattern_count": len(patterns),
        "chart_path": chart_path,
        "analyzed_at": datetime.now(tz=timezone.utc).isoformat(),
    }
