"""로깅 설정 — 단일 진입점.

2026-09-14 실측으로 드러난 두 가지:

1. **로깅이 설정된 적이 없다.** `basicConfig`/`dictConfig` 호출이 리포지토리
   어디에도 없었다. 그래서 `data_collector`·`llm/router`·`llm_calibrator`·
   `ic_ensemble` 이 이미 쓰고 있던 `logger.info(...)` 는 **전부 버려지고**
   있었다 (루트 기본 레벨 WARNING). 로그를 남기는 것처럼 보이는 코드가
   실제로는 아무것도 남기지 않는 상태였다 — §13 의 전형이다.

2. `service.log` 는 2026-04-29 이후 갱신되지 않은 5MB 파일이다. 컨테이너로
   옮기며 print 리다이렉트가 끊겼는데 파일은 남아 '최근 로그'처럼 보였다.

설정은 **한 번만** 적용한다. uvicorn 이 자체 핸들러를 붙이므로 중복 출력이
나지 않도록 propagate 를 정리한다.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import sys

DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"

#: 쿼리스트링·헤더에 실려 나오는 비밀값 패턴. 값만 가리고 키 이름은 남긴다 —
#: 무엇이 가려졌는지 모르면 디버깅이 안 된다.
_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[-_]?key|apikey|access[-_]?token|token|secret|password|passwd|pwd)"
               r"(\s*[=:]\s*|%3D)([^\s&'\")]+)"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]{8,})"),
]

#: 값 자체로 마스킹할 환경변수. 패턴에 안 걸리는 형태로 새어 나와도 잡는다.
_SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "PW", "CREDENTIAL")

_MASK = "***"


def _env_secret_values() -> list[str]:
    """마스킹 대상 실제 값. 너무 짧은 값은 오탐이 나므로 제외한다."""
    values = []
    for name, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        if any(hint in name.upper() for hint in _SECRET_ENV_HINTS):
            values.append(value)
    # 긴 값부터 지워야 부분 문자열이 남지 않는다
    return sorted(set(values), key=len, reverse=True)


class SecretRedactingFilter(logging.Filter):
    """로그에 섞여 나온 자격증명을 가린다.

    2026-09-14: 로깅을 켜자마자 `data_collector` 가 FMP 실패를 URL 통째로
    남기면서 `apikey=...` 가 컨테이너 로그에 찍혔다. 로깅을 켠 것이 곧 비밀을
    유출하는 일이 되면 안 된다 (CLAUDE.md §6-2).

    필터는 **핸들러가 아니라 레코드**에 건다 — 파일·스트림 어느 쪽으로 가든
    같은 마스킹이 적용돼야 한다.
    """

    def __init__(self) -> None:
        super().__init__()
        self._env_values = _env_secret_values()

    def scrub(self, text: str) -> str:
        for value in self._env_values:
            if value in text:
                text = text.replace(value, _MASK)
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(lambda m: m.group(1) + m.group(2) + _MASK
                               if m.re.groups == 3 else m.group(1) + _MASK, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        scrubbed = self.scrub(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        if record.exc_text:
            record.exc_text = self.scrub(record.exc_text)
        return True

_configured = False


class _RedactingMixin:
    """포맷 **결과**를 훑어 비밀값을 지운다.

    필터만으로는 부족하다. 필터가 도는 시점에 `record.exc_text` 는 아직 None 이고,
    트레이스백은 포맷 단계에서 만들어진다 — 실제로 `RuntimeError: https://...
    ?apikey=...` 가 그대로 새어 나갔다 (2026-09-14 테스트에서 적발). 예외 메시지야
    말로 URL 이 통째로 실리는 자리다.
    """

    _redactor: "SecretRedactingFilter | None" = None

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if self._redactor is not None:
            text = self._redactor.scrub(text)
        return text


class JsonFormatter(_RedactingMixin, logging.Formatter):
    """구조화 로그 — 컨테이너 로그를 기계로 읽을 때 쓴다."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(_RedactingMixin, logging.Formatter):
    """기본 텍스트 포맷 + 비밀값 마스킹."""


def _build_formatter(fmt: str, redactor: "SecretRedactingFilter") -> logging.Formatter:
    formatter: logging.Formatter = (
        JsonFormatter() if fmt.lower() == "json" else TextFormatter(DEFAULT_FORMAT)
    )
    formatter._redactor = redactor  # type: ignore[attr-defined]
    return formatter


def configure_logging(force: bool = False) -> dict:
    """루트 로거를 설정한다. 반환값은 **실제로 적용된 값**이다.

    설정 요청과 적용 결과를 같은 것으로 취급하지 않는다 — 파일 핸들러가 권한
    문제로 못 붙으면 그 사실이 반환값에 남아야 한다 (§13-2).
    """
    global _configured
    if _configured and not force:
        return {"status": "already_configured"}

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = os.getenv("LOG_FORMAT", "text")
    redactor = SecretRedactingFilter()
    formatter = _build_formatter(fmt, redactor)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    stream.addFilter(redactor)
    root.addHandler(stream)
    root.setLevel(level)

    file_path = os.getenv("LOG_FILE", "").strip()
    file_status = "disabled"
    file_error = None
    if file_path:
        try:
            directory = os.path.dirname(file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                file_path,
                maxBytes=int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024))),
                backupCount=int(os.getenv("LOG_BACKUP_COUNT", "5")),
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(redactor)
            root.addHandler(file_handler)
            file_status = "enabled"
        except OSError as exc:
            # 파일에 못 쓴다고 로깅 전체를 포기하지 않는다. 다만 조용히
            # 넘어가지도 않는다 — 파일이 없는 이유가 남아야 한다.
            file_status = "failed"
            file_error = f"{type(exc).__name__}: {exc}"
            root.warning("로그 파일 핸들러 실패 (%s): %s", file_path, file_error)

    # uvicorn 은 자체 핸들러를 붙인다. 그대로 두면 같은 줄이 두 번 찍힌다.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers = []
        uv.propagate = True

    # 외부 라이브러리는 기본적으로 조용히 — 우리 로그가 묻히면 안 된다.
    for name, lib_level in (
        ("apscheduler", logging.WARNING),
        ("httpx", logging.WARNING),
        ("httpcore", logging.WARNING),
        ("urllib3", logging.WARNING),
        ("matplotlib", logging.WARNING),
        ("yfinance", logging.WARNING),
    ):
        logging.getLogger(name).setLevel(lib_level)

    _configured = True
    return {
        "status": "configured",
        "level": logging.getLevelName(level),
        "format": "json" if isinstance(formatter, JsonFormatter) else "text",
        "file": file_path or None,
        "file_status": file_status,
        "file_error": file_error,
        "redaction": "enabled",
    }


def get_logger(name: str) -> logging.Logger:
    """모듈 로거. 설정이 아직이면 먼저 붙인다."""
    if not _configured:
        configure_logging()
    return logging.getLogger(name)
