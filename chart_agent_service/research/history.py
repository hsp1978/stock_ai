"""리서치 잡 실행 이력 — 게이트 2 판정의 근거.

잡 상태(`_JOB_STATUS`)는 **마지막 실행 1건**만 남긴다. 2주 병행 기간의 '모든 거래일에
전달됐는가'를 판정하려면 실행마다 결과를 쌓아야 한다. `app_state` 에 최근 N건을 둔다
(새 테이블이 아니라 Alembic 리비전 불필요).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

_KEY = "research.job_history"
_LIMIT = 3000  # 30분 공시 감시 × 2주 ≈ 700 + 브리핑 20 — 여유 있게


def record_run(job_id: str, started_at: datetime, result: Optional[dict], error: str = "") -> None:
    """실행 1건을 남긴다. 기록 실패는 잡을 실패시키지 않는다 — 호출자가 로그를 남긴다."""
    from db import get_app_state, set_app_state

    result = result or {}
    entry = {
        "job_id": job_id,
        "started_at": _utc_iso(started_at),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": result.get("status") or ("error" if error else "unknown"),
        "delivered": bool(result.get("delivered")),
        "market": result.get("market"),
        "items": result.get("items"),
        "new_disclosures": result.get("new_disclosures"),
        "alerted": list(result.get("alerted") or []),
        "initialized": list(result.get("initialized") or []),
        "error": (error or "")[:300],
    }
    rows = get_app_state(_KEY, default=[]) or []
    rows.append(entry)
    set_app_state(_KEY, rows[-_LIMIT:])


def load_history() -> list[dict]:
    from db import get_app_state

    return get_app_state(_KEY, default=[]) or []


def _utc_iso(dt: datetime) -> str:
    # 서비스는 naive datetime.now() 를 쓴다 — 컨테이너 TZ 가 UTC 다 (CLAUDE.md §6-9-1)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
