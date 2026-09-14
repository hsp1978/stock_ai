"""산출물 보존 정책 — output/ 무한 누적 차단.

`docs/SYSTEM_OVERVIEW.md` §13.9-5: 분석 JSON 이 정리 주체 없이 쌓이고 있었다.
2026-09-14 실측 **70,771개 / 1.58 GB**, 하루 361개(약 7.7 MB) 증가. `crontab -l`
은 비어 있었고 코드에도 삭제 경로가 없었다. CLAUDE.md Don't #7 은 "30일 이상 파일
자동 정리 cron 유지" 라고 적혀 있었지만 **그 cron 은 존재한 적이 없다.**

삭제는 되돌릴 수 없다. 여기서 고정하는 것:
  1. allowlist 패턴만 지운다 — DB·미확인 파일은 어떤 경우에도 안 지운다
  2. 하위 디렉토리·심볼릭 링크는 안 본다
  3. **화면이 참조 중인 차트는 나이와 무관하게 남긴다** (engine_get_chart_path)
  4. dry_run 은 '지울 예정'이라고 적는다 — 지웠다고 보고하지 않는다
  5. 실패는 세지 않고 사유와 함께 보고한다
"""

import os
import sys
import time
from datetime import datetime, timedelta

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import output_retention  # noqa: E402


def _touch(directory, name: str, days_old: float, size: int = 100) -> str:
    path = os.path.join(directory, name)
    with open(path, "wb") as fh:
        fh.write(b"x" * size)
    stamp = time.time() - days_old * 86400
    os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def outdir(tmp_path, monkeypatch):
    d = str(tmp_path)
    monkeypatch.setattr(output_retention, "OUTPUT_DIR", d)
    monkeypatch.setattr(output_retention, "OUTPUT_JSON_RETENTION_DAYS", 30)
    monkeypatch.setattr(output_retention, "OUTPUT_CHART_RETENTION_DAYS", 30)
    monkeypatch.setattr(output_retention, "_referenced_charts", lambda: set())
    return d


# ── 무엇을 지우는가 ───────────────────────────────────────────────


def test_old_analysis_json_is_removed(outdir):
    old = _touch(outdir, "AAPL_agent_20260401_0930.json", days_old=90)
    fresh = _touch(outdir, "AAPL_agent_20260913_0930.json", days_old=1)

    result = output_retention.cleanup_outputs()

    assert result["status"] == "completed"
    assert result["deleted"] == 1
    assert not os.path.exists(old)
    assert os.path.exists(fresh)


def test_boundary_day_is_kept(outdir):
    """경계에서 지우면 '30일 보존'이 29일 보존이 된다."""
    _touch(outdir, "A_agent_x.json", days_old=29.9)

    assert output_retention.cleanup_outputs()["deleted"] == 0


def test_databases_are_never_touched(outdir):
    """운영 DB 가 지워지면 복구할 수 없다."""
    for name in ("scan_log.db", "scan_log.db-wal", "scan_log.db-shm",
                 "order_audit.db", "state.sqlite3"):
        _touch(outdir, name, days_old=400)

    result = output_retention.cleanup_outputs()

    assert result["deleted"] == 0
    assert all(os.path.exists(os.path.join(outdir, n)) for n in os.listdir(outdir))


def test_unknown_files_are_left_alone(outdir):
    """allowlist 밖은 건드리지 않는다 — 무엇인지 모르면 지우지 않는다."""
    keep = _touch(outdir, "watchlist_backup.txt", days_old=400)
    _touch(outdir, "sector_tickers.json", days_old=400)   # *_agent_* 아님

    result = output_retention.cleanup_outputs()

    assert result["deleted"] == 0
    assert os.path.exists(keep)
    assert os.path.exists(os.path.join(outdir, "sector_tickers.json"))


def test_subdirectories_are_not_traversed(outdir):
    sub = os.path.join(outdir, "archive")
    os.makedirs(sub)
    nested = _touch(sub, "OLD_agent_x.json", days_old=400)

    output_retention.cleanup_outputs()

    assert os.path.exists(nested)


# ── 차트는 화면이 읽는다 ──────────────────────────────────────────


def test_referenced_chart_survives_regardless_of_age(outdir, monkeypatch):
    """최신 차트를 나이로 지우면 상세 페이지가 깨진다."""
    referenced = _touch(outdir, "AAPL_20260401.png", days_old=200)
    orphan = _touch(outdir, "OLD_20260401.png", days_old=200)
    monkeypatch.setattr(output_retention, "_referenced_charts",
                        lambda: {os.path.realpath(referenced)})

    result = output_retention.cleanup_outputs()

    assert os.path.exists(referenced)
    assert not os.path.exists(orphan)
    assert result["kept_referenced_charts"] == 1


def test_chart_and_json_use_separate_windows(outdir, monkeypatch):
    monkeypatch.setattr(output_retention, "OUTPUT_JSON_RETENTION_DAYS", 7)
    monkeypatch.setattr(output_retention, "OUTPUT_CHART_RETENTION_DAYS", 90)
    _touch(outdir, "A_agent_x.json", days_old=10)      # json 창 초과
    chart = _touch(outdir, "A_20260901.png", days_old=10)   # chart 창 이내

    result = output_retention.cleanup_outputs()

    assert result["by_kind"] == {"json": 1, "chart": 0}
    assert os.path.exists(chart)


# ── 보고 ──────────────────────────────────────────────────────────


def test_dry_run_reports_intent_not_completion(outdir):
    path = _touch(outdir, "A_agent_x.json", days_old=90, size=2048)

    result = output_retention.cleanup_outputs(dry_run=True)

    assert result["dry_run"] is True
    assert result["candidates"] == 1 and result["candidate_bytes"] == 2048
    assert result["deleted"] == 0 and result["freed_bytes"] == 0   # 지웠다고 안 한다
    assert os.path.exists(path)


