"""운영 상태 백업·검증 — 단일 노드 SPOF 대비.

`docs/SYSTEM_OVERVIEW.md` §13.9-10: testdev 한 대가 죽으면 전부 정지하고,
**백업·복구 절차가 없다.** 잃게 되는 것은 재생성이 불가능한 것들이다:

  scan_log.db          70,840행 스캔 이력 + signal_outcomes 5,442건 + app_state
  paper_trading_state  페이퍼 포지션·체결 이력
  trading_safety.db / approval_queue.db / order_audit.db
  watchlist.txt        SSOT
  data/scan_history.db

분석 JSON 과 차트는 **백업하지 않는다** — 재생성 가능하고 1.5GB 다
(`output_retention.py` 가 따로 관리한다).

## SQLite 를 cp 로 복사하면 안 된다

DB 는 WAL 모드다 (`journal_mode=wal`). 실행 중에 `cp` 하면 `.db` 와 `-wal` 이 서로
다른 시점의 것이 되어 **복원 시 깨진다.** 더 나쁜 건 파일 크기와 개수는 멀쩡해
보인다는 점이다 — 복구를 시도하는 순간에야 알게 된다.

그래서 `sqlite3.Connection.backup()`(온라인 백업 API)을 쓴다. 원본이 쓰이는 중에도
일관된 스냅샷을 만든다. 그리고 **만든 다음 검증한다** — `PRAGMA integrity_check` 와
행 수 비교. 백업은 '만들었다'가 아니라 '복원 가능하다'가 성공이다 (§13-2).

## .env 는 기본으로 포함하지 않는다

키 60여 개가 들어 있다. 백업 파일이 곧 자격증명 사본이 된다. `include_env=True` 로
명시할 때만 넣고, 매니페스트에 그 사실을 남긴다.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR
from logging_setup import get_logger

logger = get_logger("stock_auto.state_backup")

_SERVICE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SERVICE_DIR.parent

#: (원본 경로, 아카이브 내 상대 경로). 없는 파일은 건너뛰되 매니페스트에 남긴다.
DATABASES: tuple[tuple[Path, str], ...] = (
    (Path(OUTPUT_DIR) / "scan_log.db", "output/scan_log.db"),
    (Path(OUTPUT_DIR) / "trading_safety.db", "output/trading_safety.db"),
    (Path(OUTPUT_DIR) / "approval_queue.db", "output/approval_queue.db"),
    (Path(OUTPUT_DIR) / "order_audit.db", "output/order_audit.db"),
    (_SERVICE_DIR / "data" / "scan_history.db", "data/scan_history.db"),
)

FILES: tuple[tuple[Path, str], ...] = (
    (Path(OUTPUT_DIR) / "paper_trading_state.json", "output/paper_trading_state.json"),
    (_PROJECT_ROOT / "stock_analyzer" / "watchlist.txt", "stock_analyzer/watchlist.txt"),
)

#: 행 수를 세어 복원 검증에 쓰는 테이블. 없으면 건너뛴다.
_ROW_COUNT_TABLES = ("scan_log", "signal_outcomes", "app_state", "paper_orders")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_counts(db_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return counts
    try:
        for table in _ROW_COUNT_TABLES:
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                continue
    finally:
        conn.close()
    return counts


def _copy_database(source: Path, target: Path) -> dict[str, Any]:
    """온라인 백업 API 로 일관된 사본을 만들고 **검증한다**."""
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    verify = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        integrity = verify.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        verify.close()
    if integrity != "ok":
        raise RuntimeError(f"{source.name}: 백업본 integrity_check 실패 ({integrity})")

    source_counts = _table_counts(source)
    target_counts = _table_counts(target)
    return {
        "integrity": integrity,
        "bytes": target.stat().st_size,
        "sha256": _sha256(target),
        "rows": target_counts,
        # 원본이 계속 쓰이므로 행 수가 늘 수는 있다. 줄었다면 그건 문제다.
        "rows_source_at_copy": source_counts,
    }


def create_backup(
    dest_dir: str | os.PathLike[str],
    *,
    include_env: bool = False,
    keep: int = 7,
) -> dict[str, Any]:
    """상태 스냅샷을 `dest_dir` 에 tar.gz 로 만든다.

    Args:
        dest_dir: 아카이브를 둘 디렉토리
        include_env: `.env` 포함 여부. **기본 False** — 백업이 자격증명 사본이 된다
        keep: 최근 N개만 남긴다 (0 이면 정리하지 않음)
    """
    started = datetime.now()
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d_%H%M%S")
    archive = dest / f"stock_auto_state_{stamp}.tar.gz"

    manifest: dict[str, Any] = {
        "created_at": started.isoformat(),
        "databases": {},
        "files": {},
        "missing": [],
        "include_env": include_env,
        "archive": archive.name,
    }

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "state"
        staging.mkdir()

        for source, rel in DATABASES:
            if not source.exists():
                manifest["missing"].append(rel)
                logger.warning("백업 대상 없음: %s", rel)
                continue
            manifest["databases"][rel] = _copy_database(source, staging / rel)

        for source, rel in FILES:
            if not source.exists():
                manifest["missing"].append(rel)
                logger.warning("백업 대상 없음: %s", rel)
                continue
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            manifest["files"][rel] = {
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }

        if include_env:
            env_path = _PROJECT_ROOT / ".env"
            if env_path.exists():
                target = staging / ".env"
                shutil.copy2(env_path, target)
                # 내용은 절대 로그·매니페스트에 남기지 않는다. 존재와 크기만.
                manifest["files"][".env"] = {
                    "bytes": target.stat().st_size,
                    "sha256": _sha256(target),
                    "warning": "자격증명 포함 — 이 아카이브를 저장소에 올리지 말 것",
                }
            else:
                manifest["missing"].append(".env")

        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        with tarfile.open(archive, "w:gz") as tar:
            tar.add(staging, arcname="state")

    result = {
        "status": "completed",
        "archive": str(archive),
        "bytes": archive.stat().st_size,
        "sha256": _sha256(archive),
        "databases": len(manifest["databases"]),
        "files": len(manifest["files"]),
        "missing": manifest["missing"],
        "include_env": include_env,
        "elapsed_sec": round((datetime.now() - started).total_seconds(), 2),
        "pruned": _prune(dest, keep),
    }
    logger.info(
        "상태 백업 완료: %s (%.1f MB, DB %d개, 파일 %d개)",
        archive.name, result["bytes"] / 1024 / 1024,
        result["databases"], result["files"],
    )
    return result


def _prune(dest: Path, keep: int) -> list[str]:
    if keep <= 0:
        return []
    archives = sorted(dest.glob("stock_auto_state_*.tar.gz"), reverse=True)
    removed = []
    for stale in archives[keep:]:
        try:
            stale.unlink()
            removed.append(stale.name)
        except OSError as exc:
            logger.warning("옛 백업 삭제 실패 (%s): %s", stale.name, exc)
    return removed


def verify_backup(archive_path: str | os.PathLike[str]) -> dict[str, Any]:
    """아카이브가 **복원 가능한지** 확인한다.

    '파일이 있다'는 백업이 아니다. 풀어서 체크섬을 맞추고 DB 를 열어
    `integrity_check` 까지 돌린다.
    """
    archive = Path(archive_path)
    if not archive.exists():
        return {"status": "missing", "archive": str(archive)}

    problems: list[str] = []
    checked = {"databases": 0, "files": 0}
    manifest: dict[str, Any] = {}

    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(tmp, filter="data")
        root = Path(tmp) / "state"
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            return {"status": "invalid", "detail": "manifest.json 없음"}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        for rel, meta in manifest.get("databases", {}).items():
            path = root / rel
            if not path.exists():
                problems.append(f"{rel}: 아카이브에 없음")
                continue
            if _sha256(path) != meta["sha256"]:
                problems.append(f"{rel}: 체크섬 불일치")
                continue
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                conn.close()
            if integrity != "ok":
                problems.append(f"{rel}: integrity_check {integrity}")
                continue
            checked["databases"] += 1

        for rel, meta in manifest.get("files", {}).items():
            path = root / rel
            if not path.exists():
                problems.append(f"{rel}: 아카이브에 없음")
            elif _sha256(path) != meta["sha256"]:
                problems.append(f"{rel}: 체크섬 불일치")
            else:
                checked["files"] += 1

    return {
        "status": "ok" if not problems else "corrupt",
        "archive": str(archive),
        "created_at": manifest.get("created_at"),
        "checked": checked,
        "problems": problems,
        "row_counts": {
            rel: meta.get("rows", {})
            for rel, meta in manifest.get("databases", {}).items()
        },
    }


def latest_backup(dest_dir: str | os.PathLike[str]) -> Path | None:
    archives = sorted(Path(dest_dir).glob("stock_auto_state_*.tar.gz"), reverse=True)
    return archives[0] if archives else None
