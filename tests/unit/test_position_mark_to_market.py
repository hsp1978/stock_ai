"""보유 포지션 시가평가 — 청산 규칙이 실제로 평가되게 한다.

`/ops/data-health` 수리(#58)가 드러낸 결함이다. 보유 중인 005930.KS / AAPL 이
2026-04-23 진입 이후 **144일간 `current_price == entry_price`** 였다. 원인은
표시 문제가 아니다:

  손절·익절·트레일링·시간청산은 **전부 `update_position_prices()` 안에서만**
  평가된다. 그런데 그 함수를 부르는 스케줄 잡이 없었다 — WebUI '가격 갱신'
  버튼을 누를 때만 돌았다. 즉 **청산 규칙이 한 번도 평가된 적이 없다.**

여기서 고정하는 것:
  1. 시가평가는 스케줄 잡(`position_mark_to_market`)으로 돈다
  2. 시세를 못 받은 종목은 **갱신된 척하지 않는다** — failures 에 사유와 함께
  3. `price_updated_at` 을 남긴다 ('평가함'과 '평가한 적 없음'의 구분)
  4. 수동 엔드포인트와 스케줄 잡이 **같은 함수**를 쓴다
  5. 자동 청산이 일어나면 알린다 — 조용히 팔리면 안 된다
"""

import os
import sys
from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import service  # noqa: E402


def _frame(close: float):
    return pd.DataFrame({"Close": [close - 1, close]},
                        index=pd.to_datetime(["2026-09-12", "2026-09-13"]))


@pytest.fixture
def two_positions(monkeypatch):
    monkeypatch.setattr(service, "_get_paper_state",
                        lambda: {"positions": {"AAPL": {"qty": 10}, "005930.KS": {"qty": 1}}})
    return service


def _isolated_job(monkeypatch):
    monkeypatch.setattr(service, "_record_job_start", lambda *a, **k: "t0")
    monkeypatch.setattr(service, "_record_job_success", lambda *a, **k: None)
    monkeypatch.setattr(service, "_record_job_error", lambda *a, **k: None)


# ── 시가평가 ──────────────────────────────────────────────────────


def test_prices_are_pushed_into_positions(two_positions, monkeypatch):
    seen = {}
    monkeypatch.setattr(service, "fetch_ohlcv",
                        lambda t, period=None: _frame(200.0 if t == "AAPL" else 60000.0))
    monkeypatch.setattr(service, "update_position_prices",
                        lambda prices: seen.update(prices) or [])

    result = service.mark_positions_to_market()

    assert result["status"] == "completed"
    assert result["updated"] == 2 and result["failed"] == 0
    assert seen == {"AAPL": 200.0, "005930.KS": 60000.0}


def test_missing_price_is_reported_not_swallowed(two_positions, monkeypatch):
    """건너뛴 종목이 안 보이면 데이터 헬스가 다시 거짓 OK 를 낸다."""
    monkeypatch.setattr(service, "fetch_ohlcv",
                        lambda t, period=None: None if t == "AAPL" else _frame(60000.0))
    monkeypatch.setattr(service, "update_position_prices", lambda prices: [])

    result = service.mark_positions_to_market()

    assert result["status"] == "degraded"
    assert result["updated"] == 1 and result["failed"] == 1
    assert result["failures"] == [{"ticker": "AAPL", "error": "no_price_data"}]


def test_fetch_exception_keeps_the_reason(two_positions, monkeypatch):
    def flaky(ticker, period=None):
        if ticker == "AAPL":
            raise TimeoutError("yfinance timeout")
        return _frame(60000.0)

    monkeypatch.setattr(service, "fetch_ohlcv", flaky)
    monkeypatch.setattr(service, "update_position_prices", lambda prices: [])

    failure = service.mark_positions_to_market()["failures"][0]

    assert failure["ticker"] == "AAPL"
    assert "TimeoutError" in failure["error"] and "timeout" in failure["error"]


def test_total_failure_is_an_error_not_a_completion(two_positions, monkeypatch):
    monkeypatch.setattr(service, "fetch_ohlcv", lambda t, period=None: None)
    monkeypatch.setattr(service, "update_position_prices",
                        lambda prices: pytest.fail("가격이 하나도 없는데 갱신을 시도했다"))

    result = service.mark_positions_to_market()

    assert result["status"] == "error"
    assert result["updated"] == 0 and result["failed"] == 2


def test_no_positions_is_empty_not_success(monkeypatch):
    monkeypatch.setattr(service, "_get_paper_state", lambda: {"positions": {}})

    result = service.mark_positions_to_market()

    assert result["status"] == "empty"
    assert result["auto_closed"] == []


# ── 스케줄 잡 ─────────────────────────────────────────────────────


def test_job_is_registered_and_scheduled():
    assert "position_mark_to_market" in service._KNOWN_OPS_JOBS
    src = open(os.path.join(_AGENT_DIR, "service.py"), encoding="utf-8").read()
    assert "id='position_mark_to_market'" in src, "스케줄러에 등록되지 않았다"
    assert "POSITION_MARK_INTERVAL_MINUTES" in src


