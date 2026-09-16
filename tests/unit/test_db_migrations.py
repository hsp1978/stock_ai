"""스키마 마이그레이션 — 버전이 기록되고, 실패가 숨지 않는다.

CLAUDE.md Don't #8: "DB 직접 SQL 변경 금지. Alembic migration 도입 후
마이그레이션 스크립트로만." 규정은 있었지만 도구가 없었다. 종전 `init_db()` 는:

    conn.execute(_CREATE_TABLE)                  # IF NOT EXISTS
    try:
        conn.execute("ALTER TABLE ... ADD COLUMN ...")
    except sqlite3.OperationalError:
        pass    # 이미 존재

문제 셋:
  1. **버전 기록이 없다** — 어떤 DB 가 어디까지 왔는지 알 수 없다
  2. **실패가 숨는다** — "이미 존재"와 진짜 오류가 같은 처리다 (§13-1)
  3. 데이터 마이그레이션(백필)을 넣을 자리가 없다

SQLAlchemy 모델은 쓰지 않는다 (DB 계층 전체가 raw sqlite3). Alembic 은 **버전
관리와 순서 보장**만 담당하고 마이그레이션은 손으로 쓴다.

여기서 고정하는 것:
  1. 빈 DB → 전체 리비전 적용 (fresh)
  2. Alembic 이전 DB → 실제 스키마에 맞는 리비전으로 stamp (adopt).
     컬럼이 빠져 있으면 **head 가 아니라 베이스라인으로** stamp 해 후속 리비전이 돈다
  3. 재실행은 멱등이고 데이터를 건드리지 않는다
  4. 어느 경로를 탔는지 반환값에 남는다 ('이미 최신' ≠ '방금 만들었다')
  5. 베이스라인 SQL 은 db.py 의 상수를 그대로 쓴다 — 복사하면 갈린다
"""

import os
import sqlite3
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import db  # noqa: E402

_CORE_TABLES = {
    "scan_log", "signal_outcomes", "screener_results",
    "user_action_log", "kill_switch_events", "app_state",
}
_LATE_COLUMNS = {
    "signal_std", "agreement_level", "eval_state",
    "benchmark_symbol", "benchmark_return_7d", "benchmark_return_14d",
    "benchmark_return_30d",
    "adverse_excursion_7d", "adverse_excursion_14d", "adverse_excursion_30d",
}


def _objects(path, kind="table"):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = ?", (kind,)
            )
        }
    finally:
        conn.close()


def _columns(path, table):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


# ── fresh ─────────────────────────────────────────────────────────


def test_fresh_database_gets_the_full_schema(tmp_path):
    path = str(tmp_path / "fresh.db")

    result = db.run_migrations(path)

    assert result["mode"] == "fresh"
    assert result["revision"] == "0004_indexes"
    assert _CORE_TABLES <= _objects(path)
    assert "alembic_version" in _objects(path)


def test_fresh_database_gets_the_view_and_indexes(tmp_path):
    """VIEW 가 빠지면 signal_performance_summary 조회가 죽는다."""
    path = str(tmp_path / "fresh.db")
    db.run_migrations(path)

    assert "signal_performance_summary" in _objects(path, "view")
    indexes = {n for n in _objects(path, "index") if n.startswith("idx_")}
    assert len(indexes) >= 10, indexes


def test_fresh_schema_includes_late_columns(tmp_path):
    """베이스라인 CREATE TABLE 에 이미 들어 있어야 한다 (후속 리비전은 옛 DB 용)."""
    path = str(tmp_path / "fresh.db")
    db.run_migrations(path)

    assert _LATE_COLUMNS <= _columns(path, "signal_outcomes")
    assert "entry_price" in _columns(path, "scan_log")


# ── adopt (Alembic 이전 DB) ───────────────────────────────────────


