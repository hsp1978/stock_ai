"""모델 가중치 고정 — digest 대조로 '조용한 교체'를 잡는다.

`docs/SYSTEM_OVERVIEW.md` §13.9-8: "모델 버전 태그 핀 — `qwen3:14b-q4_K_M` 등
태그 고정이나 digest 핀은 아님."

## Ollama 는 digest 로 참조할 수 없다

Docker 처럼 `image@sha256:...` 으로 고정하는 방식은 Ollama 에 없다. 2026-09-15 확인:

    POST /api/generate {"model": "sha256:bdbd181c33f2ed1b31c9"}
    → {"error": "model 'sha256:...' not found"}

`/api/show` 도 digest 를 돌려주지 않는다 (`/api/tags` 만 준다). 즉 **참조로 고정하는
것은 불가능**하다. 그래서 여기서는 방향을 바꾼다 — 기대 digest 를 설정에 적어 두고
**실제 적재된 것과 대조**한다. 고정이 아니라 **변경 감지**다.

## 왜 필요한가

`ollama pull qwen3:14b-q4_K_M` 을 다시 하면 같은 태그로 **다른 가중치**가 들어올 수
있다. 그러면 신호 판단이 바뀌는데 아무 데도 기록이 남지 않는다. 60일 hit-rate 검증은
"같은 로직 + 같은 모델" 을 전제하므로, 모델이 바뀐 구간이 섞이면 그 통계는 무효다.

## 미설정을 '정상'이라 부르지 않는다

기대 digest 가 비어 있으면 `unverified` 다 — `ok` 가 아니다 (CLAUDE.md §13-4).
현재 값을 채우려면 `make model-pin` 으로 출력된 줄을 `.env` 에 넣는다.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from config import (
    MAC_STUDIO_URL,
    OLLAMA_BASE_URL,
    OLLAMA_MAC_MODEL,
    OLLAMA_MAC_MODEL_DIGEST,
    OLLAMA_MODEL,
    OLLAMA_MODEL_DIGEST,
)
from logging_setup import get_logger

logger = get_logger("stock_auto.model_pin")

#: (노드명, 기본 URL, 모델명, 기대 digest)
def _targets() -> tuple[tuple[str, str, str, str], ...]:
    return (
        ("rtx_5070", OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_MODEL_DIGEST),
        ("mac_studio", MAC_STUDIO_URL, OLLAMA_MAC_MODEL, OLLAMA_MAC_MODEL_DIGEST),
    )


def _normalize(digest: str | None) -> str:
    """`sha256:abc…` 와 `abc…`, 대소문자·길이 차이를 같게 본다.

    `/api/tags` 는 전체 64자를 주지만 설정에는 앞 12~20자만 적어 두는 쪽이 읽기
    쉽다. 접두 비교를 허용한다 — 12자 미만은 충돌 위험이 있어 거부한다.
    """
    if not digest:
        return ""
    value = digest.strip().lower()
    if value.startswith("sha256:"):
        value = value[len("sha256:"):]
    return value


def _digest_matches(expected: str, actual: str) -> bool:
    exp, act = _normalize(expected), _normalize(actual)
    if not exp or not act:
        return False
    if len(exp) < 12:
        return False          # 너무 짧은 접두는 대조로 쓰지 않는다
    return act.startswith(exp)


def _fetch_tags(url: str, timeout: float) -> list[dict]:
    resp = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=timeout)
    resp.raise_for_status()
    return resp.json().get("models") or []


def verify_model_pins(timeout: float = 5.0) -> dict[str, Any]:
    """설정된 모델의 digest 가 실제 적재본과 같은지 확인한다.

    Returns:
        {"status": ok|mismatch|unverified|error, "nodes": {...}}

        ok         — 기대 digest 가 모두 설정돼 있고 전부 일치
        mismatch   — 하나라도 다르다 (같은 태그로 가중치가 바뀌었다)
        unverified — 기대 digest 가 비어 있다 (대조하지 않았다)
        error      — 조회 자체가 안 된다
    """
    nodes: dict[str, Any] = {}
    for node, url, model, expected in _targets():
        entry: dict[str, Any] = {
            "model": model,
            "expected_digest": _normalize(expected) or None,
            "actual_digest": None,
            "status": "unknown",
        }
        try:
            tags = _fetch_tags(url, timeout)
        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = f"{type(exc).__name__}: {exc}"[:160]
            nodes[node] = entry
            continue

        actual = next(
            (m.get("digest") for m in tags if m.get("name") == model), None
        )
        if actual is None:
            entry["status"] = "model_absent"
            entry["available"] = sorted(m.get("name", "?") for m in tags)[:12]
        else:
            entry["actual_digest"] = _normalize(actual)[:20]
            if not expected:
                entry["status"] = "unverified"
            elif _digest_matches(expected, actual):
                entry["status"] = "ok"
            else:
                entry["status"] = "mismatch"

        nodes[node] = entry

    statuses = {e["status"] for e in nodes.values()}
    if "mismatch" in statuses or "model_absent" in statuses:
        status = "mismatch"
    elif statuses <= {"ok"}:
        status = "ok"
    elif "error" in statuses and not (statuses - {"error"}):
        status = "error"
    else:
        # 미설정을 ok 로 덮지 않는다
        status = "unverified"

    return {"status": status, "nodes": nodes}


def suggest_env_lines(timeout: float = 5.0) -> list[str]:
    """지금 적재된 digest 로 `.env` 에 넣을 줄을 만든다 (`make model-pin`)."""
    keys = {
        "rtx_5070": "OLLAMA_MODEL_DIGEST",
        "mac_studio": "OLLAMA_MAC_MODEL_DIGEST",
    }
    report = verify_model_pins(timeout=timeout)
    lines = []
    for node, entry in report["nodes"].items():
        digest = entry.get("actual_digest")
        if digest:
            lines.append(f"{keys[node]}={digest}")
        else:
            lines.append(
                f"# {keys[node]}= (조회 실패: {entry.get('status')}"
                f"{' — ' + entry['error'] if entry.get('error') else ''})"
            )
    return lines


if __name__ == "__main__":   # pragma: no cover - 운영 편의용
    import json

    report = verify_model_pins()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n# .env 에 넣을 줄:")
    for line in suggest_env_lines():
        print(line)
