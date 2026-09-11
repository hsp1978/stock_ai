"""시장 대비 초과수익 — 절대 수익만으로는 알파를 말할 수 없다.

`docs/SYSTEM_OVERVIEW.md` §15-2: 방향 보정까지 끝냈지만 지표가 **시장 대비 초과수익을
계산하지 않는다**. "+0.29%"가 같은 기간 지수 대비 무엇인지 말할 수 없었다.
시장이 +3% 오른 구간의 매수 +0.3%는 사실 -2.7%다.

여기서 고정하는 것:
  1. 종목의 시장에 맞는 지수를 고른다 (KOSDAQ/KOSPI/S&P500)
  2. 초과수익도 **방향 보정**한다 — 매도는 지수보다 더 떨어져야 이긴 것이다
  3. 벤치마크가 없는 행은 초과수익 평균에서 빠지고, 그 사실이 표본 수로 보고된다
  4. 벤치마크 컬럼 도입 전 평가분도 소급 대상이 된다
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from signal_tracker import benchmark_for, get_accuracy_stats  # noqa: E402

# 스키마는 db.py 의 실제 DDL 을 쓴다 — 복제하면 컬럼이 추가될 때마다 픽스처가
# 현실과 어긋난다 (2026-09: ticker/signal_type/eval_state/benchmark_* 추가 때마다 발생).
from db import _CREATE_OUTCOMES_TABLE as _SCHEMA  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "signals.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return str(path)


def _conn_for(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert(path, sid, *, days_ago, ret, bench=None, signal_type="buy",
            ticker="PLTR", source="scan_agent"):
    conn = sqlite3.connect(path)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source, issued_at, conviction,
            price_at_signal, return_7d, benchmark_return_7d, benchmark_symbol,
            evaluated_at)
           VALUES (?, ?, ?, ?, ?, 8.0, 100.0, ?, ?, ?, ?)""",
        (sid, ticker, signal_type, source,
         (NOW - timedelta(days=days_ago)).isoformat(), ret, bench,
         benchmark_for(ticker) if bench is not None else None, NOW.isoformat()),
    )
    conn.commit()
    conn.close()


def _stats(path, **kw):
    with patch("signal_tracker._get_conn", lambda: _conn_for(path)):
        return get_accuracy_stats(**kw)


# ── 벤치마크 선택 ─────────────────────────────────────────────────


def test_benchmark_follows_the_listing_market():
    assert benchmark_for("049430.KQ") == "^KQ11"     # KOSDAQ
    assert benchmark_for("005930.KS") == "^KS11"     # KOSPI
    assert benchmark_for("PLTR") == "^GSPC"          # 미국
    assert benchmark_for("") == "^GSPC"


# ── 초과수익 계산 ─────────────────────────────────────────────────


def test_excess_return_is_direction_adjusted(db):
    # 매수: 종목 +1%, 시장 +5% → 초과 -4%
    _insert(db, "buy-lag", days_ago=20, ret=0.01, bench=0.05, signal_type="buy")
    stats = _stats(db, horizon=7, days_back=90)

    assert stats["avg_signed_return_pct"] == 1.0        # 절대 수익은 플러스
    assert stats["avg_excess_return_pct"] == -4.0       # 시장 대비는 마이너스
    assert stats["beat_benchmark_rate_pct"] == 0.0
    assert stats["benchmark_sample"] == 1


def test_sell_beats_market_when_it_falls_further(db):
    """매도는 지수보다 더 떨어져야 이긴 것이다."""
    # 종목 -8%, 시장 -3% → signed: 종목 +8, 시장 +3 → 초과 +5
    _insert(db, "sell-win", days_ago=20, ret=-0.08, bench=-0.03, signal_type="sell")
    stats = _stats(db, horizon=7, days_back=90)

    assert stats["avg_signed_return_pct"] == 8.0
    assert stats["avg_excess_return_pct"] == 5.0
    assert stats["beat_benchmark_rate_pct"] == 100.0


def test_sell_loses_when_market_falls_more(db):
    # 종목 -2%, 시장 -6% → 초과 -4% (시장을 따라간 것일 뿐)
    _insert(db, "sell-lose", days_ago=20, ret=-0.02, bench=-0.06, signal_type="sell")
    stats = _stats(db, horizon=7, days_back=90)

    assert stats["avg_excess_return_pct"] == -4.0
    assert stats["beat_benchmark_rate_pct"] == 0.0


