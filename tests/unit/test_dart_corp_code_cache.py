"""DART corpCode 캐시 — 경합과 손상을 견딘다.

`#61` 로 로깅을 켜자 나온 두 번째 줄:

    WARNING [dart_client] get_corp_code(049430.KQ) 실패: pickle data was truncated

원인은 OpenDartReader 생성자다:

    if not os.path.exists(fn_cache):
        df = dart_list.corp_codes(api_key)
        df.to_pickle(fn_cache)      # 8.5MB 를 최종 경로에 직접 쓴다
    self.corp_codes = pd.read_pickle(fn_cache)

`to_pickle` 이 도는 동안 파일은 **이미 존재한다.** 병렬 스캔(워커 3)에서 다른
스레드가 `os.path.exists` 를 True 로 보고 반쯤 쓰인 파일을 읽는다. 더 나쁜 건
잘린 파일이 남으면 그날 내내 존재하므로 **하루 종일 DART 조회가 죽는다**는 점이다.

여기서 고정하는 것:
  1. 캐시 생성은 임시 파일 + `os.replace` — 반쯤 쓰인 파일이 보이는 순간이 없다
  2. 손상된 캐시는 지우고 다시 만든다 (그날 내내 실패 반복 금지)
  3. 스냅샷은 하루 한 번만 읽는다 (119,183행 × 매 호출 파싱 금지)
  4. 동시 호출이 겹쳐도 생성은 한 번
"""

import os
import sys
import threading

import pandas as pd
import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import dart_client as dc  # noqa: E402


def _frame():
    return pd.DataFrame({
        "corp_code": ["00126380", "00152783"],
        "corp_name": ["삼성전자", "코스메카코리아"],
        "stock_code": ["005930", "049430"],
    })


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dc, "_CORP_CACHE_DIR", "docs_cache")
    monkeypatch.setattr(dc, "_get_dart_api_key", lambda: "k" * 40)
    dc.reset_corp_frame_cache()
    yield tmp_path
    dc.reset_corp_frame_cache()


def _patch_build(monkeypatch, counter: list, frame=None, delay=0.0):
    import time

    def fake_corp_codes(api_key):
        counter.append(api_key)
        if delay:
            time.sleep(delay)
        return frame if frame is not None else _frame()

    # 매 호출 새 스텁이 필요하지 않다 — 생성은 하루 1회라 재사용해도 된다

    monkeypatch.setitem(
        sys.modules, "OpenDartReader.dart_list",
        type(sys)("OpenDartReader.dart_list"),
    )
    sys.modules["OpenDartReader.dart_list"].corp_codes = fake_corp_codes
    monkeypatch.setattr(dc, "_build_corp_cache", dc._build_corp_cache)  # 원본 유지


# ── 원자적 생성 ───────────────────────────────────────────────────


class _StubFrame:
    """`_build_corp_cache` 가 프레임에 요구하는 것은 `to_pickle` 과 `len` 뿐이다.

    DataFrame 을 서브클래싱하면 로컬 클래스라 pickle 이 안 된다 — 관찰만 하면
    되므로 최소 스텁을 쓴다.
    """

    def __init__(self, on_write=None, fail: bool = False):
        self._frame = _frame()
        self._on_write = on_write
        self._fail = fail

    def __len__(self):
        return len(self._frame)

    def to_pickle(self, path, **kw):
        if self._on_write is not None:
            self._on_write(path)
        if self._fail:
            raise OSError("disk full")
        return self._frame.to_pickle(path, **kw)


def test_cache_is_written_atomically(cache_dir, monkeypatch):
    """쓰는 도중의 파일이 다른 스레드에 보이면 안 된다."""
    target = dc._corp_cache_path("20260914")
    observed = []

    def on_write(path):
        observed.append((target.exists(), str(path) != str(target)))

    calls = []
    _patch_build(monkeypatch, calls, frame=_StubFrame(on_write=on_write))

    dc._build_corp_cache("k" * 40, target)

    assert observed == [(False, True)], "최종 경로에 직접 쓰고 있다"
    assert target.exists() and len(pd.read_pickle(target)) == 2


