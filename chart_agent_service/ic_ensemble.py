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
        # (종목, 소스, 발행일)당 1행. 소스별 IC 를 계산하는데 30분 스캔만 하루 48행씩
        # 쌓이면 scan_agent 의 IC 가 표본 수로 다른 소스를 압도한다 (2026-09-10).
        df = pd.read_sql_query(
            """WITH ranked AS (
                   SELECT signal_source, conviction, return_7d, signal_type, issued_at,
                          ROW_NUMBER() OVER (
                              PARTITION BY ticker, signal_source,
                                           substr(issued_at, 1, 10)
                              ORDER BY issued_at DESC
                          ) AS rn
                   FROM signal_outcomes
                   WHERE evaluated_at IS NOT NULL
                     AND return_7d IS NOT NULL
                     AND conviction IS NOT NULL
                     AND issued_at >= ?
               )
               SELECT signal_source, conviction, return_7d, signal_type, issued_at
               FROM ranked WHERE rn = 1
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

    # conviction 은 '이 방향을 얼마나 확신하는가'다. 원시 수익률과 상관을 재면
    # 매도 신호가 맞을수록 IC 가 음수로 잡혀, 잘 맞추는 소스의 가중치가 0이 된다
    # (2026-09-10 방향 보정 감사). 방향 보정 수익률과의 상관을 쓴다.
    scored = _with_signed_return(df)

    ic_map: dict[str, float] = {}
    for source, grp in scored.groupby("signal_source"):
        if len(grp) < _MIN_SAMPLES:
            continue
        rho, pval = spearmanr(grp["conviction"], grp["signed_return"])
        ic_map[str(source)] = float(rho) if not np.isnan(rho) else 0.0
    return ic_map


def _with_signed_return(df: pd.DataFrame) -> pd.DataFrame:
    """방향 보정 수익률 컬럼 추가. 방향이 없는 neutral 행은 제외한다."""
    if df.empty:
        return df
    if "signal_type" not in df.columns:
        # 구 스키마 호출부 — 부호를 알 수 없으면 조용히 원시값을 쓰지 않는다.
        raise KeyError("signal_type 없이는 IC 방향 보정을 할 수 없다")
    from signal_tracker import signed_return

    signed = df.apply(
        lambda r: signed_return(r.get("signal_type"), r["return_7d"]), axis=1
    )
    return df.assign(signed_return=signed).dropna(subset=["signed_return"])


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


def _inactive_reason(df: pd.DataFrame, weights: dict[str, float]) -> Optional[str]:
    """가중치가 비어 있는 이유. 빈 dict 를 '전부 0'으로 보이게 두지 않기 위함."""
    if weights:
        return None
    if df.empty:
        return "signal_outcomes 데이터 없음"
    try:
        span = (
            pd.to_datetime(df["issued_at"].max()) - pd.to_datetime(df["issued_at"].min())
        ).days
        if span < _MIN_DAYS:
            return f"누적 {span}일 < 최소 {_MIN_DAYS}일 — 균등 가중으로 폴백"
    except Exception:
        pass
    return "모든 소스 IC ≤ 0 — 균등 가중으로 폴백"


def get_ic_summary(db_path: Optional[str] = None, days: int = 90) -> dict:
    """IC 현황 요약 (디버깅·모니터링용).

    `weight` 를 항상 숫자로 내면 비활성 상태가 '모든 소스 가중치 0'으로 읽힌다.
    실제로는 `compute_ic_weights()` 가 빈 dict 를 돌려주는 폴백 상태이고, 그건
    '이 소스를 제외한다'와 완전히 다른 뜻이다 (2026-09-10 감사). 비활성이면
    weight 를 None 으로 두고 사유를 함께 낸다.
    """
    df = _load_signal_outcomes(db_path, days)
    if df.empty:
        return {
            "status": "no_data",
            "sources": {},
            "total_rows": 0,
            "active": False,
            "inactive_reason": "signal_outcomes 데이터 없음",
            "applied_in_decisions": False,
        }

    ic_map = compute_ic_per_source(df)
    weights = compute_ic_weights(db_path=db_path, days=days)
    active = bool(weights)

    return {
        "status": "ok",
        "total_rows": len(df),
        "days_range": days,
        "active": active,
        "inactive_reason": _inactive_reason(df, weights),
        "min_days_required": _MIN_DAYS,
        # IC 가중은 계산만 되고 판정 경로에 연결돼 있지 않다 (apply_ic_weights 호출부 없음).
        # 있는 것처럼 보이는 지표가 실제로 아무 데도 쓰이지 않는 상태를 명시한다.
        "applied_in_decisions": False,
        "sources": {
            src: {
                "ic": round(ic, 4),
                "weight": (weights.get(src, 0.0) if active else None),
            }
            for src, ic in ic_map.items()
        },
    }
