"""분석 산출물 보존 정책 — output/ 무한 누적 차단.

2026-09-14 실측: `output/` 에 JSON 70,771개 / **1.58 GB**, 하루 361개(약 7.7 MB)씩
늘고 있었다. 정리 주체가 없었다 — `crontab -l` 은 비어 있고 코드에도 삭제 경로가
없다. CLAUDE.md Don't #7 은 "30일 이상 파일 자동 정리 cron 유지" 라고 적혀 있었지만
**그 cron 은 존재한 적이 없다** (문서가 없는 통제를 있다고 말하던 경우다).

두 산출물의 성격이 다르다:

  JSON (`*_agent_*.json`) — **쓰기 전용이다.** `json_path` 는 문자열로 기록될 뿐
    어떤 코드도 다시 열지 않는다 (2026-09-14 리포지토리 전수 확인). 분석 내용은
    이미 `scan_log` DB 에 들어간다. 보존은 사후 감사용이다.

  PNG (`*.png`) — **화면이 읽는다.** `engine_get_chart_path()` 가 종목별 최신
    차트를 상세 페이지에 띄운다. 오래됐다는 이유로 지우면 화면이 깨진다.

그래서 PNG 는 나이만으로 지우지 않고 **현재 참조 중인 차트를 먼저 제외**한다.

삭제는 되돌릴 수 없다. 여기서 지키는 것:
  1. `OUTPUT_DIR` 바로 아래 **파일만** 본다 (하위 디렉토리·심볼릭 링크 제외)
  2. 정해진 패턴만 지운다 — `*.db*` 는 어떤 경우에도 건드리지 않는다
  3. `dry_run` 으로 무엇이 지워질지 먼저 볼 수 있다
  4. 실패는 세지 않고 **사유와 함께** 보고한다
"""

from __future__ import annotations

import fnmatch
import os
from datetime import datetime, timedelta
from typing import Iterable

from config import (
    OUTPUT_CHART_RETENTION_DAYS,
    OUTPUT_DIR,
    OUTPUT_JSON_RETENTION_DAYS,
)

from logging_setup import get_logger

logger = get_logger("stock_auto.output_retention")

#: 지워도 되는 파일 패턴. 여기에 없으면 건드리지 않는다 (allowlist).
JSON_PATTERNS = ("*_agent_*.json", "*_quant_*.json")
CHART_PATTERNS = ("*.png",)

#: 어떤 규칙에도 걸리면 안 되는 파일. DB 는 운영 데이터다.
PROTECTED_PATTERNS = ("*.db", "*.db-wal", "*.db-shm", "*.sqlite*")