def test_freed_bytes_and_remaining_are_reported(outdir):
    _touch(outdir, "A_agent_x.json", days_old=90, size=1000)
    _touch(outdir, "B_agent_y.json", days_old=90, size=2000)
    _touch(outdir, "C_agent_z.json", days_old=1, size=500)

    result = output_retention.cleanup_outputs()

    assert result["deleted"] == 2 and result["freed_bytes"] == 3000
    assert result["remaining_files"] == 1 and result["remaining_bytes"] == 500
    assert result["retention_days"] == {"json": 30, "chart": 30}


def test_delete_failure_is_reported_with_a_reason(outdir, monkeypatch):
    _touch(outdir, "A_agent_x.json", days_old=90)
    _touch(outdir, "B_agent_y.json", days_old=90)

    real_remove = os.remove

    def flaky(path):
        if path.endswith("A_agent_x.json"):
            raise PermissionError("read-only file system")
        return real_remove(path)

    monkeypatch.setattr(output_retention.os, "remove", flaky)
    result = output_retention.cleanup_outputs()

    assert result["status"] == "degraded"
    assert result["deleted"] == 1 and result["failed"] == 1
    assert "PermissionError" in result["failures"][0]["error"]


def test_total_failure_is_an_error(outdir, monkeypatch):
    _touch(outdir, "A_agent_x.json", days_old=90)
    monkeypatch.setattr(output_retention.os, "remove",
                        lambda p: (_ for _ in ()).throw(OSError("disk error")))

    assert output_retention.cleanup_outputs()["status"] == "error"


def test_nothing_to_clean_is_completed(outdir):
    _touch(outdir, "A_agent_x.json", days_old=1)
    result = output_retention.cleanup_outputs()

    assert result["status"] == "completed" and result["deleted"] == 0


# ── 스케줄 등록 ───────────────────────────────────────────────────


def test_job_is_registered_and_scheduled():
    import service

    assert "output_retention" in service._KNOWN_OPS_JOBS
    src = open(os.path.join(_AGENT_DIR, "service.py"), encoding="utf-8").read()
    assert "id='output_retention'" in src, "스케줄러에 등록되지 않았다"
    assert "OUTPUT_RETENTION_HOUR" in src


def test_ops_run_job_accepts_retention(monkeypatch):
    import service

    called = []
    monkeypatch.setattr(service, "run_output_retention",
                        lambda: called.append(1) or {"status": "completed"})
    service.ops_run_job("output_retention")
    service.ops_run_job("cleanup")

    assert len(called) == 2


def test_job_alerts_on_partial_failure(monkeypatch):
    import service

    monkeypatch.setattr(service, "_record_job_start", lambda *a, **k: "t0")
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: None)
    sent = []
    monkeypatch.setattr(service, "_send_ops_alert",
                        lambda title, detail, **k: sent.append(detail))
    monkeypatch.setattr(
        "output_retention.cleanup_outputs",
        lambda dry_run=False: {"status": "degraded", "deleted": 3, "failed": 1,
                               "failures": [{"name": "A.json", "error": "PermissionError"}]},
    )

    service.run_output_retention()

    assert sent and "A.json(PermissionError)" in sent[0]


# ── 참조 목록을 모를 때 ───────────────────────────────────────────
#
# `_referenced_charts()` 는 서버 프로세스 안에서는 `latest_results` 를, 밖에서는
# DB 에 영속된 요약을 읽는다. 둘 다 실패하면 **무엇이 참조 중인지 모르는 상태**다.
# 그때 차트를 나이만 보고 지우면 상세 페이지가 깨진다.


def test_charts_are_skipped_when_references_are_unknown(outdir, monkeypatch):
    def unknown():
        raise RuntimeError("referenced charts unknown")

    monkeypatch.setattr(output_retention, "_referenced_charts", unknown)
    chart = _touch(outdir, "OLD_20260401.png", days_old=200)
    _touch(outdir, "A_agent_x.json", days_old=200)

    result = output_retention.cleanup_outputs()

    assert os.path.exists(chart), "참조를 모르는데 차트를 지웠다"
    assert result["by_kind"] == {"json": 1, "chart": 0}
    assert result["charts_evaluated"] is False      # 정상 완료로 위장하지 않는다


def test_charts_evaluated_is_true_in_the_normal_path(outdir):
    _touch(outdir, "A_agent_x.json", days_old=90)
    assert output_retention.cleanup_outputs()["charts_evaluated"] is True


def test_referenced_charts_does_not_import_service_module(monkeypatch):
    """서버 밖에서 service 를 새로 적재하면 스케줄러까지 딸려 온다."""
    import sys

    monkeypatch.delitem(sys.modules, "service", raising=False)
    monkeypatch.setattr("db.get_app_state", lambda key, default=None: None)

    output_retention._referenced_charts()

    assert "service" not in sys.modules, "service 모듈을 새로 적재했다"


def test_referenced_charts_restores_from_persisted_summary(monkeypatch, tmp_path):
    import json as _json
    import sys

    chart = tmp_path / "AAPL_20260401.png"
    chart.write_bytes(b"x")
    monkeypatch.delitem(sys.modules, "service", raising=False)
    monkeypatch.setattr(
        "db.get_app_state",
        lambda key, default=None: _json.dumps(
            {"AAPL": {"result": {"chart_path": str(chart)}}}
        ),
    )

    assert output_retention._referenced_charts() == {os.path.realpath(str(chart))}
