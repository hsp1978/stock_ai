"""방향 보정 — 매도 신호가 맞을수록 지표가 나빠지던 결함.

2026-09-10 감사: `signal_outcomes.return_7d` 는 **가격 변화**다. 매도 신호는 가격이
내려가야 맞은 것인데, 지표 네 곳이 부호를 그대로 평균하거나 `> 0` 으로 적중을
판정하고 있었다.

  - `/signal-accuracy` 의 `avg_return_pct` — 전체 -0.352%인데 매도는 맞고 있었다
  - `llm_calibrator` 의 hit = `return_7d > 0` — 표본의 44%(매도)를 반대로 라벨링
  - `ic_ensemble` 의 IC = corr(conviction, return_7d) — 잘 맞추는 매도 소스가 IC 음수
  - `signal_performance_summary` VIEW 의 hit_rate_7d / expectancy

공통 결과는 하나다: **잘 맞춘 신호가 못 맞춘 것처럼 보인다.**
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


def _insert(path, signal_id, *, days_ago, ret, signal_type="buy", ticker="PLTR",
            source="scan_agent", conviction=8.0, regime="normal"):
    issued = NOW - timedelta(days=days_ago)
    conn = sqlite3.connect(path)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source, issued_at, conviction,
            price_at_signal, return_7d, return_30d, evaluated_at, regime)
           VALUES (?, ?, ?, ?, ?, ?, 100.0, ?, ?, ?, ?)""",
        (signal_id, ticker, signal_type, source, issued.isoformat(), conviction,
         ret, ret, NOW.isoformat(), regime),
    )
    conn.commit()
    conn.close()


def _stats(path, **kwargs):
    with patch("signal_tracker._get_conn", lambda: _conn_for(path)):
        from signal_tracker import get_accuracy_stats

        return get_accuracy_stats(**kwargs)


def test_signed_return_flips_sign_for_sell_and_is_none_for_neutral():
    from signal_tracker import signed_return

    assert signed_return("buy", 0.05) == 0.05
    assert signed_return("sell", -0.05) == 0.05     # 내려가면 매도가 맞은 것
    assert signed_return("sell", 0.03) == -0.03
    assert signed_return("neutral", 0.05) is None   # 부호를 붙일 수 없다


def test_correct_sell_signals_no_longer_read_as_losses(db):
    """매도 4건이 전부 -5% (완벽하게 맞음). 원시 평균은 -5%, 방향보정은 +5%."""
    for i, day in enumerate((30, 25, 20, 15)):
        _insert(db, f"sell-{i}", days_ago=day, ret=-0.05, signal_type="sell",
                ticker=f"T{i}")

    stats = _stats(db, horizon=7, days_back=90)

    assert stats["win_count"] == 4                      # 판정은 원래 방향을 알았다
    assert stats["avg_signed_return_pct"] == 5.0        # 성과 지표
    assert stats["avg_raw_return_pct"] == -5.0          # 진단용 원시값
    assert stats["signed_sample"] == 4
    # 이름만 봐서는 부호 규칙을 알 수 없던 옛 키는 없앴다 — 조용히 틀린 값을 주느니
    # 소비자가 시끄럽게 깨지는 편이 낫다.
    assert "avg_return_pct" not in stats


def test_mixed_book_expectancy_is_not_cancelled_out(db):
    """매수 +4%, 매도 -4% (둘 다 적중). 원시 평균은 0%로 상쇄된다."""
    _insert(db, "b1", days_ago=20, ret=0.04, signal_type="buy", ticker="A")
    _insert(db, "s1", days_ago=20, ret=-0.04, signal_type="sell", ticker="B")

    stats = _stats(db, horizon=7, days_back=90)

    assert stats["avg_raw_return_pct"] == 0.0
    assert stats["avg_signed_return_pct"] == 4.0
    assert stats["win_count"] == 2


def test_neutral_rows_are_excluded_from_signed_average(db):
    _insert(db, "b1", days_ago=20, ret=0.04, signal_type="buy", ticker="A")
    _insert(db, "n1", days_ago=20, ret=0.10, signal_type="neutral", ticker="B")

    stats = _stats(db, horizon=7, days_back=90)

    assert stats["signed_sample"] == 1                 # neutral 제외
    assert stats["avg_signed_return_pct"] == 4.0
    assert stats["by_signal"]["neutral"]["signed_sample"] == 0


def test_by_signal_and_by_source_carry_both_numbers(db):
    _insert(db, "s1", days_ago=20, ret=-0.06, signal_type="sell", ticker="A",
            source="multi_agent_final")

    stats = _stats(db, horizon=7, days_back=90)

    sell = stats["by_signal"]["sell"]
    assert sell["avg_signed_return_pct"] == 6.0 and sell["avg_raw_return_pct"] == -6.0
    src = stats["by_source"]["multi_agent_final"]
    assert src["avg_signed_return_pct"] == 6.0 and src["avg_raw_return_pct"] == -6.0
    band = [b for b in stats["by_confidence_band"] if b["total"]][0]
    assert band["avg_signed_return_pct"] == 6.0


