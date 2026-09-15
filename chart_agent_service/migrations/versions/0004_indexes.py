"""인덱스 — 컬럼 리비전이 모두 끝난 뒤에 만든다

`db._CREATE_INDEX` 에는 `signal_outcomes(regime)` 처럼 **후속 리비전에서 생기는
컬럼**을 참조하는 인덱스가 있다. 베이스라인에서 만들면 옛 DB 에서 컬럼이 생기기
전에 실행돼 `no such column: regime` 으로 죽는다 (2026-09-15 테스트가 잡았다).

그래서 인덱스만 마지막으로 분리한다. 전부 `IF NOT EXISTS` 라 재실행은 무해하다.

Revision ID: 0004_indexes
Revises: 0003_scan_log_entry_price
"""
from alembic import op

revision = "0004_indexes"
down_revision = "0003_scan_log_entry_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    import db

    conn = op.get_bind()
    for statement in db._CREATE_INDEX.split(";"):
        body = "\n".join(
            line for line in statement.splitlines() if not line.strip().startswith("--")
        ).strip()
        if body:
            conn.exec_driver_sql(body)


def downgrade() -> None:
    import db
    import re

    conn = op.get_bind()
    for statement in db._CREATE_INDEX.split(";"):
        m = re.search(r"CREATE INDEX IF NOT EXISTS\s+(\w+)", statement)
        if m:
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS {m.group(1)}")
