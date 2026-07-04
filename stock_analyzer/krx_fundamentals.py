#!/usr/bin/env python3
"""KRX(pykrx) 펀더멘털 조회 — Value Investor 한국 종목 보강.

yfinance는 KDR(예: 950170.KQ JTC)·비주력 한국 종목에서 재무 지표가 결측이거나
과거 회계연도 값을 반환하는 품질 문제가 있다. KRX 일별 펀더멘털(PER/PBR/EPS/BPS)을
1차 소스로 보강한다.

주의: KRX 정보데이터시스템은 2025-05부터 재무 데이터 조회에 로그인을 요구한다.
pykrx(>=1.2.6)는 KRX_ID / KRX_PW 환경 변수로 로그인한다. 자격증명이 없거나
조회에 실패하면 {"available": False, "reason": ...}를 반환해 호출부가 yfinance
단독 경로로 안전하게 폴백하도록 한다.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Dict, Optional


def is_krx_ticker(ticker: Optional[str]) -> bool:
    """한국(KRX) 티커 여부 (.KS / .KQ)."""
    if not ticker or not isinstance(ticker, str):
        return False
    upper = ticker.upper()
    return upper.endswith(".KS") or upper.endswith(".KQ")


def krx_credentials_configured() -> bool:
    """KRX 정보데이터시스템 로그인 자격증명 설정 여부."""
    return bool(os.getenv("KRX_ID") and os.getenv("KRX_PW"))


def fetch_krx_fundamentals(ticker: str, lookback_days: int = 14) -> Dict[str, Any]:
    """KRX 일별 펀더멘털 조회.

    Returns:
        available=True 시: per, pbr, eps, bps, dividend_yield, roe(=EPS/BPS 근사),
        as_of(기준일), source="krx".
        available=False 시: reason에 폴백 사유.
    """
    if not is_krx_ticker(ticker):
        return {"available": False, "reason": "KRX 티커 아님"}

    code = ticker.split(".")[0]
    if len(code) != 6:
        return {"available": False, "reason": f"KRX 종목코드 형식 아님: {code}"}

    if not krx_credentials_configured():
        return {
            "available": False,
            "reason": "KRX_ID/KRX_PW 미설정 — KRX 재무 조회 비활성 (yfinance 폴백)",
        }

    try:
        from pykrx import stock as krx_stock

        end = date.today()
        start = end - timedelta(days=lookback_days)
        df = krx_stock.get_market_fundamental(
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            code,
        )
        if df is None or df.empty:
            # KRX 일별 재무 지표는 KDR(외국기업 주식예탁증권, 코드 9xxxxx)을
            # 제공하지 않는다 (실측: 2026-07, KOSDAQ 스냅샷에 9xxxxx 0종목).
            if code.startswith("9"):
                return {
                    "available": False,
                    "reason": "KDR(외국기업)은 KRX 재무 지표 미제공 — yfinance 폴백",
                }
            return {"available": False, "reason": "KRX 펀더멘털 데이터 없음"}

        # BPS가 0이면 무의미한 행 (거래정지 등) — 유효 행 중 최신 사용
        valid = df[df["BPS"] > 0]
        if valid.empty:
            return {"available": False, "reason": "KRX 유효 펀더멘털 행 없음"}

        row = valid.iloc[-1]
        eps = float(row.get("EPS", 0) or 0)
        bps = float(row.get("BPS", 0) or 0)
        per = float(row.get("PER", 0) or 0)
        pbr = float(row.get("PBR", 0) or 0)
        div = float(row.get("DIV", 0) or 0)

        # ROE = EPS/BPS 근사 (KRX EPS는 지배주주 연간 기준 — TTM과 다를 수 있음)
        roe = eps / bps if bps > 0 else None

        return {
            "available": True,
            "per": per if per > 0 else None,
            "pbr": pbr if pbr > 0 else None,
            "eps": eps,
            "bps": bps,
            "dividend_yield": div,
            "roe": roe,
            "as_of": str(valid.index[-1].date()) if hasattr(valid.index[-1], "date") else str(valid.index[-1]),
            "source": "krx",
        }

    except Exception as exc:  # pykrx 미설치·네트워크·KRX 응답 형식 변경 등
        return {"available": False, "reason": f"KRX 조회 실패: {str(exc)[:120]}"}
