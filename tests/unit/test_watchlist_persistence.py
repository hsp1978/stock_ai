"""워치리스트 저장 검증 테스트.

2026-08-03: 삭제가 UI에서는 된 듯 보이는데 새로고침하면 종목이 되살아났다.
사용자 액션 로그에는 remove가 남았지만 watchlist.txt mtime은 그보다 이전 —
쓰기가 파일에 닿지 않았는데 성공으로 보고된 것이다. 저장 후 되읽어 검증한다.
"""

import os
import sys

import pytest
import yaml

_ROOT = os.path.join(os.path.dirname(__file__), "../..")
_ANALYZER_DIR = os.path.join(_ROOT, "stock_analyzer")
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _ANALYZER_DIR)


def _load_wl_module(tmp_path, monkeypatch):
    """streamlit 의존 없이 저장 로직만 재현한다 (webui.py는 import가 무겁다)."""
    path = tmp_path / "watchlist.txt"

    header = (
        "# 관심 종목 리스트 (SSOT: WebUI/백엔드/배치 스크립트 공용)\n"
        "# 한 줄에 하나, #은 주석, 빈 줄은 무시됨\n\n"
    )

    def save(tickers, *, sabotage=False):
        expected = sorted({t.strip().upper() for t in tickers if t and t.strip()})
        with open(path, "w", encoding="utf-8") as f:
            f.write(header)
            for t in (expected[:-1] if sabotage and expected else expected):
                f.write(f"{t}\n")
            f.flush()
            os.fsync(f.fileno())
        persisted = sorted(
            line.strip().upper()
            for line in open(path, encoding="utf-8")
            if line.strip() and not line.startswith("#")
        )
        if persisted != expected:
            raise IOError(
                f"워치리스트 저장 검증 실패: 기대 {len(expected)}종목 / 실제 {len(persisted)}종목"
            )
        return expected

    return path, save


def test_save_persists_and_verifies(tmp_path, monkeypatch):
    path, save = _load_wl_module(tmp_path, monkeypatch)
    save(["IONQ", "pltr", "005930.KS"])

    lines = [
        line.strip()
        for line in open(path, encoding="utf-8")
        if line.strip() and not line.startswith("#")
    ]
    assert lines == ["005930.KS", "IONQ", "PLTR"], "정렬·대문자 정규화 실패"


def test_save_raises_when_content_mismatches(tmp_path, monkeypatch):
    """되읽기 검증이 없으면 부분 기록이 성공으로 보고된다."""
    _, save = _load_wl_module(tmp_path, monkeypatch)
    with pytest.raises(IOError, match="저장 검증 실패"):
        save(["IONQ", "PLTR"], sabotage=True)


def test_clear_writes_empty_list(tmp_path, monkeypatch):
    path, save = _load_wl_module(tmp_path, monkeypatch)
    save(["IONQ", "PLTR"])
    save([])

    lines = [
        line.strip()
        for line in open(path, encoding="utf-8")
        if line.strip() and not line.startswith("#")
    ]
    assert lines == []


def test_duplicates_collapsed(tmp_path, monkeypatch):
    path, save = _load_wl_module(tmp_path, monkeypatch)
    assert save(["IONQ", "ionq", " IONQ "]) == ["IONQ"]


# ── compose 마운트 계약 ─────────────────────────────────────────


def _agent_api_volumes():
    with open(os.path.join(_ROOT, "compose.yaml"), encoding="utf-8") as f:
        compose = yaml.safe_load(f)
    return compose["services"]["agent-api"]["volumes"]


def test_agent_api_can_write_watchlist():
    """/watchlist/{add,remove,set}가 쓰는 파일이 ro면 500으로 죽는다."""
    vols = _agent_api_volumes()
    wl = [v for v in vols if v.endswith("/app/stock_analyzer/watchlist.txt")]

    assert wl, "watchlist.txt rw 마운트가 없다 — 쓰기 엔드포인트가 동작하지 않는다"
    assert not wl[0].endswith(":ro"), f"watchlist.txt가 read-only로 마운트됨: {wl[0]}"


def test_stock_analyzer_dir_stays_read_only():
    """코드 디렉터리는 ro 유지 — 컨테이너가 소스를 덮어쓰지 못하게 한다."""
    vols = _agent_api_volumes()
    dir_mounts = [v for v in vols if v.endswith("/app/stock_analyzer:ro")]
    assert dir_mounts, "stock_analyzer 디렉터리 ro 마운트가 사라졌다"
