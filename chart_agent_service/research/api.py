"""/research API — 보유 종목 직접 입력과 브리핑 조회."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from research.briefing import build_briefing
from research.holdings import list_holdings, remove_holding, upsert_holding
from research.models import Briefing, Holding

router = APIRouter(prefix="/research", tags=["research"])


class HoldingsResponse(BaseModel):
    holdings: list[Holding]


class RemoveResponse(BaseModel):
    ticker: str
    removed: bool


#: 워치리스트 단일 소스 — service._load_watchlist_files 와 같은 파일 (WebUI 가 관리).
_WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "stock_analyzer", "watchlist.txt")


def _watchlist(path: str = _WATCHLIST_FILE) -> list[str]:
    if not os.path.exists(path):
        return []
    seen: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            t = line.strip().upper()
            if t and not t.startswith("#") and t not in seen:
                seen.append(t)
    return seen


@router.get("/holdings", response_model=HoldingsResponse)
def get_holdings() -> HoldingsResponse:
    return HoldingsResponse(holdings=list_holdings())


@router.put("/holdings", response_model=HoldingsResponse)
def put_holding(holding: Holding) -> HoldingsResponse:
    return HoldingsResponse(holdings=upsert_holding(holding))


@router.delete("/holdings/{ticker}", response_model=RemoveResponse)
def delete_holding(ticker: str) -> RemoveResponse:
    removed = remove_holding(ticker)
    if not removed:
        # 없던 티커를 '삭제됨'으로 보고하지 않는다 (§13 워치리스트 사례)
        raise HTTPException(404, f"{ticker.upper()}: 보유 목록에 없음")
    return RemoveResponse(ticker=ticker.upper(), removed=True)


@router.get("/briefing", response_model=Briefing)
def get_briefing(tickers: Optional[str] = None) -> Briefing:
    """tickers 를 주면 그 종목만, 아니면 보유 + 워치리스트."""
    universe = [t for t in (tickers.split(",") if tickers else _watchlist()) if t.strip()]
    holdings = list_holdings()
    if tickers:
        wanted = {t.strip().upper() for t in universe}
        holdings = [h for h in holdings if h.ticker in wanted]
    return build_briefing(universe, holdings)
