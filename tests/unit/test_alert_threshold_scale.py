"""알림 임계값 스케일 정합 + V2 배치 텔레그램 요약 테스트.

2026-07 진단: composite score 실측 [-1.4, +2.2]인데 알림 임계 ±5.0 —
83일간 BUY 22건 전부 "점수 범위 밖"으로 알림 차단 (구조적 영구 침묵).
"""

import os
import sys

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import service  # noqa: E402


def test_thresholds_are_reachable_on_composite_scale():
    """임계값이 신호 결정 컷(BUY avg>+2 / SELL avg<-2)보다 느슨해야
    신호 발생 시 알림 게이트가 차단하지 않는다."""
    assert service.BUY_THRESHOLD <= 2.0, "BUY 알림 임계가 신호 결정 컷(+2)보다 엄격하면 알림 불가"
    assert service.SELL_THRESHOLD >= -2.0, "SELL 알림 임계가 신호 결정 컷(-2)보다 엄격하면 알림 불가"


def test_buy_signal_now_passes_alert_gate(monkeypatch):
    """83일 실측에서 발생했던 BUY(score 2.02~2.18)가 알림 게이트를 통과해야 한다."""
    monkeypatch.setattr(service, "cooling_off_state", {})
    monkeypatch.setattr(service, "latest_results", {})
    monkeypatch.setattr(service, "_persist_cooling_off_state", lambda: None)

    alert = service.check_alert_condition(
        "TEST.KQ",
        {"composite_score": 2.1, "confidence": 7.0, "final_signal": "BUY"},
    )

    assert alert is not None, "실측 최대 스케일의 BUY가 여전히 차단됨"
    assert alert["signal"] == "BUY"


def test_low_confidence_still_blocked(monkeypatch):
    monkeypatch.setattr(service, "cooling_off_state", {})
    monkeypatch.setattr(service, "latest_results", {})
    monkeypatch.setattr(service, "_persist_cooling_off_state", lambda: None)

    alert = service.check_alert_condition(
        "TEST.KQ",
        {"composite_score": 2.1, "confidence": 3.0, "final_signal": "BUY"},
    )

    assert alert is None


def test_hold_never_alerts(monkeypatch):
    monkeypatch.setattr(service, "cooling_off_state", {})
    monkeypatch.setattr(service, "latest_results", {})
    monkeypatch.setattr(service, "_persist_cooling_off_state", lambda: None)

    alert = service.check_alert_condition(
        "TEST.KQ",
        {"composite_score": 2.1, "confidence": 8.0, "final_signal": "HOLD"},
    )

    assert alert is None


# ── V2 배치 텔레그램 요약 ─────────────────────────────────────


def _summary(signals, failed=0, errors=None):
    return {
        "status": "completed",
        "succeeded": len(signals),
        "failed": failed,
        "signals": signals,
        "errors": errors or {},
    }


def test_batch_summary_lists_directional_signals():
    text = service._format_batch_summary(_summary({
        "005930.KS": {"signal": "buy", "confidence": 6.5},
        "950170.KQ": {"signal": "neutral", "confidence": 4.0},
    }))

    assert "005930.KS" in text
    assert "BUY (6.5/10)" in text
    assert "관망: 950170.KQ" in text


def test_batch_summary_all_neutral():
    text = service._format_batch_summary(_summary({
        "A": {"signal": "neutral", "confidence": 4.0},
        "B": {"signal": "neutral", "confidence": 5.0},
    }))

    assert "방향성 신호 없음" in text


def test_batch_summary_includes_failures():
    text = service._format_batch_summary(_summary(
        {"A": {"signal": "buy", "confidence": 5.0}},
        failed=1,
        errors={"BROKEN.KQ": "LLM timeout"},
    ))

    assert "실패: BROKEN.KQ" in text


def test_batch_wrapper_sends_telegram_summary(monkeypatch):
    sent = []
    monkeypatch.setattr(service, "_record_job_start", lambda *a, **k: "t0")
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: None)
    monkeypatch.setattr(service, "_record_job_error", lambda *a, **k: None)
    monkeypatch.setattr(
        service, "_run_multi_agent_batch_impl",
        lambda tickers=None: _summary({"A": {"signal": "buy", "confidence": 5.0}}),
    )
    monkeypatch.setattr(service, "send_telegram", lambda text, **k: sent.append(text) or True)

    service.run_multi_agent_batch()

    assert len(sent) == 1
    assert "Multi-Agent 일일 배치" in sent[0]


def test_batch_wrapper_skips_telegram_when_module_unavailable(monkeypatch):
    sent = []
    monkeypatch.setattr(service, "_record_job_start", lambda *a, **k: "t0")
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: None)
    monkeypatch.setattr(
        service, "_run_multi_agent_batch_impl",
        lambda tickers=None: {"status": "skipped", "reason": "unavailable"},
    )
    monkeypatch.setattr(service, "send_telegram", lambda text, **k: sent.append(text) or True)

    service.run_multi_agent_batch()

    assert sent == []
