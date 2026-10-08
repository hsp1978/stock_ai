"""종목 점검(브리핑) — 사실과 거리만 담고 판단은 담지 않는다.

각 조각(가격·검증·실적·공시)은 따로 수집하고, 실패하면 그 사유를 `errors` 에 남긴다.
한 조각이 실패해도 나머지는 나간다 — 그러나 실패가 정상처럼 보이지는 않는다 (CLAUDE.md §13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

import pandas as pd

from research.models import Briefing, BriefingItem, Disclosure, Holding

#: 사람이 먼저 봐야 할 것의 임계. 판단이 아니라 '주의 환기'다.
STOP_NEAR_PCT = 3.0        # 손절가까지 이 % 이내
TARGET_NEAR_PCT = 3.0      # 목표가까지 이 % 이내
EARNINGS_SOON_DAYS = 7.0   # 실적 발표 D-7 이내
BIG_MOVE_PCT = 5.0         # 하루 등락 ±5% 이상
VOLUME_SPIKE = 2.0         # 거래량 20일 평균의 2배 이상
DISCLOSURE_DAYS = 3        # 최근 N일 공시


def _is_kr(ticker: str) -> bool:
    return ticker.upper().endswith((".KS", ".KQ"))


def dart_url(rcept_no: str) -> str:
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


@dataclass
class Fetchers:
    """외부 조회 함수 묶음 — 테스트에서 바꿔 끼운다."""

    ohlcv: Callable[[str], pd.DataFrame]
    bar_status: Callable[[str, pd.DataFrame], dict]
    verify: Callable[[str], object]
    earnings: Callable[[str], Optional[float]]
    disclosures: Callable[[str], list[dict]]

    @classmethod
    def default(cls) -> "Fetchers":
        from dart_client import fetch_recent_disclosures
        from data_collector import fetch_ohlcv, latest_bar_status, verify_latest_close
        from research.earnings import fetch_days_to_earnings

        return cls(
            ohlcv=fetch_ohlcv,
            bar_status=latest_bar_status,
            verify=verify_latest_close,
            earnings=fetch_days_to_earnings,
            disclosures=lambda t: fetch_recent_disclosures(t, days_back=DISCLOSURE_DAYS),
        )


@dataclass
class _Acc:
    values: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _price_part(ticker: str, f: Fetchers, acc: _Acc) -> None:
    try:
        df = f.ohlcv(ticker)
    except Exception as exc:
        acc.errors.append(f"시세 조회 실패: {type(exc).__name__}: {exc}")
        return
    if df is None or df.empty or "Close" not in df.columns:
        acc.errors.append("시세 없음")
        return

    status = f.bar_status(ticker, df)
    state = status.get("state", "unknown")
    acc.values["bar_state"] = state
    # 장중이면 마지막 봉은 미완성이다 — 등락·거래량은 직전 완결 봉으로 본다.
    complete = df if state == "complete" else df.iloc[:-1]
    if len(complete) < 2:
        acc.errors.append("완결 봉 부족")
        return
    last, prev = complete.iloc[-1], complete.iloc[-2]
    close, prev_close = float(last["Close"]), float(prev["Close"])
    acc.values.update(
        close=round(close, 4),
        prev_close=round(prev_close, 4),
        change_pct=round((close / prev_close - 1) * 100, 2) if prev_close else None,
        bar_date=str(complete.index[-1])[:10],
    )
    if state == "in_progress":
        # 상태 안내일 뿐 '볼 것'이 아니다 — flags 에 넣으면 장중 브리핑마다 한국 종목이
        # 전부 '볼 것'으로 올라온다 (2026-10-08 실측).
        acc.values["bar_note"] = f"장중 — 마지막 완결 봉({acc.values['bar_date']}) 기준"
    if "Volume" in complete.columns and len(complete) >= 21:
        base = complete["Volume"].iloc[-21:-1].mean()
        if base and base > 0:
            ratio = round(float(last["Volume"]) / float(base), 2)
            acc.values["volume_ratio"] = ratio
            if ratio >= VOLUME_SPIKE:
                acc.flags.append(f"거래량 {ratio:.1f}배 (20일 평균 대비)")
    chg = acc.values.get("change_pct")
    if chg is not None and abs(chg) >= BIG_MOVE_PCT:
        acc.flags.append(f"하루 {chg:+.1f}%")


def _verify_part(ticker: str, f: Fetchers, acc: _Acc) -> None:
    try:
        pv = f.verify(ticker)
    except Exception as exc:
        acc.values["price_check"] = "unavailable"
        acc.errors.append(f"가격 검증 실패: {type(exc).__name__}")
        return
    status = getattr(pv, "status", "unknown")
    acc.values["price_check"] = status
    acc.values["price_check_detail"] = getattr(pv, "detail", "")
    if status != "ok":
        acc.flags.append(f"가격 검증 {status}")


def _holding_part(h: Holding, acc: _Acc) -> None:
    acc.values.update(qty=h.qty, avg_price=h.avg_price,
                      stop_price=h.stop_price, target_price=h.target_price)
    close = acc.values.get("close")
    if not close:
        return
    acc.values["pnl_pct"] = round((close / h.avg_price - 1) * 100, 2)
    if h.stop_price:
        to_stop = round((h.stop_price / close - 1) * 100, 2)
        acc.values["to_stop_pct"] = to_stop
        if close <= h.stop_price:
            acc.flags.append("손절가 도달")
        elif abs(to_stop) <= STOP_NEAR_PCT:
            acc.flags.append(f"손절가까지 {abs(to_stop):.1f}%")
    if h.target_price:
        to_target = round((h.target_price / close - 1) * 100, 2)
        acc.values["to_target_pct"] = to_target
        if close >= h.target_price:
            acc.flags.append("목표가 도달")
        elif abs(to_target) <= TARGET_NEAR_PCT:
            acc.flags.append(f"목표가까지 {abs(to_target):.1f}%")


def _earnings_part(ticker: str, f: Fetchers, acc: _Acc) -> None:
    from research.earnings import EarningsDataMissing

    try:
        days = f.earnings(ticker)
    except EarningsDataMissing as exc:
        # 소스의 알려진 한계 — 수집 실패(errors)가 아니라 상태로 남긴다
        acc.values["earnings_status"] = "unavailable"
        acc.values["earnings_note"] = str(exc)
        return
    except Exception as exc:
        acc.values["earnings_status"] = "unavailable"
        acc.errors.append(f"실적 일정 조회 실패: {type(exc).__name__}")
        return
    acc.values["earnings_status"] = "ok"
    acc.values["days_to_earnings"] = None if days is None else round(days, 1)
    if days is not None and days <= EARNINGS_SOON_DAYS:
        acc.flags.append(f"실적 발표 D-{days:.0f}")


def _disclosure_part(ticker: str, f: Fetchers, acc: _Acc) -> None:
    if not _is_kr(ticker):
        acc.values["disclosure_status"] = "not_applicable"
        return
    try:
        rows = f.disclosures(ticker)
    except Exception as exc:  # DartUnavailable 포함 — '공시 없음'과 구분한다
        acc.values["disclosure_status"] = "unavailable"
        acc.errors.append(f"공시 조회 실패: {exc}")
        return
    acc.values["disclosure_status"] = "ok"
    items = tuple(
        Disclosure(date=r.get("rcept_dt", ""), title=str(r.get("report_nm", "")).strip(),
                   kind=r.get("classified", ""), url=dart_url(r.get("rcept_no", "")))
        for r in rows
    )
    acc.values["disclosures"] = items
    if items:
        acc.flags.append(f"최근 {DISCLOSURE_DAYS}일 공시 {len(items)}건")


def build_item(ticker: str, holding: Optional[Holding], f: Fetchers) -> BriefingItem:
    ticker = ticker.strip().upper()
    acc = _Acc()
    _price_part(ticker, f, acc)
    _verify_part(ticker, f, acc)
    if holding:
        _holding_part(holding, acc)
    _earnings_part(ticker, f, acc)
    _disclosure_part(ticker, f, acc)
    return BriefingItem(
        ticker=ticker,
        market="KRX" if _is_kr(ticker) else "NYSE",
        is_holding=holding is not None,
        flags=tuple(acc.flags),
        errors=tuple(acc.errors),
        **acc.values,
    )


def build_briefing(
    tickers: Iterable[str], holdings: Iterable[Holding], f: Optional[Fetchers] = None
) -> Briefing:
    """보유 종목 먼저, 그다음 관심 종목. 중복 티커는 한 번만."""
    f = f or Fetchers.default()
    by_ticker = {h.ticker: h for h in holdings}
    order = list(by_ticker) + [t.strip().upper() for t in tickers if t.strip().upper() not in by_ticker]
    seen: set[str] = set()
    items = []
    for t in order:
        if t in seen:
            continue
        seen.add(t)
        items.append(build_item(t, by_ticker.get(t), f))
    return Briefing(generated_at=datetime.now(timezone.utc).isoformat(), items=tuple(items))
