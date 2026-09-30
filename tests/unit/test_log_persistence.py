"""로그는 컨테이너보다 오래 살아야 한다.

2026-09-29 RTX 사고(docs/SYSTEM_OVERVIEW.md §13.9w)에서 원인을 가를 agent-api
로그가 하나도 남지 않았다. 두 가지가 겹쳤다:

  1. `LOG_FILE` 미설정 — 로그가 stdout(json-file)에만 있었다
  2. `stock-auto.service` 의 `ExecStop=docker compose down` — 재부팅 때 컨테이너가
     삭제되고, 부팅 시 `up -d` 가 새로 만들면서 `docker logs` 가 초기화됐다

여기서 고정하는 것:
  1. compose 가 agent-api 의 LOG_FILE 을 **호스트 바인드 마운트 안의 경로**로 지정한다
  2. 그 호스트 디렉토리가 저장소에 있다 (없으면 docker 가 root 로 만들어 못 쓴다)
  3. 유닛의 ExecStop 이 컨테이너를 지우지 않는다
  4. 파일 로그 상태가 `/health` 에 실린다 — 실패·미설정이 조용히 지나가지 않는다
"""

import os
import sys

import yaml

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
_AGENT_DIR = os.path.join(_ROOT, "chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)


def _agent_service() -> dict:
    with open(os.path.join(_ROOT, "compose.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)["services"]["agent-api"]


def _host_dir_for(container_path: str) -> str | None:
    """Return the host dir bind-mounted over container_path, if any."""
    for vol in _agent_service().get("volumes", []):
        host, _, rest = vol.partition(":")
        target = rest.split(":")[0]
        if container_path == target or container_path.startswith(target.rstrip("/") + "/"):
            return host
    return None


def test_compose_sets_a_log_file_for_agent_api():
    env = _agent_service().get("environment", {})
    assert env.get("LOG_FILE"), "agent-api 의 LOG_FILE 이 비었다 — 로그가 컨테이너와 같이 지워진다"


def test_log_file_lives_on_a_host_bind_mount():
    log_file = _agent_service()["environment"]["LOG_FILE"]
    host = _host_dir_for(log_file)
    assert host, f"{log_file} 이 어느 바인드 마운트에도 속하지 않는다 — 컨테이너 안에만 남는다"
    assert host.startswith("./") or host.startswith("/"), (
        f"named volume 이 아니라 호스트 경로여야 한다: {host}"
    )


def test_log_mount_is_not_the_retention_directory():
    """output/ 은 output_retention 잡이 정리한다 — 로그를 거기 두면 섞인다."""
    log_file = _agent_service()["environment"]["LOG_FILE"]
    assert "/output" not in log_file


def test_host_log_directory_is_tracked():
    log_file = _agent_service()["environment"]["LOG_FILE"]
    host = _host_dir_for(log_file)
    host_abs = os.path.normpath(os.path.join(_ROOT, host))
    assert os.path.isfile(os.path.join(host_abs, ".gitkeep")), (
        f"{host} 가 저장소에 없다 — docker 가 root 로 만들면 uid 1000 이 못 쓴다"
    )


def test_systemd_unit_does_not_remove_containers_on_stop():
    with open(os.path.join(_ROOT, "deploy", "stock-auto.service"), encoding="utf-8") as fh:
        stops = [ln for ln in fh if ln.startswith("ExecStop=")]
    assert stops, "ExecStop 이 없다"
    for line in stops:
        assert " down" not in line, f"ExecStop 이 컨테이너를 지운다: {line.strip()}"


# ── /health ──────────────────────────────────────────────────────────


def test_health_reports_disabled_file_logging_as_a_warning(monkeypatch):
    import service

    monkeypatch.setattr(service, "_LOGGING_STATUS", {"file": None, "file_status": "disabled"})
    info = service._logging_health()
    assert info["file_status"] == "disabled"
    assert "warning" in info, "미설정을 정상처럼 보고한다"


def test_health_carries_the_failure_reason(monkeypatch):
    import service

    monkeypatch.setattr(
        service,
        "_LOGGING_STATUS",
        {
            "file": "/app/logs/x.log",
            "file_status": "failed",
            "file_error": "PermissionError: denied",
        },
    )
    info = service._logging_health()
    assert info["file_status"] == "failed"
    assert "PermissionError" in info["file_error"]


def test_health_reports_size_of_live_file(monkeypatch, tmp_path):
    import service

    log = tmp_path / "agent-api.log"
    log.write_text("hello\n", encoding="utf-8")
    monkeypatch.setattr(service, "_LOGGING_STATUS", {"file": str(log), "file_status": "enabled"})
    info = service._logging_health()
    assert info["file_status"] == "enabled"
    assert info["size_bytes"] == 6


def test_health_notices_the_file_vanished(monkeypatch, tmp_path):
    """기동 때 열렸다고 지금도 있는 것은 아니다 (enabled ≠ 지금 쓰이는 중)."""
    import service

    monkeypatch.setattr(
        service, "_LOGGING_STATUS", {"file": str(tmp_path / "gone.log"), "file_status": "enabled"}
    )
    info = service._logging_health()
    assert info["file_status"] == "missing"
    assert info["file_error"]


def test_health_response_includes_logging():
    import inspect

    import service

    assert '"logging": _logging_health()' in inspect.getsource(service.health)


def test_second_configure_still_reports_the_applied_file(monkeypatch, tmp_path):
    """배포 실측 회귀 (2026-09-30): config 임포트 중 get_logger 가 먼저 설정하자
    service 의 configure_logging() 이 already_configured 만 받아 /health 가
    file=None, unknown 을 보고했다. 파일 로그는 실제로 잘 쓰이고 있었다."""
    import logging

    import logging_setup

    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "agent-api.log"))
    monkeypatch.setattr(logging_setup, "_configured", False)
    try:
        logging_setup.get_logger("early.import")  # 먼저 설정하는 쪽
        again = logging_setup.configure_logging()  # service.py 최상위 호출

        assert again["status"] == "already_configured"
        assert again["file"] == str(tmp_path / "agent-api.log")
        assert again["file_status"] == "enabled"
    finally:
        for h in list(root.handlers):
            if h not in saved_handlers:
                h.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)
        logging_setup._configured = False
