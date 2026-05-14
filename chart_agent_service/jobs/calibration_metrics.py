"""
신호 보정 지표 계산 (Step 4).

compute_ece(): Expected Calibration Error
"""

from __future__ import annotations

import pandas as pd


def compute_ece(df: pd.DataFrame, n_bins: int = 10) -> float:
    """
    Expected Calibration Error.

    Args:
        df: signal_outcomes 행들 (conviction, return_7d 컬럼 필수)
        n_bins: conviction을 나눌 구간 수

    Returns:
        ECE (낮을수록 conviction이 실제 적중률에 잘 보정됨)
    """
    if df.empty or "conviction" not in df.columns or "return_7d" not in df.columns:
        return float("nan")

    valid = df[["conviction", "return_7d"]].dropna()
    if valid.empty:
        return float("nan")

    # conviction 0~10 → 0~1 정규화
    valid = valid.copy()
    valid["conf_norm"] = valid["conviction"].clip(0, 10) / 10.0

    bins = pd.cut(valid["conf_norm"], bins=n_bins, labels=False, include_lowest=True)
    ece = 0.0
    n_total = len(valid)

    for b in range(n_bins):
        group = valid[bins == b]
        if len(group) == 0:
            continue
        avg_conf = group["conf_norm"].mean()
        accuracy = (group["return_7d"] > 0).mean()
        ece += len(group) / n_total * abs(avg_conf - accuracy)

    return float(ece)
