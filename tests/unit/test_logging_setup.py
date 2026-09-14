"""로깅 설정 — 남기는 것처럼 보이는 코드가 실제로 남기게 한다.

`docs/SYSTEM_OVERVIEW.md` §13.9-3: `print()` 기반 로깅. 그런데 실제 문제는 print
자체보다 **로깅이 설정된 적이 없다는 것**이었다 (2026-09-14 확인):

  `basicConfig`/`dictConfig` 호출이 리포지토리 어디에도 없다. 그래서 이미
  `logger.info(...)` 를 쓰고 있던 data_collector·llm/router·llm_calibrator·
  ic_ensemble 의 로그는 **전부 버려지고 있었다** (루트 기본 레벨 WARNING).
  로그를 남기는 것처럼 보이는 코드가 아무것도 남기지 않는 상태다.

여기서 고정하는 것:
  1. 설정은 한 번만, 그리고 **적용된 값을 돌려준다** (요청 ≠ 적용)
  2. 파일 핸들러가 실패해도 로깅 전체를 포기하지 않되, 사유를 남긴다
  3. 회전(rotation)을 건다 — service.log 는 로테이션 없이 5MB 까지 갔다
  4. uvicorn 핸들러 중복으로 같은 줄이 두 번 찍히지 않는다
  5. INFO 가 실제로 출력된다 (종전에는 조용히 사라졌다)
"""

import logging
import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import logging_setup  # noqa: E402


@pytest.fixture(autouse=True)
def clean_root():
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    logging_setup._configured = False
    yield
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    logging_setup._configured = False


