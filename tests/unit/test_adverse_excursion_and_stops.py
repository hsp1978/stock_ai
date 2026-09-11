"""왼쪽 꼬리 — 역행폭 기록과 손절 시뮬레이션.

`docs/SYSTEM_OVERVIEW.md` §15-2(2026-09-11 갱신): 밴드를 제거하고 분포를 보니
**방향 적중률 51.9% 인데 평균이 −2.57%, 중앙값은 +0.14%** 였다. 방향은 반반 맞히지만
**틀릴 때 더 크게 잃는다.**

종료 시점 수익률만으로는 그 구조를 고칠 수 없다 — 손절이 어디서 걸렸을지 모르기
때문이다. 되돌아온 손실(보유 중 -15% 갔다가 -1% 로 마감)은 수익률에 보이지 않는다.

여기서 고정하는 것:
  1. 역행폭(보유 중 반대 방향 최대 이동)을 방향에 맞게 계산한다 — 매수는 저가,
     매도는 고가 기준
  2. 프리페치 구간이 **발행일부터** 시작한다 (종전에는 보유 초반 봉이 없었다)
  3. 꼬리 비대칭을 지표로 낸다 (p10/p90, payoff_ratio)
  4. 손절 시뮬레이션은 **가정을 명시**한다 — 슬리피지·갭 미반영이라 낙관적이다
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd
import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

import signal_tracker as st  # noqa: E402
from db import _CREATE_OUTCOMES_TABLE  # noqa: E402

NOW = datetime.now(timezone.utc)


def _frame(rows):
    """[(날짜, low, high, close)] → OHLCV 프레임."""
    idx = pd.to_datetime([d for d, *_ in rows])
    return pd.DataFrame(
        {
            "Low": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Close": [r[3] for r in rows],
        },
        index=idx,
    )


def _with_cache(ticker, frame):
    st.clear_price_history_cache()
    st._PRICE_CACHE.frames = {ticker: frame}
    st._PRICE_CACHE.requested = {ticker}


# ── 역행폭 계산 ───────────────────────────────────────────────────


def test_buy_adverse_excursion_uses_lows():
    """매수는 보유 중 저가까지 얼마나 밀렸는지가 손절 판단 기준이다."""
    issued = datetime(2026, 8, 1, tzinfo=timezone.utc)
    _with_cache("PLTR", _frame([
        ("2026-08-01", 100.0, 102.0, 101.0),
        ("2026-08-03", 85.0, 101.0, 90.0),     # 저가 85 → -15%
        ("2026-08-08", 99.0, 105.0, 104.0),    # 마감은 +4%
    ]))

    value = st.adverse_excursion(
        "PLTR", "buy", 100.0, issued, issued + timedelta(days=7)
    )

    assert value == pytest.approx(0.15)        # 되돌아온 손실이 보인다


def test_sell_adverse_excursion_uses_highs():
    """매도는 가격이 오르는 게 불리하다."""
    issued = datetime(2026, 8, 1, tzinfo=timezone.utc)
    _with_cache("005930.KS", _frame([
        ("2026-08-01", 99.0, 101.0, 100.0),
        ("2026-08-04", 100.0, 112.0, 110.0),   # 고가 112 → +12% 불리
        ("2026-08-07", 88.0, 95.0, 90.0),      # 마감은 -10% (매도 적중)
    ]))

    value = st.adverse_excursion(
        "005930.KS", "sell", 100.0, issued, issued + timedelta(days=7)
    )

    assert value == pytest.approx(0.12)


def test_adverse_excursion_falls_back_to_close_when_no_high_low():
    issued = datetime(2026, 8, 1, tzinfo=timezone.utc)
    frame = pd.DataFrame(
        {"Close": [100.0, 92.0, 101.0]},
        index=pd.to_datetime(["2026-08-01", "2026-08-04", "2026-08-07"]),
    )
    _with_cache("X", frame)

    assert st.adverse_excursion(
        "X", "buy", 100.0, issued, issued + timedelta(days=7)
    ) == pytest.approx(0.08)


def test_favorable_only_move_has_zero_adverse_excursion():
    issued = datetime(2026, 8, 1, tzinfo=timezone.utc)
    _with_cache("UP", _frame([
        ("2026-08-01", 100.0, 103.0, 102.0),
        ("2026-08-05", 104.0, 110.0, 109.0),
    ]))

    assert st.adverse_excursion(
        "UP", "buy", 100.0, issued, issued + timedelta(days=7)
    ) == 0.0


def test_window_is_bounded_by_the_holding_period():
    """종료일 이후의 급락은 이 신호의 역행폭이 아니다."""
    issued = datetime(2026, 8, 1, tzinfo=timezone.utc)
    _with_cache("B", _frame([
        ("2026-08-01", 99.0, 101.0, 100.0),
        ("2026-08-05", 97.0, 101.0, 99.0),     # 보유 중 -3%
        ("2026-08-20", 60.0, 70.0, 65.0),      # 종료 후 급락 — 제외돼야 한다
    ]))

    value = st.adverse_excursion(
        "B", "buy", 100.0, issued, issued + timedelta(days=7)
    )
    assert value == pytest.approx(0.03)


# ── 평가 루프 기록 ────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "signals.db"
    conn = sqlite3.connect(path)
    conn.executescript(_CREATE_OUTCOMES_TABLE)
    conn.commit()
    conn.close()
    return str(path)


def _conn_for(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_evaluation_records_adverse_excursion_from_issue_date(db):
    """프리페치가 발행일부터 시작해야 보유 초반 급락이 잡힌다."""
    conn = sqlite3.connect(db)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source, issued_at, conviction,
            price_at_signal)
           VALUES ('s1', 'PLTR', 'buy', 'scan_agent', ?, 8.0, 100.0)""",
        ((NOW - timedelta(days=40)).isoformat(),),
    )
    conn.commit()
    conn.close()

    requested = []

    def fake_fetch(ticker, start, end):
        requested.append((ticker, start.date(), end.date()))
        days = pd.date_range(end=(NOW + timedelta(days=1)).date(), periods=80, freq="D")
        # 발행 직후 -12% 까지 밀렸다가 회복하는 경로
        lows = [100.0] * 80
        lows[40] = 88.0
        return pd.DataFrame(
            {"Low": lows, "High": [105.0] * 80, "Close": [102.0] * 80}, index=days
        )

    with (
        patch("signal_tracker._get_conn", lambda: _conn_for(db)),
        patch("signal_tracker._fetch_history", side_effect=fake_fetch),
    ):
        st.clear_price_history_cache()
        stats = st.evaluate_past_signals(days_back=90, limit=10)

    assert stats["adverse_filled"] >= 1
    stock_req = [r for r in requested if r[0] == "PLTR"][0]
    issued_date = (NOW - timedelta(days=40)).date()
    assert stock_req[1] <= issued_date      # 발행일 이전부터 받는다

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT adverse_excursion_7d, adverse_excursion_30d, return_7d "
        "FROM signal_outcomes WHERE signal_id='s1'"
    ).fetchone()
    conn.close()

    assert row[0] is not None and row[0] > 0      # 되돌아온 손실이 기록됐다
    assert row[1] is not None
    assert row[2] == pytest.approx(0.02)          # 종료 수익률은 +2%