def _legacy_db(path, *, with_late_columns: bool):
    conn = sqlite3.connect(path)
    late = (
        ", ".join(f"{c} REAL" if "return" in c or "excursion" in c or c == "signal_std"
                  else f"{c} TEXT" for c in sorted(_LATE_COLUMNS))
        if with_late_columns else ""
    )
    conn.executescript(
        f"""
        CREATE TABLE scan_log (
            id INTEGER PRIMARY KEY, ticker TEXT, scanned_at TEXT
            {", entry_price REAL" if with_late_columns else ""}
        );
        CREATE TABLE signal_outcomes (
            signal_id TEXT PRIMARY KEY, ticker TEXT NOT NULL,
            signal_type TEXT NOT NULL, signal_source TEXT NOT NULL,
            issued_at TIMESTAMP NOT NULL, conviction REAL NOT NULL,
            price_at_signal REAL NOT NULL, return_7d REAL,
            -- V2 초기 스키마에 있던 컬럼들 (Step 12 이전)
            return_14d REAL, return_30d REAL, max_drawdown_30d REAL,
            evaluated_at TIMESTAMP, market_context TEXT, regime TEXT
            {", " + late if late else ""}
        );
        INSERT INTO signal_outcomes
            (signal_id, ticker, signal_type, signal_source, issued_at,
             conviction, price_at_signal, return_7d)
        VALUES ('s1', 'PLTR', 'buy', 'scan_agent', '2026-08-01', 8.0, 100.0, 0.05);
        """
    )
    conn.commit()
    conn.close()


def test_legacy_db_missing_columns_is_caught_up(tmp_path):
    """핵심 — 기존 DB 를 head 로 stamp 하면 빠진 것이 영영 안 채워진다.

    처음 구현은 "이미 최신이면 head, 아니면 베이스라인으로 stamp" 였다. 그 방식은
    스키마가 **일부만** 있는 DB 에서 깨졌다 — stamp 는 0001 을 건너뛰므로 없는
    테이블이 안 만들어진다 (test_direction_adjusted_metrics 가 잡았다).
    지금은 채택 시에도 처음부터 올린다: 0001 은 전부 IF NOT EXISTS,
    0002·0003 은 컬럼 존재를 직접 확인한다.
    """
    path = str(tmp_path / "legacy.db")
    _legacy_db(path, with_late_columns=False)

    result = db.run_migrations(path)

    assert result["mode"] == "adopt"
    assert result["revision"] == "0004_indexes"
    assert _LATE_COLUMNS <= _columns(path, "signal_outcomes"), "후속 리비전이 돌지 않았다"
    assert "entry_price" in _columns(path, "scan_log")


def test_partial_schema_db_gets_missing_tables(tmp_path):
    """테이블이 일부만 있는 DB — stamp 방식이 여기서 깨졌다."""
    path = str(tmp_path / "partial.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE signal_outcomes (
            signal_id TEXT PRIMARY KEY, ticker TEXT NOT NULL,
            signal_type TEXT NOT NULL, signal_source TEXT NOT NULL,
            issued_at TIMESTAMP NOT NULL, conviction REAL NOT NULL,
            price_at_signal REAL NOT NULL, return_7d REAL,
            return_14d REAL, return_30d REAL, max_drawdown_30d REAL,
            evaluated_at TIMESTAMP, market_context TEXT, regime TEXT);
        """
    )
    conn.commit()
    conn.close()

    result = db.run_migrations(path)

    assert result["mode"] == "adopt"
    assert _CORE_TABLES <= _objects(path), "빠진 테이블이 채워지지 않았다"
    assert _LATE_COLUMNS <= _columns(path, "signal_outcomes")


def test_adoption_preserves_existing_rows(tmp_path):
    path = str(tmp_path / "legacy.db")
    _legacy_db(path, with_late_columns=False)

    db.run_migrations(path)

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0] == 1
        row = conn.execute("SELECT ticker, return_7d FROM signal_outcomes").fetchone()
        assert row == ("PLTR", 0.05)
    finally:
        conn.close()


def test_up_to_date_legacy_db_is_stamped_to_head(tmp_path):
    """이미 최신 스키마인 DB 는 후속 리비전을 다시 돌릴 필요가 없다."""
    path = str(tmp_path / "current.db")
    _legacy_db(path, with_late_columns=True)

    result = db.run_migrations(path)

    assert result["mode"] == "adopt"
    assert result["revision"] == "0004_indexes"


def test_pre_v2_outcomes_table_is_moved_aside(tmp_path):
    """signal_id 가 없는 V2 이전 테이블은 베이스라인이 만들 수 없다."""
    path = str(tmp_path / "prev2.db")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE signal_outcomes (
            id INTEGER PRIMARY KEY, scan_log_id INTEGER, return_7d REAL);
        INSERT INTO signal_outcomes (scan_log_id, return_7d) VALUES (1, 0.03);
        """
    )
    conn.commit()
    conn.close()

    db.run_migrations(path)

    tables = _objects(path)
    assert "signal_outcomes_legacy" in tables, "옛 데이터를 지웠다"
    assert "signal_id" in _columns(path, "signal_outcomes")
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM signal_outcomes_legacy").fetchone()[0] == 1
    finally:
        conn.close()