def test_temp_file_is_cleaned_up_on_failure(cache_dir, monkeypatch):
    target = dc._corp_cache_path("20260914")
    calls = []
    _patch_build(monkeypatch, calls, frame=_StubFrame(fail=True))
    target.parent.mkdir(parents=True, exist_ok=True)

    with pytest.raises(OSError):
        dc._build_corp_cache("k" * 40, target)

    assert not target.exists()
    assert list(target.parent.glob("*.tmp")) == []      # 임시 파일이 남지 않는다


# ── 손상 복구 ─────────────────────────────────────────────────────


def test_truncated_cache_is_rebuilt(cache_dir, monkeypatch):
    """잘린 파일을 그대로 두면 그날 내내 DART 가 죽는다."""
    calls = []
    _patch_build(monkeypatch, calls)

    from datetime import datetime

    day = datetime.today().strftime("%Y%m%d")
    path = dc._corp_cache_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    _frame().to_pickle(path)
    truncated = path.read_bytes()[:40]
    path.write_bytes(truncated)                        # 반쯤 쓰인 상태 재현

    frame = dc._load_corp_frame("k" * 40)

    assert len(frame) == 2
    assert len(calls) == 1, "손상 캐시를 재생성하지 않았다"
    assert len(pd.read_pickle(path)) == 2               # 정상 파일로 대체됐다


def test_get_corp_code_recovers_from_a_corrupt_cache(cache_dir, monkeypatch):
    calls = []
    _patch_build(monkeypatch, calls)

    from datetime import datetime

    path = dc._corp_cache_path(datetime.today().strftime("%Y%m%d"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x80\x05broken")

    assert dc.get_corp_code("005930.KS") == "00126380"


# ── 하루 한 번만 ──────────────────────────────────────────────────


def test_snapshot_is_parsed_once_per_day(cache_dir, monkeypatch):
    """119,183행 스냅샷을 호출마다 파싱하던 것을 멈춘다."""
    calls = []
    _patch_build(monkeypatch, calls)
    reads = []

    real_read = pd.read_pickle

    def counting_read(path, *a, **k):
        reads.append(str(path))
        return real_read(path, *a, **k)

    monkeypatch.setattr(pd, "read_pickle", counting_read)

    for _ in range(5):
        dc.get_corp_code("005930.KS")

    assert len(calls) == 1              # 생성 1회
    assert len(reads) == 0              # 생성 직후 프레임을 메모리에 들고 있다


def test_concurrent_first_calls_build_once(cache_dir, monkeypatch):
    """병렬 스캔(워커 3)의 첫 호출들이 겹치는 상황."""
    calls = []
    _patch_build(monkeypatch, calls, delay=0.05)
    results = []

    def worker():
        results.append(dc.get_corp_code("049430.KQ"))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1, f"생성이 {len(calls)}회 일어났다 (경합)"
    assert results == ["00152783"] * 5


# ── 조회 ──────────────────────────────────────────────────────────


def test_unknown_ticker_returns_none(cache_dir, monkeypatch):
    calls = []
    _patch_build(monkeypatch, calls)

    assert dc.get_corp_code("999999.KS") is None


def test_missing_api_key_skips_without_building(cache_dir, monkeypatch):
    calls = []
    _patch_build(monkeypatch, calls)
    monkeypatch.setattr(dc, "_get_dart_api_key", lambda: "")

    assert dc.get_corp_code("005930.KS") is None
    assert calls == []


def test_reader_is_constructed_once_and_after_the_cache_exists(cache_dir, monkeypatch):
    """생성자가 스스로 스냅샷을 내려받는 경로를 타면 안 된다."""
    calls = []
    _patch_build(monkeypatch, calls)
    seen = []

    from datetime import datetime

    day = datetime.today().strftime("%Y%m%d")

    class FakeReader:
        def __init__(self, api_key):
            seen.append(dc._corp_cache_path(day).exists())

    # 이 패키지는 sys.modules 항목이 클래스다 (dart_client 주석 참조).
    # 그래도 `from OpenDartReader import dart_list` 가 되게 속성을 달아 준다.
    FakeReader.dart_list = sys.modules["OpenDartReader.dart_list"]
    monkeypatch.setitem(sys.modules, "OpenDartReader", FakeReader)

    dc.get_dart_reader("k" * 40)
    dc.get_dart_reader("k" * 40)

    assert seen == [True], "캐시가 없는 상태에서 리더를 만들었다"
