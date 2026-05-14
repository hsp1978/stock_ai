"""
IC(Information Coefficient)-weighted Ensemble (P2).

signal_outcomes 테이블의 60일 누적 데이터에서
에이전트·소스별 IC(예측-실현 수익률 상관)를 계산하고
이를 ensemble 가중치로 사용한다.

IC = Spearman correlation(conviction, return_7d)

최소 60일 데이터가 없으면 균등 가중치(equal-weight)로 폴백한다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_MIN_SAMPLES = 10  # 소스당 최소 샘플 수
_MIN_DAYS = 60  # IC 계산에 필요한 최소 누적 일수


def _load_signal_outcomes(
    db_path: Optional[str] = None, days: int = 90
) -> pd.DataFrame:
    """signal_outcomes에서 evaluated 데이터를 로드한다."""
    import sqlite3

    if db_path is None:
        from config import OUTPUT_DIR
        import os

        db_path = os.path.join(OUTPUT_DIR, "scan_log.db")

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            """SELECT signal_source, conviction, return_7d, issued_at
               FROM signal_outcomes
               WHERE evaluated_at IS NOT NULL
                 AND return_7d IS NOT NULL
                 AND conviction IS NOT NULL
                 AND issued_at >= ?
               ORDER BY issued_at DESC""",
            conn,
            params=(cutoff,),
        )
    except Exception as exc:
        logger.warning("signal_outcomes 로드 실패: %s", exc)
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


def compute_ic_per_source(df: pd.DataFrame) -> dict[str, float]:
    """
    소스별 IC(Spearman ρ)를 계산한다.

    IC > 0 : conviction과 실현 수익률 양의 상관 → 신뢰할 수 있는 소스
    IC < 0 : 역방향 → 가중치 0으로 처리

    Returns:
        {source_name: ic_value}
    """
    from scipy.stats import spearmanr  # type: ignore[import-untyped]

    ic_map: dict[str, float] = {}
    for source, grp in df.groupby("signal_source"):
        if len(grp) < _MIN_SAMPLES:
            continue
        rho, pval = spearmanr(grp["conviction"], grp["return_7d"])
        ic_map[str(source)] = float(rho) if not np.isnan(rho) else 0.0
    return ic_map


def compute_ic_weights(
    db_path: Optional[str] = None,
    sources: Optional[list[str]] = None,
    days: int = 90,
) -> dict[str, float]:
    """
    소스별 IC-based 가중치를 계산한다.

    - IC ≤ 0인 소스는 가중치 0
    - 나머지는 IC 값에 비례해 정규화 (합 = 1)
    - 데이터 부족 시 균등 가중치 반환

    Args:
        db_path: SQLite DB 경로 (None → 기본)
        sources: 가중치를 계산할 소스 목록 (None → 전체)
        days:    과거 N일 데이터 사용

    Returns:
        {source_name: weight}  (합 = 1.0)
    """
    df = _load_signal_outcomes(db_path, days)

    if df.empty:
        logger.info("IC 계산: signal_outcomes 데이터 없음 → 균등 가중치")
        return _equal_weights(sources)

    # 최소 60일 경과 확인
    if "issued_at" in df.columns and len(df) > 0:
        try:
            oldest = pd.to_datetime(df["issued_at"].min())
            newest = pd.to_datetime(df["issued_at"].max())
            span_days = (newest - oldest).days
            if span_days < _MIN_DAYS:
                logger.info(
                    "IC 계산: 데이터 누적 %d일 < %d일 최소치 → 균등 가중치",
                    span_days,
                    _MIN_DAYS,
                )
                return _equal_weights(sources)
        except Exception:
            pass

    ic_map = compute_ic_per_source(df)

    if sources:
        # 요청된 소스만 필터링
        ic_map = {k: v for k, v in ic_map.items() if k in sources}

    if not ic_map:
        return _equal_weights(sources)

    # 음의 IC → 0 처리, 양의 IC만 사용
    positive = {k: max(v, 0.0) for k, v in ic_map.items()}
    total = sum(positive.values())

    if total < 1e-10:
        logger.info("IC 계산: 모든 소스 IC ≤ 0 → 균등 가중치")
        return _equal_weights(list(positive.keys()))

    return {k: round(v / total, 4) for k, v in positive.items()}


def _equal_weights(sources: Optional[list[str]]) -> dict[str, float]:
    if not sources:
        return {}
    w = round(1.0 / len(sources), 4)
    return {s: w for s in sources}


def apply_ic_weights(
    source_signals: dict[str, tuple[str, float]],
    ic_weights: dict[str, float],
) -> tuple[str, float]:
    """
    IC 가중치를 적용해 최종 신호와 conviction을 산출한다.

    Args:
        source_signals: {source: (signal, conviction)}  signal: buy/sell/neutral
        ic_weights:     {source: weight}

    Returns:
        (final_signal, final_conviction)
    """
    _score = {"buy": 1.0, "sell": -1.0, "neutral": 0.0}

    weighted_score = 0.0
    total_weight = 0.0

    for source, (signal, conviction) in source_signals.items():
        w = ic_weights.get(source, 0.0)
        weighted_score += _score.get(signal, 0.0) * conviction * w
        total_weight += w

    if total_weight < 1e-10:
        return "neutral", 0.0

    final_score = weighted_score / total_weight
    final_signal = (
        "buy" if final_score > 0.3 else "sell" if final_score < -0.3 else "neutral"
    )
    final_conviction = min(10.0, abs(final_score))

    return final_signal, round(final_conviction, 3)


def get_ic_summary(db_path: Optional[str] = None, days: int = 90) -> dict:
    """IC 현황 요약 (디버깅·모니터링용)."""
    df = _load_signal_outcomes(db_path, days)
    if df.empty:
        return {"status": "no_data", "sources": {}, "total_rows": 0}

    ic_map = compute_ic_per_source(df)
    weights = compute_ic_weights(db_path=db_path, days=days)

    return {
        "status": "ok",
        "total_rows": len(df),
        "days_range": days,
        "sources": {
            src: {"ic": round(ic, 4), "weight": weights.get(src, 0.0)}
            for src, ic in ic_map.items()
        },
    }
