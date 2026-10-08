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


def _is_trading_day(market: str) -> bool:
    from market_cal import is_trading_day

    return is_trading_day(market)


def _send(text: str) -> bool:
    from telegram_bot import send_telegram_html

    return send_telegram_html(text)


def run_briefing_job(market: str) -> dict:
    """스케줄 잡·수동 실행 공용."""
    from research.jobs import run_market_briefing

    return run_market_briefing(market, _watchlist(), list_holdings(), _send, _is_trading_day)


def run_disclosure_job() -> dict:
    from dart_client import fetch_recent_disclosures
    from research.jobs import load_seen_disclosures, run_disclosure_watch, save_seen_disclosures

    tickers = _watchlist() + [h.ticker for h in list_holdings()]
    return run_disclosure_watch(
        tickers,
        lambda t: fetch_recent_disclosures(t, days_back=1),
        _send,
        load_seen_disclosures,
        save_seen_disclosures,
    )


class JobResult(BaseModel):
    result: dict


@router.post("/briefing/send", response_model=JobResult)
def send_briefing(market: str = "KRX") -> JobResult:
    """수동 발송 — 스케줄과 같은 경로. 휴장일이면 보내지 않는다."""
    market = market.upper()
    if market not in ("KRX", "NYSE"):
        raise HTTPException(400, "market 은 KRX 또는 NYSE")
    return JobResult(result=run_briefing_job(market))


class DisclosureRow(BaseModel):
    ticker: str
    date: str
    title: str
    kind: str
    url: str


class DisclosuresResponse(BaseModel):
    days: int
    rows: list[DisclosureRow]
    errors: list[str]


@router.get("/disclosures", response_model=DisclosuresResponse)
def get_disclosures(days: int = 7) -> DisclosuresResponse:
    """보유 + 관심 한국 종목의 최근 공시. 조회 실패는 errors 로 — '공시 없음'과 구분."""
    from dart_client import fetch_recent_disclosures
    from research.briefing import dart_url

    days = max(1, min(days, 90))
    tickers = sorted({t for t in _watchlist() + [h.ticker for h in list_holdings()]
                      if t.endswith((".KS", ".KQ"))})
    rows: list[DisclosureRow] = []
    errors: list[str] = []
    for t in tickers:
        try:
            items = fetch_recent_disclosures(t, days_back=days, max_items=30)
        except Exception as exc:
            errors.append(f"{t}: {exc}")
            continue
        for r in items:
            rows.append(DisclosureRow(
                ticker=t, date=str(r.get("rcept_dt", "")),
                title=str(r.get("report_nm", "")).strip(), kind=str(r.get("classified", "")),
                url=dart_url(str(r.get("rcept_no", ""))),
            ))
    rows.sort(key=lambda r: r.date, reverse=True)
    return DisclosuresResponse(days=days, rows=rows, errors=errors)
