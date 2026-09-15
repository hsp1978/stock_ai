"""signal_outcomes 후속 컬럼 — 베이스라인 이전 DB 를 따라잡는다

베이스라인(`0001`)의 `CREATE TABLE` 에는 이 컬럼들이 이미 들어 있다. 이 리비전은
**그보다 먼저 만들어진 DB**를 위한 것이다 (Step 12 / 2026-09 에 손으로 추가했던
것들). 예: 옛 백업을 복구한 경우.

종전에는 `db._migrate_signal_outcomes()` 가 이렇게 했다:

    try:
        conn.execute(f"ALTER TABLE signal_outcomes ADD COLUMN {col} {coltype}")
    except sqlite3.OperationalError:
        pass    # 이미 존재

"이미 존재"와 **진짜 오류**를 같은 것으로 취급한다 (CLAUDE.md §13-1). 여기서는
`PRAGMA table_info` 로 존재를 확인하고, 그 외 오류는 그대로 올린다.

Revision ID: 0002_signal_outcomes_columns
Revises: 0001_baseline
"""
from alembic import op

revision = "0002_signal_outcomes_columns"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

#: (컬럼, 타입). 베이스라인 CREATE TABLE 과 이름·타입이 일치해야 한다.
_COLUMNS = (
    ("signal_std", "REAL"),
    ("agreement_level", "TEXT"),
    ("eval_state", "TEXT"),
    ("benchmark_symbol", "TEXT"),
    ("benchmark_return_7d", "REAL"),
    ("benchmark_return_14d", "REAL"),
    ("benchmark_return_30d", "REAL"),
    ("adverse_excursion_7d", "REAL"),
    ("adverse_excursion_14d", "REAL"),
    ("adverse_excursion_30d", "REAL"),
)


def _existing_columns(conn) -> set[str]:
    rows = conn.exec_driver_sql("PRAGMA table_info(signal_outcomes)").fetchall()
    return {row[1] for row in rows}


def upgrade() -> None:
    conn = op.get_bind()
    present = _existing_columns(conn)
    if not present:
        # 테이블 자체가 없다 = 0001 이 만들지 않았다는 뜻이므로 조용히 넘기지 않는다.
        raise RuntimeError("signal_outcomes 테이블이 없다 — 0001 베이스라인을 먼저 적용하라")

    for column, coltype in _COLUMNS:
        if column in present:
            continue
        # ALTER 실패는 삼키지 않는다 — 존재 여부는 위에서 이미 걸렀다.
        conn.exec_driver_sql(
            f"ALTER TABLE signal_outcomes ADD COLUMN {column} {coltype}"
        )


def downgrade() -> None:
    # SQLite 는 DROP COLUMN 이 3.35+ 에서만 되고, 되돌려도 데이터가 사라진다.
    # 측정 체계가 이 컬럼들에 의존하므로(벤치마크·역행폭) 내리지 않는다.
    raise NotImplementedError(
        "이 컬럼들은 평가 지표의 입력이다. 되돌리려면 백업에서 복구하라 "
        "(docs/RUNBOOK_BACKUP.md §4)."
    )
