"""모델 가중치 고정 — digest 대조로 '조용한 교체'를 잡는다.

`docs/SYSTEM_OVERVIEW.md` §13.9-8: "모델 버전 태그 핀 — 태그 고정이나 digest 핀은
아님."

## Ollama 는 digest 로 참조할 수 없다 (2026-09-15 확인)

    POST /api/generate {"model": "sha256:bdbd181c33f2ed1b31c9"}
    → {"error": "model 'sha256:...' not found"}

`/api/show` 도 digest 를 안 준다 (`/api/tags` 만). Docker 식 불변 참조가 불가능하다.
그래서 **고정이 아니라 변경 감지**로 방향을 바꿨다 — 기대 digest 를 설정에 적어 두고
실제 적재본과 대조한다.

## 왜 필요한가

`ollama pull qwen3:14b-q4_K_M` 을 다시 하면 같은 태그로 다른 가중치가 들어올 수 있다.
신호 판단이 바뀌는데 기록이 남지 않는다. 60일 hit-rate 검증은 "같은 로직 + 같은 모델"
을 전제하므로, 모델이 바뀐 구간이 섞이면 그 통계는 무효다.

여기서 고정하는 것:
  1. 기대 digest 미설정은 **`unverified`** 다 — `ok` 가 아니다 (§13-4)
  2. 불일치는 `mismatch` 로 올라간다 (조용히 넘기지 않는다)
  3. 모델이 아예 없으면 `model_absent` — 대조 불가와 구분한다
  4. 접두 비교를 허용하되 12자 미만은 거부한다 (충돌 위험)
  5. `/health` 의 `model_pin` 으로 드러난다
"""

import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import model_pin as mp  # noqa: E402

_RTX = "bdbd181c33f2ed1b31c9aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_MAC = "9f13ba1299afea09d9a9bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _patch(monkeypatch, *, rtx_expected="", mac_expected="",
           rtx_tags=None, mac_tags=None, rtx_exc=None):
    monkeypatch.setattr(mp, "OLLAMA_MODEL", "qwen3:14b-q4_K_M")
    monkeypatch.setattr(mp, "OLLAMA_MAC_MODEL", "qwen2.5:32b-instruct-q4_K_M")
    monkeypatch.setattr(mp, "OLLAMA_MODEL_DIGEST", rtx_expected)
    monkeypatch.setattr(mp, "OLLAMA_MAC_MODEL_DIGEST", mac_expected)
    monkeypatch.setattr(mp, "OLLAMA_BASE_URL", "http://rtx:11434")
    monkeypatch.setattr(mp, "MAC_STUDIO_URL", "http://mac:8080")

    default_rtx = [{"name": "qwen3:14b-q4_K_M", "digest": _RTX}]
    default_mac = [{"name": "qwen2.5:32b-instruct-q4_K_M", "digest": _MAC}]

    def fake(url, timeout):
        if "rtx" in url:
            if rtx_exc:
                raise rtx_exc
            return default_rtx if rtx_tags is None else rtx_tags
        return default_mac if mac_tags is None else mac_tags

    monkeypatch.setattr(mp, "_fetch_tags", fake)


# ── 상태 판정 ─────────────────────────────────────────────────────


def test_unset_expectation_is_unverified_not_ok(monkeypatch):
    """미설정을 ok 로 덮으면 '고정했다'는 착시가 된다."""
    _patch(monkeypatch)

    report = mp.verify_model_pins()

    assert report["status"] == "unverified"
    assert report["nodes"]["rtx_5070"]["status"] == "unverified"
    # 그래도 실제 digest 는 보여줘야 한다 (핀을 채울 수 있게)
    assert report["nodes"]["rtx_5070"]["actual_digest"] == _RTX[:20]


def test_matching_digests_are_ok(monkeypatch):
    _patch(monkeypatch, rtx_expected=_RTX[:20], mac_expected=_MAC[:20])

    report = mp.verify_model_pins()

    assert report["status"] == "ok"
    assert all(n["status"] == "ok" for n in report["nodes"].values())


def test_changed_weights_are_reported_as_mismatch(monkeypatch):
    """같은 태그로 다른 가중치가 들어온 경우 — 이게 잡으려는 상황이다."""
    _patch(monkeypatch, rtx_expected="ffffffffffffffffffff", mac_expected=_MAC[:20])

    report = mp.verify_model_pins()

    assert report["status"] == "mismatch"
    assert report["nodes"]["rtx_5070"]["status"] == "mismatch"
    assert report["nodes"]["mac_studio"]["status"] == "ok"


