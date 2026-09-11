"""DART 임원·주요주주 소유상황보고(elestock) 연동.

2026-09 사후검증에서 이 데이터의 부재가 실손실로 확인됐다. 유엔젤(072130) 안갑대
이사가 2026-04-01 공시로 보유 12,002주를 **전량** 매도해 잔량 0주가 됐고, 당시
Event Analyst 는 "내부자 거래 데이터도 없어 파악 불가"로 답했다. 그 시점 ~₩6,000대
주가는 2026-09-10 ₩3,510 (약 -42%).

아래 픽스처는 **실제 DART 응답**(2026-09-11 조회)이다.

여기서 고정하는 것:
  1. 잔량 0(전량 이탈)은 부분 매도와 다른 사건으로 취급한다
  2. 콤마 포함 문자열·'-' 결측을 정확히 파싱한다
  3. 조회 불가(DartUnavailable)를 '변동 없음'으로 적지 않는다 — #17 과 같은 함정
  4. 6개월 창 밖 보고는 제외한다
"""

import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from dart_client import (  # noqa: E402
    DartUnavailable,
    InsiderTrade,
    fetch_insider_trades,
    score_insider_trades,
)


def _row(rcept_dt, repror, ofcps, cnt, irds, rate="0.00", major="-"):
    return {
        "rcept_no": "20260401000001",
        "rcept_dt": rcept_dt,
        "corp_code": "00416654",
        "corp_name": "유엔젤",
        "repror": repror,
        "isu_exctv_rgist_at": "등기임원",
        "isu_exctv_ofcps": ofcps,
        "isu_main_shrholdr": major,
        "sp_stock_lmp_cnt": cnt,
        "sp_stock_lmp_irds_cnt": irds,
        "sp_stock_lmp_rate": rate,
        "sp_stock_lmp_irds_rate": "0.07",
    }


def _payload(rows, status="000"):
    return {"status": status, "message": "정상", "list": rows}