def test_calibrator_labels_correct_sell_signals_as_hits(db):
    """hit = return_7d > 0 이면 매도는 맞을 때마다 오답으로 학습된다."""
    from llm_calibrator import LLMCalibrator

    _insert(db, "s1", days_ago=20, ret=-0.05, signal_type="sell", ticker="A")
    _insert(db, "s2", days_ago=19, ret=-0.04, signal_type="sell", ticker="B")
    _insert(db, "b1", days_ago=18, ret=0.03, signal_type="buy", ticker="C")
    _insert(db, "b2", days_ago=17, ret=-0.03, signal_type="buy", ticker="D")

    df = LLMCalibrator(db_path=db).load_outcomes()

    assert len(df) == 4
    assert df["hit"].sum() == 3.0        # 매도 2건 적중 + 매수 1건 적중


def test_ic_is_positive_when_high_conviction_sells_are_right(db):
    """잘 맞추는 매도 소스가 IC 음수로 잡혀 가중치 0이 되던 부분."""
    from ic_ensemble import _load_signal_outcomes, compute_ic_per_source

    # conviction 이 높을수록 더 크게 하락 = 매도 신호로서 더 정확
    for i in range(12):
        _insert(
            db, f"s-{i}", days_ago=20 + i, ret=-0.01 * (i + 1),
            signal_type="sell", ticker=f"T{i}", source="bear_agent",
            conviction=1.0 + i * 0.7,
        )

    df = _load_signal_outcomes(db_path=db, days=180)
    ic = compute_ic_per_source(df)

    assert ic["bear_agent"] > 0.8, ic


def test_performance_view_counts_sell_hits_and_reports_both_expectancies(tmp_path):
    """VIEW 정의가 바뀌면 기존 DB의 옛 정의도 갱신돼야 한다 (DROP 후 재생성)."""
    db_path = tmp_path / "scan_log.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    # 옛 정의의 VIEW 를 먼저 만들어 둔다 — init_db 가 이걸 덮어써야 한다
    conn.execute(
        """CREATE VIEW signal_performance_summary AS
           SELECT signal_source, signal_type, regime, COUNT(*) AS n,
                  AVG(CASE WHEN return_7d > 0 THEN 1.0 ELSE 0.0 END) AS hit_rate_7d,
                  AVG(return_7d) AS expectancy_7d
           FROM signal_outcomes GROUP BY signal_source, signal_type, regime"""
    )
    conn.commit()
    conn.close()

    _insert(str(db_path), "s1", days_ago=20, ret=-0.05, signal_type="sell", ticker="A")
    _insert(str(db_path), "s2", days_ago=19, ret=-0.03, signal_type="sell", ticker="B")

    import db as db_module

    with patch.object(db_module, "DB_PATH", str(db_path)):
        db_module.init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM signal_performance_summary").fetchone()
    conn.close()

    assert row["hit_rate_7d"] == 1.0                    # 매도 2건 모두 적중
    assert round(row["signed_expectancy_7d"], 4) == 0.04
    assert round(row["raw_expectancy_7d"], 4) == -0.04


def test_ic_summary_says_inactive_instead_of_showing_every_weight_as_zero(db):
    """비활성 폴백이 '모든 소스 가중치 0'으로 읽히던 부분.

    `compute_ic_weights()` 는 누적 일수가 모자라면 빈 dict 를 돌려준다. 요약이
    `weights.get(src, 0.0)` 으로 렌더하면 '이 소스는 제외됨'처럼 보이는데,
    실제 뜻은 '가중 자체가 꺼져 있음'이다 — 완전히 다른 상태다.
    """
    from ic_ensemble import get_ic_summary

    # 누적 20일치만 — 최소 60일 요건 미달
    for i in range(12):
        _insert(db, f"s-{i}", days_ago=20 + (i % 20), ret=-0.01 * (i + 1),
                signal_type="sell", ticker=f"T{i}", source="bear_agent",
                conviction=1.0 + i * 0.7)

    summary = get_ic_summary(db_path=db, days=90)

    assert summary["active"] is False
    assert "최소" in summary["inactive_reason"]
    assert summary["sources"]["bear_agent"]["weight"] is None   # 0.0 이 아니다
    assert summary["sources"]["bear_agent"]["ic"] > 0           # IC 는 계산돼 있다
    # 계산만 되고 판정에 연결돼 있지 않다는 사실도 응답에 있어야 한다
    assert summary["applied_in_decisions"] is False
