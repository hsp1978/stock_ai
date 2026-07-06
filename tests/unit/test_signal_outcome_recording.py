"""signal_outcomes 미기록 버그(2026-07 감사) 회귀 테스트.

83일 운영 동안 signal_outcomes가 0행이었던 원인:
1. _try_insert_group_outcomes가 group_results를 최상위에서 조회
   (실제로는 final_decision 안에 중첩) → 항상 조기 return
2. 스캔/멀티에이전트 결과 dict에 가격 키 부재 → price<=0 조기 return
3. V2 최종 신호(multi_agent_final)는 기록 대상 자체가 아니었음
"""

import os
import sys

import pandas as pd

# 주의: stock_analyzer를 앞에 넣으면 동명 모듈(news_analyzer)이 잘못 로드된다.
# service.py 임포트에는 chart_agent_service 경로만 필요하다.
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import service  # noqa: E402


def _capture_inserts(monkeypatch):
    rows = []

    def _fake_insert(**kwargs):
        rows.append(kwargs)
        return "fake-id"

    monkeypatch.setattr(service, "insert_signal_outcome", _fake_insert)
    return rows


def _fake_ohlcv(monkeypatch, close=4910.0):
    df = pd.DataFrame({"Close": [close * 0.99, close]})
    monkeypatch.setattr(service, "fetch_ohlcv", lambda ticker: df)


def _multi_agent_result(final_signal="buy", group_signal="buy"):
    """실제 orchestrator 출력 구조 재현: group_results는 final_decision에 중첩."""
    return {
        "ticker": "950170.KQ",
        "agent_results": [],
        "final_decision": {
            "final_signal": final_signal,
            "final_confidence": 6.5,
            "regime": "ranging",
            "signal_std": 0.4,
            "agreement_level": "high",
            "group_results": {
                "technical": {"signal": group_signal, "confidence": 7.0},
                "risk": {"signal": "neutral", "confidence": 5.0},
            },
        },
    }


def test_group_outcomes_read_from_nested_final_decision(monkeypatch):
    rows = _capture_inserts(monkeypatch)
    _fake_ohlcv(monkeypatch)

    service._try_insert_group_outcomes("950170.KQ", _multi_agent_result())

    sources = {r["signal_source"] for r in rows}
    assert "group_technical" in sources, f"그룹 신호 미기록: {sources}"
    group_row = next(r for r in rows if r["signal_source"] == "group_technical")
    assert group_row["price_at_signal"] == 4910.0  # OHLCV 폴백
    assert group_row["regime"] == "ranging"
    assert group_row["agreement_level"] == "high"


def test_multi_agent_final_signal_is_recorded(monkeypatch):
    """V2 최종 buy/sell 신호가 multi_agent_final 소스로 기록돼야 한다."""
    rows = _capture_inserts(monkeypatch)
    _fake_ohlcv(monkeypatch)

    service._try_insert_group_outcomes("950170.KQ", _multi_agent_result(final_signal="buy"))

    final_rows = [r for r in rows if r["signal_source"] == "multi_agent_final"]
    assert len(final_rows) == 1
    assert final_rows[0]["signal_type"] == "buy"
    assert final_rows[0]["conviction"] == 6.5


def test_neutral_final_signal_not_recorded_but_groups_are(monkeypatch):
    rows = _capture_inserts(monkeypatch)
    _fake_ohlcv(monkeypatch)

    service._try_insert_group_outcomes(
        "950170.KQ", _multi_agent_result(final_signal="neutral", group_signal="sell")
    )

    sources = [r["signal_source"] for r in rows]
    assert "multi_agent_final" not in sources
    assert "group_technical" in sources


def test_scan_buy_recorded_with_price_fallback(monkeypatch):
    """V1 스캔 결과에 가격 키가 없어도 OHLCV 폴백으로 기록돼야 한다."""
    rows = _capture_inserts(monkeypatch)
    _fake_ohlcv(monkeypatch, close=71000.0)

    service._try_insert_signal_outcome(
        "005930.KS",
        {"final_signal": "BUY", "confidence": 7.2},  # 가격 키 없음 (실제 스캔 구조)
    )

    assert len(rows) == 1
    assert rows[0]["signal_source"] == "scan_agent"
    assert rows[0]["signal_type"] == "buy"
    assert rows[0]["price_at_signal"] == 71000.0


def test_scan_hold_not_recorded(monkeypatch):
    rows = _capture_inserts(monkeypatch)
    _fake_ohlcv(monkeypatch)

    service._try_insert_signal_outcome("005930.KS", {"final_signal": "HOLD"})

    assert rows == []


def test_price_resolution_prefers_result_keys_over_fetch(monkeypatch):
    rows = _capture_inserts(monkeypatch)
    monkeypatch.setattr(
        service, "fetch_ohlcv",
        lambda ticker: (_ for _ in ()).throw(RuntimeError("네트워크 호출 금지")),
    )

    result = _multi_agent_result()
    result["final_decision"]["entry_plan"] = {"limit_price": 4900.0}
    service._try_insert_group_outcomes("950170.KQ", result)

    assert rows, "entry_plan 가격으로 기록됐어야 한다"
    assert all(r["price_at_signal"] == 4900.0 for r in rows)


def test_unresolvable_price_skips_without_exception(monkeypatch):
    rows = _capture_inserts(monkeypatch)
    monkeypatch.setattr(service, "fetch_ohlcv", lambda ticker: pd.DataFrame())

    service._try_insert_group_outcomes("950170.KQ", _multi_agent_result())

    assert rows == []
