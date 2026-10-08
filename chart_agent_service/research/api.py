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

    from research.disclosure_summary import get_summary

    tickers = _watchlist() + [h.ticker for h in list_holdings()]
    return run_disclosure_watch(
        tickers,
        lambda t: fetch_recent_disclosures(t, days_back=1),
        _send,
        load_seen_disclosures,
        save_seen_disclosures,
        summarize=get_summary,
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
    rcept_no: str
    ticker: str
    date: str
    title: str
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
                rcept_no=str(r.get("rcept_no", "")), ticker=t, date=str(r.get("rcept_dt", "")),
                title=str(r.get("report_nm", "")).strip(),
                url=dart_url(str(r.get("rcept_no", ""))),
            ))
    rows.sort(key=lambda r: r.date, reverse=True)
    return DisclosuresResponse(days=days, rows=rows, errors=errors)


@router.get("/disclosures/{rcept_no}/summary")
def get_disclosure_summary(rcept_no: str, ticker: str = "", title: str = "",
                           refresh: bool = False) -> dict:
    """공시 요약 (캐시 우선). 원문에 근거가 확인된 문장만, 출처 링크와 함께."""
    from research.disclosure_summary import get_summary

    if not rcept_no.isdigit() or len(rcept_no) != 14:
        raise HTTPException(400, "rcept_no 는 14자리 DART 접수번호")
    return get_summary(rcept_no, ticker.upper(), title, refresh=refresh).model_dump()


def build_gate2_report_payload(start: str | None = None, end: str | None = None) -> dict:
    """게이트 2 판정. 기간 기본값은 config (RESEARCH_GATE2_START/END)."""
    from datetime import date, datetime, timezone

    from config import (
        RESEARCH_BRIEFING_KR_HOUR,
        RESEARCH_BRIEFING_KR_MINUTE,
        RESEARCH_BRIEFING_US_HOUR,
        RESEARCH_BRIEFING_US_MINUTE,
        RESEARCH_GATE2_END,
        RESEARCH_GATE2_START,
    )
    from dart_client import fetch_recent_disclosures
    from market_cal import get_valid_trading_days
    from research.gate_report import build_report, collect_filings, due_days, to_markdown
    from research.history import load_history

    s = date.fromisoformat(start or RESEARCH_GATE2_START)
    e = date.fromisoformat(end or RESEARCH_GATE2_END)
    now = datetime.now(timezone.utc)
    today = now.date()
    upto = min(e, today)
    times = {"KRX": (RESEARCH_BRIEFING_KR_HOUR, RESEARCH_BRIEFING_KR_MINUTE),
             "NYSE": (RESEARCH_BRIEFING_US_HOUR, RESEARCH_BRIEFING_US_MINUTE)}
    trading = {
        m: due_days([d.date() for d in get_valid_trading_days(m, s, upto)], *times[m], now)
        for m in ("KRX", "NYSE")
    }
    tickers = _watchlist() + [h.ticker for h in list_holdings()]
    filings, ferr = collect_filings(
        tickers, (today - s).days + 1,
        lambda t, days: fetch_recent_disclosures(t, days_back=days, max_items=100),
    )
    from research.jobs import load_seen_disclosures

    report = build_report(s, upto, load_history(), trading, filings, ferr,
                          seen=load_seen_disclosures() or [])
    if upto < e:
        report["gaps"].append(f"기간 진행 중 — {upto} 까지 중간 점검")
        if report["verdict"] == "PASS":
            report["verdict"] = "INCOMPLETE"
    report["markdown"] = to_markdown(report)
    return report


@router.get("/gate2-report")
def get_gate2_report(start: Optional[str] = None, end: Optional[str] = None,
                     saved: bool = False) -> dict:
    """게이트 2 판정. saved=true 면 자동 실행이 저장한 최종 리포트를 돌려준다."""
    if saved:
        from db import get_app_state

        stored = get_app_state("research.gate2_report", default=None)
        if not stored:
            raise HTTPException(404, "저장된 게이트 2 리포트 없음 (자동 실행 전)")
        return stored
    try:
        return build_gate2_report_payload(start, end)
    except ValueError as exc:
        raise HTTPException(400, f"날짜 형식 오류: {exc}")
