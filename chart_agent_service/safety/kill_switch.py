"""
GlobalKillSwitch — 포트폴리오 수준 자동 거래 정지 메커니즘.

evaluate()  : 컨텍스트를 평가해 이벤트를 DB에 append-only 기록
is_blocked(): 현재 cool_down 상태 확인 (True 이면 신규 주문 차단)
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from starlette.responses import JSONResponse

from config import settings
from safety.models import DecisionContext, KillSwitchEvent


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS kill_switch_events (
    event_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    triggered_at     TIMESTAMP NOT NULL,
    trigger_type     TEXT      NOT NULL,
    trigger_value    REAL      NOT NULL,
    portfolio_pnl_pct REAL,
    action           TEXT      NOT NULL,
    cool_down_until  TIMESTAMP,
    metadata         TEXT
);
CREATE INDEX IF NOT EXISTS idx_kse_triggered_at ON kill_switch_events(triggered_at);
CREATE INDEX IF NOT EXISTS idx_kse_action       ON kill_switch_events(action);
"""


class GlobalKillSwitch:
    """
    포트폴리오 손실 한도, VIX, 데이터 신선도, 연속 손실 기반 자동 거래 정지.

    모든 이벤트는 kill_switch_events 테이블에 append-only로 기록된다.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            from config import OUTPUT_DIR

            db_path = os.path.join(OUTPUT_DIR, "scan_log.db")
        self._db_path = db_path
        self._ensure_table()

    # ── DB helpers ─────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_table(self) -> None:
        conn = self._get_conn()
        conn.executescript(_CREATE_TABLE)
        conn.commit()
        conn.close()

    def _record_event(self, event: KillSwitchEvent) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO kill_switch_events
               (triggered_at, trigger_type, trigger_value, portfolio_pnl_pct,
                action, cool_down_until, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                _iso(event.triggered_at),
                event.trigger_type,
                event.trigger_value,
                event.portfolio_pnl_pct,
                event.action,
                _iso(event.cool_down_until) if event.cool_down_until else None,
                json.dumps(event.metadata),
            ),
        )
        conn.commit()
        conn.close()

    # ── Public API ──────────────────────────────────────────────────────

    def evaluate(self, ctx: DecisionContext) -> list[KillSwitchEvent]:
        """컨텍스트를 평가해 이벤트 목록을 반환하고 DB에 기록한다."""
        events: list[KillSwitchEvent] = []
        now = _utcnow()
        cool_until = now + timedelta(hours=settings.COOL_DOWN_HOURS)

        def _halt(trigger_type: str, value: float, **meta: object) -> KillSwitchEvent:
            ev = KillSwitchEvent(
                triggered_at=now,
                trigger_type=trigger_type,  # type: ignore[arg-type]
                trigger_value=value,
                portfolio_pnl_pct=ctx.portfolio_pnl_pct,
                action="halt",
                cool_down_until=cool_until,
                metadata=dict(meta),
            )
            self._record_event(ev)
            return ev

        def _alert(trigger_type: str, value: float) -> KillSwitchEvent:
            ev = KillSwitchEvent(
                triggered_at=now,
                trigger_type=trigger_type,  # type: ignore[arg-type]
                trigger_value=value,
                portfolio_pnl_pct=ctx.portfolio_pnl_pct,
                action="alert",
            )
            self._record_event(ev)
            return ev

        # 1. 일일 손실 한도
        pnl = ctx.portfolio_pnl_pct
        if pnl <= -settings.DAILY_LOSS_LIMIT_HARD_PCT:
            events.append(_halt("daily_loss_halt", pnl))
        elif pnl <= -settings.DAILY_LOSS_LIMIT_ALERT_PCT:
            events.append(_alert("daily_loss_alert", pnl))

        # 2. 주간 드로우다운
        if ctx.weekly_drawdown_pct <= -settings.WEEKLY_DRAWDOWN_LIMIT_PCT:
            events.append(_halt("weekly_drawdown_halt", ctx.weekly_drawdown_pct))

        # 3. 고점 대비 드로우다운
        if ctx.trailing_peak_dd_pct <= -settings.TRAILING_PEAK_DD_PCT:
            events.append(_halt("trailing_dd_halt", ctx.trailing_peak_dd_pct))

        # 4. 연속 손실
        if ctx.consecutive_losses >= settings.CONSECUTIVE_LOSS_COUNT:
            events.append(_halt("consecutive_loss_halt", float(ctx.consecutive_losses)))

        # 5. VIX 임계값
        if ctx.vix >= settings.VIX_CAP:
            events.append(_halt("vix_halt", ctx.vix))

        # 6. VIX 스파이크
        if ctx.vix_prev > 0:
            spike_pct = (ctx.vix - ctx.vix_prev) / ctx.vix_prev * 100
            if spike_pct >= settings.VIX_SPIKE_PCT:
                events.append(
                    _halt(
                        "vix_spike_halt", spike_pct, vix=ctx.vix, vix_prev=ctx.vix_prev
                    )
                )

        # 7. 데이터 신선도
        if ctx.data_freshness_hours >= settings.DATA_STALENESS_HALT_HOURS:
            events.append(_halt("data_stale_halt", ctx.data_freshness_hours))

        return events

    def is_blocked(self) -> tuple[bool, str | None]:
        """현재 차단 상태 확인. (is_blocked, reason)"""
        now_iso = _iso(_utcnow())
        conn = self._get_conn()
        row = conn.execute(
            """SELECT trigger_type, cool_down_until
               FROM kill_switch_events
               WHERE action IN ('halt', 'cool_down')
                 AND cool_down_until > ?
               ORDER BY event_id DESC LIMIT 1""",
            (now_iso,),
        ).fetchone()
        conn.close()
        if row:
            return True, f"{row['trigger_type']} (해제: {row['cool_down_until']})"
        return False, None

    def get_recent_events(self, limit: int = 10) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM kill_switch_events ORDER BY event_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def force_halt(
        self, reason: str = "manual", hours: int | None = None
    ) -> KillSwitchEvent:
        """수동으로 halt 이벤트를 기록한다 (테스트 / 긴급 차단용)."""
        now = _utcnow()
        cool_hours = hours if hours is not None else settings.COOL_DOWN_HOURS
        ev = KillSwitchEvent(
            triggered_at=now,
            trigger_type="manual_halt",
            trigger_value=0.0,
            action="halt",
            cool_down_until=now + timedelta(hours=cool_hours),
            metadata={"reason": reason},
        )
        self._record_event(ev)
        return ev

    def release_halt(self, reason: str = "manual") -> int:
        """활성 halt/cool_down 이벤트들의 cool_down_until 을 현재로 만료시켜
        is_blocked() = False 가 되도록 한다. 수동 해제 트랙용 audit 이벤트도 함께 기록.

        Returns: 만료시킨 활성 이벤트 수.
        """
        now = _utcnow()
        now_iso = _iso(now)
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """UPDATE kill_switch_events
                   SET cool_down_until = ?
                   WHERE action IN ('halt', 'cool_down')
                     AND cool_down_until > ?""",
                (now_iso, now_iso),
            )
            affected = cur.rowcount or 0
            conn.commit()
        finally:
            conn.close()

        # audit 이벤트 1건 기록 (action='alert', cool_down 없음)
        audit = KillSwitchEvent(
            triggered_at=now,
            trigger_type="manual_release",
            trigger_value=float(affected),
            action="alert",
            cool_down_until=None,
            metadata={"reason": reason, "released_count": affected},
        )
        self._record_event(audit)
        return affected


# ── 경로 보호 헬퍼 (service.py 미들웨어와 공유) ───────────────────────
# (prefix, allowed_methods) — 해당 메서드일 때만 차단.
# GET류 조회 경로(/trading/orders/recent 등)는 차단되지 않아 운영 가시성이 유지된다.
# /trading/kill-switch/activate|deactivate는 의도적으로 미보호 — kill switch 활성
# 상태에서도 토글이 가능해야 한다.
_PROTECTED_PREFIXES: tuple[tuple[str, frozenset[str]], ...] = (
    ("/decide", frozenset({"POST"})),
    ("/scan", frozenset({"POST"})),
    ("/paper/order", frozenset({"POST"})),
    ("/paper/virtual-buy", frozenset({"POST"})),
    ("/paper/partial-close", frozenset({"POST"})),
    ("/execute", frozenset({"POST"})),
    ("/trading/orders", frozenset({"POST"})),
    ("/trading/approval", frozenset({"POST"})),
)


def _is_kill_switch_protected(path: str, method: str = "POST") -> bool:
    """경로/메서드가 kill switch 보호 대상인지.

    `method` 기본값 "POST"는 기존 호출자(테스트 포함)의 시그니처 호환을 위함.
    """
    method_upper = method.upper()
    for prefix, methods in _PROTECTED_PREFIXES:
        if method_upper not in methods:
            continue
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


# ── 모듈 수준 싱글톤 ──────────────────────────────────────────────────

_instance: GlobalKillSwitch | None = None


def get_kill_switch() -> GlobalKillSwitch:
    """프로세스 내 싱글톤 반환."""
    global _instance
    if _instance is None:
        _instance = GlobalKillSwitch()
    return _instance


class KillSwitchASGIMiddleware:
    """FastAPI/Starlette용 kill switch ASGI 미들웨어."""

    def __init__(self, app, kill_switch: GlobalKillSwitch | None = None):
        self.app = app
        self.kill_switch = kill_switch

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path", "")
            method = scope.get("method", "GET")
            if _is_kill_switch_protected(path, method):
                ks = self.kill_switch or get_kill_switch()
                blocked, reason = ks.is_blocked()
                if blocked:
                    response = JSONResponse(
                        status_code=423,
                        content={"detail": "kill_switch_active", "reason": reason},
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)