def _recent(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _fetch(payload, ticker="072130.KQ", months=6):
    with (
        patch("dart_client._get_dart_api_key", lambda: "test-key"),
        patch("dart_client.get_corp_code", lambda t: "00416654"),
        patch("dart_client._request_elestock", lambda corp, key: payload),
    ):
        return fetch_insider_trades(ticker, months=months)


# ── 파싱 ──────────────────────────────────────────────────────────


def test_parses_real_dart_response_including_full_exit():
    """실제 유엔젤 응답 형태 — 잔량 0 / 증감 -12,002."""
    rows = [
        _row(_recent(150), "차문호", "상무이사", "149,687", "6,000", "1.16"),
        _row(_recent(20), "안갑대", "이사", "0", "-12,002", "0.00"),
    ]
    trades = _fetch(_payload(rows))

    assert len(trades) == 2
    latest = trades[0]                       # 최신순 정렬
    assert latest.reporter == "안갑대"
    assert latest.shares_after == 0
    assert latest.shares_delta == -12002     # 콤마·음수 파싱
    assert latest.is_full_exit is True
    assert trades[1].is_full_exit is False   # 매수 건


def test_missing_values_and_dash_are_none_not_zero():
    """'-' 를 0으로 읽으면 '잔량 0(전량 이탈)'로 오판한다."""
    rows = [_row(_recent(10), "최용욱", "상무이사", "-", "-", "-")]
    trades = _fetch(_payload(rows))

    assert trades[0].shares_after is None
    assert trades[0].shares_delta is None
    assert trades[0].ownership_pct is None
    assert trades[0].is_full_exit is False   # 결측은 전량 이탈이 아니다


def test_window_filter_excludes_old_reports():
    rows = [
        _row(_recent(400), "옛보고", "이사", "0", "-1,000"),
        _row(_recent(30), "최근보고", "이사", "100", "-50"),
    ]
    trades = _fetch(_payload(rows), months=6)

    assert [t.reporter for t in trades] == ["최근보고"]


def test_major_holder_flag_and_no_data_status():
    rows = [_row(_recent(5), "최대주주", "-", "1,000", "500", major="최대주주")]
    assert _fetch(_payload(rows))[0].is_major_holder is True
    # status 013 = 조회된 데이터 없음 → 빈 리스트(정상)
    assert _fetch(_payload([], status="013")) == []


# ── 조회 불가 vs 변동 없음 ────────────────────────────────────────


def test_missing_api_key_raises_instead_of_returning_empty():
    with patch("dart_client._get_dart_api_key", lambda: ""):
        with pytest.raises(DartUnavailable, match="DART_API_KEY"):
            fetch_insider_trades("072130.KQ")


def test_corp_code_failure_raises():
    with (
        patch("dart_client._get_dart_api_key", lambda: "k"),
        patch("dart_client.get_corp_code", lambda t: None),
    ):
        with pytest.raises(DartUnavailable, match="고유번호"):
            fetch_insider_trades("072130.KQ")


def test_api_error_status_raises_with_reason():
    with pytest.raises(DartUnavailable, match="status=020"):
        _fetch({"status": "020", "message": "사용한도 초과", "list": []})


# ── 점수화 ────────────────────────────────────────────────────────


def _trade(delta, after, reporter="안갑대", position="이사", day="2026-04-01"):
    return InsiderTrade(
        report_date=day, reporter=reporter, position=position,
        registered="등기임원", is_major_holder=False,
        shares_after=after, shares_delta=delta, ownership_pct=0.0,
        receipt_no="1",
    )


def test_full_exit_is_strong_sell_with_critical_risk():
    """유엔젤 케이스 — 이게 -42% 의 선행 지표였다."""
    sig = score_insider_trades([_trade(-12002, 0)])

    assert sig.signal == "strong_sell"
    assert sig.score == -5
    assert "잔량 0주" in sig.detail and "안갑대" in sig.detail
    assert sig.critical_risks and "전량 매도" in sig.critical_risks[0]
    # 이탈이 기간 매도의 100%이고 순매도라는 근거가 detail 에 실린다
    assert "100%" in sig.detail and "순매도" in sig.detail


def test_large_cap_single_exit_amid_net_buying_is_not_a_sell_signal():
    """실측 회귀 — 삼성전자(005930) 6개월 보고 837건, 순매수 +939,336주인데
    임원 1명이 937주(매도의 2.3%)를 비운 것이 전량 이탈로 잡힌다. 이를 최대 강도
    매도로 읽으면 대형주에서 오탐이 쏟아진다 (2026-09-11 실측에서 발견).
    """
    trades = [_trade(-937, 0, reporter="Lee Sungki", position="상무")]
    trades += [_trade(1000, 5000, reporter=f"임원{i}") for i in range(20)]

    sig = score_insider_trades(trades)

    assert sig.signal == "neutral" and sig.score == 0
    assert sig.critical_risks == []          # 핵심 리스크로 승격하지 않는다
    assert sig.full_exits                    # 다만 사실은 리포트에 남는다
    assert "퇴임성" in sig.detail


def test_exit_with_net_selling_but_small_weight_is_moderate_sell():
    """순매도지만 이탈이 매도의 절반 미만이면 중간 강도."""
    trades = [
        _trade(-100, 0, reporter="소액이탈"),
        _trade(-9000, 1000, reporter="대량매도"),
        _trade(500, 2000, reporter="소액매수"),
    ]
    sig = score_insider_trades(trades)

    assert sig.signal == "sell" and sig.score == -3
    assert sig.critical_risks == []
    assert "전량 이탈 1건 포함" in sig.detail


def test_net_sell_and_net_buy_scale_with_dominance():
    heavy_sell = score_insider_trades([_trade(-9000, 1000), _trade(500, 2000)])
    assert heavy_sell.signal == "sell" and heavy_sell.score == -3

    mild_sell = score_insider_trades([_trade(-1100, 1000), _trade(1000, 2000)])
    assert mild_sell.signal == "sell" and mild_sell.score == -1

    heavy_buy = score_insider_trades([_trade(9000, 9000), _trade(-500, 100)])
    assert heavy_buy.signal == "buy" and heavy_buy.score == 3


def test_no_reports_is_neutral_but_says_so():
    sig = score_insider_trades([])
    assert sig.signal == "neutral" and sig.score == 0
    assert "보고 없음" in sig.detail


# ── 도구 연동 ─────────────────────────────────────────────────────


def _agent_for(ticker):
    """AnalysisTools 인스턴스를 __init__ 없이 만든다 (OHLCV 불필요)."""
    from analysis_tools import AnalysisTools

    tools = AnalysisTools.__new__(AnalysisTools)
    tools.ticker = ticker
    return tools


def test_tool_uses_dart_for_korean_tickers():
    tools = _agent_for("072130.KQ")
    with (
        patch("dart_client._get_dart_api_key", lambda: "k"),
        patch("dart_client.get_corp_code", lambda t: "00416654"),
        patch(
            "dart_client._request_elestock",
            lambda corp, key: _payload([_row(_recent(10), "안갑대", "이사", "0", "-12,002")]),
        ),
    ):
        out = tools._insider_trading_from_dart()

    assert out["data_source"] == "dart_elestock"
    assert out["signal"] == "sell"          # strong_sell → 도구 신호 어휘로 정규화
    assert out["score"] == -5
    assert out["critical_risks"]
    assert out["recent_trades"][0]["shares_after"] == 0


def test_tool_reports_unavailable_instead_of_no_activity():
    """조회 불가를 '변동 없음'으로 적으면 장애가 정상으로 위장된다."""
    tools = _agent_for("072130.KQ")
    with patch("dart_client._get_dart_api_key", lambda: ""):
        out = tools._insider_trading_from_dart()

    assert out["data_source"] == "unavailable"
    assert "미확인" in out["detail"]
    assert out["score"] == 0
    assert "없음" not in out["detail"].replace("미확인", "")


def test_decision_maker_promotes_full_exit_to_critical_risk():
    # append — insert(0) 하면 chart_agent_service 보다 앞서서 동명 모듈 해석이 뒤바뀐다
    sys.path.append(os.path.join(os.path.dirname(__file__), "../../stock_analyzer"))
    from enhanced_decision_maker import EnhancedDecisionMaker

    class _Result:
        error = None
        evidence = [{
            "tool": "insider_trading_analysis",
            "result": {
                "data_source": "dart_elestock",
                "critical_risks": ["내부자 전량 매도(잔량 0주): 안갑대(이사) 2026-04-01"],
            },
        }]

    risks = EnhancedDecisionMaker()._collect_agent_risks([_Result()])
    assert any("전량 매도" in r for r in risks)


def test_decision_maker_surfaces_unavailable_insider_data():
    # append — insert(0) 하면 chart_agent_service 보다 앞서서 동명 모듈 해석이 뒤바뀐다
    sys.path.append(os.path.join(os.path.dirname(__file__), "../../stock_analyzer"))
    from enhanced_decision_maker import EnhancedDecisionMaker

    class _Result:
        error = None
        evidence = [{
            "tool": "insider_trading_analysis",
            "result": {"data_source": "unavailable", "detail": "DART 조회 불가"},
        }]

    risks = EnhancedDecisionMaker()._collect_agent_risks([_Result()])
    assert any("미확인" in r for r in risks)
