"""상태 백업 — '만들었다'가 아니라 '복원 가능하다'를 확인한다.

`docs/SYSTEM_OVERVIEW.md` §13.9-10: testdev 한 대가 죽으면 전부 정지하고
**백업·복구 절차가 없었다.** 잃게 되는 것은 재생성 불가능한 것들이다 —
scan_log.db(70,840행 + signal_outcomes 5,442건 + app_state), 페이퍼 포지션,
워치리스트, 거래 안전장치 DB.

가장 위험한 함정은 **cp 로 백업하는 것**이다. DB 는 WAL 모드라 실행 중에 복사하면
`.db` 와 `-wal` 이 서로 다른 시점의 것이 되어 복원 시 깨진다. 그런데 파일 크기도
개수도 멀쩡해 보인다 — 복구를 시도하는 순간에야 안다.

여기서 고정하는 것:
  1. sqlite 온라인 백업 API 사용 (쓰기 중에도 일관된 스냅샷)
  2. 만든 다음 **검증한다** — 체크섬 + `PRAGMA integrity_check`
  3. 재생성 가능한 것(분석 JSON·차트)은 담지 않는다
  4. `.env` 는 기본 미포함 — 백업이 자격증명 사본이 되면 안 된다
  5. 없는 대상은 조용히 넘기지 않고 `missing` 에 남긴다
"""

import json
import os
import sqlite3
import sys
import tarfile

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import state_backup as sb  # noqa: E402


def _make_db(path, rows: int = 5, table: str = "scan_log"):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, ticker TEXT)")
    conn.executemany(
        f"INSERT INTO {table} (ticker) VALUES (?)", [(f"T{i}",) for i in range(rows)]
    )
    conn.commit()
    return conn            # 열린 채로 둘 수 있다 — 실행 중 백업을 흉내낸다


@pytest.fixture
def env(tmp_path, monkeypatch):
    out = tmp_path / "output"
    data = tmp_path / "data"
    wl = tmp_path / "stock_analyzer" / "watchlist.txt"
    wl.parent.mkdir(parents=True)
    wl.write_text("PLTR\nMSFT\n", encoding="utf-8")
    (out).mkdir(parents=True)
    (out / "paper_trading_state.json").write_text('{"cash": 100}', encoding="utf-8")

    conn = _make_db(out / "scan_log.db", rows=7)
    _make_db(data / "scan_history.db", rows=2, table="scan_log").close()

    monkeypatch.setattr(sb, "DATABASES", (
        (out / "scan_log.db", "output/scan_log.db"),
        (data / "scan_history.db", "data/scan_history.db"),
        (out / "absent.db", "output/absent.db"),        # 없는 대상
    ))
    monkeypatch.setattr(sb, "FILES", (
        (out / "paper_trading_state.json", "output/paper_trading_state.json"),
        (wl, "stock_analyzer/watchlist.txt"),
    ))
    monkeypatch.setattr(sb, "_PROJECT_ROOT", tmp_path)
    yield tmp_path
    conn.close()


# ── 생성 ──────────────────────────────────────────────────────────


def test_backup_contains_the_irreplaceable_state(env, tmp_path):
    result = sb.create_backup(tmp_path / "backups")

    assert result["status"] == "completed"
    assert result["databases"] == 2 and result["files"] == 2

    with tarfile.open(result["archive"], "r:gz") as tar:
        names = set(tar.getnames())
    assert "state/output/scan_log.db" in names
    assert "state/stock_analyzer/watchlist.txt" in names
    assert "state/manifest.json" in names


def test_missing_targets_are_listed_not_silently_skipped(env, tmp_path):
    """빠진 게 안 보이면 '백업 있음'이 거짓이 된다."""
    result = sb.create_backup(tmp_path / "backups")

    assert result["missing"] == ["output/absent.db"]


def test_open_wal_database_is_copied_consistently(env, tmp_path):
    """실행 중(WAL)인 DB 를 cp 하면 복원 시 깨진다 — 온라인 백업 API 를 쓴다."""
    result = sb.create_backup(tmp_path / "backups")
    verification = sb.verify_backup(result["archive"])

    assert verification["status"] == "ok"
    assert verification["row_counts"]["output/scan_log.db"]["scan_log"] == 7


def test_manifest_records_row_counts_for_restore_checking(env, tmp_path):
    result = sb.create_backup(tmp_path / "backups")

    with tarfile.open(result["archive"], "r:gz") as tar:
        manifest = json.loads(
            tar.extractfile("state/manifest.json").read().decode("utf-8")
        )

    rows = manifest["databases"]["output/scan_log.db"]["rows"]
    assert rows["scan_log"] == 7
    assert manifest["databases"]["output/scan_log.db"]["integrity"] == "ok"


# ── .env ──────────────────────────────────────────────────────────


def test_env_is_excluded_by_default(env, tmp_path):
    (tmp_path / ".env").write_text("DART_API_KEY=super-secret-value", encoding="utf-8")

    result = sb.create_backup(tmp_path / "backups")

    with tarfile.open(result["archive"], "r:gz") as tar:
        assert "state/.env" not in tar.getnames()
    assert result["include_env"] is False


