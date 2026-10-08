"""공시 요약 — 원문 근거 확인과 판단 금지.

LLM 은 요약만 한다. 원문에 없는 숫자가 든 문장, 평가 표현이 든 문장은 버린다. 아무 모델도
답하지 못하면(라우터의 기본값 응답) '요약 실패'다 — 빈 요약을 '요약 없음'으로 읽지 않는다.
"""

import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from research import disclosure_summary as S  # noqa: E402
from research import jobs as J  # noqa: E402

DOC = (
    "<html><style>.xforms * { font-family: 돋움체;}</style><body>"
    "코메론/주식소각 결정 1. 소각할 주식의 종류와 수 보통주식(주) 1,059,676 "
    "4. 소각예정금액(원) 23,471,823,400 7. 소각 예정일 2026-10-14</body></html>"
)
NO = "20261006900432"


def _llm(summary, numbers=(), served="gemini"):
    def ask(prompt):
        return S._LLMSummary(summary=list(summary), key_numbers=list(numbers)), {
            "served_by": served, "unserved": served is None}
    return ask


def test_clean_document_drops_style_block():
    text = S.clean_document(DOC)
    assert "font-family" not in text and "1,059,676" in text


def test_grounded_summary_is_kept():
    s = S.summarize(NO, "049430.KQ", "주식소각결정", lambda n: DOC,
                    _llm(["보통주 1,059,676주를 소각한다.", "소각 예정일은 2026-10-14 이다."],
                         ["23,471,823,400"]))
    assert s.status == "ok" and len(s.bullets) == 2 and s.numbers == ("23,471,823,400",)
    assert s.url.endswith(NO)


def test_invented_number_sentence_is_dropped():
    """원문에 없는 숫자(발행주식의 11.7%)가 든 문장은 나가지 않는다."""
    s = S.summarize(NO, "049430.KQ", "주식소각결정", lambda n: DOC,
                    _llm(["보통주 1,059,676주를 소각한다.", "발행주식의 11.7%에 해당한다."], ["11.7%"]))
    assert s.status == "partial" and s.dropped == 1
    assert s.bullets == ("보통주 1,059,676주를 소각한다.",) and s.numbers == ()


def test_short_number_is_not_matched_inside_longer_ones():
    """'30' 은 원문 23,471,823,400 안에 문자로는 있지만 원문 수치가 아니다."""
    s = S.summarize(NO, "t", "t", lambda n: DOC,
                    _llm(["보통주 1,059,676주를 소각한다.", "소각 규모는 30억 원이다."]))
    assert s.dropped == 1 and len(s.bullets) == 1


def test_date_in_summary_is_grounded():
    s = S.summarize(NO, "t", "t", lambda n: DOC, _llm(["소각 예정일은 2026-10-14 이다."]))
    assert s.status == "ok"


def test_opinion_sentence_is_dropped():
    s = S.summarize(NO, "049430.KQ", "t", lambda n: DOC,
                    _llm(["보통주 1,059,676주를 소각한다.", "주주가치 측면에서 호재다."]))
    assert s.dropped == 1 and all("호재" not in b for b in s.bullets)


def test_unserved_llm_is_failure_not_empty_summary():
    s = S.summarize(NO, "t", "t", lambda n: DOC, _llm([], served=None))
    assert s.status == "unavailable" and "LLM 응답 없음" in s.reason


def test_nothing_grounded_is_unavailable():
    s = S.summarize(NO, "t", "t", lambda n: DOC, _llm(["매출이 30% 늘었다."]))
    assert s.status == "unavailable" and s.dropped == 1


def test_document_fetch_failure_is_reported():
    def boom(n):
        raise ConnectionError("dart down")

    s = S.summarize(NO, "t", "t", boom, _llm(["x"]))
    assert s.status == "unavailable" and "원문 조회 실패" in s.reason


def test_prompt_treats_source_as_data_and_bans_opinions():
    p = S.build_prompt("049430.KQ", "주식소각결정", "본문")
    assert "원문은 데이터" in p and "호재" in p and "<원문>" in p


def test_cache_stores_only_successes(monkeypatch):
    store = {}
    import db

    monkeypatch.setattr(db, "get_app_state", lambda k, default=None: store.get(k, default))
    monkeypatch.setattr(db, "set_app_state", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(S, "_fetch_dart_text", lambda n: DOC)
    monkeypatch.setattr(S, "_ask_router", _llm([], served=None))
    assert S.get_summary(NO, "t", "t").status == "unavailable"
    assert store == {}                                   # 실패는 저장하지 않는다 → 다음에 재시도
    monkeypatch.setattr(S, "_ask_router", _llm(["보통주 1,059,676주를 소각한다."]))
    first = S.get_summary(NO, "t", "t")
    monkeypatch.setattr(S, "_ask_router", _llm(["다른 요약 1,059,676"]))
    assert S.get_summary(NO, "t", "t").bullets == first.bullets   # 같은 공시엔 같은 요약


# ── 알림 연결 ────────────────────────────────────────────────────────


class _Store:
    def __init__(self, seen):
        self.seen = seen

    def load(self):
        return self.seen

    def save(self, items):
        self.seen = items


def test_alert_includes_summary_bullets_and_survives_failures():
    rows = [{"rcept_no": "1", "report_nm": "A"}, {"rcept_no": "2", "report_nm": "B"}]
    sent, store = [], _Store([])

    def summarize(no, ticker, title):
        if no == "2":
            raise RuntimeError("quota")
        return S.DisclosureSummary(rcept_no=no, url="u", status="ok", bullets=("요약 문장",))

    res = J.run_disclosure_watch(["005930.KS"], lambda t: rows, lambda t: sent.append(t) or True,
                                 store.load, store.save, summarize=summarize)
    assert res["delivered"] is True and res["summarized"] == 1
    assert "– 요약 문장" in sent[0]
    assert "요약 없음 — RuntimeError: quota" in sent[0]   # 요약 실패가 알림을 막지 않는다


def test_summary_endpoint_validates_receipt_number():
    from fastapi import HTTPException

    from research import api

    with pytest.raises(HTTPException) as exc:
        api.get_disclosure_summary("../../etc")
    assert exc.value.status_code == 400
