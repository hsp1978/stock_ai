"""
사용자 승인 대기 큐 (APPROVAL 모드 전용).

주문 → 승인 큐 적재 → Telegram 알림 → 사용자 승인 → 브로커 제출.
미승인 주문은 TTL(기본 30분) 후 자동 만료.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from brokers.base import OrderRequest


APPROVAL_TTL_MINUTES = int(os.getenv("APPROVAL_TTL_MINUTES", "30"))


class ApprovalQueue:
    """SQLite 기반 승인 대기 큐."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_EXPIRED = "expired"
    STATUS_EXECUTED = "executed"

    def __init__(self, db_path: Optional[str] = None):
        from config import OUTPUT_DIR
        self.db_path = db_path or os.path.join(OUTPUT_DIR, "approval_queue.db")
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS approval_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_order_id TEXT UNIQUE,
                ticker TEXT,
                side TEXT,
                qty INTEGER,
                order_type TEXT,
                limit_price REAL,
                order_json TEXT,
                status TEXT DEFAULT 'pending',
                requested_at TEXT,
                responded_at TEXT,
                responder TEXT,
                execution_result TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON approval_queue(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_requested ON approval_queue(requested_at)")
        conn.commit()
        conn.close()

    def enqueue(self, req: OrderRequest) -> int:
        """주문을 대기 큐에 추가. row id 반환."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute("""
                INSERT INTO approval_queue (
                    client_order_id, ticker, side, qty, order_type, limit_price,
                    order_json, status, requested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                req.client_order_id, req.ticker, req.side, req.qty, req.order_type,
                req.limit_price,
                json.dumps(req.to_dict(), default=str, ensure_ascii=False),
                self.STATUS_PENDING,
                datetime.now().isoformat(),
            ))
            row_id = cur.lastrowid
            conn.commit()
            conn.close()
        return row_id

    def approve(self, queue_id: int, responder: str = "user") -> bool:
        """승인 처리."""
        return self._update_status(queue_id, self.STATUS_APPROVED, responder)

    def reject(self, queue_id: int, responder: str = "user") -> bool:
        return self._update_status(queue_id, self.STATUS_REJECTED, responder)

    def mark_executed(self, queue_id: int, result_summary: Optional[str] = None) -> bool:
        """승인된 주문이 실행 완료된 후 호출."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE approval_queue SET status=?, execution_result=? WHERE id=?",
                (self.STATUS_EXECUTED, result_summary, queue_id),
            )
            changed = conn.total_changes > 0
            conn.commit()
            conn.close()
        return changed

    def _update_status(self, queue_id: int, new_status: str, responder: str) -> bool:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """UPDATE approval_queue
                   SET status=?, responded_at=?, responder=?
                   WHERE id=? AND status=?""",
                (new_status, datetime.now().isoformat(), responder, queue_id, self.STATUS_PENDING),
            )
            changed = conn.total_changes > 0
            conn.commit()
            conn.close()
        return changed

    def get_pending(self, max_age_minutes: int = APPROVAL_TTL_MINUTES) -> List[Dict[str, Any]]:
        """만료 안 된 대기 주문 반환."""
        cutoff = (datetime.now() - timedelta(minutes=max_age_minutes)).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM approval_queue WHERE status=? AND requested_at >= ? ORDER BY id DESC",
            (self.STATUS_PENDING, cutoff),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_by_client_order_id(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM approval_queue WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def expire_old(self) -> int:
        """TTL 초과된 pending 주문을 expired로 변경."""
        cutoff = (datetime.now() - timedelta(minutes=APPROVAL_TTL_MINUTES)).isoformat()
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE approval_queue SET status=? WHERE status=? AND requested_at < ?",
                (self.STATUS_EXPIRED, self.STATUS_PENDING, cutoff),
            )
            changed = conn.total_changes
            conn.commit()
            conn.close()
        return changed

    def restore_request(self, queue_row: Dict[str, Any]) -> OrderRequest:
        """큐 row에서 OrderRequest 복원."""
        data = json.loads(queue_row["order_json"])
        return OrderRequest(
            ticker=data["ticker"],
            qty=data["qty"],
            side=data["side"],
            order_type=data.get("order_type", "market"),
            limit_price=data.get("limit_price"),
            stop_price=data.get("stop_price"),
            time_in_force=data.get("time_in_force", "day"),
            client_order_id=data.get("client_order_id"),
            source=data.get("source", "approval_queue"),
            reason=data.get("reason"),
            entry_plan_snapshot=data.get("entry_plan_snapshot"),
        )

    def stats(self) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM approval_queue GROUP BY status"
        ).fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}


_global_queue: Optional[ApprovalQueue] = None


def get_approval_queue() -> ApprovalQueue:
    global _global_queue
    if _global_queue is None:
        _global_queue = ApprovalQueue()
    return _global_queue
