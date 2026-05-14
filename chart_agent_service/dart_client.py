"""
DART(전자공시시스템) API 클라이언트 (P2).

OpenDartReader를 사용해 한국 상장기업 공시를 조회한다.
DART_API_KEY 환경변수가 없으면 모든 함수가 None/빈 리스트를 반환한다.

주요 기능:
- get_corp_code(): 종목코드 → DART 고유번호 변환
- fetch_recent_disclosures(): 최근 N일 공시 목록
- classify_disclosure(): 공시 유형 분류 (호재/악재/중립)
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# 공시 유형 키워드 → 호재/악재
_POSITIVE_KEYWORDS = [
    "자사주",
    "배당",
    "무상증자",
    "자회사 설립",
    "신규 계약",
    "수주",
    "경영실적",
    "실적 호조",
    "최대 매출",
    "흑자",
    "영업이익 증가",
]
_NEGATIVE_KEYWORDS = [
    "불성실공시",
    "횡령",
    "배임",
    "영업정지",
    "조업중단",
    "대규모 손실",
    "소송",
    "행정처분",
    "제재",
    "주식거래 정지",
    "상장폐지 사유",
    "자산 매각",
    "유상증자",
]


def _get_dart_api_key() -> Optional[str]:
    key = os.getenv("DART_API_KEY", "")
    return key if key.strip() else None


def get_corp_code(ticker: str) -> Optional[str]:
    """
    6자리 종목코드 → DART 고유번호 변환.

    Args:
        ticker: "005930" 또는 "005930.KS" 형식

    Returns:
        DART 고유번호 8자리 문자열 (없으면 None)
    """
    api_key = _get_dart_api_key()
    if not api_key:
        logger.debug("DART_API_KEY 없음 — get_corp_code 건너뜀")
        return None

    try:
        import OpenDartReader as odr  # type: ignore[import-untyped]

        code = ticker.upper().split(".")[0]  # "005930.KS" → "005930"
        dart = odr.OpenDartReader(api_key)
        result = dart.find_corp_code(code)
        if result and len(result) > 0:
            return (
                str(result.iloc[0]["corp_code"])
                if hasattr(result, "iloc")
                else str(result)
            )
    except Exception as exc:
        logger.warning("get_corp_code(%s) 실패: %s", ticker, exc)
    return None


def fetch_recent_disclosures(
    ticker: str,
    days_back: int = 30,
    max_items: int = 10,
) -> list[dict]:
    """
    최근 N일 DART 공시 목록 조회.

    Args:
        ticker:     종목코드 (6자리 또는 "005930.KS")
        days_back:  조회 기간 (일)
        max_items:  최대 반환 건수

    Returns:
        공시 목록 [{rcept_no, rcept_dt, corp_name, report_nm, classified}]
    """
    api_key = _get_dart_api_key()
    if not api_key:
        return []

    try:
        import OpenDartReader as odr  # type: ignore[import-untyped]

        code = ticker.upper().split(".")[0]
        dart = odr.OpenDartReader(api_key)

        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)

        df = dart.list(
            code,
            start=start_date.strftime("%Y%m%d"),
            end=end_date.strftime("%Y%m%d"),
            kind="A",  # 정기공시
        )
        if df is None or df.empty:
            # 비정기 공시도 조회
            df = dart.list(
                code,
                start=start_date.strftime("%Y%m%d"),
                end=end_date.strftime("%Y%m%d"),
            )

        if df is None or df.empty:
            return []

        results = []
        for _, row in df.head(max_items).iterrows():
            report_name = str(row.get("report_nm", ""))
            classified = classify_disclosure(report_name)
            results.append(
                {
                    "rcept_no": str(row.get("rcept_no", "")),
                    "rcept_dt": str(row.get("rcept_dt", "")),
                    "corp_name": str(row.get("corp_name", "")),
                    "report_nm": report_name,
                    "classified": classified,
                }
            )
        return results

    except Exception as exc:
        logger.warning("fetch_recent_disclosures(%s) 실패: %s", ticker, exc)
        return []


def classify_disclosure(report_name: str) -> str:
    """
    공시 제목으로 호재/악재/중립 분류.

    Returns:
        "positive" | "negative" | "neutral"
    """
    for kw in _NEGATIVE_KEYWORDS:
        if kw in report_name:
            return "negative"
    for kw in _POSITIVE_KEYWORDS:
        if kw in report_name:
            return "positive"
    return "neutral"


def compute_disclosure_score(disclosures: list[dict]) -> dict:
    """
    공시 목록에서 시그널 점수와 요약을 산출한다.

    Returns:
        {"score": float, "signal": str, "positive": int, "negative": int,
         "neutral": int, "total": int, "recent_titles": list[str]}
    """
    pos = sum(1 for d in disclosures if d.get("classified") == "positive")
    neg = sum(1 for d in disclosures if d.get("classified") == "negative")
    neutral = len(disclosures) - pos - neg
    total = len(disclosures)

    # 기준: 호재-악재 차이를 0~10 범위로 매핑
    net = pos - neg
    score = max(-10.0, min(10.0, float(net) * 2.0))
    signal = "buy" if score > 1 else "sell" if score < -1 else "neutral"

    return {
        "score": round(score, 1),
        "signal": signal,
        "positive": pos,
        "negative": neg,
        "neutral": neutral,
        "total": total,
        "recent_titles": [d["report_nm"] for d in disclosures[:3]],
    }
