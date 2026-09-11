"""표본 독립성 — 30분 스캔의 반복 기록이 통계·칼리브레이션을 지배하지 못하게 한다.

2026-09-10 진단: 평가 큐를 고쳐 표본이 생겼는데, 그 표본의 93%가 30분 주기 스캔이었다.
같은 종목이 하루 최대 48행, 7일 horizon 이면 연속된 날짜끼리도 수익률 구간이 겹친다.
n=3,030 으로 보이지만 독립 관측은 수백 건 수준이라 승률·신뢰구간·IC 가중이 전부
과대평가된다.

여기서 고정하는 것:
  1. 기본 표본 단위는 (종목, 소스, 발행일) 1건 — 그날 마지막 행이 대표
  2. 신뢰구간은 **독립 블록 수**로 계산한다 (행 수로 계산하면 거짓으로 좁아진다)
  3. 원시 행 수는 사라지지 않고 `sampling.rows_raw` 로 함께 보고된다
  4. llm_calibrator·ic_ensemble 도 같은 표본 단위를 쓴다
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

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


def _insert(path, signal_id, *, days_ago, ret, ticker="PLTR", source="scan_agent",
            signal_type="buy", conviction=7.0, hour=0):
    issued = (NOW - timedelta(days=days_ago)).replace(hour=hour, minute=0, second=0)
    conn = sqlite3.connect(path)
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source, issued_at, conviction,
            price_at_signal, return_7d, return_14d, return_30d, evaluated_at)
           VALUES (?, ?, ?, ?, ?, ?, 100.0, ?, ?, ?, ?)""",
        (signal_id, ticker, signal_type, source, issued.isoformat(), conviction,
         ret, ret, ret, NOW.isoformat()),
    )
    conn.commit()
    conn.close()


def _scan_day(path, day, *, ret, per_day=48, ticker="PLTR", prefix=""):
    """하루치 30분 스캔을 그대로 재현한다 (기본 48행)."""
    for i in range(per_day):
        _insert(
            path,
            f"{prefix}{ticker}-d{day}-{i}",
            days_ago=day,
            ret=ret,
            ticker=ticker,
            hour=i % 24,
        )


def _stats(path, **kwargs):
    from unittest.mock import patch

    with patch("signal_tracker._get_conn", lambda: _conn_for(path)):
        from signal_tracker import get_accuracy_stats

        return get_accuracy_stats(**kwargs)


def test_repeated_intraday_scans_collapse_to_one_sample_per_day(db):
    """하루 48회 스캔이 48건으로 세어지던 부분 — 이게 원 문제다."""
    _scan_day(db, day=20, ret=0.05)
    _scan_day(db, day=19, ret=-0.05)

    stats = _stats(db, horizon=7, days_back=90)

    assert stats["sampling"]["rows_raw"] == 96
    assert stats["total_evaluated"] == 2          # 하루 1건
    assert stats["sampling"]["collapse_ratio"] == 48.0
    band = stats["band_outcome"]
    assert band["win"] == 1 and band["loss"] == 1
    assert band["win_rate_pct"] == 50.0
    # 대표 지표는 밴드 없는 방향 적중률이다
    assert stats["direction_hit_rate_pct"] == 50.0


def test_last_row_of_the_day_represents_the_day(db):
    """대표는 그날 마지막 행 — EOD 상태에 가장 가깝다."""
    _insert(db, "early", days_ago=20, ret=0.10, hour=1)
    _insert(db, "late", days_ago=20, ret=-0.10, hour=23)

    stats = _stats(db, horizon=7, days_back=90)

    assert stats["total_evaluated"] == 1
    assert stats["band_outcome"]["loss"] == 1     # 마지막(23시) 행이 뽑혔다
    assert stats["avg_signed_return_pct"] == -10.0   # 매수 신호라 부호 그대로


def test_dedupe_none_reproduces_the_raw_inflated_count(db):
    """원시 집계도 볼 수 있어야 한다 — 다만 기본값이 아니다."""
    _scan_day(db, day=20, ret=0.05)

    raw = _stats(db, horizon=7, days_back=90, dedupe="none")
    sampled = _stats(db, horizon=7, days_back=90)

    assert raw["total_evaluated"] == 48
    assert sampled["total_evaluated"] == 1
    assert raw["sampling"]["mode"] == "none"