def test_rows_without_benchmark_are_excluded_and_counted(db):
    """벤치마크 없는 행을 0으로 채우면 초과수익이 희석된다."""
    _insert(db, "with", days_ago=20, ret=0.04, bench=0.01, ticker="PLTR")
    _insert(db, "without", days_ago=19, ret=0.10, bench=None, ticker="MSFT")

    stats = _stats(db, horizon=7, days_back=90)

    assert stats["total_evaluated"] == 2
    assert stats["benchmark_sample"] == 1              # 1건만 계산에 들어간다
    assert stats["avg_excess_return_pct"] == 3.0       # (4 - 1), 10% 는 제외
    assert stats["avg_signed_return_pct"] == 7.0       # 절대 수익은 2건 평균


def test_no_benchmark_data_reports_zero_sample(db):
    _insert(db, "a", days_ago=20, ret=0.05, bench=None)
    stats = _stats(db, horizon=7, days_back=90)

    assert stats["benchmark_sample"] == 0
    assert stats["avg_excess_return_pct"] == 0.0       # 말할 수 없다 = 표본 0
    assert stats["beat_benchmark_rate_pct"] == 0.0


def test_by_signal_and_by_source_carry_excess(db):
    _insert(db, "s1", days_ago=20, ret=-0.08, bench=-0.03, signal_type="sell",
            source="multi_agent_final")
    stats = _stats(db, horizon=7, days_back=90)

    assert stats["by_signal"]["sell"]["avg_excess_return_pct"] == 5.0
    assert stats["by_source"]["multi_agent_final"]["benchmark_sample"] == 1


# ── 평가 루프 연동 ────────────────────────────────────────────────


def _frame(prices, start_days_ago=60):
    import pandas as pd

    idx = pd.date_range(
        end=(NOW + timedelta(days=1)).date(), periods=len(prices), freq="D"
    )
    return pd.DataFrame({"Close": prices}, index=idx)


def test_evaluation_fills_benchmark_returns(db):
    """평가 시 지수 수익률도 같은 창으로 채운다."""
    import signal_tracker as st

    conn = sqlite3.connect(db)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source, issued_at, conviction,
            price_at_signal)
           VALUES ('new', '049430.KQ', 'buy', 'scan_agent', ?, 8.0, 100.0)""",
        ((NOW - timedelta(days=20)).isoformat(),),
    )
    conn.commit()
    conn.close()

    fetched = []

    def fake_fetch(ticker, start, end):
        fetched.append(ticker)
        # 종목은 110 고정, 지수는 105 고정 → 종목 +10%, 지수 +5%
        return _frame([110.0] * 60) if not ticker.startswith("^") else _frame([105.0] * 60)

    with (
        patch("signal_tracker._get_conn", lambda: _conn_for(db)),
        patch("signal_tracker._fetch_history", side_effect=fake_fetch),
    ):
        st.clear_price_history_cache()
        stats = st.evaluate_past_signals(days_back=90, limit=10)

    assert stats["updated"] == 1
    assert stats["benchmark_filled"] >= 1
    assert "^KQ11" in fetched                     # KOSDAQ 지수를 함께 받았다

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT benchmark_symbol, benchmark_return_7d, return_7d "
        "FROM signal_outcomes WHERE signal_id='new'"
    ).fetchone()
    conn.close()

    assert row[0] == "^KQ11"
    assert row[1] == pytest.approx(0.0)           # 지수는 105 고정 → 변화 0
    assert row[2] == pytest.approx(0.1)           # 종목 110/100 - 1


def test_rows_evaluated_before_benchmark_columns_are_backfilled(db):
    """컬럼 도입 전 평가분(수익률 있음 / 벤치마크 없음)도 대상이 된다."""
    import signal_tracker as st

    _insert(db, "old", days_ago=40, ret=0.07, bench=None, ticker="049430.KQ")

    with (
        patch("signal_tracker._get_conn", lambda: _conn_for(db)),
        patch("signal_tracker._fetch_history",
              side_effect=lambda t, s, e: _frame([105.0] * 60)),
    ):
        st.clear_price_history_cache()
        stats = st.evaluate_past_signals(days_back=90, limit=10)

    assert stats["candidates"] == 1               # 후보로 잡힌다
    assert stats["benchmark_filled"] >= 1

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT benchmark_return_7d, return_7d FROM signal_outcomes WHERE signal_id='old'"
    ).fetchone()
    conn.close()

    assert row[0] is not None                    # 소급 채움 완료
    assert row[1] == pytest.approx(0.07)         # 기존 수익률은 보존
