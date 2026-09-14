"""백업을 이 노드 밖으로 복제한다.

`docs/RUNBOOK_BACKUP.md` §3 이 남긴 한계: 백업이 **같은 디스크**에 있다. 디스크가
죽으면 백업도 같이 죽는다 — 그건 SPOF 대비가 아니다. 여기서 그 마지막 구간을 잇는다.

## 목적지는 코드가 정하지 않는다

어디에 금융 데이터 사본을 둘지는 운영자의 결정이다. `OFFSITE_BACKUP_DEST` 가 비어
있으면 **아무 데도 보내지 않고** `disabled` 로 보고한다 — '설정 안 됨'을 '성공'으로
덮지 않는다 (CLAUDE.md §13-4).

목적지는 두 형태를 받는다:
  `/mnt/backup/stock_auto`          로컬·마운트 경로 (외장 디스크, NFS, 다른 볼륨)
  `user@host:/path/stock_auto`      rsync over SSH

**로컬 경로는 순수 Python 으로 복사한다** — 컨테이너에 rsync 를 넣지 않기 위해서다.
원격(SSH) 목적지는 `rsync`/`ssh` 가 있는 곳에서 실행해야 한다. agent-api 컨테이너에는
둘 다 없고, **넣지 않는 게 맞다**: 네트워크에 노출된 서비스 컨테이너에 개인키를
마운트하는 것은 백업으로 얻는 것보다 잃는 게 크다. 원격 복제는 호스트에서
`scripts/offsite_sync.sh` (cron/systemd)로 돌린다 — `docs/RUNBOOK_BACKUP.md` §3.

## 복사했다 ≠ 도착했다

`rsync` 종료코드 0 은 전송이 끝났다는 뜻이지 **반대편 파일이 온전하다는 뜻이 아니다.**
그래서 복제 후 최신 아카이브의 sha256 을 목적지에서 다시 계산해 원본과 대조한다.
이 검증이 실패하면 `degraded` 다 — 오프사이트 사본이 있다고 믿는 상태가 없는 것보다
나쁠 수 있다 (§13.9g 에서 cp 백업에 대해 적은 것과 같은 이유다).
"""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from logging_setup import get_logger

logger = get_logger("stock_auto.offsite_backup")

#: 원격 목적지 판별 — `user@host:/path` 형태인가.
def _is_remote(dest: str) -> bool:
    head = dest.split("/", 1)[0]
    return ":" in head


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _sync_local(source: Path, dest: Path) -> dict[str, int]:
    """로컬·마운트 경로 미러링. 컨테이너에 rsync 가 없어도 동작한다.

    `--delete` 와 같은 의미로 목적지의 잉여 아카이브를 지운다 — 원본에서 정리된
    옛 백업이 목적지에만 영원히 남으면 보존 정책이 두 갈래가 된다.
    """
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    wanted = set()
    for src_file in sorted(source.glob("stock_auto_state_*.tar.gz")):
        wanted.add(src_file.name)
        target = dest / src_file.name
        if target.exists() and target.stat().st_size == src_file.stat().st_size:
            continue                      # 아카이브는 불변이다 — 크기가 같으면 같은 것
        shutil.copy2(src_file, target)
        copied += 1

    removed = 0
    for stale in dest.glob("stock_auto_state_*.tar.gz"):
        if stale.name not in wanted:
            stale.unlink()
            removed += 1
    return {"copied": copied, "removed": removed}


def _remote_digest(dest: str, filename: str, ssh_opts: list[str], timeout: int) -> str | None:
    """목적지에서 sha256 을 계산한다. 못 하면 None (모른다는 뜻)."""
    target, _, remote_path = dest.partition(":")
    quoted = shlex.quote(os.path.join(remote_path, filename))
    # sha256sum(GNU) 과 shasum(macOS) 둘 다 대응한다
    command = f"sha256sum {quoted} 2>/dev/null || shasum -a 256 {quoted}"
    result = _run(["ssh", *ssh_opts, target, command], timeout)
    if result.returncode != 0:
        logger.warning("원격 체크섬 계산 실패: %s", result.stderr.strip()[:200])
        return None
    parts = result.stdout.split()
    return parts[0] if parts else None


