"""오프사이트 복제 — 백업이 이 노드 밖에도 있어야 한다.

`docs/RUNBOOK_BACKUP.md` §3 이 남긴 한계: 백업(#66)이 **같은 디스크**에 있다. 디스크가
죽으면 백업도 같이 죽는다 — SPOF 대비가 아니다.

여기서 고정하는 것:
  1. 목적지 미설정은 **`disabled`** 다 — '설정 안 됨'을 성공으로 덮지 않는다
  2. `rsync` 종료코드 0 은 '전송 끝'이지 '반대편이 온전함'이 아니다 →
     목적지에서 sha256 을 다시 계산해 대조한다
  3. 대조 실패·확인 불가는 `degraded` — 오프사이트 사본이 있다고 믿는 상태가
     없는 것보다 나쁠 수 있다
  4. 로컬 경로와 `user@host:/path` 를 모두 받는다
  5. 검증을 통과한 백업만 내보낸다 (깨진 사본을 복제하지 않는다)
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import offsite_backup as ob  # noqa: E402


@pytest.fixture
def backup_dir(tmp_path):
    source = tmp_path / "backups"
    source.mkdir()
    (source / "stock_auto_state_20260913_040000.tar.gz").write_bytes(b"older")
    (source / "stock_auto_state_20260914_040000.tar.gz").write_bytes(b"newest")
    return source


# ── 목적지 미설정 ─────────────────────────────────────────────────


def test_missing_destination_is_disabled_not_success(backup_dir):
    """설정하지 않은 것을 '완료'라고 부르면 SPOF 가 해결된 줄 안다."""
    result = ob.replicate(backup_dir, "")

    assert result["status"] == "disabled"
    assert "이 노드에만" in result["detail"]


def test_missing_source_is_an_error(tmp_path):
    result = ob.replicate(tmp_path / "nope", "/mnt/backup")

    assert result["status"] == "error"


def test_empty_source_is_an_error(tmp_path):
    (tmp_path / "backups").mkdir()
    result = ob.replicate(tmp_path / "backups", "/mnt/backup")

    assert result["status"] == "error" and "아카이브 없음" in result["detail"]


# ── 로컬 경로 복제 ────────────────────────────────────────────────


def test_local_destination_replicates_and_verifies(backup_dir, tmp_path):
    dest = tmp_path / "offsite"

    result = ob.replicate(backup_dir, str(dest))

    assert result["status"] == "completed"
    assert result["checksum_match"] is True
    assert result["verified_archive"] == "stock_auto_state_20260914_040000.tar.gz"
    assert (dest / "stock_auto_state_20260914_040000.tar.gz").read_bytes() == b"newest"
    assert (dest / "stock_auto_state_20260913_040000.tar.gz").exists()


def test_deleted_archives_are_removed_at_the_destination(backup_dir, tmp_path):
    """원본에서 정리된 옛 백업이 목적지에 영원히 쌓이면 안 된다."""
    dest = tmp_path / "offsite"
    ob.replicate(backup_dir, str(dest))

    (backup_dir / "stock_auto_state_20260913_040000.tar.gz").unlink()
    ob.replicate(backup_dir, str(dest))

    assert not (dest / "stock_auto_state_20260913_040000.tar.gz").exists()


def test_corrupted_destination_copy_is_degraded(backup_dir, tmp_path, monkeypatch):
    """전송이 성공을 돌려줘도 반대편이 깨졌을 수 있다 — 그래서 대조한다."""
    dest = tmp_path / "offsite"
    dest.mkdir()

    def broken_transfer(source, target):
        (target / "stock_auto_state_20260914_040000.tar.gz").write_bytes(b"truncated")
        return {"copied": 1, "removed": 0}

    monkeypatch.setattr(ob, "_sync_local", broken_transfer)
    result = ob.replicate(backup_dir, str(dest))

    assert result["status"] == "degraded"
    assert result["checksum_match"] is False
    assert "온전하지 않다" in result["detail"]


def test_absent_destination_copy_is_degraded(backup_dir, tmp_path, monkeypatch):
    """전송했다는데 목적지에 파일이 없으면 '모름'이 아니라 문제다."""
    monkeypatch.setattr(ob, "_sync_local", lambda source, target: {"copied": 0, "removed": 0})

    result = ob.replicate(backup_dir, str(tmp_path / "empty_dest"))

    assert result["status"] == "degraded"
    assert result["checksum_match"] is None


def test_local_sync_skips_unchanged_archives(backup_dir, tmp_path):
    """아카이브는 불변이다 — 매번 12MB 를 다시 복사할 이유가 없다."""
    dest = tmp_path / "offsite"

    first = ob.replicate(backup_dir, str(dest))
    second = ob.replicate(backup_dir, str(dest))

    assert first["copied"] == 2
    assert second["copied"] == 0 and second["status"] == "completed"


# ── 원격(SSH) ─────────────────────────────────────────────────────


@pytest.mark.parametrize("dest,expected", [
    ("user@host:/srv/backups", True),
    ("macstudio:~/stock_auto_backups", True),
    ("/mnt/backup/stock_auto", False),
    ("/srv/a:b/backups", False),          # 경로 안의 콜론은 원격이 아니다
])
def test_remote_destination_detection(dest, expected):
    assert ob._is_remote(dest) is expected


def test_remote_uses_ssh_and_checks_remote_digest(backup_dir, monkeypatch):
    calls = []
    digest = ob._sha256(backup_dir / "stock_auto_state_20260914_040000.tar.gz")

    def fake_run(cmd, timeout):
        calls.append(cmd)
        if cmd[0] == "ssh":
            return subprocess.CompletedProcess(cmd, 0, f"{digest}  /remote/path\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ob, "_run", fake_run)
    result = ob.replicate(backup_dir, "hsptest@macstudio:~/stock_auto_backups")

    assert result["status"] == "completed" and result["remote"] is True
    rsync_cmd = calls[0]
    assert "-e" in rsync_cmd and "ssh" in rsync_cmd[rsync_cmd.index("-e") + 1]
    assert "BatchMode=yes" in rsync_cmd[rsync_cmd.index("-e") + 1]
    # 원격 체크섬은 sha256sum 과 shasum 을 모두 시도해야 한다 (리눅스/macOS)
    ssh_cmd = calls[1]
    assert "sha256sum" in ssh_cmd[-1] and "shasum -a 256" in ssh_cmd[-1]


def test_remote_digest_failure_is_degraded_not_completed(backup_dir, monkeypatch):
    def fake_run(cmd, timeout):
        if cmd[0] == "ssh":
            return subprocess.CompletedProcess(cmd, 255, "", "Permission denied")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ob, "_run", fake_run)
    result = ob.replicate(backup_dir, "user@host:/srv/backups")

    assert result["status"] == "degraded"
    assert "미검증" in result["detail"]


def test_rsync_failure_keeps_the_reason(backup_dir, monkeypatch):
    monkeypatch.setattr(ob, "_run", lambda cmd, timeout: subprocess.CompletedProcess(
        cmd, 12, "", "rsync: connection unexpectedly closed"))

    result = ob.replicate(backup_dir, "user@host:/srv/backups")

    assert result["status"] == "error" and result["returncode"] == 12
    assert "connection unexpectedly closed" in result["detail"]


def test_timeout_is_reported(backup_dir, monkeypatch):
    def boom(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(ob, "_run", boom)
    result = ob.replicate(backup_dir, "user@host:/srv/backups", timeout_sec=30)

    assert result["status"] == "error" and "타임아웃" in result["detail"]


def test_missing_rsync_points_to_the_host_side_path(backup_dir, monkeypatch):
    """컨테이너에는 rsync·ssh 를 두지 않는다 — 개인키를 넣지 않기 위해서다.

    원격 목적지가 설정됐는데 실행 환경에 rsync 가 없으면, 그 사실과 **어디서
    돌려야 하는지**를 함께 알린다.
    """
    def boom(cmd, timeout):
        raise FileNotFoundError("rsync")

    monkeypatch.setattr(ob, "_run", boom)
    result = ob.replicate(backup_dir, "user@host:/srv/backups")

    assert result["status"] == "error"
    assert "offsite_sync.sh" in result["detail"]


def test_local_destination_does_not_need_rsync(backup_dir, tmp_path, monkeypatch):
    """로컬·마운트 경로는 순수 Python 으로 복사한다."""
    monkeypatch.setattr(ob, "_run",
                        lambda cmd, timeout: pytest.fail("로컬인데 외부 명령을 호출했다"))

    result = ob.replicate(backup_dir, str(tmp_path / "offsite"))

    assert result["status"] == "completed"


# ── 백업 잡과의 연결 ──────────────────────────────────────────────


def _job_env(monkeypatch, verification_status="ok", missing=None):
    import service

    monkeypatch.setattr(service, "_record_job_start", lambda *a, **k: "t0")
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: None)
    monkeypatch.setattr("state_backup.create_backup",
                        lambda *a, **k: {"status": "completed", "archive": "/x.tar.gz",
                                         "missing": missing or []})
    monkeypatch.setattr("state_backup.verify_backup",
                        lambda p: {"status": verification_status, "problems": []})
    return service


def test_corrupt_backup_is_not_replicated(monkeypatch):
    """깨진 사본을 내보내면 오프사이트에도 깨진 것이 쌓인다."""
    service = _job_env(monkeypatch, verification_status="corrupt")
    monkeypatch.setattr(service, "_send_ops_alert", lambda *a, **k: None)
    monkeypatch.setattr("offsite_backup.replicate",
                        lambda *a, **k: pytest.fail("검증 실패인데 복제를 시도했다"))

    assert service.run_state_backup()["status"] == "error"


def test_offsite_failure_degrades_the_backup_job(monkeypatch):
    """백업은 됐다. 다만 이 노드 밖에는 없다 — 다른 사실이다."""
    service = _job_env(monkeypatch)
    sent = []
    monkeypatch.setattr(service, "_send_ops_alert",
                        lambda title, detail, **k: sent.append((title, detail)))
    monkeypatch.setattr("offsite_backup.replicate",
                        lambda *a, **k: {"status": "error", "dest": "user@host:/b",
                                         "detail": "connection refused"})

    result = service.run_state_backup()

    assert result["status"] == "degraded"
    assert result["offsite"]["status"] == "error"
    assert any("Offsite" in title for title, _ in sent)


def test_disabled_offsite_does_not_degrade_the_job(monkeypatch):
    """목적지를 안 정한 것은 장애가 아니다 — 다만 /ops/backups 에 드러난다."""
    service = _job_env(monkeypatch)
    monkeypatch.setattr(service, "_send_ops_alert",
                        lambda *a, **k: pytest.fail("미설정으로 알림이 나갔다"))
    monkeypatch.setattr("offsite_backup.replicate",
                        lambda *a, **k: {"status": "disabled", "detail": "미설정"})

    result = service.run_state_backup()

    assert result["status"] == "completed"
    assert result["offsite"]["status"] == "disabled"
