"""Alembic 환경 — SQLite(scan_log.db) 스키마 버전 관리.

## 왜 도입했나

종전에는 `init_db()` 가 `CREATE TABLE IF NOT EXISTS` 와 손으로 쓴
`ALTER TABLE ADD COLUMN` 루프로 스키마를 맞췄다. 문제는 세 가지였다:

1. **버전 기록이 없다.** 어떤 DB 가 어디까지 왔는지 알 방법이 없었다.
2. **실패가 숨는다.** `except sqlite3.OperationalError: pass` 가 "이미 존재"와
   진짜 오류를 같은 것으로 취급했다 (CLAUDE.md §13-1).
3. 데이터 마이그레이션(백필·값 변환)을 넣을 자리가 없었다.

CLAUDE.md Don't #8 이 이미 "Alembic migration 도입 후 마이그레이션 스크립트로만"
을 규정하고 있었다.

## SQLAlchemy 모델은 쓰지 않는다

DB 계층 전체가 raw `sqlite3` 다. 모델이 없으니 `--autogenerate` 는 쓸 수 없고,
마이그레이션은 `op.execute()` / `op.add_column()` 으로 직접 쓴다. Alembic 은
**버전 관리와 순서 보장**만 담당한다 — 그게 필요했던 부분이다.

## 기존 DB 채택(adopt)

운영 DB 에는 이미 최신 스키마가 들어 있다. 베이스라인 리비전을 그대로 돌리면
"이미 존재" 오류가 난다. 그래서 `db.init_db()` 가 **테이블이 있으면 stamp**,
없으면 upgrade 하는 표준 채택 절차를 쓴다 (`db._alembic_bootstrap`).
"""

from __future__ import annotations

import os
import sys

from alembic import context
from sqlalchemy import create_engine, pool

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVICE_DIR = os.path.dirname(_HERE)
if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

config = context.config

# **`fileConfig()` 를 부르지 않는다.**
#
# Alembic 템플릿의 기본 env.py 는 `fileConfig(config.config_file_name)` 을 호출한다.
# 그건 alembic.ini 의 [loggers]/[handlers]/[formatters] 로 **루트 로거를 통째로
# 교체**한다. 이 서비스는 기동 시 `logging_setup.configure_logging()` 으로 이미
# 로깅을 구성하는데, `init_db()` → 마이그레이션 순서 때문에 그 설정이 덮였다.
#
# 2026-09-15 실측 피해 (PR #72 회귀):
#   configure_logging 직후 : root=INFO    formatter=[%(name)s]  filters=[SecretRedactingFilter]
#   init_db(alembic) 이후  : root=WARNING formatter=[alembic]   filters=[]
#
#   → logger.info 전부 소실 (배치 진행 로그·data_collector INFO 가 다시 죽었다)
#   → 모든 모듈 로그가 `[alembic]` 로 표기
#   → **API 키 마스킹 필터가 제거됐다** (#61 에서 막은 유출이 되살아난 상태)
#
# Alembic 은 `alembic` 로거로 남기고, 그건 루트 설정을 상속하면 충분하다.
# alembic.ini 에서도 로깅 섹션을 제거해 CLI 단독 실행 때도 덮지 않게 했다.


def _db_url() -> str:
    """대상 DB. 호출자가 넘긴 경로가 우선하고, 없으면 운영 DB 를 쓴다.

    테스트가 임시 DB 를 지정할 수 있어야 한다 — 그렇지 않으면 마이그레이션
    테스트가 운영 DB 를 건드린다 (2026-09-12 에 실제로 그런 사고가 있었다).
    """
    override = config.get_main_option("sqlalchemy.url", None)
    if override:
        return override
    path = os.environ.get("ALEMBIC_DB_PATH")
    if not path:
        from db import DB_PATH

        path = DB_PATH
    return f"sqlite:///{path}"


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_db_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            # SQLite 는 ALTER 가 제한적이다 — batch 모드로 테이블 재생성 경로를 쓴다.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
