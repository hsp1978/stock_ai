"""pykrx 컬럼 해석 — 한 글자 차이로 32일간 틀린 값을 보고했다.

2026-09-22 감사. 24개 분석 도구 중 어느 것이 실제로 방향을 내는지 세다가
`외국인/공매도 복합 분석` 이 **224 ticker_day 내내 정확히 0점**인 것을 발견했다.
리포트 상세는 이랬다:

    외국인소진율=9048000.0% (stable), 공매도비율=0.0% (stable)

904만 퍼센트다. 원인은 컬럼명 한 글자였다.

    pykrx 실제 컬럼      코드가 찾던 것
    ──────────────────────────────────
    한도소진률           "소진율"        (률 ≠ 율)
    비중                 "비율"

**진짜 결함은 매칭 실패 후의 폴백이다.**

    rate_col = [c for c in df.columns if "소진율" in str(c) or ...]
    if not rate_col:
        rate_col = df.columns.tolist()      # ← 전 컬럼
    current_rate = float(df[rate_col[0]].iloc[-1])   # ← 첫 컬럼 = 상장주식수

공매도 쪽은 빈 리스트가 되어 `current_ratio = 0.0` 을 조용히 썼다 — 비율 0% 는
'공매도가 없다'는 강한 주장인데, 실제로는 컬럼을 못 찾았다는 뜻이었다.

두 경우 모두 하류 규칙이 `neutral, score 0` 으로 떨어져, **고장이 '중립 판단'
으로 보였다** (CLAUDE.md §13 — 장애가 정상으로 보고되는 형태).

실측 (수정 후):

    049430.KQ  외국인 22.55% (9,048,000 아님)   공매도 0.40% (0.0 아님)  score +2
    328130.KQ  외국인  9.56% (74,458,180 아님)  공매도 0.61%            score  0

여기서 고정하는 것:
  1. 실제 컬럼명(`한도소진률`, `비중`)을 집는다
  2. 못 찾으면 **아무거나 고르지 않는다** — available=False
  3. 값이 0~100 밖이면 판단 불가 — 잘못된 컬럼을 값으로 잡는다
  4. 판단 불가를 숫자처럼 적지 않는다
"""

import os
import sys

import pandas as pd
import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.append(_AGENT_DIR)

from data_sources import pykrx_source as ps  # noqa: E402

# pykrx 가 실제로 주는 모양 (2026-09-22 실측)
FOREIGN_COLS = ["상장주식수", "보유수량", "지분율", "한도수량", "한도소진률"]
SHORT_COLS = ["공매도잔고", "상장주식수", "공매도금액", "시가총액", "비중"]


def _foreign_df(rates=(22.4, 22.55)):
    return pd.DataFrame(
        {"상장주식수": [9048000.0] * len(rates), "보유수량": [2040427.0] * len(rates),
         "지분율": list(rates), "한도수량": [9048000.0] * len(rates),
         "한도소진률": list(rates)}
    )[FOREIGN_COLS]


def _short_df(ratios=(0.48, 0.40)):
    return pd.DataFrame(
        {"공매도잔고": [40000.0, 35910.0][: len(ratios)],
         "상장주식수": [9048000.0] * len(ratios),
         "공매도금액": [9e8] * len(ratios), "시가총액": [2e11] * len(ratios),
         "비중": list(ratios)}
    )[SHORT_COLS]


def _patch(monkeypatch, foreign=None, short=None):
    class _Stock:
        @staticmethod
        def get_exhaustion_rates_of_foreign_investment_by_date(s, e, code):
            if isinstance(foreign, Exception):
                raise foreign
            return foreign

        @staticmethod
        def get_shorting_balance_by_date(s, e, code):
            if isinstance(short, Exception):
                raise short
            return short

    mod = type(sys)("pykrx")
    mod.stock = _Stock()
    monkeypatch.setitem(sys.modules, "pykrx", mod)


# ── 컬럼 선택 ─────────────────────────────────────────────────────


def test_picks_the_real_exhaustion_column_not_the_share_count(monkeypatch):
    """이게 32일간 틀렸던 것 — 상장주식수를 퍼센트로 읽었다."""
    _patch(monkeypatch, foreign=_foreign_df())

    r = ps.PykrxSource.get_foreign_holding_info("049430.KQ")

    assert r["available"] is True
    assert r["exhaustion_rate"] == pytest.approx(22.55)
    assert r["exhaustion_rate"] != 9048000.0


def test_picks_비중_for_the_short_ratio(monkeypatch):
    """컬럼은 `비중` 이다 — `비율` 을 찾으면 못 만난다."""
    _patch(monkeypatch, short=_short_df())

    r = ps.PykrxSource.get_short_selling_info("049430.KQ")

    assert r["available"] is True
    assert r["short_ratio"] == pytest.approx(0.40)
    assert r["short_balance"] == 35910


def test_unknown_columns_do_not_fall_back_to_the_first_one(monkeypatch):
    """pykrx 가 이름을 또 바꾸면 **판단 불가**여야 한다 — 아무 값이나 쓰지 않는다."""
    df = pd.DataFrame({"뭔가": [1.0, 2.0], "다른것": [9048000.0, 9048000.0]})
    _patch(monkeypatch, foreign=df)

    r = ps.PykrxSource.get_foreign_holding_info("049430.KQ")

    assert r["available"] is False
    assert r["reason"] == "rate_column_not_found"
    assert r["exhaustion_rate"] is None
    assert "뭔가" in r["columns"]


