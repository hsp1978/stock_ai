"""agent-api 호출 클라이언트 — in-proc 엔진 우선, HTTP 폴백.

`webui.py` 에서 분리한 두 번째 조각(CLAUDE.md §6-10 점진 분리). 모든 페이지가 쓰는
공용 경로라 페이지를 떼기 전에 먼저 내보냈다.

호출 규약 — **기본은 HTTP 단일 경로**다 (`WEBUI_ENGINE_MODE=http`).
  - 모든 호출이 agent-api 로 간다. 상태(결과 캐시·signal_outcomes DB·스캔 로그·잡)는
    agent-api 프로세스와 그 마운트된 output 이 단일 소스다.
  - `WEBUI_ENGINE_MODE=local` 은 agent-api 없이 webui 를 단독 실행할 때만 쓴다.
    이때만 in-process 엔진을 먼저 시도하고 None 이면 HTTP 로 폴백한다.
    `/paper`·`/trading/`·`/gpu`·`/ml/*` 는 local 모드에서도 HTTP 다.

※ 2026-10-07 이전에는 `local_engine` import 가 성공하면 자동으로 in-process 였다.
  webui 이미지에 chart_agent_service 가 들어간 2026-04-29 부터 webui 는 **마운트되지
  않은 자기 컨테이너의 빈 상태**를 읽었다 — 결과 0건, signal_outcomes 0건(실제 8,860건),
  스캔 로그 0건. 상세·Signal Accuracy·History·Scan Log 화면이 운영 데이터를 못 봤고,
  webui 에서 누른 스캔·멀티에이전트는 webui 컨테이너 안에서 돌아 기록이 재생성 때 사라졌다.
"""

from __future__ import annotations

import os
import sys

import httpx
import streamlit as st

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ANALYZER_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_ANALYZER_DIR)
for _p in (_ANALYZER_DIR, os.path.join(_PROJECT_ROOT, "chart_agent_service")):
    if _p not in sys.path:
        sys.path.append(_p)

from app_logging import get_logger  # noqa: E402 — sys.path 설정 뒤

logger = get_logger("stock_auto.webui.api_client")

try:
    from chart_agent_service.config import AGENT_API_HOST, AGENT_API_PORT
except ImportError:
    AGENT_API_HOST = os.getenv("AGENT_API_HOST", "localhost")
    AGENT_API_PORT = int(os.getenv("AGENT_API_PORT", "8100"))

AGENT_API_URL = os.getenv("AGENT_API_URL", f"http://{AGENT_API_HOST}:{AGENT_API_PORT}")

#: http(기본) | local. local 은 agent-api 없이 단독 실행할 때만 — 위 모듈 docstring 참조.
WEBUI_ENGINE_MODE = os.getenv("WEBUI_ENGINE_MODE", "http").strip().lower()

USE_LOCAL_ENGINE = False
if WEBUI_ENGINE_MODE == "local":
    try:
        from local_engine import (
            engine_dispatch_get,
            engine_dispatch_post,
            engine_get_chart_path,
        )

        USE_LOCAL_ENGINE = True
    except ImportError as _exc:  # 요청한 모드를 못 쓰면 조용히 넘어가지 않는다
        logger.warning("WEBUI_ENGINE_MODE=local 이지만 local_engine import 실패 — HTTP 사용: %s", _exc)
elif WEBUI_ENGINE_MODE != "http":
    logger.warning("알 수 없는 WEBUI_ENGINE_MODE=%r — HTTP 사용", WEBUI_ENGINE_MODE)


def _agent_api_candidates() -> list[str]:
    """AGENT_API_URL이 오래된 원격 주소여도 로컬 agent-api로 폴백."""
    candidates = [
        AGENT_API_URL,
        f"http://{AGENT_API_HOST}:{AGENT_API_PORT}",
        f"http://localhost:{AGENT_API_PORT}",
        f"http://127.0.0.1:{AGENT_API_PORT}",
    ]
    seen = set()
    result = []
    for base in candidates:
        base = (base or "").rstrip("/")
        if base and base not in seen:
            result.append(base)
            seen.add(base)
    return result