def _env(monkeypatch, **kw):
    for key in ("LOG_LEVEL", "LOG_FORMAT", "LOG_FILE", "LOG_MAX_BYTES", "LOG_BACKUP_COUNT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in kw.items():
        monkeypatch.setenv(key, value)


# ── 기본 동작 ─────────────────────────────────────────────────────


def test_info_actually_reaches_the_stream(monkeypatch, capsys):
    """종전에는 이 한 줄이 조용히 사라졌다."""
    _env(monkeypatch)
    logging_setup.configure_logging(force=True)

    logging.getLogger("stock_auto.test").info("표본 적립 7건")

    assert "표본 적립 7건" in capsys.readouterr().out


def test_existing_module_loggers_now_emit(monkeypatch, capsys):
    """data_collector 등은 이미 logger.info 를 쓰고 있었다 — 설정만 없었다."""
    _env(monkeypatch)
    logging_setup.configure_logging(force=True)

    logging.getLogger("data_collector").info("OHLCV 캐시 적중")

    out = capsys.readouterr().out
    assert "OHLCV 캐시 적중" in out and "data_collector" in out


def test_configure_reports_what_was_applied(monkeypatch):
    _env(monkeypatch, LOG_LEVEL="DEBUG", LOG_FORMAT="json")
    result = logging_setup.configure_logging(force=True)

    assert result["status"] == "configured"
    assert result["level"] == "DEBUG" and result["format"] == "json"
    assert logging.getLogger().level == logging.DEBUG


def test_second_call_is_a_noop(monkeypatch):
    _env(monkeypatch)
    logging_setup.configure_logging(force=True)
    again = logging_setup.configure_logging()

    assert again["status"] == "already_configured"
    assert len(logging.getLogger().handlers) == 1     # 핸들러가 쌓이지 않는다


def test_level_filters_below_threshold(monkeypatch, capsys):
    _env(monkeypatch, LOG_LEVEL="WARNING")
    logging_setup.configure_logging(force=True)

    logging.getLogger("x").info("보이면 안 된다")
    logging.getLogger("x").warning("보여야 한다")

    out = capsys.readouterr().out
    assert "보이면 안 된다" not in out and "보여야 한다" in out


def test_invalid_level_falls_back_to_info(monkeypatch):
    _env(monkeypatch, LOG_LEVEL="VERBOSE")
    assert logging_setup.configure_logging(force=True)["level"] == "INFO"


# ── JSON 포맷 ─────────────────────────────────────────────────────


def test_json_format_is_machine_readable(monkeypatch, capsys):
    import json

    _env(monkeypatch, LOG_FORMAT="json")
    logging_setup.configure_logging(force=True)

    logging.getLogger("stock_auto.scan").warning("stale 2건")
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    assert payload["level"] == "WARNING"
    assert payload["logger"] == "stock_auto.scan"
    assert payload["msg"] == "stale 2건"


def test_json_format_carries_the_traceback(monkeypatch, capsys):
    import json

    _env(monkeypatch, LOG_FORMAT="json")
    logging_setup.configure_logging(force=True)

    try:
        raise ValueError("가격 해석 실패")
    except ValueError:
        logging.getLogger("x").exception("기록 불가")

    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "ValueError" in payload["exc"] and "가격 해석 실패" in payload["exc"]


# ── 파일 핸들러 ───────────────────────────────────────────────────


def test_rotating_file_handler_is_attached(monkeypatch, tmp_path):
    import logging.handlers

    path = tmp_path / "logs" / "service.log"
    _env(monkeypatch, LOG_FILE=str(path), LOG_MAX_BYTES="2048", LOG_BACKUP_COUNT="3")
    result = logging_setup.configure_logging(force=True)

    handlers = [h for h in logging.getLogger().handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert result["file_status"] == "enabled"
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 2048 and handlers[0].backupCount == 3


def test_log_file_rotates_instead_of_growing(monkeypatch, tmp_path):
    """service.log 는 로테이션 없이 5MB 까지 갔다."""
    path = tmp_path / "service.log"
    _env(monkeypatch, LOG_FILE=str(path), LOG_MAX_BYTES="1024", LOG_BACKUP_COUNT="2")
    logging_setup.configure_logging(force=True)

    log = logging.getLogger("x")
    for i in range(200):
        log.info("긴 줄 %03d %s", i, "y" * 80)

    assert path.exists() and path.stat().st_size <= 4096
    assert (tmp_path / "service.log.1").exists()


def test_file_failure_keeps_stream_logging_and_reports_why(monkeypatch, tmp_path, capsys):
    """파일에 못 써도 콘솔 로그는 살아야 하고, 사유는 남아야 한다."""
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    _env(monkeypatch, LOG_FILE=str(blocked / "service.log"))

    result = logging_setup.configure_logging(force=True)

    assert result["file_status"] == "failed"
    assert result["file_error"] and "Error" in result["file_error"]
    logging.getLogger("x").info("콘솔은 살아 있다")
    assert "콘솔은 살아 있다" in capsys.readouterr().out


def test_no_file_handler_when_unset(monkeypatch):
    _env(monkeypatch)
    result = logging_setup.configure_logging(force=True)

    assert result["file"] is None and result["file_status"] == "disabled"


# ── uvicorn / 외부 라이브러리 ─────────────────────────────────────


def test_uvicorn_loggers_do_not_double_print(monkeypatch, capsys):
    _env(monkeypatch)
    uv = logging.getLogger("uvicorn.error")
    uv.addHandler(logging.StreamHandler(sys.stdout))

    logging_setup.configure_logging(force=True)
    uv.info("Application startup complete")

    assert capsys.readouterr().out.count("Application startup complete") == 1


def test_noisy_libraries_are_quieted(monkeypatch):
    _env(monkeypatch, LOG_LEVEL="DEBUG")
    logging_setup.configure_logging(force=True)

    for name in ("httpx", "apscheduler", "urllib3", "matplotlib"):
        assert logging.getLogger(name).level == logging.WARNING


# ── service.py 전환 ───────────────────────────────────────────────


def test_agent_service_modules_have_no_bare_print():
    """agent-api 전체 — print 는 레벨도 타임스탬프도 없어 걸러낼 수 없다.

    webui 쪽(`stock_analyzer/`)은 아직 남아 있다. CLI 성격 스크립트가 섞여 있어
    한 번에 옮기지 않는다 (CLAUDE.md §6-10 과 같은 이유).
    """
    import glob
    import re

    offenders = {}
    for path in glob.glob(os.path.join(_AGENT_DIR, "**", "*.py"), recursive=True):
        src = open(path, encoding="utf-8").read()
        hits = re.findall(r"^\s*print\(", src, re.M)
        if hits:
            offenders[os.path.relpath(path, _AGENT_DIR)] = len(hits)

    assert not offenders, f"print 잔존: {offenders}"


def test_service_module_has_no_bare_print():
    """print 는 레벨도 타임스탬프도 없다 — 컨테이너 로그에서 걸러낼 수 없다."""
    import re

    src = open(os.path.join(_AGENT_DIR, "service.py"), encoding="utf-8").read()
    remaining = re.findall(r"^\s*print\(", src, re.M)

    assert not remaining, f"service.py 에 print {len(remaining)}건 잔존"


def test_service_configures_logging_on_import():
    """모듈 적재 시점에 설정한다 — 첫 로그가 설정 전에 나가면 사라진다.

    `_configured` 플래그는 다른 테스트가 리셋하므로 보지 않는다. 대신 모듈
    최상위에 호출이 있는지와, 서비스 로거가 붙었는지를 본다.
    """
    import service

    src = open(os.path.join(_AGENT_DIR, "service.py"), encoding="utf-8").read()
    assert "\nconfigure_logging()\n" in src, "모듈 최상위 설정 호출이 없다"
    assert service.logger.name == "stock_auto.service"


def test_get_logger_configures_lazily(monkeypatch):
    _env(monkeypatch)
    logging_setup._configured = False

    log = logging_setup.get_logger("stock_auto.lazy")

    assert logging_setup._configured is True
    assert log.name == "stock_auto.lazy"


# ── 비밀값 마스킹 ─────────────────────────────────────────────────
#
# 2026-09-14: 로깅을 켜자마자 data_collector 가 FMP 실패를 URL 통째로 남기면서
# `apikey=...` 가 컨테이너 로그에 찍혔다. **로깅을 켠 것이 곧 비밀을 유출하는
# 일이 되면 안 된다** (CLAUDE.md §6-2).


def test_api_key_in_a_url_is_masked(monkeypatch, capsys):
    _env(monkeypatch)
    logging_setup.configure_logging(force=True)

    logging.getLogger("data_collector").warning(
        "fundamentals failed: 403 for https://fmp.example/api/v3/profile/AAPL"
        "?apikey=svo6QLxZtke0YUW8Ek04vBxGTGfGu7fS"
    )

    out = capsys.readouterr().out
    assert "svo6QLxZtke0YUW8Ek04vBxGTGfGu7fS" not in out
    assert "apikey=***" in out
    assert "403" in out                      # 진단에 필요한 정보는 남는다


@pytest.mark.parametrize("text,secret", [
    ("token=abcd1234efgh5678", "abcd1234efgh5678"),
    ("api_key: MY-SUPER-SECRET-VALUE", "MY-SUPER-SECRET-VALUE"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9", "eyJhbGciOiJIUzI1NiJ9"),
    ("password=hunter2hunter2", "hunter2hunter2"),
])
def test_common_credential_shapes_are_masked(monkeypatch, capsys, text, secret):
    _env(monkeypatch)
    logging_setup.configure_logging(force=True)

    logging.getLogger("x").error(text)

    assert secret not in capsys.readouterr().out


def test_env_secret_values_are_masked_even_without_a_key_name(monkeypatch, capsys):
    """패턴에 안 걸리는 형태로 새어 나와도 값 자체로 잡는다."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567890:AAH-verylongtokenvalue")
    _env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567890:AAH-verylongtokenvalue")
    logging_setup.configure_logging(force=True)

    logging.getLogger("x").error("전송 실패 (1234567890:AAH-verylongtokenvalue)")

    out = capsys.readouterr().out
    assert "AAH-verylongtokenvalue" not in out and "***" in out


def test_short_env_values_are_not_masked(monkeypatch, capsys):
    """8자 미만까지 지우면 평범한 단어가 사라져 로그를 못 읽는다."""
    monkeypatch.setenv("SOME_KEY", "dev")
    _env(monkeypatch)
    monkeypatch.setenv("SOME_KEY", "dev")
    logging_setup.configure_logging(force=True)

    logging.getLogger("x").info("dev 환경에서 실행")

    assert "dev 환경에서 실행" in capsys.readouterr().out


def test_masking_applies_to_the_file_handler_too(monkeypatch, tmp_path):
    path = tmp_path / "service.log"
    _env(monkeypatch, LOG_FILE=str(path))
    logging_setup.configure_logging(force=True)

    logging.getLogger("x").error("https://api.example/x?apikey=SECRETVALUE12345")
    logging.shutdown()

    assert "SECRETVALUE12345" not in path.read_text()


def test_masking_survives_lazy_formatting(monkeypatch, capsys):
    """logger.warning('%s', url) 형태로도 새어 나온다."""
    _env(monkeypatch)
    logging_setup.configure_logging(force=True)

    logging.getLogger("x").warning("호출 실패: %s", "https://x/y?token=LEAKEDTOKEN123")

    assert "LEAKEDTOKEN123" not in capsys.readouterr().out


def test_exception_text_is_scrubbed(monkeypatch, capsys):
    _env(monkeypatch)
    logging_setup.configure_logging(force=True)

    try:
        raise RuntimeError("https://x?apikey=INSIDEEXCEPTION123")
    except RuntimeError:
        logging.getLogger("x").exception("외부 호출 실패")

    assert "INSIDEEXCEPTION123" not in capsys.readouterr().out


def test_redaction_is_reported_as_enabled(monkeypatch):
    _env(monkeypatch)
    assert logging_setup.configure_logging(force=True)["redaction"] == "enabled"
