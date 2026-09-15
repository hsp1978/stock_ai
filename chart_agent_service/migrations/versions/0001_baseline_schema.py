"""baseline — 2026-09-15 시점 scan_log.db 스키마 전체

Alembic 채택 시점의 베이스라인이다. `db.py` 의 `_CREATE_*` 상수를 **그대로**
실행한다 — SQL 을 여기 복사하면 두 곳이 갈리고, 갈린 쪽을 아무도 모른다.

기존 운영 DB 는 이 리비전을 실행하지 않고 `stamp` 로 채택한다
(`db._alembic_bootstrap`). 모든 문장이 `IF NOT EXISTS` 라 실행돼도 안전하지만,
"이미 최신"과 "방금 만들었다"를 구분하기 위해 경로를 나눈다.

Revision ID: 0001_baseline
Revises: None
"""
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _db_module():
    import db

    return db


def _exec_script(conn, sql: str) -> None:
    """여러 문장을 순서대로 실행한다.

    `exec_driver_sql` 은 한 번에 한 문장만 받는다("You can only execute one
    statement at a time"). `sqlite3.executescript` 를 쓰면 되지만 그쪽은 암묵적
    COMMIT 을 걸어 Alembic 의 트랜잭션·버전 기록을 흐트러뜨린다. 그래서 직접
    쪼갠다 — `db.py` 의 DDL 에는 문자열 리터럴 안의 세미콜론이 없다.
    """
    for statement in sql.split(";"):
        # 주석으로 **시작하는** 청크를 통째로 버리면 안 된다 — VIEW 정의가 `--`
        # 주석 5줄 뒤에 온다. 주석 줄만 걷어내고 남은 것이 있는지 본다.
        body = "\n".join(
            line for line in statement.splitlines() if not line.strip().startswith("--")
        ).strip()
        if not body:
            continue
        conn.exec_driver_sql(body)


def upgrade() -> None:
    db = _db_module()
    conn = op.get_bind()

    # 실행 순서는 db.init_db() 와 같아야 한다 (VIEW 가 테이블을 참조한다).
    for stmt in (
        db._CREATE_TABLE,
        db._CREATE_OUTCOMES_TABLE,
        db._CREATE_SCREENER_TABLE,
        db._CREATE_USER_ACTION_TABLE,
        db._CREATE_KILL_SWITCH_TABLE,
        db._CREATE_APP_STATE_TABLE,
        # 인덱스는 여기서 만들지 않는다 — `_CREATE_INDEX` 에 `signal_outcomes(regime)`
        # 같은 후속 컬럼 참조가 있어서, 옛 DB 에서는 컬럼이 생기기 전에 실행돼
        # "no such column" 으로 죽는다 (2026-09-15 테스트가 잡았다).
        # 컬럼 리비전이 모두 끝난 뒤 0004 에서 만든다.
    ):
        _exec_script(conn, stmt)

    # VIEW 는 IF NOT EXISTS 가 옛 정의를 남기므로 항상 재생성한다
    # (2026-09 방향 보정에서 실제로 문제가 됐다 — db.init_db() 주석 참조).
    conn.exec_driver_sql("DROP VIEW IF EXISTS signal_performance_summary")
    _exec_script(conn, db._CREATE_SIGNAL_PERF_VIEW)


def downgrade() -> None:
    # 베이스라인을 되돌리면 운영 데이터 전체가 사라진다. 막아 둔다 —
    # 스키마를 비우려면 백업에서 복구하는 쪽이 옳다 (docs/RUNBOOK_BACKUP.md).
    raise NotImplementedError(
        "베이스라인 downgrade 는 전체 데이터 삭제다. 복구는 RUNBOOK_BACKUP.md §4 참조."
    )
