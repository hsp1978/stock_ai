"""
Variance-aware aggregation 단위 테스트 (EXECUTION_PLAN Step 12)

테스트 시나리오:
- 4 그룹 모두 BUY conviction 0.7 → low variance, conviction 유지
- 2 그룹 BUY + 2 그룹 SELL → high variance, conviction 30% 감소
- 1 그룹 strong SELL + 3 그룹 weak BUY → medium variance
"""

import os
import sys

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
for _d in (_ANALYZER_DIR, _AGENT_DIR):
    if _d not in sys.path:  # noqa: E402
        sys.path.insert(0, _d)

from agent_groups import (  # noqa: E402
    AgentGroup,
    GroupResult,
    aggregate_with_variance,
)


# ── GroupResult 더미 생성 헬퍼 ────────────────────────────────────────


def _gr(group: AgentGroup, signal: str, conf: float) -> GroupResult:
    return GroupResult(
        group=group,
        signal=signal,
        confidence=conf,
        member_count=2,
        member_results=[],
        error_count=0,
    )


# ── aggregate_with_variance ──────────────────────────────────────────


def test_all_buy_low_variance():
    """4 그룹 모두 BUY, 동일 conviction → 분산 작음 → agreement=high."""
    group_results = {
        AgentGroup.TECHNICAL: _gr(AgentGroup.TECHNICAL, "buy", 7.0),
        AgentGroup.FUNDAMENTAL: _gr(AgentGroup.FUNDAMENTAL, "buy", 7.0),
        AgentGroup.MACRO: _gr(AgentGroup.MACRO, "buy", 7.0),
        AgentGroup.RISK: _gr(AgentGroup.RISK, "buy", 7.0),
    }
    result = aggregate_with_variance(group_results)
    assert result["agreement"] == "high"
    assert result["std"] < 1.5
    assert result["mean_score"] > 0  # 모두 buy → 양수


def test_two_buy_two_sell_high_variance():
    """2 그룹 BUY + 2 그룹 SELL, 동일 conviction → 분산 큼 → agreement=low."""
    group_results = {
        AgentGroup.TECHNICAL: _gr(AgentGroup.TECHNICAL, "buy", 7.0),
        AgentGroup.FUNDAMENTAL: _gr(AgentGroup.FUNDAMENTAL, "buy", 7.0),
        AgentGroup.MACRO: _gr(AgentGroup.MACRO, "sell", 7.0),
        AgentGroup.RISK: _gr(AgentGroup.RISK, "sell", 7.0),
    }
    result = aggregate_with_variance(group_results)
    assert result["agreement"] == "low"
    assert result["std"] >= 3.0


def test_strong_sell_vs_weak_buys_medium_variance():
    """1 그룹 SELL(높은 conf) + 3 그룹 BUY(낮은 conf) → medium variance."""
    group_results = {
        AgentGroup.TECHNICAL: _gr(AgentGroup.TECHNICAL, "sell", 9.0),
        AgentGroup.FUNDAMENTAL: _gr(AgentGroup.FUNDAMENTAL, "buy", 2.0),
        AgentGroup.MACRO: _gr(AgentGroup.MACRO, "buy", 2.0),
        AgentGroup.RISK: _gr(AgentGroup.RISK, "buy", 2.0),
    }
    result = aggregate_with_variance(group_results)
    # scores: sell*9=-9, buy*2=2, buy*2=2, buy*2=2
    # mean_score < 0 (sell 우세)
    assert result["agreement"] in ("medium", "low")
    assert isinstance(result["std"], float)
    assert result["std"] >= 0


def test_empty_group_results():
    """빈 group_results → mean_score=0, std=0, agreement=high."""
    result = aggregate_with_variance({})
    assert result["mean_score"] == 0.0
    assert result["std"] == 0.0
    assert result["agreement"] == "high"


def test_mean_score_direction_buy():
    """모두 BUY → mean_score > 0."""
    group_results = {
        AgentGroup.TECHNICAL: _gr(AgentGroup.TECHNICAL, "buy", 8.0),
        AgentGroup.FUNDAMENTAL: _gr(AgentGroup.FUNDAMENTAL, "buy", 6.0),
    }
    result = aggregate_with_variance(group_results)
    assert result["mean_score"] > 0


def test_mean_score_direction_sell():
    """모두 SELL → mean_score < 0."""
    group_results = {
        AgentGroup.TECHNICAL: _gr(AgentGroup.TECHNICAL, "sell", 8.0),
        AgentGroup.FUNDAMENTAL: _gr(AgentGroup.FUNDAMENTAL, "sell", 6.0),
    }
    result = aggregate_with_variance(group_results)
    assert result["mean_score"] < 0


def test_regime_weights_applied():
    """STRONG_UPTREND 가중치 적용 시 momentum(Technical) 그룹이 더 강하게 반영."""
    group_results = {
        AgentGroup.TECHNICAL: _gr(AgentGroup.TECHNICAL, "buy", 5.0),
        AgentGroup.FUNDAMENTAL: _gr(AgentGroup.FUNDAMENTAL, "sell", 5.0),
    }
    uptrend_weights = {"momentum": 1.5, "mean_reversion": 0.3, "fundamental": 1.0}
    result_weighted = aggregate_with_variance(group_results, uptrend_weights)
    result_equal = aggregate_with_variance(group_results)  # 가중치 없음

    # STRONG_UPTREND에서 Technical(momentum ×1.5) BUY가 유리하므로
    # mean_score가 equal 가중치보다 높아야 함
    assert result_weighted["mean_score"] > result_equal["mean_score"]


# ── signal_tracker 파라미터 호환성 ────────────────────────────────────


def test_insert_signal_outcome_accepts_variance_params():
    """insert_signal_outcome이 signal_std/agreement_level 파라미터를 받는다."""
    import sqlite3
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = tmp + "/test.db"
        conn = sqlite3.connect(db)
        conn.executescript("""
            CREATE TABLE signal_outcomes (
                signal_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                signal_source TEXT NOT NULL,
                issued_at TIMESTAMP NOT NULL,
                conviction REAL NOT NULL,
                price_at_signal REAL NOT NULL,
                market_context TEXT,
                regime TEXT,
                signal_std REAL,
                agreement_level TEXT
            )
        """)
        conn.commit()
        conn.close()

        from unittest.mock import patch

        def _patched_conn():
            c = sqlite3.connect(db)
            c.row_factory = sqlite3.Row
            return c

        with patch("signal_tracker._get_conn", _patched_conn):
            from signal_tracker import insert_signal_outcome

            sid = insert_signal_outcome(
                ticker="AAPL",
                signal_type="buy",
                signal_source="test",
                conviction=7.0,
                price_at_signal=100.0,
                signal_std=2.5,
                agreement_level="medium",
            )

        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT signal_std, agreement_level FROM signal_outcomes WHERE signal_id=?",
            (sid,),
        ).fetchone()
        conn.close()

        assert row[0] == 2.5
        assert row[1] == "medium"