def test_job_alerts_when_some_tickers_fail(two_positions, monkeypatch):
    _isolated_job(monkeypatch)
    monkeypatch.setattr(service, "fetch_ohlcv",
                        lambda t, period=None: None if t == "AAPL" else _frame(60000.0))
    monkeypatch.setattr(service, "update_position_prices", lambda prices: [])

    sent = []
    monkeypatch.setattr(service, "_send_ops_alert",
                        lambda title, detail, **k: sent.append((title, detail)))

    result = service.run_position_mark_to_market()

    assert result["status"] == "degraded"
    assert sent and "AAPL(no_price_data)" in sent[0][1]


def test_auto_close_is_announced(two_positions, monkeypatch):
    """자동 청산이 조용히 일어나면 안 된다."""
    _isolated_job(monkeypatch)
    monkeypatch.setattr(service, "fetch_ohlcv", lambda t, period=None: _frame(1.0))
    monkeypatch.setattr(service, "update_position_prices",
                        lambda prices: [{"ticker": "AAPL", "qty": 10,
                                         "reason": "Stop Loss: $140.00"}])

    sent = []
    monkeypatch.setattr(service, "_send_ops_alert",
                        lambda title, detail, **k: sent.append((title, detail)))

    service.run_position_mark_to_market()

    assert any("auto-closed" in title.lower() for title, _ in sent)
    assert any("Stop Loss" in detail for _, detail in sent)


def test_manual_endpoint_and_job_share_one_path(monkeypatch):
    """수동/자동 경로가 갈라지면 둘 중 하나만 고쳐진다."""
    calls = []
    monkeypatch.setattr(service, "mark_positions_to_market",
                        lambda: calls.append("called") or {"status": "empty", "updated": 0,
                                                           "failed": 0, "prices": {},
                                                           "failures": [], "auto_closed": []})
    service.api_update_prices()
    assert calls == ["called"]


def test_ops_run_job_accepts_the_new_job(monkeypatch):
    called = []
    monkeypatch.setattr(service, "run_position_mark_to_market",
                        lambda: called.append(1) or {"status": "empty"})

    service.ops_run_job("position_mark_to_market")
    service.ops_run_job("mark_to_market")

    assert len(called) == 2


# ── paper_trader 측 기록 ──────────────────────────────────────────


def test_update_position_prices_stamps_the_time(tmp_path, monkeypatch):
    import paper_trader

    state = {"positions": {"AAPL": {"qty": 10, "entry_price": 150.0,
                                    "current_price": 150.0, "peak_price": 150.0,
                                    "entry_date": "2026-04-23T17:01:23"}},
             "cash": 1000.0}
    saved = {}
    monkeypatch.setattr(paper_trader, "_load_state", lambda: state)
    monkeypatch.setattr(paper_trader, "_save_state", lambda s: saved.update(s))
    monkeypatch.setattr(paper_trader, "_apply_corporate_actions_to_state",
                        lambda state, tickers=None: None)

    paper_trader.update_position_prices({"AAPL": 175.0})
    pos = saved["positions"]["AAPL"]

    assert pos["current_price"] == 175.0
    stamped = datetime.fromisoformat(pos["price_updated_at"])
    assert (datetime.now() - stamped).total_seconds() < 60


def test_untouched_positions_keep_their_old_stamp(monkeypatch):
    """시세를 못 받은 종목이 '방금 평가됨'으로 보이면 안 된다."""
    import paper_trader

    state = {"positions": {
        "AAPL": {"qty": 10, "entry_price": 150.0, "current_price": 150.0},
        "005930.KS": {"qty": 1, "entry_price": 59626.0, "current_price": 59626.0,
                      "price_updated_at": "2026-04-23T17:01:23"},
    }, "cash": 1000.0}
    saved = {}
    monkeypatch.setattr(paper_trader, "_load_state", lambda: state)
    monkeypatch.setattr(paper_trader, "_save_state", lambda s: saved.update(s))
    monkeypatch.setattr(paper_trader, "_apply_corporate_actions_to_state",
                        lambda state, tickers=None: None)

    paper_trader.update_position_prices({"AAPL": 175.0})

    assert saved["positions"]["005930.KS"]["price_updated_at"] == "2026-04-23T17:01:23"


def test_portfolio_status_exposes_the_stamp(monkeypatch):
    import paper_trader

    monkeypatch.setattr(paper_trader, "_load_state", lambda: {
        "positions": {"AAPL": {"qty": 10, "entry_price": 150.0, "current_price": 175.0,
                               "price_updated_at": "2026-09-14T09:00:00"}},
        "cash": 1000.0, "account_size": 10000.0, "closed_trades": []})

    status = paper_trader.get_portfolio_status()

    assert status["positions"]["AAPL"]["price_updated_at"] == "2026-09-14T09:00:00"
