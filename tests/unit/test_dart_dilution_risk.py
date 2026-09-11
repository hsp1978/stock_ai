"""전환사채·유상증자 희석 리스크 — 규모를 보지 않던 문제.

2026-09 사후검증: SKAI 는 시가총액 1,117억 대비 CB 450억(4월) + 30억(7월), 약 43%
규모를 발행하는 동안 스크리너 A등급 1순위였다. 주가는 ₩2,530 → ₩6,160(고점) →
₩2,280~2,560. 급등 → CB 발행 → 희석 → 급락.

시스템은 `"유상증자"` 키워드를 악재 목록에 갖고 있었을 뿐 **규모를 보지 않았다.**

DART 주요사항보고서는 전환 시 발행될 주식수의 비율(`cvisstk_tisstk_vs`)을 직접 주므로
시가총액으로 추정할 필요가 없다. 아래 픽스처는 **실제 DART 응답**(엔투텍 2026-09-11
전환사채권발행결정, 권면총액 100억, 희석 20.51%)에서 가져왔다.
"""

import os
import sys
from unittest.mock import patch

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from dart_client import (  # noqa: E402
    DartUnavailable,
    DilutionEvent,
    fetch_dilution_events,
    score_dilution_events,
)

# 실제 cvbdIsDecsn.json 응답 (일부 필드)
_REAL_CB_ROW = {
    "rcept_no": "20260911000004",
    "corp_cls": "K",
    "corp_code": "01105621",
    "corp_name": "엔투텍",
    "bddd": "2026년 09월 10일",
    "bd_knd": "무기명식 이권부 무보증 사모 전환사채",
    "bd_fta": "10,000,000,000",
    "bdis_mthn": "사모",
    "cv_prc": "1,413",
    "cvisstk_cnt": "7,077,140",
    "cvisstk_tisstk_vs": "20.51",
}

_REAL_RIGHTS_ROW = {
    "rcept_no": "20260815000123",
    "corp_code": "00367695",
    "corp_name": "에이전트AI",
    "ic_mthn": "제3자배정증자",
    "nstk_ostk_cnt": "1,000,000",
    "bfic_tisstk_ostk": "20,000,000",
}


def _fetch(cb_rows=None, rights_rows=None, cb_status="000", rights_status="013"):
    payloads = {
        "cvbdIsDecsn": {"status": cb_status, "list": cb_rows or []},
        "piicDecsn": {"status": rights_status, "list": rights_rows or []},
    }

    def fake_request(url, corp_code, api_key, bgn_de, end_de):
        for name, payload in payloads.items():
            if name in url:
                return payload
        raise AssertionError(f"unexpected url {url}")

    with (
        patch("dart_client._get_dart_api_key", lambda: "k"),
        patch("dart_client.get_corp_code", lambda t: "01105621"),
        patch("dart_client._request_major_report", fake_request),
    ):
        return fetch_dilution_events("486500.KQ", months=6)


# ── 파싱 ──────────────────────────────────────────────────────────


def test_parses_real_cb_response_with_dart_provided_dilution_pct():
    events = _fetch(cb_rows=[_REAL_CB_ROW])

    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "cb" and ev.label == "전환사채"
    assert ev.date == "2026-09-10"                 # bddd '2026년 09월 10일'
    assert ev.amount_krw == 10_000_000_000
    assert ev.new_shares == 7_077_140
    assert ev.dilution_pct == 20.51                # DART 제공값을 그대로 쓴다
    assert ev.private_placement is True            # 사모


def test_rights_offering_dilution_is_computed_from_share_counts():
    events = _fetch(rights_rows=[_REAL_RIGHTS_ROW], rights_status="000")

    ev = events[0]
    assert ev.kind == "rights" and ev.label == "유상증자"
    assert ev.date == "2026-08-15"                 # 접수번호 앞 8자리
    assert ev.dilution_pct == 5.0                  # 1,000,000 / 20,000,000
    assert ev.private_placement is True            # 제3자배정


def test_amended_duplicate_disclosures_are_collapsed():
    """기재정정 공시가 같은 내용으로 중복 접수되는 경우가 많다."""
    events = _fetch(cb_rows=[_REAL_CB_ROW, dict(_REAL_CB_ROW, rcept_no="20260911000005")])
    assert len(events) == 1


def test_missing_counts_stay_none_not_zero():
    """규모 미상을 0%로 읽으면 '희석 없음'이 된다."""
    row = dict(_REAL_RIGHTS_ROW, nstk_ostk_cnt="-", bfic_tisstk_ostk="-")
    ev = _fetch(rights_rows=[row], rights_status="000")[0]
    assert ev.dilution_pct is None and ev.new_shares is None


def test_no_data_status_means_no_issuance():
    assert _fetch(cb_status="013", rights_status="013") == []


def test_all_endpoints_failing_raises_instead_of_reporting_none():
    with pytest.raises(DartUnavailable):
        _fetch(cb_status="020", rights_status="020")


def test_missing_api_key_raises():
    with patch("dart_client._get_dart_api_key", lambda: ""):
        with pytest.raises(DartUnavailable, match="DART_API_KEY"):
            fetch_dilution_events("486500.KQ")


