"""알림 전송 실패 은폐 방지 테스트.

2026-07-30 진단: TELEGRAM_CHAT_ID 오류로 텔레그램이 400 'chat not found'를
반환하고 있었는데, 전송 함수가 `except Exception: return False`로 사유를 삼키고
호출부가 반환값을 버려서 scan_log에는 '알림 4건 발송'으로 남아 있었다.
실제 도착은 0건. 로그에도 흔적이 없어 언제부터인지 특정할 수 없었다.
"""

import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import service  # noqa: E402
import telegram_bot  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_send_state():
    telegram_bot._SEND_STATE.update(
        last_success_at=None,
        last_failure_at=None,
        last_error=None,
        consecutive_failures=0,
        total_success=0,
        total_failure=0,
    )
    yield


class _Resp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


# ── 전송 실패가 상태에 남는가 ────────────────────────────────────


def test_http_error_recorded_with_reason(monkeypatch):
    """400 응답의 사유가 상태에 남아야 한다 — 조용한 False 금지."""
    monkeypatch.setattr(telegram_bot, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(telegram_bot, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(
        telegram_bot.httpx,
        "post",
        lambda *a, **k: _Resp(400, '{"description":"Bad Request: chat not found"}'),
    )

    assert telegram_bot.send_telegram_html("hi") is False

    snap = telegram_bot.send_state_snapshot()
    assert snap["status"] == "failing"
    assert snap["consecutive_failures"] == 1
    assert "chat not found" in snap["last_error"]


def test_token_never_appears_in_error(monkeypatch):
    """실패 사유에 봇 토큰이 새면 안 된다 (URL에 토큰이 들어 있다)."""
    secret = "1234567890:SUPERSECRETTOKENVALUE"
    monkeypatch.setattr(telegram_bot, "TELEGRAM_BOT_TOKEN", secret)
    monkeypatch.setattr(telegram_bot, "TELEGRAM_CHAT_ID", "123")

    def _boom(*a, **k):
        raise RuntimeError("connection failed")

    monkeypatch.setattr(telegram_bot.httpx, "post", _boom)
    telegram_bot.send_telegram_html("hi")

    assert secret not in (telegram_bot.send_state_snapshot()["last_error"] or "")


def test_success_clears_consecutive_failures(monkeypatch):
    monkeypatch.setattr(telegram_bot, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(telegram_bot, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(telegram_bot.httpx, "post", lambda *a, **k: _Resp(400, "nope"))
    telegram_bot.send_telegram_html("a")
    telegram_bot.send_telegram_html("b")
    assert telegram_bot.send_state_snapshot()["consecutive_failures"] == 2

    monkeypatch.setattr(telegram_bot.httpx, "post", lambda *a, **k: _Resp(200))
    assert telegram_bot.send_telegram_html("c") is True

    snap = telegram_bot.send_state_snapshot()
    assert snap["status"] == "ok"
    assert snap["consecutive_failures"] == 0
    assert snap["total_failure"] == 2


# ── /health가 미발송을 드러내는가 ────────────────────────────────


def test_health_exposes_failing_delivery(monkeypatch):
    monkeypatch.setattr(telegram_bot, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(telegram_bot, "TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr(telegram_bot.httpx, "post", lambda *a, **k: _Resp(400, "chat not found"))
    telegram_bot.send_telegram_html("x")

    status = service._telegram_delivery_status()
    assert status["status"] == "failing"
    assert "chat not found" in status["last_error"]


def test_health_untested_before_any_send():
    """한 번도 안 보냈으면 'ok'가 아니라 'untested' — 미검증을 green으로 덮지 않는다."""
    assert service._telegram_delivery_status()["status"] in ("untested", "unconfigured")


# ── 전송 실패 시 부수효과 ────────────────────────────────────────


def _alert(ticker="IONQ", signal="SELL"):
    return {"ticker": ticker, "signal": signal, "score": -0.5, "confidence": 5.5, "result": {}}


def test_failed_send_returns_false_and_skips_suppression(monkeypatch):
    """전송 실패 시 중복 억제 타임스탬프를 남기면 다음 1시간 알림이 막힌다."""
    monkeypatch.setattr(service, "latest_results", {})
    monkeypatch.setattr(service, "_flush_latest_result_summaries", lambda: None)
    monkeypatch.setattr(service, "_stage_latest_result_summary", lambda t: None)
    monkeypatch.setattr(telegram_bot, "send_daily_digest", lambda *a, **k: False)

    assert service.send_summary_alert([_alert()]) is False
    assert "IONQ" not in service.latest_results, "실패했는데 억제 타임스탬프가 남았다"


def test_successful_send_records_suppression(monkeypatch):
    monkeypatch.setattr(service, "latest_results", {})
    monkeypatch.setattr(service, "_flush_latest_result_summaries", lambda: None)
    monkeypatch.setattr(service, "_stage_latest_result_summary", lambda t: None)
    monkeypatch.setattr(telegram_bot, "send_daily_digest", lambda *a, **k: True)

    assert service.send_summary_alert([_alert()]) is True
    assert service.latest_results["IONQ"]["alert_sent_at"]


# ── scan_log.alert_sent가 실제 전송을 반영하는가 ────────────────


def _fresh_db(tmp_path, monkeypatch):
    import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    return db


def test_insert_scan_returns_row_id(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    rid = db.insert_scan("IONQ", {"final_signal": "SELL", "composite_score": -0.5,
                                  "confidence": 5.5}, alert_sent=False)
    assert isinstance(rid, int) and rid > 0


def test_set_alert_sent_marks_delivered(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    r1 = db.insert_scan("IONQ", {"final_signal": "SELL", "composite_score": -0.5,
                                 "confidence": 5.5}, alert_sent=False)
    r2 = db.insert_scan("PLTR", {"final_signal": "BUY", "composite_score": 1.4,
                                 "confidence": 7.7}, alert_sent=False)

    assert db.set_alert_sent([r1, r2], True) == 2
    rows = {r["ticker"]: r["alert_sent"] for r in db.get_scan_logs(limit=10)["logs"]}
    assert rows["IONQ"] == 1 and rows["PLTR"] == 1


def test_set_alert_sent_records_failure_as_zero(tmp_path, monkeypatch):
    """전송 실패는 0으로 남아야 한다 — 이게 이번 버그의 핵심."""
    db = _fresh_db(tmp_path, monkeypatch)
    rid = db.insert_scan("IONQ", {"final_signal": "SELL", "composite_score": -0.5,
                                  "confidence": 5.5}, alert_sent=False)

    db.set_alert_sent([rid], False)
    assert db.get_scan_logs(limit=1)["logs"][0]["alert_sent"] == 0


def test_set_alert_sent_empty_is_noop(tmp_path, monkeypatch):
    db = _fresh_db(tmp_path, monkeypatch)
    assert db.set_alert_sent([], True) == 0