# ── 멱등성 ────────────────────────────────────────────────────────


def test_rerun_is_idempotent(tmp_path):
    path = str(tmp_path / "fresh.db")
    db.run_migrations(path)
    conn = sqlite3.connect(path)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source, issued_at,
            conviction, price_at_signal)
           VALUES ('x', 'MSFT', 'buy', 'scan_agent', '2026-09-01', 7.0, 400.0)"""
    )
    conn.commit()
    conn.close()

    again = db.run_migrations(path)

    assert again["mode"] == "upgrade"          # 이미 버전 관리 중
    assert again["revision"] == "0004_indexes"
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0] == 1
    finally:
        conn.close()


def test_current_revision_reports_unmanaged_db(tmp_path):
    """'미관리'와 '최신'을 구분할 수 있어야 한다."""
    path = str(tmp_path / "plain.db")
    sqlite3.connect(path).close()

    assert db.current_revision(path) is None

    db.run_migrations(path)
    assert db.current_revision(path) == "0004_indexes"


# ── 설계 불변식 ───────────────────────────────────────────────────


def test_baseline_reuses_db_constants_instead_of_copying_sql():
    """SQL 을 리비전에 복사하면 db.py 와 갈리고, 갈린 쪽을 아무도 모른다."""
    path = os.path.join(_AGENT_DIR, "migrations", "versions", "0001_baseline_schema.py")
    src = open(path, encoding="utf-8").read()

    assert "db._CREATE_TABLE" in src
    assert "db._CREATE_OUTCOMES_TABLE" in src
    assert "CREATE TABLE IF NOT EXISTS signal_outcomes" not in src, "SQL 을 복사했다"


def test_init_db_no_longer_owns_ddl():
    """스키마 변경은 리비전으로만. init_db 에 CREATE/ALTER 를 되돌리지 말 것.

    docstring 은 과거 경위를 설명하느라 `ALTER TABLE` 을 인용한다 — 문자열
    슬라이싱으로 보면 그것까지 코드로 읽는다. AST 로 **본문만** 본다.
    """
    import ast

    src = open(os.path.join(_AGENT_DIR, "db.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    func = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "init_db"
    )
    statements = func.body
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
    ):
        statements = statements[1:]          # docstring 제외
    body = "\n".join(ast.unparse(node) for node in statements)

    assert "ALTER TABLE" not in body, "init_db 가 다시 ALTER 를 들고 있다"
    assert "CREATE TABLE" not in body, "init_db 가 다시 CREATE TABLE 을 들고 있다"
    assert "run_migrations()" in body


def _code_without_docstrings(path: str) -> str:
    """docstring 을 제외한 코드만. 주석·설명 인용을 코드로 오인하지 않기 위해서다."""
    import ast

    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_migrations_do_not_swallow_operational_errors():
    """`except sqlite3.OperationalError: pass` 가 이 결함의 원인이었다.

    리비전 docstring 들은 그 옛 코드를 **인용**한다 — 원문 검색으로 보면 인용까지
    위반으로 읽는다. 코드만 본다.
    """
    import glob

    for path in glob.glob(os.path.join(_AGENT_DIR, "migrations", "versions", "*.py")):
        code = _code_without_docstrings(path)
        name = os.path.basename(path)
        assert "OperationalError" not in code, f"{name}: 오류를 삼킨다"
        assert "except Exception" not in code, f"{name}: 광범위 except"


def test_baseline_downgrade_is_blocked(tmp_path):
    """베이스라인 downgrade 는 전체 데이터 삭제다."""
    sys.path.insert(0, os.path.join(_AGENT_DIR, "migrations", "versions"))
    import importlib

    mod = importlib.import_module("0001_baseline_schema")
    with pytest.raises(NotImplementedError):
        mod.downgrade()


# ── 로깅 설정을 덮지 않는다 ───────────────────────────────────────
#
# 2026-09-15 회귀 (PR #72 가 만든 것). Alembic 템플릿의 기본 env.py 는
# `fileConfig(config.config_file_name)` 을 호출하는데, 그건 alembic.ini 의
# 로깅 섹션으로 **루트 로거를 통째로 교체**한다. 서비스는 기동 시
# `logging_setup.configure_logging()` 으로 로깅을 구성하고, 그 직후
# `init_db()` → 마이그레이션이 돌기 때문에 설정이 덮였다.
#
#   configure_logging 직후 : root=INFO    formatter=[%(name)s]  filters=[SecretRedactingFilter]
#   init_db(alembic) 이후  : root=WARNING formatter=[alembic]   filters=[]
#
# 피해 셋: logger.info 전부 소실(배치 진행 로그를 못 봤다), 모든 로그가 `[alembic]`
# 로 표기, 그리고 **API 키 마스킹 필터 제거** — #61 에서 막은 유출이 되살아났다.


def test_migrations_do_not_clobber_logging_config(tmp_path):
    """레벨·포맷·마스킹 필터가 마이그레이션 후에도 살아 있어야 한다."""
    import logging

    sys.path.insert(0, _AGENT_DIR)
    import logging_setup

    logging_setup.configure_logging(force=True)
    root = logging.getLogger()
    handler = root.handlers[0]
    before = (
        root.level,
        getattr(handler.formatter, "_fmt", None),
        sorted(type(f).__name__ for f in handler.filters),
    )
    assert "SecretRedactingFilter" in before[2], "전제가 깨졌다 — 마스킹 필터가 없다"

    db.run_migrations(str(tmp_path / "logging.db"))

    root = logging.getLogger()
    handler = root.handlers[0]
    after = (
        root.level,
        getattr(handler.formatter, "_fmt", None),
        sorted(type(f).__name__ for f in handler.filters),
    )
    assert after == before, f"마이그레이션이 로깅 설정을 바꿨다\n  전: {before}\n  후: {after}"


def test_env_py_does_not_call_fileconfig():
    """호출하면 루트 로거가 alembic.ini 설정으로 교체된다."""
    src = open(os.path.join(_AGENT_DIR, "migrations", "env.py"), encoding="utf-8").read()
    code = _code_without_docstrings(
        os.path.join(_AGENT_DIR, "migrations", "env.py")
    )

    assert "fileConfig" not in code, "env.py 가 fileConfig 를 호출한다"
    assert "logging" not in code.replace("logging_setup", ""), "env.py 가 로깅을 건드린다"
    del src


def test_alembic_ini_has_no_logging_sections():
    """섹션이 있으면 CLI 단독 실행(`alembic upgrade`)에서 다시 덮인다.

    ini 의 설명 주석이 `[loggers]` 를 인용하므로 **주석을 걷어내고** 본다.
    """
    lines = open(os.path.join(_AGENT_DIR, "alembic.ini"), encoding="utf-8").read().splitlines()
    sections = {
        line.strip() for line in lines
        if line.strip().startswith("[") and not line.lstrip().startswith("#")
    }

    assert sections == {"[alembic]"}, f"로깅 섹션이 남아 있다: {sorted(sections)}"
