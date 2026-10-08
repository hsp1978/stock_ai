"""보유 종목 — 운영자 직접 입력 (제안서 결정 2026-10-08).

`app_state` 키-값 저장소에 둔다. 새 테이블이 아니라서 Alembic 리비전이 필요 없다.
"""

from __future__ import annotations

from typing import Iterable

from db import get_app_state, set_app_state
from research.models import Holding

_STATE_KEY = "research.holdings"


def list_holdings() -> list[Holding]:
    raw = get_app_state(_STATE_KEY, default=[]) or []
    return [Holding(**row) for row in raw]


def _save(items: Iterable[Holding]) -> None:
    set_app_state(_STATE_KEY, [h.model_dump() for h in items])


def upsert_holding(holding: Holding) -> list[Holding]:
    """같은 티커가 있으면 바꾸고, 없으면 추가한다."""
    items = [h for h in list_holdings() if h.ticker != holding.ticker]
    items.append(holding)
    items.sort(key=lambda h: h.ticker)
    _save(items)
    return items


def remove_holding(ticker: str) -> bool:
    """삭제했으면 True. 없던 티커면 False — '삭제됨'으로 보고하지 않는다."""
    ticker = ticker.strip().upper()
    items = list_holdings()
    kept = [h for h in items if h.ticker != ticker]
    if len(kept) == len(items):
        return False
    _save(kept)
    return True