# ── 꼬리 지표 ─────────────────────────────────────────────────────


def test_tail_metrics_expose_asymmetry():
    from signal_tracker import _tail_metrics

    # 8건은 +2%, 2건은 -20% → 방향 적중률 80% 인데 기대값은 마이너스
    signed = [0.02] * 8 + [-0.20] * 2
    tail = _tail_metrics(signed)

    assert tail["p10"] < 0 and tail["p90"] > 0
    assert tail["tail_ratio"] > 1          # 손실 꼬리가 두껍다
    assert tail["payoff_ratio"] == pytest.approx(0.1)   # 2% / 20%
    assert tail["loss_share_pct"] == 20.0


def test_tail_metrics_on_empty_sample():
    from signal_tracker import _tail_metrics

    assert _tail_metrics([])["tail_ratio"] == 0.0


# ── 손절 시뮬레이션 ───────────────────────────────────────────────


def _row(signal_type, ret, adverse):
    return {"signal_type": signal_type, "ret": ret, "adverse": adverse}


def test_stop_simulation_cuts_the_left_tail():
    """역행폭 -20% 를 지난 건은 손절가에서 끊겼다고 본다."""
    rows = [_row("buy", 0.02, 0.01)] * 8 + [_row("buy", -0.20, 0.22)] * 2
    result = st.simulate_stop_levels(rows, levels=[0.05, 0.10])

    no_stop = sum(r["ret"] for r in rows) / len(rows) * 100
    by_level = {r["stop_pct"]: r for r in result}

    assert by_level[10.0]["trigger_rate_pct"] == 20.0
    # -20% 2건이 -10% 로 끊기면 기대값이 개선된다
    assert by_level[10.0]["avg_signed_return_pct"] > no_stop
    assert by_level[10.0]["delta_vs_no_stop_pct"] > 0


def test_tight_stop_can_hurt_when_it_cuts_winners():
    """손절이 좁으면 되돌아온 승자까지 끊는다 — 개선폭이 음수로 나와야 한다."""
    # 보유 중 -6% 까지 밀렸지만 +10% 로 마감한 신호들
    rows = [_row("buy", 0.10, 0.06)] * 10
    result = {r["stop_pct"]: r for r in st.simulate_stop_levels(rows, levels=[0.05, 0.10])}

    assert result[5.0]["trigger_rate_pct"] == 100.0
    assert result[5.0]["delta_vs_no_stop_pct"] < 0     # 승자를 끊었다
    assert result[10.0]["trigger_rate_pct"] == 0.0
    assert result[10.0]["delta_vs_no_stop_pct"] == 0.0


def test_sell_signals_use_direction_adjusted_returns():
    rows = [_row("sell", -0.08, 0.02)] * 5      # 종목 -8% = 매도 +8%
    result = st.simulate_stop_levels(rows, levels=[0.05])[0]

    assert result["trigger_rate_pct"] == 0.0
    assert result["avg_signed_return_pct"] == pytest.approx(8.0)


def test_rows_without_adverse_data_are_excluded():
    rows = [_row("buy", 0.02, None)] * 3 + [_row("buy", -0.10, 0.11)]
    result = st.simulate_stop_levels(rows, levels=[0.05])[0]

    assert result["sample"] == 1          # 역행폭 없는 행은 시뮬레이션 불가
