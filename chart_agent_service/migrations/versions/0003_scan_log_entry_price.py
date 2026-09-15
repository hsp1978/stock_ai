"""scan_log.entry_price — 베이스라인 이전 DB 를 따라잡는다

베이스라인(`0001`)의 `CREATE TABLE scan_log` 에는 이미 들어 있다. 이 리비전은
그보다 오래된 DB 를 위한 것이다.

종전 `db.init_db()` 는 이렇게 했다:

    try:
        conn.execute("ALTER TABLE scan_log ADD COLUMN entry_price REAL")
    except sqlite3.OperationalError:
        pass  # 이미 존재

0002 와 같은 이유로 존재 확인을 명시하고, 그 외 오류는 올린다.

Revision ID: 0003_scan_log_entry_price
Revises: 0002_signal_outcomes_columns
"""
from alembic import op

revision = "0003_scan_log_entry_price"
down_revision = "0002_signal_outcomes_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {
        row[1] for row in conn.exec_driver_sql("PRAGMA table_info(scan_log)").fetchall()
    }
    if not cols:
        raise RuntimeError("scan_log 테이블이 없다 — 0001 베이스라인을 먼저 적용하라")
    if "entry_price" not in cols:
        conn.exec_driver_sql("ALTER TABLE scan_log ADD COLUMN entry_price REAL")


def downgrade() -> None:
    raise NotImplementedError(
        "entry_price 는 리포트·주문 경로가 읽는다. 복구는 RUNBOOK_BACKUP.md §4 참조."
    )