def _matches(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _referenced_charts() -> set[str]:
    """지금 화면이 가리키는 차트 경로. 나이와 무관하게 남긴다.

    `import service` 를 쓰지 않는다 — 서버 밖에서 호출하면 service 모듈을 새로
    적재하면서 부작용(스케줄러·상태 복원)이 따라온다. 이미 적재된 모듈만 본다.
    서버 밖이라 참조 정보가 없으면 **빈 집합이 아니라 DB 에 저장된 요약**을
    읽는다. 참조를 모른 채로 지우면 화면이 깨지기 때문이다.
    """
    import sys

    referenced: set[str] = set()

    def _collect(entries) -> None:
        for entry in (entries or {}).values():
            path = ((entry or {}).get("result") or {}).get("chart_path")
            if path:
                referenced.add(os.path.realpath(str(path)))

    module = sys.modules.get("service")
    if module is not None:
        _collect(getattr(module, "latest_results", {}))
        if referenced:
            return referenced

    try:  # 서버 프로세스 밖 — 영속된 최신 분석 요약에서 복원한다
        import json

        from db import get_app_state

        raw = get_app_state("service.latest_results.summary")
        if raw:
            _collect(json.loads(raw) if isinstance(raw, str) else raw)
    except Exception as exc:
        logger.error(f"[output-retention] 참조 차트 복원 실패 — 차트는 건드리지 않는다: {exc}")
        raise RuntimeError("referenced charts unknown") from exc

    return referenced


def _candidates(now: datetime) -> tuple[list[dict], dict]:
    """(삭제 후보, 현황 통계). 후보 선정 근거를 함께 돌려준다."""
    json_cutoff = now - timedelta(days=OUTPUT_JSON_RETENTION_DAYS)
    chart_cutoff = now - timedelta(days=OUTPUT_CHART_RETENTION_DAYS)
    try:
        referenced = _referenced_charts()
        charts_safe = True
    except RuntimeError:
        # 무엇이 참조 중인지 모르면 차트는 아예 건드리지 않는다.
        referenced, charts_safe = set(), False

    candidates: list[dict] = []
    total_files = 0
    total_bytes = 0
    kept_referenced = 0

    with os.scandir(OUTPUT_DIR) as entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False):
                continue
            name = entry.name
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue

            total_files += 1
            total_bytes += stat.st_size

            if _matches(name, PROTECTED_PATTERNS):
                continue

            modified = datetime.fromtimestamp(stat.st_mtime)
            if _matches(name, JSON_PATTERNS):
                kind, cutoff = "json", json_cutoff
            elif _matches(name, CHART_PATTERNS):
                kind, cutoff = "chart", chart_cutoff
            else:
                continue                      # allowlist 밖은 건드리지 않는다

            if modified >= cutoff:
                continue

            if kind == "chart":
                if not charts_safe:
                    continue                   # 참조 목록 미상 — 차트는 보류
                if os.path.realpath(entry.path) in referenced:
                    kept_referenced += 1       # 화면이 아직 쓴다
                    continue

            candidates.append({
                "path": entry.path,
                "name": name,
                "kind": kind,
                "size": stat.st_size,
                "age_days": round((now - modified).total_seconds() / 86400.0, 1),
            })

    stats = {
        "charts_evaluated": charts_safe,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "kept_referenced_charts": kept_referenced,
    }
    return candidates, stats


def cleanup_outputs(dry_run: bool = False) -> dict:
    """보존 기간이 지난 산출물을 정리한다.

    Args:
        dry_run: True 면 무엇이 지워질지만 계산하고 실제로는 지우지 않는다.
    """
    now = datetime.now()
    candidates, stats = _candidates(now)

    by_kind = {"json": 0, "chart": 0}
    bytes_by_kind = {"json": 0, "chart": 0}
    for row in candidates:
        by_kind[row["kind"]] += 1
        bytes_by_kind[row["kind"]] += row["size"]

    deleted = 0
    freed_bytes = 0
    failures: list[dict] = []

    if not dry_run:
        for row in candidates:
            try:
                os.remove(row["path"])
            except OSError as exc:
                failures.append({
                    "name": row["name"],
                    "error": f"{type(exc).__name__}: {exc}"[:160],
                })
                continue
            deleted += 1
            freed_bytes += row["size"]

    if failures and not deleted:
        status = "error"
    elif failures:
        status = "degraded"
    else:
        status = "completed"

    return {
        "status": status,
        "dry_run": dry_run,
        # dry_run 에서는 '지웠다'가 아니라 '지울 예정'이라고 적는다.
        "candidates": len(candidates),
        "candidate_bytes": sum(row["size"] for row in candidates),
        "deleted": deleted,
        "freed_bytes": freed_bytes,
        "failed": len(failures),
        "failures": failures[:20],
        "by_kind": by_kind,
        "bytes_by_kind": bytes_by_kind,
        "retention_days": {
            "json": OUTPUT_JSON_RETENTION_DAYS,
            "chart": OUTPUT_CHART_RETENTION_DAYS,
        },
        "remaining_files": stats["total_files"] - deleted,
        "remaining_bytes": stats["total_bytes"] - freed_bytes,
        "kept_referenced_charts": stats["kept_referenced_charts"],
        # False 면 참조 목록을 못 읽어 차트를 건너뛴 것이다 — 정상 완료가 아니다
        "charts_evaluated": stats["charts_evaluated"],
        "output_dir": OUTPUT_DIR,
    }