def test_partial_pinning_is_unverified_overall(monkeypatch):
    """한쪽만 핀했으면 전체를 ok 라고 부를 수 없다."""
    _patch(monkeypatch, rtx_expected=_RTX[:20], mac_expected="")

    assert mp.verify_model_pins()["status"] == "unverified"


def test_absent_model_is_distinguished(monkeypatch):
    """모델이 없는 것과 digest 가 다른 것은 다른 문제다."""
    _patch(monkeypatch, rtx_expected=_RTX[:20], mac_expected=_MAC[:20],
           rtx_tags=[{"name": "llama3.1:8b", "digest": "abc"}])

    report = mp.verify_model_pins()

    assert report["nodes"]["rtx_5070"]["status"] == "model_absent"
    assert "llama3.1:8b" in report["nodes"]["rtx_5070"]["available"]
    assert report["status"] == "mismatch"      # 대조 실패로 올린다


def test_unreachable_node_keeps_the_reason(monkeypatch):
    _patch(monkeypatch, rtx_expected=_RTX[:20], mac_expected=_MAC[:20],
           rtx_exc=ConnectionError("connection refused"))

    entry = mp.verify_model_pins()["nodes"]["rtx_5070"]

    assert entry["status"] == "error"
    assert "refused" in entry["error"]


def test_all_nodes_unreachable_is_error(monkeypatch):
    _patch(monkeypatch, rtx_exc=ConnectionError("down"))
    monkeypatch.setattr(mp, "_fetch_tags",
                        lambda url, timeout: (_ for _ in ()).throw(ConnectionError("down")))

    assert mp.verify_model_pins()["status"] == "error"


# ── digest 정규화 ─────────────────────────────────────────────────


@pytest.mark.parametrize("expected,actual,match", [
    (_RTX[:20], _RTX, True),                      # 접두 비교
    ("sha256:" + _RTX[:20], _RTX, True),          # sha256: 접두 허용
    (_RTX[:20].upper(), _RTX, True),              # 대소문자 무시
    (_RTX, _RTX, True),                           # 전체 일치
    ("bdbd1811", _RTX, False),                    # 12자 미만은 거부
    ("", _RTX, False),
    (_RTX[:20], "", False),
    ("ffffffffffff", _RTX, False),
])
def test_digest_comparison(expected, actual, match):
    assert mp._digest_matches(expected, actual) is match


def test_short_prefix_is_refused_even_if_it_matches():
    """8자 접두는 우연히 맞을 수 있다 — 대조 근거로 쓰지 않는다."""
    assert mp._digest_matches(_RTX[:8], _RTX) is False
    assert mp._digest_matches(_RTX[:12], _RTX) is True


# ── env 제안 ──────────────────────────────────────────────────────


def test_suggest_env_lines_emits_current_digests(monkeypatch):
    _patch(monkeypatch)

    lines = mp.suggest_env_lines()

    assert f"OLLAMA_MODEL_DIGEST={_RTX[:20]}" in lines
    assert f"OLLAMA_MAC_MODEL_DIGEST={_MAC[:20]}" in lines


def test_suggest_env_lines_comments_out_failures(monkeypatch):
    """조회 실패를 빈 값으로 내보내면 '핀 없음'과 구분이 안 된다."""
    _patch(monkeypatch, rtx_exc=TimeoutError("timeout"))

    lines = mp.suggest_env_lines()

    assert any(line.startswith("# OLLAMA_MODEL_DIGEST=") for line in lines)
    assert any("error" in line for line in lines)


# ── /health 노출 ──────────────────────────────────────────────────


def test_health_payload_includes_model_pin():
    import asyncio

    import service

    with service._HEALTH_PROBE_LOCK:
        service._HEALTH_PROBE["model_pin"] = {"status": "ok", "nodes": {}}
    payload = asyncio.run(service.health())

    assert payload["model_pin"]["status"] == "ok"


def test_probe_refresh_collects_model_pin():
    import inspect

    import service

    src = inspect.getsource(service._refresh_health_probe)
    assert "verify_model_pins" in src
    # blocking 조회이므로 워커 스레드로 보내야 한다
    assert "to_thread.run_sync(verify_model_pins)" in src
