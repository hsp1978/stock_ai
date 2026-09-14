"""webui·스캐너 로깅 진입점 — agent-api 와 **같은 설정**을 쓴다.

설정 구현을 두 벌 두면 한쪽만 고쳐진다. `chart_agent_service/logging_setup.py`
하나를 공유하고, 여기서는 경로만 붙인다 (webui 컨테이너에도
`/app/chart_agent_service` 가 있다).

비밀값 마스킹(`SecretRedactingFilter`)도 그대로 따라온다 — 2026-09-14 에
agent-api 에서 로깅을 켜자 FMP API 키가 로그에 찍혔다. webui 쪽에서 같은 일이
반복되지 않게 처음부터 같은 필터를 태운다.

`stock_analyzer/` 의 `print()` 는 전부 없애지 않는다. `if __name__ == "__main__"`
아래의 출력은 사람이 스크립트를 직접 돌릴 때 보라고 있는 것이다 — stdout 이 맞다.
로거로 바꾸는 대상은 **라이브러리 경로**(webui·agent 가 import 해서 쓰는 코드)다.
"""

from __future__ import annotations

import logging
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
for _p in (_THIS_DIR, os.path.join(_PROJECT_ROOT, "chart_agent_service")):
    if _p not in sys.path:
        sys.path.append(_p)

try:
    from logging_setup import configure_logging, get_logger  # type: ignore[import-not-found]
except ImportError:  # agent 모듈이 없는 배포 — 최소 설정으로라도 돌아간다
    _fallback_configured = False

    def configure_logging(force: bool = False) -> dict:  # type: ignore[misc]
        """폴백: 공용 설정 모듈이 없을 때의 최소 구성.

        사유를 반환값에 남긴다 — 마스킹 필터가 없는 상태를 모르고 쓰면 안 된다.
        """
        global _fallback_configured
        if _fallback_configured and not force:
            return {"status": "already_configured", "redaction": "unavailable"}
        logging.basicConfig(
            level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
            format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
            stream=sys.stdout,
            force=True,
        )
        _fallback_configured = True
        return {
            "status": "configured",
            "redaction": "unavailable",
            "detail": "chart_agent_service/logging_setup.py 를 찾지 못했다 — 비밀값 마스킹 없음",
        }

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        configure_logging()
        return logging.getLogger(name)


__all__ = ["configure_logging", "get_logger"]
