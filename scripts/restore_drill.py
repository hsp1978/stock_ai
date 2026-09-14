"""복구 리허설 — 운영 파일을 건드리지 않고 복원을 실제로 해 본다.

**테스트되지 않은 복구 절차는 백업이 아니다.** 아카이브가 만들어졌다는 것과 그것으로
시스템을 되살릴 수 있다는 것은 다른 얘기다. 이 스크립트는 최신 아카이브를 임시 경로에
풀어서 확인한다:

  1. 체크섬 + `PRAGMA integrity_check` (verify_backup)
  2. manifest 의 행 수 ↔ 복원된 DB 의 실제 행 수
  3. 파일 크기 일치
  4. 운영 DB 와의 행 수 차이 (백업 시점 이후 늘어난 만큼만 나야 한다)

운영 데이터는 읽기만 한다. 실제 복구 절차는 `docs/RUNBOOK_BACKUP.md` §4.

사용:
    docker exec stock-auto-agent-api python /app/scripts/restore_drill.py
    python3 scripts/restore_drill.py            # 호스트에서 (경로는 .env 기준)
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "chart_agent_service"), "/app/chart_agent_service"):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from state_backup import latest_backup, verify_backup  # noqa: E402


def main() -> int:
    backup_dir = os.environ.get("STATE_BACKUP_DIR", "/home/ubuntu/stock_auto_backups")
    archive = latest_backup(backup_dir)
    if archive is None:
        print(f"백업 없음: {backup_dir}")
        return 1
    print(f"대상 아카이브: {os.path.basename(str(archive))}")

    verification = verify_backup(archive)
    print(f"사전 검증: {verification['status']} | 문제: {verification['problems']}")
    if verification["status"] != "ok":
        print("검증 실패 — 이 아카이브로는 복구하지 않는다")
        return 1

    restore_root = tempfile.mkdtemp(prefix="restore_drill_")
    ok = True
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(restore_root, filter="data")
        state = os.path.join(restore_root, "state")
        manifest = json.load(open(os.path.join(state, "manifest.json"), encoding="utf-8"))

        print("\n복원본 대조 (manifest ↔ 실제 복원 파일):")
        for rel, meta in manifest["databases"].items():
            path = os.path.join(state, rel)
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                actual = {
                    table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in meta.get("rows", {})
                }
            finally:
                conn.close()
            match = actual == meta.get("rows", {})
            ok &= integrity == "ok" and match
            print(f"  {rel:34s} integrity={integrity:4s} rows={actual} 일치={match}")

        for rel, meta in manifest["files"].items():
            size = os.path.getsize(os.path.join(state, rel))
            print(f"  {rel:34s} {size}B 일치={size == meta['bytes']}")
            ok &= size == meta["bytes"]

        live_path = os.path.join(_ROOT, "chart_agent_service", "output", "scan_log.db")
        if not os.path.exists(live_path):
            live_path = "/app/chart_agent_service/output/scan_log.db"
        if os.path.exists(live_path):
            conn = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True)
            try:
                live_rows = conn.execute("SELECT COUNT(*) FROM scan_log").fetchone()[0]
            finally:
                conn.close()
            restored = manifest["databases"]["output/scan_log.db"]["rows"]["scan_log"]
            # 백업 이후 스캔이 돌면 운영 쪽이 더 많다. 반대면 문제다.
            print(f"\n운영 scan_log {live_rows:,}행 ↔ 복원본 {restored:,}행 "
                  f"(차이 {live_rows - restored})")
            if restored > live_rows:
                print("  ⚠ 복원본이 운영보다 많다 — 운영 DB 가 손실됐을 수 있다")
    finally:
        shutil.rmtree(restore_root, ignore_errors=True)

    print("\n리허설 결과:", "성공" if ok else "실패")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