# ── 점수화 ────────────────────────────────────────────────────────


def _event(pct, kind="cb", date="2026-04-21", amount=45_000_000_000, private=True):
    return DilutionEvent(
        kind=kind, date=date, new_shares=1000, dilution_pct=pct,
        amount_krw=amount, private_placement=private, receipt_no="1",
    )


def test_large_dilution_is_critical_risk():
    """SKAI 케이스 — 시총 대비 43% 규모."""
    sig = score_dilution_events([_event(35.0), _event(8.0, date="2026-07-22")])

    assert sig.signal == "sell" and sig.score == -4
    assert sig.total_dilution_pct == 43.0
    assert sig.critical_risks and "43.0%" in sig.critical_risks[0]
    assert "사모" in sig.detail


def test_moderate_dilution_warns_without_blocking():
    sig = score_dilution_events([_event(6.0)])

    assert sig.signal == "sell" and sig.score == -2
    assert sig.critical_risks == [] and sig.warnings


def test_small_dilution_is_recorded_only():
    sig = score_dilution_events([_event(1.2)])

    assert sig.signal == "neutral" and sig.score == 0
    assert sig.total_dilution_pct == 1.2


def test_unknown_scale_is_surfaced_not_silently_zero():
    sig = score_dilution_events([_event(None)])

    assert sig.signal == "neutral"
    assert "규모 미상" in sig.detail
    assert any("수동 확인" in w for w in sig.warnings)


def test_no_events_says_so():
    sig = score_dilution_events([])
    assert sig.signal == "neutral" and "없음" in sig.detail


# ── 도구 연동 ─────────────────────────────────────────────────────


def _tools_with_prices(prices):
    import pandas as pd

    from analysis_tools import AnalysisTools

    tools = AnalysisTools.__new__(AnalysisTools)
    tools.ticker = "486500.KQ"
    tools.df = pd.DataFrame({"Close": prices})
    tools.close = tools.df["Close"]
    return tools


def test_tool_merges_dilution_and_flips_signal_negative():
    tools = _tools_with_prices([1000.0] * 30)
    result = {"signal": "buy", "score": 2, "detail": "공시 3건"}

    with (
        patch("dart_client.fetch_dilution_events", lambda t, months=6: [_event(35.0)]),
        patch("dart_client.score_dilution_events", score_dilution_events),
    ):
        tools._merge_dilution_into(result)

    assert result["dilution_pct"] == 35.0
    assert result["signal"] == "sell"          # 2 + (-4) = -2 → 매도
    assert result["score"] == -2
    assert result["critical_risks"]
    assert result["dilution_events"][0]["private_placement"] is True


def test_tool_flags_capital_raise_right_after_a_spike():
    """급등 직후 조달 = 고점 자금조달 패턴 (SKAI 주가 경로)."""
    prices = [2500.0] * 9 + [6000.0] * 13      # 1개월 전 대비 +140%
    tools = _tools_with_prices(prices)
    result = {"signal": "neutral", "score": 0, "detail": ""}

    with (
        patch("dart_client.fetch_dilution_events", lambda t, months=6: [_event(3.0)]),
        patch("dart_client.score_dilution_events", score_dilution_events),
    ):
        tools._merge_dilution_into(result)

    assert any("고점 자금조달" in w for w in result["warnings"])


def test_tool_reports_unavailable_instead_of_no_dilution():
    tools = _tools_with_prices([1000.0] * 30)
    result = {"signal": "neutral", "score": 0, "detail": ""}

    def _raise(ticker, months=6):
        raise DartUnavailable("DART_API_KEY 미설정")

    with patch("dart_client.fetch_dilution_events", _raise):
        tools._merge_dilution_into(result)

    assert "희석 조회 불가" in result["dilution_unavailable"]
    assert "dilution_pct" not in result       # 0% 로 적지 않는다


# ── 판정 게이트 연동 ──────────────────────────────────────────────


def test_dilution_critical_risk_blocks_buy_signal():
    # append — insert(0) 하면 chart_agent_service 보다 앞서서 동명 모듈 해석이 뒤바뀐다
    sys.path.append(os.path.join(os.path.dirname(__file__), "../../stock_analyzer"))
    from enhanced_decision_maker import EnhancedDecisionMaker

    class _Result:
        error = None
        evidence = [{
            "tool": "dart_disclosure_analysis",
            "result": {"critical_risks": ["희석 리스크 43.0% — 전환사채 2026-04-21 35.0%(사모)"]},
        }]

    dm = EnhancedDecisionMaker()
    blocks = dm._collect_tool_hard_blocks([_Result()])
    assert blocks and "43.0%" in blocks[0]

    decision = dm._apply_valuation_gate(
        {"signal": "buy", "confidence": 8.0, "conflicts": "없음",
         "risks": ["특별한 리스크 없음"]},
        {"critical_risks": blocks},
    )
    assert decision["signal"] == "neutral"
    assert decision["execution_ready"] is False
    assert any("희석" in r for r in decision["risks"])