def test_missing_short_ratio_column_is_not_reported_as_zero_percent(monkeypatch):
    """0% 는 '공매도 없음'이라는 주장이다 — 못 찾은 것과 다르다."""
    df = pd.DataFrame({"공매도잔고": [1.0], "엉뚱": [2.0]})
    _patch(monkeypatch, short=df)

    r = ps.PykrxSource.get_short_selling_info("049430.KQ")

    assert r["available"] is False
    assert r["short_ratio"] is None
    assert r["short_ratio"] != 0.0


# ── 범위 검사 ─────────────────────────────────────────────────────


def test_out_of_range_rate_is_rejected(monkeypatch):
    """퍼센트가 0~100 밖이면 컬럼을 잘못 잡은 것이다. 이 검사 하나면 잡혔다."""
    df = _foreign_df()
    df["한도소진률"] = [9048000.0, 9048000.0]
    _patch(monkeypatch, foreign=df)

    r = ps.PykrxSource.get_foreign_holding_info("049430.KQ")

    assert r["available"] is False
    assert r["reason"] == "rate_out_of_range"
    assert r["raw_value"] == 9048000.0
    assert r["exhaustion_rate"] is None


def test_out_of_range_short_ratio_is_rejected(monkeypatch):
    df = _short_df()
    df["비중"] = [74458180.0, 74458180.0]
    _patch(monkeypatch, short=df)

    r = ps.PykrxSource.get_short_selling_info("049430.KQ")

    assert r["available"] is False
    assert r["reason"] == "ratio_out_of_range"


def test_zero_percent_is_a_legitimate_value(monkeypatch):
    """경계를 과하게 막지 말 것 — 0% 와 100% 는 실제로 가능하다."""
    _patch(monkeypatch, short=_short_df(ratios=(0.0, 0.0)))
    assert ps.PykrxSource.get_short_selling_info("049430.KQ")["available"] is True

    df = _foreign_df()
    df["한도소진률"] = [100.0, 100.0]
    _patch(monkeypatch, foreign=df)
    assert ps.PykrxSource.get_foreign_holding_info("005930.KS")["available"] is True


# ── 실패를 값처럼 적지 않는다 ─────────────────────────────────────


def test_unavailable_is_not_written_as_a_number(monkeypatch):
    """`외국인소진율=9048000.0% (stable)` 같은 문장을 다시 만들지 않는다."""
    import analysis_tools as at

    monkeypatch.setattr(ps.PykrxSource, "get_foreign_holding_info",
                        staticmethod(lambda t, days=5: {
                            "exhaustion_rate": None, "signal": "neutral", "score": 0,
                            "available": False, "reason": "rate_column_not_found"}))
    monkeypatch.setattr(ps.PykrxSource, "get_short_selling_info",
                        staticmethod(lambda t, days=5: {
                            "short_ratio": 0.4, "trend": "decreasing", "signal": "buy",
                            "score": 2, "available": True}))

    agent = at.AnalysisTools.__new__(at.AnalysisTools)
    agent.ticker = "049430.KQ"
    r = at.AnalysisTools.institutional_flow_analysis(agent)

    assert "판단불가" in r["detail"]
    assert "rate_column_not_found" in r["detail"]
    assert r["data_unavailable"] == ["외국인"]
    # 살아 있는 쪽은 그대로 숫자로 적는다
    assert "0.4%" in r["detail"]


def test_both_available_reads_as_plain_numbers(monkeypatch):
    import analysis_tools as at

    monkeypatch.setattr(ps.PykrxSource, "get_foreign_holding_info",
                        staticmethod(lambda t, days=5: {
                            "exhaustion_rate": 22.55, "trend": "increasing",
                            "signal": "neutral", "score": 0, "available": True}))
    monkeypatch.setattr(ps.PykrxSource, "get_short_selling_info",
                        staticmethod(lambda t, days=5: {
                            "short_ratio": 0.4, "trend": "decreasing", "signal": "buy",
                            "score": 2, "available": True}))

    agent = at.AnalysisTools.__new__(at.AnalysisTools)
    agent.ticker = "049430.KQ"
    r = at.AnalysisTools.institutional_flow_analysis(agent)

    assert r["data_unavailable"] == []
    assert "22.55%" in r["detail"] and "0.4%" in r["detail"]
    assert "판단불가" not in r["detail"]
    assert r["score"] == 2          # 죽어 있던 도구가 실제 점수를 낸다


# ── 헬퍼 자체 ─────────────────────────────────────────────────────


def test_pick_column_refuses_when_several_partial_matches(monkeypatch):
    """둘 이상 걸리면 어느 것인지 모른다 — 고르지 않는다."""
    df = pd.DataFrame({"공매도비중": [1.0], "기타비중": [2.0]})

    assert ps._pick_column(df, ("비중",), "테스트") is None


def test_pick_column_prefers_exact_match_over_partial():
    df = pd.DataFrame({"비중": [1.0], "공매도비중": [2.0]})

    assert ps._pick_column(df, ("비중",), "테스트") == "비중"
