"""매도 신호 advisory 모드 테스트.

2026-10-07 분석(현재 로직, ticker_day, 14일): 매도 평균 −5.70%·적중 43.3%(블록 63),
시장 +2% 상승 구간 적중 5.1% — 종목 선별력 없이 시장 방향에 건 내기였다. 공매도가
없는 시스템이라 틀린 매도의 비용은 청산 후 놓친 상승이고, 냉각기가 이후 매수 알림까지
막았다. advisory(기본)는 판정·기록은 두고 행동(청산·냉각기)만 막는다.
"""

import os
import sys
from datetime import datetime

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import config  # noqa: E402
import paper_trader  # noqa: E402
import sell_policy  # noqa: E402
import service  # noqa: E402


@pytest.fixture
def advisory(monkeypatch):
    monkeypatch.setattr(sell_policy, "SELL_SIGNAL_MODE", "advisory")


@pytest.fixture
def actionable(monkeypatch):
    monkeypatch.setattr(sell_policy, "SELL_SIGNAL_MODE", "actionable")


@pytest.fixture(autouse=True)
def _isolate_service_state(monkeypatch):
    monkeypatch.setattr(service, "cooling_off_state", {})
    monkeypatch.setattr(service, "latest_results", {})
    monkeypatch.setattr(service, "_persist_cooling_off_state", lambda: None)


def test_default_mode_is_advisory():
    assert config.Settings.model_fields["SELL_SIGNAL_MODE"].default == "advisory"


def _sell_result():
    return {"final_signal": "SELL", "composite_score": -1.0, "confidence": 7.0,
            "tool_details": [], "tool_summaries": [], "signal_distribution": {}}


# ── 페이퍼 청산 ──────────────────────────────────────────────────────


def _with_position(monkeypatch):
    orders = []
    monkeypatch.setattr(paper_trader, "_load_state",
                        lambda: {"positions": {"PLTR": {"qty": 10, "entry_price": 100.0}}})
    monkeypatch.setattr(paper_trader, "execute_paper_order",
                        lambda *a, **k: orders.append(a) or {"status": "filled"})
    return orders


def test_advisory_sell_does_not_liquidate(advisory, monkeypatch):
    orders = _with_position(monkeypatch)
    assert paper_trader.process_agent_signal("PLTR", _sell_result(), 120.0) is None
    assert orders == []


def test_actionable_sell_liquidates(actionable, monkeypatch):
    orders = _with_position(monkeypatch)
    paper_trader.process_agent_signal("PLTR", _sell_result(), 120.0)
    assert orders and orders[0][1] == "SELL" and orders[0][2] == 10


# ── 알림·냉각기 ──────────────────────────────────────────────────────


def test_advisory_sell_alerts_without_cooling_off(advisory):
    alert = service.check_alert_condition("PLTR", _sell_result())
    assert alert is not None and alert["advisory"] is True
    assert "PLTR" not in service.cooling_off_state


def test_advisory_ignores_existing_cooling_off_for_buy(advisory):
    """검증 안 된 매도가 남긴 냉각기가 매수 알림을 막지 않는다."""
    service.cooling_off_state["PLTR"] = {"signal": "SELL", "triggered_at": datetime.now().isoformat()}
    buy = {"final_signal": "BUY", "composite_score": 2.0, "confidence": 7.0}
    assert service.check_alert_condition("PLTR", buy) is not None


def test_actionable_sell_sets_cooling_off_and_blocks_buy(actionable):
    service.check_alert_condition("PLTR", _sell_result())
    assert "PLTR" in service.cooling_off_state
    buy = {"final_signal": "BUY", "composite_score": 2.0, "confidence": 7.0}
    assert service.check_alert_condition("PLTR", buy) is None


# ── 표시 ────────────────────────────────────────────────────────────


def test_advisory_alert_message_label(advisory):
    msg = service.format_alert_message("PLTR", _sell_result())
    assert "리스크 경고(매도·참고용)" in msg
    assert sell_policy.ADVISORY_NOTE in msg


def test_actionable_alert_message_label(actionable):
    msg = service.format_alert_message("PLTR", _sell_result())
    assert "리스크 경고" not in msg
    assert "<b>신호:</b> 매도" in msg


def test_ui_note_matches_policy_note():
    """화면 문구와 정책 문구가 어긋나지 않게 고정한다 (webui 는 agent-api 필드를 따른다)."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../stock_analyzer"))
    from ui.components import SELL_ADVISORY_NOTE

    assert SELL_ADVISORY_NOTE == sell_policy.ADVISORY_NOTE
