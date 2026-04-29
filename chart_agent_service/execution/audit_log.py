"""
주문 감사 로그 — 모든 주문 시도/결과를 SQLite에 기록.

Phase 2 운영 안정화 기간에 "어떤 주문이 왜 실행/거부됐는지"를
모두 추적 가능하게 함.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from brokers.base import OrderRequest, OrderResult


class AuditLog:
    """SQLite 기반 주문 감사 로그."""

    def __init__(self, db_path: Optional[str] = None):
        from config import OUTPUT_DIR
        self.db_path = db_path or os.path.join(OUTPUT_DIR, "order_audit.db")
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS order_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_order_id TEXT,
                broker_order_id TEXT,
                broker TEXT,
                ticker TEXT,
                side TEXT,
                qty INTEGER,
                order_type TEXT,
                limit_price REAL,
                stop_price REAL,
                source TEXT,
                reason TEXT,
                trading_mode TEXT,
                safety_check_passed INTEGER,
                safety_reason TEXT,
                result_status TEXT,
                result_success INTEGER,
                filled_qty INTEGER DEFAULT 0,
                avg_fill_price REAL,
                error_message TEXT,
                entry_plan_snapshot TEXT,
                raw_response TEXT,
                created_at TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_ticker ON order_audit(ticker)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_created ON order_audit(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_client_id ON order_audit(client_order_id)"
        )
        conn.commit()
        conn.close()

    def log(
        self,
        req: OrderRequest,
        result: Optional[OrderResult] = None,
        trading_mode: str = "",
        safety_passed: bool = True,
        safety_reason: str = "ok",
    ) -> int:
        """감사 로그 1건 기록. INSERT된 행 ID 반환."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cur = conn.execute("""
                INSERT INTO order_audit (
                    client_order_id, broker_order_id, broker,
                    ticker, side, qty, order_type, limit_price, stop_price,
                    source, reason, trading_mode,
                    safety_check_passed, safety_reason,
                    result_status, result_success,
                    filled_qty, avg_fill_price, error_message,
                    entry_plan_snapshot, raw_response, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                req.client_order_id,
                result.broker_order_id if result else None,
                result.broker if result else "",
                req.ticker, req.side, req.qty, req.order_type,
                req.limit_price, req.stop_price,
                req.source, req.reason, trading_mode,
                1 if safety_passed else 0, safety_reason,
                result.status if result else "", 1 if result and result.success else 0,
                result.filled_qty if result else 0,
                result.avg_fill_price if result else None,
                result.error_message if result else None,
                json.dumps(req.entry_plan_snapshot, ensure_ascii=False) if req.entry_plan_snapshot else None,
                json.dumps(result.raw_response, default=str, ensure_ascii=False) if result and result.raw_response else None,
                datetime.now().isoformat(),
            ))
            row_id = cur.lastrowid
            conn.commit()
            conn.close()
        return row_id

    def get_recent(self, limit: int = 50, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if ticker:
            rows = conn.execute(
                "SELECT * FROM order_audit WHERE ticker = ? ORDER BY id DESC LIMIT ?",
                (ticker.upper(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM order_audit ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_stats(self, days_back: int = 7) -> Dict[str, Any]:
        """최근 N일 통계."""
        cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
        conn = sqlite3.connect(self.db_path)
        total = conn.execute(
            "SELECT COUNT(*) FROM order_audit WHERE created_at >= ?", (cutoff,)
        ).fetchone()[0]
        by_mode = conn.execute(
            """SELECT trading_mode, COUNT(*) FROM order_audit
               WHERE created_at >= ? GROUP BY trading_mode""",
            (cutoff,),
        ).fetchall()
        by_status = conn.execute(
            """SELECT result_status, COUNT(*) FROM order_audit
               WHERE created_at >= ? GROUP BY result_status""",
            (cutoff,),
        ).fetchall()
        blocked = conn.execute(
            "SELECT COUNT(*) FROM order_audit WHERE safety_check_passed = 0 AND created_at >= ?",
            (cutoff,),
        ).fetchone()[0]
        conn.close()
        return {
            "days_back": days_back,
            "total_orders": total,
            "blocked_by_safety": blocked,
            "by_trading_mode": {r[0] or "?": r[1] for r in by_mode},
            "by_result_status": {r[0] or "?": r[1] for r in by_status},
        }


_global_audit: Optional[AuditLog] = None


def get_audit_log() -> AuditLog:
    global _global_audit
    if _global_audit is None:
        _global_audit = AuditLog()
    return _global_audit