def test_env_can_be_included_explicitly_and_is_flagged(env, tmp_path):
    (tmp_path / ".env").write_text("DART_API_KEY=super-secret-value", encoding="utf-8")

    result = sb.create_backup(tmp_path / "backups", include_env=True)

    with tarfile.open(result["archive"], "r:gz") as tar:
        names = tar.getnames()
        manifest = json.loads(
            tar.extractfile("state/manifest.json").read().decode("utf-8")
        )
    assert "state/.env" in names
    assert "저장소에 올리지 말 것" in manifest["files"][".env"]["warning"]
    # 매니페스트에 키 값이 새면 안 된다
    assert "super-secret-value" not in json.dumps(manifest)


# ── 검증 ──────────────────────────────────────────────────────────


def test_verify_detects_a_corrupted_archive(env, tmp_path):
    """깨진 아카이브는 풀리지 않는다 — 그 실패가 드러나야 한다.

    처음에는 가운데 한 바이트를 뒤집었는데, deflate 스트림에서 그 바이트가 어디에
    떨어지느냐에 따라 예외가 안 날 때가 있었다 (단독 실행은 통과, 전체 실행에서
    실패). **잘라내기**는 결정적이고, 실제로도 흔한 손상 형태다 — 복사가 중간에
    끊긴 경우.
    """
    result = sb.create_backup(tmp_path / "backups")
    archive = tmp_path / "backups" / os.path.basename(result["archive"])

    raw = archive.read_bytes()
    archive.write_bytes(raw[: int(len(raw) * 0.6)])   # 60% 에서 잘림

    with pytest.raises(Exception):
        sb.verify_backup(archive)


def test_verify_detects_a_tampered_database(env, tmp_path):
    result = sb.create_backup(tmp_path / "backups")

    # 아카이브를 풀어 DB 를 바꿔치기한 뒤 다시 묶는다
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(result["archive"], "r:gz") as tar:
            tar.extractall(tmp, filter="data")
        (pathlib_path := os.path.join(tmp, "state", "output", "scan_log.db"))
        with open(pathlib_path, "wb") as fh:
            fh.write(b"not a database")
        os.remove(result["archive"])
        with tarfile.open(result["archive"], "w:gz") as tar:
            tar.add(os.path.join(tmp, "state"), arcname="state")
        shutil.rmtree(tmp, ignore_errors=True)

    verification = sb.verify_backup(result["archive"])

    assert verification["status"] == "corrupt"
    assert any("scan_log.db" in p for p in verification["problems"])


def test_verify_reports_missing_archive():
    assert sb.verify_backup("/nonexistent/backup.tar.gz")["status"] == "missing"


# ── 보존 ──────────────────────────────────────────────────────────


def test_old_backups_are_pruned(env, tmp_path):
    dest = tmp_path / "backups"
    for i in range(5):
        (dest).mkdir(exist_ok=True)
        (dest / f"stock_auto_state_2026090{i}_000000.tar.gz").write_bytes(b"x")

    result = sb.create_backup(dest, keep=3)

    remaining = sorted(p.name for p in dest.glob("stock_auto_state_*.tar.gz"))
    assert len(remaining) == 3
    assert os.path.basename(result["archive"]) in remaining   # 방금 것은 남는다


def test_keep_zero_disables_pruning(env, tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    (dest / "stock_auto_state_20260901_000000.tar.gz").write_bytes(b"x")

    sb.create_backup(dest, keep=0)

    assert len(list(dest.glob("stock_auto_state_*.tar.gz"))) == 2


def test_latest_backup_picks_the_newest(env, tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    for name in ("stock_auto_state_20260901_000000.tar.gz",
                 "stock_auto_state_20260914_120000.tar.gz"):
        (dest / name).write_bytes(b"x")

    assert sb.latest_backup(dest).name == "stock_auto_state_20260914_120000.tar.gz"


# ── 스케줄 잡 ─────────────────────────────────────────────────────


def test_job_is_registered_and_scheduled():
    import service

    assert "state_backup" in service._KNOWN_OPS_JOBS
    src = open(os.path.join(_AGENT_DIR, "service.py"), encoding="utf-8").read()
    assert "id='state_backup'" in src, "스케줄러에 등록되지 않았다"


def test_job_fails_loudly_when_verification_fails(monkeypatch):
    import service

    monkeypatch.setattr(service, "_record_job_start", lambda *a, **k: "t0")
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: None)
    sent = []
    monkeypatch.setattr(service, "_send_ops_alert",
                        lambda title, detail, **k: sent.append((title, detail)))
    monkeypatch.setattr("state_backup.create_backup",
                        lambda *a, **k: {"status": "completed", "archive": "/x.tar.gz",
                                         "missing": []})
    monkeypatch.setattr("state_backup.verify_backup",
                        lambda p: {"status": "corrupt", "problems": ["scan_log.db: 체크섬 불일치"]})

    result = service.run_state_backup()

    assert result["status"] == "error"          # 검증 실패는 성공이 아니다
    assert sent and "체크섬 불일치" in sent[0][1]


def test_job_degrades_when_targets_are_missing(monkeypatch):
    import service

    monkeypatch.setattr(service, "_record_job_start", lambda *a, **k: "t0")
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: None)
    sent = []
    monkeypatch.setattr(service, "_send_ops_alert",
                        lambda title, detail, **k: sent.append(detail))
    monkeypatch.setattr("state_backup.create_backup",
                        lambda *a, **k: {"status": "completed", "archive": "/x.tar.gz",
                                         "missing": ["output/order_audit.db"]})
    monkeypatch.setattr("state_backup.verify_backup", lambda p: {"status": "ok", "problems": []})

    result = service.run_state_backup()

    assert result["status"] == "degraded"
    assert sent and "order_audit.db" in sent[0]
