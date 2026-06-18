import json


def _write_state(path, position):
    state = {
        "account_size": 100_000,
        "cash": 90_000,
        "positions": {"AAPL": position},
        "closed_trades": [],
        "order_history": [],
        "corporate_action_history": [],
        "applied_corporate_actions": {},
        "corporate_actions_last_checked": {},
        "created_at": "2026-01-01T00:00:00",
    }
    path.write_text(json.dumps(state), encoding="utf-8")


def test_split_adjustment_is_idempotent(tmp_path, monkeypatch):
    import paper_trader as pt

    state_path = tmp_path / "paper_state.json"
    monkeypatch.setattr(pt, "PAPER_STATE_FILE", str(state_path))
    _write_state(
        state_path,
        {
            "qty": 10,
            "entry_price": 100.0,
            "current_price": 110.0,
            "peak_price": 120.0,
            "entry_date": "2026-01-01T00:00:00",
            "trailing_stop_pct": 0.1,
            "stop_loss_price": 90.0,
            "take_profit_price": 130.0,
        },
    )
    monkeypatch.setattr(
        pt,
        "_fetch_corporate_actions",
        lambda ticker: [{"date": "2026-02-01", "type": "split", "value": 2.0}],
    )

    first = pt.adjust_corporate_actions(["AAPL"], force=True)
    second = pt.adjust_corporate_actions(["AAPL"], force=True)
    state = pt._load_state()
    pos = state["positions"]["AAPL"]

    assert first["applied"] == 1
    assert second["applied"] == 0
    assert pos["qty"] == 20
    assert pos["entry_price"] == 50.0
    assert pos["current_price"] == 55.0
    assert pos["peak_price"] == 60.0
    assert pos["stop_loss_price"] == 45.0
    assert pos["take_profit_price"] == 65.0
    assert len(state["corporate_action_history"]) == 1


def test_dividend_adjustment_credits_cash_and_basis(tmp_path, monkeypatch):
    import paper_trader as pt

    state_path = tmp_path / "paper_state.json"
    monkeypatch.setattr(pt, "PAPER_STATE_FILE", str(state_path))
    _write_state(
        state_path,
        {
            "qty": 10,
            "entry_price": 100.0,
            "current_price": 110.0,
            "peak_price": 120.0,
            "entry_date": "2026-01-01T00:00:00",
            "trailing_stop_pct": 0.1,
            "stop_loss_price": 90.0,
            "take_profit_price": 130.0,
        },
    )
    monkeypatch.setattr(
        pt,
        "_fetch_corporate_actions",
        lambda ticker: [{"date": "2026-02-01", "type": "dividend", "value": 1.5}],
    )

    result = pt.adjust_corporate_actions(["AAPL"], force=True)
    state = pt._load_state()
    pos = state["positions"]["AAPL"]

    assert result["applied"] == 1
    assert state["cash"] == 90_015.0
    assert pos["qty"] == 10
    assert pos["entry_price"] == 98.5
    assert pos["current_price"] == 108.5
    assert pos["peak_price"] == 118.5
    assert pos["stop_loss_price"] == 88.5
    assert pos["take_profit_price"] == 128.5
    assert state["corporate_action_history"][0]["cash_credit"] == 15.0