def _force_http_api(path: str) -> bool:
    # Paper/Virtual Trade 상태는 agent-api의 mounted output을 단일 소스로 쓴다.
    # GPU 제어는 스케줄러와 Ollama 연결을 소유한 agent-api 프로세스에서 실행해야
    # 한다 — in-proc으로 돌면 webui 프로세스가 언로드를 쏘게 되어 소유권이 갈린다.
    return (
        path.startswith("/paper")
        or path.startswith("/trading/")
        or path.startswith("/gpu")
    )


def api_get(path: str, timeout: int = 10):
    # 기본(http) 모드에서는 바로 HTTP. local 모드에서만 in-process 를 먼저 시도하고
    # None(핸들러 부재)이면 HTTP 로 폴백한다. /ml/* 는 local 모드에서도 HTTP.
    if USE_LOCAL_ENGINE and not path.startswith("/ml/") and not _force_http_api(path):
        result = engine_dispatch_get(path)
        if result is not None:
            return result
    last_error = None
    for base_url in _agent_api_candidates():
        try:
            resp = httpx.get(f"{base_url}{path}", timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError as e:
            last_error = e
            continue
        except httpx.HTTPStatusError as e:
            last_error = e
            break
        except Exception as e:
            last_error = e
            continue
    if last_error is not None and not isinstance(last_error, httpx.ConnectError):
        st.error(f"API Error: {last_error}")
    return None


def api_post(path: str, timeout: int = 300, json_body: dict = None):
    """API POST. json_body가 주어지면 FastAPI body 파라미터로 전달.

    로컬 엔진이 None 반환 시 (핸들러 부재 — 예: /trading/*, /paper/virtual-buy,
    /paper/partial-close) HTTP fallback. json_body는 HTTP 경로에서 사용된다.
    """
    if USE_LOCAL_ENGINE and not _force_http_api(path):
        result = engine_dispatch_post(path, json_body=json_body, timeout=timeout)
        if result is not None:
            return result
    last_error = None
    for base_url in _agent_api_candidates():
        try:
            if json_body is not None:
                resp = httpx.post(f"{base_url}{path}", json=json_body, timeout=timeout)
            else:
                resp = httpx.post(f"{base_url}{path}", timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError as e:
            last_error = e
            continue
        except httpx.HTTPStatusError as e:
            last_error = e
            break
        except Exception as e:
            last_error = e
            continue
    if last_error is not None and not isinstance(last_error, httpx.ConnectError):
        st.error(f"API Error: {last_error}")
    return None


def _get_session_id() -> str:
    """Streamlit session 당 1회 생성되는 UUID — user_action_log 트래킹용."""
    if "_action_log_sid" not in st.session_state:
        import uuid as _uuid
        st.session_state._action_log_sid = _uuid.uuid4().hex[:16]
    return st.session_state._action_log_sid


def log_action(
    action_type: str,
    page: str | None = None,
    ticker: str | None = None,
    query: str | None = None,
    metadata: dict | None = None,
) -> None:
    """WebUI 행위 로깅 헬퍼. 실패해도 UI 흐름을 막지 않는다.

    action_type 권장 값: page_view, ticker_search, manual_scan,
    watchlist_edit, export, other.
    """
    try:
        api_post(
            "/user-action",
            timeout=3,
            json_body={
                "action_type": action_type,
                "page": page,
                "ticker": ticker,
                "query": query,
                "metadata": metadata,
                "session_id": _get_session_id(),
            },
        )
    except Exception:
        pass  # 로깅 실패가 UI를 막지 않도록


def get_chart_url(ticker: str) -> str:
    """local_engine 모드: 파일 경로 반환 / HTTP 모드: URL 반환"""
    if USE_LOCAL_ENGINE:
        return engine_get_chart_path(ticker) or ""
    return f"{AGENT_API_URL}/chart/{ticker}"
