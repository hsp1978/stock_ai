"""게이트 2 판정 — 병행 2주간 알림 누락 0 (전환 제안서, 2026-10-08 기록).

판정 기준 (제안서 '이전 계획' 진행 현황):
1. 병행 기간의 모든 거래일에 시장별 브리핑이 delivered=true (휴장일 제외)
2. 공시 감시의 delivery_failed 가 없거나, 있어도 뒤이은 실행에서 재전송됨
3. 보유·관심 한국 종목의 실제 DART 공시 중 알림으로 오지 않은 것이 없음

판정할 수 없는 것은 '통과'로 적지 않는다 — 이력이 기간을 덮지 못하면 INCOMPLETE.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Callable, Iterable, Literal, Optional

Verdict = Literal["PASS", "FAIL", "INCOMPLETE"]
_BRIEFING_JOBS = {"KRX": "research_briefing_kr", "NYSE": "research_briefing_us"}


def _d(iso: str) -> date:
    return datetime.fromisoformat(iso).astimezone(timezone.utc).date()


def due_days(days: Iterable[date], hour: int, minute: int, now: datetime,
             grace_minutes: int = 30) -> list[date]:
    """발송 시각 + 여유가 지난 거래일만. 아직 오지 않은 브리핑을 '누락'으로 세지 않는다.

    중간 점검(2026-10-08 02:32 UTC)에서 그날 07:10·21:10 브리핑이 '누락'으로 잡혀
    FAIL 이 나왔다.
    """
    from datetime import timedelta

    out = []
    for d in days:
        due = datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)
        if due + timedelta(minutes=grace_minutes) <= now:
            out.append(d)
    return out


def check_briefings(history: list[dict], trading_days: dict[str, list[date]]) -> dict:
    missing: list[str] = []
    failed: list[str] = []
    for market, days in trading_days.items():
        runs = [h for h in history if h["job_id"] == _BRIEFING_JOBS[market]]
        for day in days:
            on_day = [h for h in runs if _d(h["started_at"]) == day]
            if not on_day:
                missing.append(f"{market} {day}")
            elif not any(h.get("delivered") for h in on_day):
                failed.append(f"{market} {day} ({on_day[-1].get('status')})")
    total = sum(len(v) for v in trading_days.values())
    return {"expected": total, "missing": missing, "failed": failed,
            "ok": total - len(missing) - len(failed)}


def check_disclosure_delivery(history: list[dict]) -> dict:
    runs = sorted((h for h in history if h["job_id"] == "research_disclosure_watch"),
                  key=lambda h: h["started_at"])
    unrecovered: list[str] = []
    for i, h in enumerate(runs):
        if h.get("status") == "delivery_failed":
            if not any(later.get("delivered") for later in runs[i + 1:]):
                unrecovered.append(h["started_at"])
    errors = [h["started_at"] for h in runs if h.get("status") == "error"]
    return {"runs": len(runs),
            "delivery_failed": sum(1 for h in runs if h.get("status") == "delivery_failed"),
            "unrecovered": unrecovered, "errored_runs": len(errors)}


def check_disclosure_coverage(
    history: list[dict], filings: Iterable[dict], since: date, seen: Iterable[str] = ()
) -> dict:
    """DART 에 올라온 공시(rcept_dt >= since)가 알림으로 나갔는가.

    `seen`(공시 감시의 '본 것' 목록)도 근거로 쓴다 — 거기에는 **전송에 성공했거나 첫
    실행에서 기준으로 둔 것만** 들어간다(jobs.run_disclosure_watch). 이력 기록이 생기기
    전에 일어난 첫 실행분이 '놓침'으로 잘못 잡히지 않게 한다.
    """
    alerted = {n for h in history for n in (h.get("alerted") or [])}
    baseline = {n for h in history for n in (h.get("initialized") or [])} | set(seen)
    rows = [f for f in filings if str(f.get("rcept_dt", "")) >= since.strftime("%Y%m%d")]
    missed = [f"{f.get('ticker')} {f.get('rcept_dt')} {str(f.get('report_nm', '')).strip()}"
              for f in rows
              if str(f.get("rcept_no")) not in alerted and str(f.get("rcept_no")) not in baseline]
    return {"filings": len(rows), "alerted": len(rows) - len(missed), "missed": missed}


def build_report(
    start: date,
    end: date,
    history: list[dict],
    trading_days: dict[str, list[date]],
    filings: list[dict],
    filings_error: str = "",
    now: Optional[datetime] = None,
    seen: Iterable[str] = (),
) -> dict:
    now = now or datetime.now(timezone.utc)
    window = [h for h in history if start <= _d(h["started_at"]) <= end]
    first = min((h["started_at"] for h in history), default=None)

    b = check_briefings(window, trading_days)
    d = check_disclosure_delivery(window)
    c = check_disclosure_coverage(window, filings, start, seen)

    gaps: list[str] = []
    if first is None:
        gaps.append("실행 이력 없음")
    elif _d(first) > start:
        gaps.append(f"이력 시작 {first[:16]} — 그 전 구간은 판정 근거 없음")
    if filings_error:
        gaps.append(f"DART 대조 불가: {filings_error}")

    failed = bool(b["missing"] or b["failed"] or d["unrecovered"] or c["missed"])
    verdict: Verdict = "FAIL" if failed else ("INCOMPLETE" if gaps else "PASS")
    return {"verdict": verdict, "start": start.isoformat(), "end": end.isoformat(),
            "generated_at": now.isoformat(), "briefings": b, "disclosure_delivery": d,
            "disclosure_coverage": c, "gaps": gaps, "history_runs": len(window)}


def to_markdown(r: dict) -> str:
    b, d, c = r["briefings"], r["disclosure_delivery"], r["disclosure_coverage"]
    lines = [
        f"# 게이트 2 판정 — {r['verdict']}",
        f"기간 {r['start']} ~ {r['end']} · 생성 {r['generated_at'][:16]} UTC · 실행 이력 {r['history_runs']}건",
        "",
        f"1. 브리핑 전달: {b['ok']}/{b['expected']} 거래일"
        + (f" — 누락 {len(b['missing'])}, 실패 {len(b['failed'])}" if b["missing"] or b["failed"] else " — 누락 0"),
    ]
    lines += [f"   - 누락: {x}" for x in b["missing"]] + [f"   - 실패: {x}" for x in b["failed"]]
    lines.append(
        f"2. 공시 알림 전송: 실행 {d['runs']}회, 전송 실패 {d['delivery_failed']}회, "
        f"재전송 안 됨 {len(d['unrecovered'])}회, 오류 실행 {d['errored_runs']}회"
    )
    lines.append(f"3. 공시 커버리지: DART {c['filings']}건 중 알림 {c['alerted']}건"
                 + (f" — 놓친 공시 {len(c['missed'])}건" if c["missed"] else " — 누락 0"))
    lines += [f"   - 놓침: {x}" for x in c["missed"]]
    if r["gaps"]:
        lines += ["", "판정 근거 부족:"] + [f"- {g}" for g in r["gaps"]]
    return "\n".join(lines)


def collect_filings(
    tickers: Iterable[str], days_back: int, fetch: Callable[[str, int], list[dict]]
) -> tuple[list[dict], str]:
    rows: list[dict] = []
    errors: list[str] = []
    for t in sorted({t.upper() for t in tickers if t.upper().endswith((".KS", ".KQ"))}):
        try:
            rows += [{**r, "ticker": t} for r in fetch(t, days_back)]
        except Exception as exc:
            errors.append(f"{t}: {exc}")
    return rows, "; ".join(errors)