def test_confidence_interval_uses_independent_blocks_not_rows(db):
    """행 수로 CI를 계산하면 구간이 거짓으로 좁아진다."""
    # 7일 안에 몰린 5일치 — 수익률 구간이 서로 겹친다
    for day in (20, 19, 18, 17, 16):
        _scan_day(db, day=day, ret=0.05)

    stats = _stats(db, horizon=7, days_back=90)

    assert stats["total_evaluated"] == 5
    # 5일이 같은 7일 블록 1~2개에 들어간다 — 표본 수보다 작아야 한다
    assert stats["independent_blocks"] <= 2
    lo, hi = stats["direction_hit_ci95"]
    assert hi - lo > 40, (lo, hi)   # 블록 1~2개면 구간이 넓어야 정직하다


def test_non_overlapping_mode_keeps_one_row_per_horizon_block(db):
    _scan_day(db, day=20, ret=0.05)
    _scan_day(db, day=19, ret=0.05)
    _scan_day(db, day=5, ret=0.05)

    blocks = _stats(db, horizon=7, days_back=90, dedupe="ticker_horizon")

    assert blocks["sampling"]["mode"] == "ticker_horizon"
    # 20·19일 전은 같은 7일 블록, 5일 전은 다른 블록
    assert blocks["total_evaluated"] == 2


def test_dominant_source_share_is_reported(db):
    """한 소스가 표본을 지배하면 그 사실이 지표와 함께 나와야 한다."""
    for day in range(2, 12):
        _scan_day(db, day=day, ret=0.05, per_day=48)
    _insert(db, "agent-1", days_ago=3, ret=0.05, source="multi_agent_final")

    stats = _stats(db, horizon=7, days_back=90)

    assert stats["sampling"]["dominant_source"] == "scan_agent"
    assert stats["sampling"]["dominant_source_share_pct"] > 80
    assert stats["by_source"]["multi_agent_final"]["total"] == 1


def test_per_ticker_days_are_independent_samples(db):
    """같은 날이라도 종목이 다르면 별개 표본이다."""
    _scan_day(db, day=20, ret=0.05, ticker="PLTR")
    _scan_day(db, day=20, ret=0.05, ticker="MSFT", prefix="m")

    stats = _stats(db, horizon=7, days_back=90)

    assert stats["total_evaluated"] == 2
    assert stats["independent_blocks"] == 2


def test_llm_calibrator_fits_on_deduped_rows(db):
    from llm_calibrator import LLMCalibrator

    _scan_day(db, day=20, ret=0.05)
    _insert(db, "other-day", days_ago=10, ret=-0.05)

    calib = LLMCalibrator(db_path=db)
    df = calib.load_outcomes()

    assert len(df) == 2, "하루 48행이 그대로 학습 표본이 되면 안 된다"


def test_ic_ensemble_loads_deduped_rows(db):
    from ic_ensemble import _load_signal_outcomes

    _scan_day(db, day=20, ret=0.05)
    _insert(db, "agent-1", days_ago=20, ret=0.05, source="multi_agent_final")

    df = _load_signal_outcomes(db_path=db, days=90)

    # scan_agent 48행 → 1행, multi_agent_final 1행 → 소스 간 표본 수가 대등해진다
    assert len(df) == 2
    assert set(df["signal_source"]) == {"scan_agent", "multi_agent_final"}


def test_horizon_buckets_match_the_block_definition(db):
    """표본 단위와 독립 블록이 같은 경계를 써야 한다.

    julianday 를 그대로 나누면 기준점이 기원전 4713년 정오라 블록 경계가 UTC
    자정과 어긋난다. 실측에서 ticker_horizon 표본 358건 > 독립 블록 320건이라는
    모순이 나왔다 — 겹치지 않게 뽑은 표본이 블록보다 많을 수는 없다.
    """
    for day in range(1, 40):
        _insert(db, f"row-{day}", days_ago=day, ret=0.05)

    stats = _stats(db, horizon=7, days_back=90, dedupe="ticker_horizon")

    assert stats["total_evaluated"] == stats["independent_blocks"]
