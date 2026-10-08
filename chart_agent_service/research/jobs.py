"""리서치 도구 스케줄 잡 — 시장별 일일 브리핑, 공시 감시.

결과는 '조건 충족'이 아니라 '결과'로 기록한다 (CLAUDE.md §13-2): 텔레그램이 실제로
받았는지(`delivered`)를 보고, 공시는 전송에 성공해야 '본 것'으로 남긴다 — 실패한 알림은
다음 실행에서 다시 나간다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Callable, Iterable, Literal, Optional

from research.briefing import Fetchers, build_briefing, dart_url
from research.models import Briefing, Holding
from research.telegram_format import format_briefing

Market = Literal["KRX", "NYSE"]

_SEEN_KEY = "research.seen_disclosures"
_SEEN_LIMIT = 1000  # 오래된 접수번호는 잘라낸다 (DART 접수번호는 날짜로 시작해 정렬된다)


def _market_of(ticker: str) -> Market:
    return "KRX" if ticker.upper().endswith((".KS", ".KQ")) else "NYSE"


def _filter_market(tickers: Iterable[str], market: Market) -> list[str]:
    return [t for t in tickers if _market_of(t) == market]


def run_market_briefing(
    market: Market,
    watchlist: list[str],
    holdings: list[Holding],
    send: Callable[[str], bool],
    is_trading_day: Callable[[Market], bool],
    fetchers: Optional[Fetchers] = None,
    now: Optional[datetime] = None,
) -> dict:
    """그 시장의 보유 + 관심 종목 브리핑을 보낸다. 휴장일이면 보내지 않는다."""
    now = now or datetime.now(timezone.utc)
    if not is_trading_day(market):
        return {"status": "skipped_holiday", "market": market, "delivered": False, "items": 0}

    tickers = _filter_market(watchlist, market)
    held = [h for h in holdings if _market_of(h.ticker) == market]
    if not tickers and not held:
        return {"status": "skipped_empty", "market": market, "delivered": False, "items": 0}

    briefing: Briefing = build_briefing(tickers, held, fetchers)
    label = f"{now.date().isoformat()} {'한국장' if market == 'KRX' else '미국장'} 마감"
    delivered = bool(send(format_briefing(briefing, label)))
    return {
        "status": "completed" if delivered else "delivery_failed",
        "market": market,
        "delivered": delivered,
        "items": len(briefing.items),
        "flagged": sum(1 for i in briefing.items if i.flags),
        "failed": sum(1 for i in briefing.items if i.errors),
    }


#: 알림 한 번에 요약할 최대 공시 수 — LLM 쿼터(모델당 하루 20회)를 감시 잡이 다 쓰지 않게
_MAX_SUMMARIES = 5


def _format_disclosure_alert(new: list[tuple[str, dict]], summaries: Optional[dict] = None) -> str:
    from html import escape

    summaries = summaries or {}
    lines = [f"📄 <b>새 공시 {len(new)}건</b>"]
    for ticker, row in new[:20]:
        title = escape(str(row.get("report_nm", "")).strip())
        no = str(row.get("rcept_no", ""))
        lines.append(f'• <b>{escape(ticker)}</b> <a href="{escape(dart_url(no))}">{title}</a>')
        summ = summaries.get(no)
        if summ is not None and summ.bullets:
            lines += [f"   – {escape(b)}" for b in summ.bullets]
        elif summ is not None:
            lines.append(f"   <i>요약 없음 — {escape(summ.reason or '실패')}</i>")
    if len(new) > 20:
        lines.append(f"…외 {len(new) - 20}건 (화면에서 확인)")
    lines.append("<i>원문 링크입니다. 매수·매도 판단이 아닙니다.</i>")
    return "\n".join(lines)


def run_disclosure_watch(
    tickers: Iterable[str],
    fetch: Callable[[str], list[dict]],
    send: Callable[[str], bool],
    load_seen: Callable[[], Optional[list[str]]],
    save_seen: Callable[[list[str]], None],
    summarize: Optional[Callable[[str, str, str], object]] = None,
) -> dict:
    """한국 종목의 새 공시를 알린다.

    첫 실행(본 목록 없음)은 지금 있는 공시를 '본 것'으로만 기록하고 보내지 않는다 —
    배포 직후 지난 공시가 한꺼번에 쏟아지지 않게.
    """
    kr = sorted({t.strip().upper() for t in tickers if _market_of(t) == "KRX"})
    seen_list = load_seen()
    first_run = seen_list is None
    seen = set(seen_list or [])

    new: list[tuple[str, dict]] = []
    errors: list[str] = []
    for ticker in kr:
        try:
            rows = fetch(ticker)
        except Exception as exc:  # DartUnavailable 포함 — 사유를 남긴다
            errors.append(f"{ticker}: {exc}")
            continue
        for row in rows:
            no = str(row.get("rcept_no", ""))
            if no and no not in seen:
                new.append((ticker, row))

    result = {"tickers": len(kr), "new_disclosures": len(new), "errors": errors[:5],
              "error_count": len(errors)}
    found = [str(r.get("rcept_no")) for _, r in new]

    if first_run:
        save_seen(sorted(seen | set(found))[-_SEEN_LIMIT:])
        # 보내지 않고 기준으로 삼은 공시 — 게이트 판정에서 '누락'으로 세지 않도록 남긴다
        return {**result, "status": "initialized", "delivered": False, "initialized": found}
    if not new:
        status = "partial_failure" if errors else "completed"
        return {**result, "status": status, "delivered": False}

    summaries: dict = {}
    summarized_ok = 0
    if summarize is not None:
        for ticker, row in new[:_MAX_SUMMARIES]:
            no = str(row.get("rcept_no", ""))
            try:
                summ = summarize(no, ticker, str(row.get("report_nm", "")).strip())
            except Exception as exc:  # 요약 실패는 알림을 막지 않는다 — 링크는 나간다
                summ = SimpleNamespace(bullets=(), reason=f"{type(exc).__name__}: {exc}")
            summaries[no] = summ
            summarized_ok += 1 if getattr(summ, "bullets", ()) else 0
    result["summarized"] = summarized_ok

    delivered = bool(send(_format_disclosure_alert(new, summaries)))
    if delivered:
        save_seen(sorted(seen | set(found))[-_SEEN_LIMIT:])
    status = "delivery_failed" if not delivered else ("partial_failure" if errors else "completed")
    # 실제로 알림이 나간 공시 — 게이트 2 '누락 0' 판정의 근거
    return {**result, "status": status, "delivered": delivered,
            "alerted": found if delivered else []}


def load_seen_disclosures() -> Optional[list[str]]:
    from db import get_app_state

    return get_app_state(_SEEN_KEY, default=None)


def save_seen_disclosures(items: list[str]) -> None:
    from db import set_app_state

    set_app_state(_SEEN_KEY, items)