def _local_digest(dest: str, filename: str) -> str | None:
    path = Path(dest) / filename
    return _sha256(path) if path.exists() else None


def replicate(
    source_dir: str | os.PathLike[str],
    dest: str,
    *,
    timeout_sec: int = 900,
    ssh_opts: list[str] | None = None,
) -> dict[str, Any]:
    """백업 디렉토리를 목적지로 복제하고 **도착 여부를 검증한다**."""
    started = datetime.now()
    source = Path(source_dir)

    if not dest:
        # 설정하지 않은 것을 성공이라 부르지 않는다.
        return {
            "status": "disabled",
            "detail": "OFFSITE_BACKUP_DEST 미설정 — 백업이 이 노드에만 있다",
        }
    if not source.exists():
        return {"status": "error", "detail": f"백업 디렉토리 없음: {source}"}

    archives = sorted(source.glob("stock_auto_state_*.tar.gz"), reverse=True)
    if not archives:
        return {"status": "error", "detail": f"복제할 아카이브 없음: {source}"}
    latest = archives[0]

    remote = _is_remote(dest)
    opts = ssh_opts or ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    transfer: dict[str, Any] = {}

    if remote:
        cmd = ["rsync", "-a", "--delete", "-e", " ".join(["ssh", *opts]),
               f"{source}/", dest if dest.endswith("/") else f"{dest}/"]
        try:
            result = _run(cmd, timeout_sec)
        except subprocess.TimeoutExpired:
            logger.error("오프사이트 복제 타임아웃 (%ds): %s", timeout_sec, dest)
            return {"status": "error", "detail": f"rsync 타임아웃 ({timeout_sec}s)",
                    "dest": dest}
        except FileNotFoundError:
            # 컨테이너에는 rsync·ssh 를 두지 않는다 (개인키를 넣지 않기 위해).
            return {
                "status": "error",
                "dest": dest,
                "detail": "rsync 미설치 — 원격 복제는 호스트에서 "
                          "scripts/offsite_sync.sh 로 실행할 것 (RUNBOOK_BACKUP.md §3)",
            }
        if result.returncode != 0:
            logger.error("오프사이트 복제 실패 (rc=%d): %s", result.returncode,
                         result.stderr.strip()[:300])
            return {
                "status": "error",
                "dest": dest,
                "returncode": result.returncode,
                "detail": result.stderr.strip()[:300],
            }
    else:
        try:
            transfer = _sync_local(source, Path(dest))
        except OSError as exc:
            logger.error("오프사이트 복제 실패 (%s): %s", dest, exc)
            return {"status": "error", "dest": dest,
                    "detail": f"{type(exc).__name__}: {exc}"[:300]}

    # rsync 성공 = 전송 완료. 반대편 파일이 온전한지는 별개다.
    local_digest = _sha256(latest)
    remote_digest = (
        _remote_digest(dest, latest.name, opts, timeout=120)
        if remote
        else _local_digest(dest, latest.name)
    )

    if remote_digest is None:
        status, detail = "degraded", "목적지 체크섬을 확인하지 못했다 — 도착 여부 미검증"
    elif remote_digest != local_digest:
        status, detail = "degraded", "목적지 체크섬 불일치 — 사본이 온전하지 않다"
    else:
        status, detail = "completed", None

    payload = {
        "status": status,
        "dest": dest,
        "remote": remote,
        "verified_archive": latest.name,
        "archives": len(archives),
        "checksum_match": remote_digest == local_digest if remote_digest else None,
        "elapsed_sec": round((datetime.now() - started).total_seconds(), 2),
        **transfer,
    }
    if detail:
        payload["detail"] = detail
        logger.warning("오프사이트 복제 %s: %s", status, detail)
    else:
        logger.info("오프사이트 복제 완료: %s (%d개, %.1fs)",
                    dest, len(archives), payload["elapsed_sec"])
    return payload
