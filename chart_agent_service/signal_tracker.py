"""
신호 정확도 추적 및 신뢰도 보정 모듈.

기능:
1. evaluate_past_signals(): 과거 스캔 신호의 실제 결과를 평가 (buy/sell이 맞았는가?)
2. get_accuracy_stats(): 신뢰도 구간별·신호별 적중률 통계
3. ConfidenceCalibrator: 과거 성과 기반 신뢰도 보정 (Platt scaling 근사)

실행 주기:
- 일일 cron 또는 scanner의 스케줄러에서 evaluate_past_signals() 호출
- 매주 1회 calibrator.refit()으로 보정 함수 업데이트
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from db import _get_conn

# 평가 horizon (영업일 기준 근사: 7/14/30 캘린더 일)
HORIZONS = [7, 14, 30]

# outcome 판정 threshold (±%)
OUTCOME_THRESHOLD_PCT = 2.0


def insert_signal_outcome(
    ticker: str,
    signal_type: str,
    signal_source: str,
    conviction: float,
    price_at_signal: float,
    market_context: Optional[Dict] = None,
    regime: Optional[str] = None,
) -> str:
    """
    시그널 발주 시점에 signal_outcomes에 row를 생성한다.

    Returns: 생성된 signal_id (UUID4)
    """
    signal_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source,
            issued_at, conviction, price_at_signal,
            market_context, regime)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            signal_id,
            ticker.upper(),
            signal_type.lower(),
            signal_source,
            now,
            conviction,
            price_at_signal,
            json.dumps(market_context) if market_context else None,
            regime,
        ),
    )
    conn.commit()
    conn.close()
    return signal_id


def _latest_close_for(ticker: str, target_date: datetime) -> Optional[float]:
    """
    target_date 이후 첫 거래일의 종가 반환 (yfinance/FDR 사용).
    주말/휴장일은 다음 거래일로 자동 조정.
    """
    try:
        import yfinance as yf

        # target_date부터 +5일 범위에서 첫 유효 데이터
        end = target_date + timedelta(days=7)
        start = target_date - timedelta(days=1)
        t = yf.Ticker(ticker)
        hist = t.history(start=start.date(), end=end.date())
        if hist is None or hist.empty:
            return None
        # target_date와 같거나 이후의 첫 행
        for idx in hist.index:
            idx_naive = (
                idx.tz_localize(None)
                if hasattr(idx, "tz_localize") and idx.tzinfo
                else idx
            )
            if idx_naive.to_pydatetime().date() >= target_date.date():
                return float(hist.loc[idx, "Close"])
        # 없으면 마지막 행
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def _outcome_label(return_pct: float, signal: str) -> str:
    """
    수익률과 신호를 비교하여 win/loss/neutral 판정.
    - buy: +2%↑ win, -2%↓ loss, 그 외 neutral
    - sell: -2%↓ win (공매도/회피 성공), +2%↑ loss, 그 외 neutral
    - neutral: |±2%| 이내 win (안정), 아니면 loss
    """
    if signal == "buy":
        if return_pct > OUTCOME_THRESHOLD_PCT:
            return "win"
        if return_pct < -OUTCOME_THRESHOLD_PCT:
            return "loss"
        return "neutral"
    if signal == "sell":
        if return_pct < -OUTCOME_THRESHOLD_PCT:
            return "win"
        if return_pct > OUTCOME_THRESHOLD_PCT:
            return "loss"
        return "neutral"
    # neutral 신호: 가격 안정이면 적중
    if abs(return_pct) <= OUTCOME_THRESHOLD_PCT:
        return "win"
    return "loss"


def evaluate_past_signals(days_back: int = 45, limit: int = 500) -> Dict:
    """
    과거 스캔 로그를 순회하여 signal_outcomes 테이블을 갱신.

    로직:
    - scan_log에서 아직 30일 outcome이 없는 레코드 조회
    - 각 레코드마다 7/14/30일 후 가격을 가져와 수익률/outcome 계산
    - signal_outcomes UPSERT

    Args:
        days_back: 얼마나 오래된 신호까지 재평가할지 (기본 45일)
        limit: 한 번에 처리할 최대 레코드 수

    Returns:
        처리 통계 dict
    """
    now = datetime.now()
    cutoff = (now - timedelta(days=days_back)).isoformat()

    conn = _get_conn()
    # 30일 평가 완료된 것은 재평가 불필요
    rows = conn.execute(
        """
        SELECT s.id, s.ticker, s.signal, s.score, s.confidence, s.scanned_at, s.entry_price
        FROM scan_log s
        LEFT JOIN signal_outcomes o ON o.scan_log_id = s.id
        WHERE s.scanned_at >= ?
          AND (o.outcome_30d IS NULL)
          AND s.signal IS NOT NULL
          AND s.signal != ''
        ORDER BY s.scanned_at DESC
        LIMIT ?
        """,
        (cutoff, limit),
    ).fetchall()

    processed = 0
    updated = 0
    skipped_no_entry = 0
    errors = 0

    for row in rows:
        scan_log_id = row["id"]
        ticker = row["ticker"]
        signal = (row["signal"] or "").lower()
        scanned_at = datetime.fromisoformat(row["scanned_at"])
        entry_price = row["entry_price"]

        # entry_price가 없으면 scanned_at 당일 종가를 폴백으로 조회
        if not entry_price:
            entry_price = _latest_close_for(ticker, scanned_at)
        if not entry_price:
            skipped_no_entry += 1
            continue

        processed += 1

        # 각 horizon별 미래 가격과 outcome 계산
        horizon_data = {}
        for h in HORIZONS:
            target = scanned_at + timedelta(days=h)
            if target > now:
                # 아직 도달 안 한 horizon은 NULL로 유지
                horizon_data[h] = (None, None, None)
                continue

            future_price = _latest_close_for(ticker, target)
            if future_price is None:
                horizon_data[h] = (None, None, None)
                continue

            ret_pct = (future_price / entry_price - 1) * 100
            outcome = _outcome_label(ret_pct, signal)
            horizon_data[h] = (future_price, round(ret_pct, 3), outcome)

        # UPSERT
        try:
            conn.execute(
                """
                INSERT INTO signal_outcomes
                  (scan_log_id, ticker, signal, score, confidence, scanned_at, entry_price,
                   price_7d, return_7d_pct, outcome_7d,
                   price_14d, return_14d_pct, outcome_14d,
                   price_30d, return_30d_pct, outcome_30d,
                   evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?,  ?, ?, ?,  ?, ?, ?,  ?, ?, ?,  ?)
                ON CONFLICT(scan_log_id) DO UPDATE SET
                  price_7d=excluded.price_7d,
                  return_7d_pct=excluded.return_7d_pct,
                  outcome_7d=excluded.outcome_7d,
                  price_14d=excluded.price_14d,
                  return_14d_pct=excluded.return_14d_pct,
                  outcome_14d=excluded.outcome_14d,
                  price_30d=excluded.price_30d,
                  return_30d_pct=excluded.return_30d_pct,
                  outcome_30d=excluded.outcome_30d,
                  evaluated_at=excluded.evaluated_at
                """,
                (
                    scan_log_id,
                    ticker,
                    signal,
                    row["score"],
                    row["confidence"],
                    row["scanned_at"],
                    entry_price,
                    horizon_data[7][0],
                    horizon_data[7][1],
                    horizon_data[7][2],
                    horizon_data[14][0],
                    horizon_data[14][1],
                    horizon_data[14][2],
                    horizon_data[30][0],
                    horizon_data[30][1],
                    horizon_data[30][2],
                    now.isoformat(),
                ),
            )
            updated += 1
        except Exception:
            errors += 1

    conn.commit()
    conn.close()

    return {
        "processed": processed,
        "updated": updated,
        "skipped_no_entry": skipped_no_entry,
        "errors": errors,
        "scanned_at": now.isoformat(),
    }


def get_accuracy_stats(
    horizon: int = 7,
    min_confidence: float = 0.0,
    signal: Optional[str] = None,
    days_back: int = 180,
) -> Dict:
    """
    신뢰도·신호 조합별 정확도 집계.

    Returns: {
      "horizon_days": int,
      "total_evaluated": int,
      "win_count": int, "loss_count": int, "neutral_count": int,
      "win_rate_pct": float,
      "avg_return_pct": float,
      "by_signal": {"buy": {...}, "sell": {...}, "neutral": {...}},
      "by_confidence_band": [{"band": "7.0-8.0", ...}, ...],
      "sample_size": int,
    }
    """
    if horizon not in HORIZONS:
        horizon = 7

    out_col = f"outcome_{horizon}d"
    ret_col = f"return_{horizon}d_pct"
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()

    conn = _get_conn()

    # 기본 필터
    where_parts = [
        f"{out_col} IS NOT NULL",
        "confidence >= ?",
        "scanned_at >= ?",
    ]
    params: List = [min_confidence, cutoff]
    if signal:
        where_parts.append("signal = ?")
        params.append(signal.lower())
    where = " AND ".join(where_parts)

    # 전체 집계
    row = conn.execute(
        f"""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN {out_col}='win' THEN 1 ELSE 0 END) AS wins,
          SUM(CASE WHEN {out_col}='loss' THEN 1 ELSE 0 END) AS losses,
          SUM(CASE WHEN {out_col}='neutral' THEN 1 ELSE 0 END) AS neutrals,
          AVG({ret_col}) AS avg_return
        FROM signal_outcomes
        WHERE {where}
        """,
        params,
    ).fetchone()

    total = row["total"] or 0
    wins = row["wins"] or 0
    losses = row["losses"] or 0
    neutrals = row["neutrals"] or 0
    win_rate_pct = (wins / total * 100) if total else 0
    avg_return = row["avg_return"] or 0

    # 신호별
    by_signal: Dict[str, Dict] = {}
    for sig in ("buy", "sell", "neutral"):
        r = conn.execute(
            f"""
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN {out_col}='win' THEN 1 ELSE 0 END) AS wins,
              AVG({ret_col}) AS avg_return
            FROM signal_outcomes
            WHERE {out_col} IS NOT NULL AND signal = ? AND scanned_at >= ?
            """,
            (sig, cutoff),
        ).fetchone()
        t = r["total"] or 0
        w = r["wins"] or 0
        by_signal[sig] = {
            "total": t,
            "wins": w,
            "win_rate_pct": round((w / t * 100) if t else 0, 1),
            "avg_return_pct": round(r["avg_return"] or 0, 3),
        }

    # 신뢰도 구간별 (0~2, 2~4, 4~6, 6~8, 8~10)
    bands: List[Dict] = []
    for lo, hi in [(0, 2), (2, 4), (4, 6), (6, 8), (8, 10.1)]:
        r = conn.execute(
            f"""
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN {out_col}='win' THEN 1 ELSE 0 END) AS wins,
              AVG({ret_col}) AS avg_return
            FROM signal_outcomes
            WHERE {out_col} IS NOT NULL
              AND confidence >= ? AND confidence < ?
              AND scanned_at >= ?
            """,
            (lo, hi, cutoff),
        ).fetchone()
        t = r["total"] or 0
        w = r["wins"] or 0
        bands.append(
            {
                "band": f"{lo:.1f}-{min(hi, 10.0):.1f}",
                "total": t,
                "wins": w,
                "win_rate_pct": round((w / t * 100) if t else 0, 1),
                "avg_return_pct": round(r["avg_return"] or 0, 3),
            }
        )

    conn.close()

    return {
        "horizon_days": horizon,
        "min_confidence_filter": min_confidence,
        "days_back": days_back,
        "total_evaluated": total,
        "win_count": wins,
        "loss_count": losses,
        "neutral_count": neutrals,
        "win_rate_pct": round(win_rate_pct, 1),
        "avg_return_pct": round(avg_return, 3),
        "by_signal": by_signal,
        "by_confidence_band": bands,
        "sample_size": total,
    }


# ─────────────────────────────────────────────────────────
#  ConfidenceCalibrator (#9): 과거 성과 기반 신뢰도 보정
# ─────────────────────────────────────────────────────────
class ConfidenceCalibrator:
    """
    신뢰도 구간별 실제 적중률로 raw confidence를 보정.
    간단한 binning 방식 (Platt scaling 대안).

    사용:
        calib = ConfidenceCalibrator()
        calib.refit()
        adjusted = calib.adjust(raw_confidence=8.0, signal="buy")
    """

    # 보정 데이터를 축적하는 최소 표본 (이 이하면 raw 그대로 반환)
    MIN_SAMPLE_SIZE = 50

    def __init__(self, horizon: int = 7):
        self.horizon = horizon
        # band 구간별 실제 win_rate (0-1 스케일)
        # 예: {"buy": {(6,8): 0.62, (8,10): 0.71}, ...}
        self._calibration: Dict[str, Dict[Tuple[float, float], float]] = {}
        self._last_refit: Optional[str] = None
        self._total_samples = 0

    def refit(self, days_back: int = 180):
        """
        DB의 signal_outcomes를 읽어 보정 맵을 재생성.
        표본이 MIN_SAMPLE_SIZE 미만이면 보정 비활성화.
        """
        stats = get_accuracy_stats(horizon=self.horizon, days_back=days_back)
        self._total_samples = stats.get("sample_size", 0)
        self._last_refit = datetime.now().isoformat()

        if self._total_samples < self.MIN_SAMPLE_SIZE:
            self._calibration = {}
            return

        # 각 신호별로 band 구간에서 win_rate 산출
        for sig in ("buy", "sell", "neutral"):
            sig_stats = get_accuracy_stats(
                horizon=self.horizon, signal=sig, days_back=days_back
            )
            if sig_stats["sample_size"] < 10:  # 신호별 최소 10건
                continue
            band_map = {}
            for b in sig_stats["by_confidence_band"]:
                if b["total"] < 5:
                    continue
                lo, hi = (float(x) for x in b["band"].split("-"))
                band_map[(lo, hi)] = b["win_rate_pct"] / 100.0
            if band_map:
                self._calibration[sig] = band_map

    def adjust(self, raw_confidence: float, signal: str) -> float:
        """
        raw_confidence (0-10)를 과거 성과 기반으로 보정.

        로직:
        - 해당 신호·구간의 실제 win_rate를 10점 만점으로 변환
        - 학습 데이터 부족(<MIN_SAMPLE_SIZE)하면 raw 반환
        - 표본 <5인 구간은 raw 반환
        """
        if not self._calibration:
            return raw_confidence

        band_map = self._calibration.get(signal.lower())
        if not band_map:
            return raw_confidence

        for (lo, hi), win_rate in band_map.items():
            if lo <= raw_confidence < hi or (raw_confidence == 10 and hi >= 10):
                # win_rate 0.5 = 중립(confidence 5.0), 1.0 = 최대(10.0)
                calibrated = win_rate * 10.0
                # 급격한 변화 방지: raw와 calibrated의 70:30 혼합
                return round(0.3 * raw_confidence + 0.7 * calibrated, 2)

        return raw_confidence

    def status(self) -> Dict:
        """보정기 상태 (UI 표시용)."""
        active = bool(self._calibration) and self._total_samples >= self.MIN_SAMPLE_SIZE
        return {
            "active": active,
            "total_samples": self._total_samples,
            "last_refit": self._last_refit,
            "min_required": self.MIN_SAMPLE_SIZE,
            "signals_calibrated": list(self._calibration.keys()),
        }


# 전역 싱글톤 (multi_agent/service에서 공유)
_global_calibrator: Optional[ConfidenceCalibrator] = None


def get_calibrator(horizon: int = 7) -> ConfidenceCalibrator:
    global _global_calibrator
    if _global_calibrator is None or _global_calibrator.horizon != horizon:
        _global_calibrator = ConfidenceCalibrator(horizon=horizon)
    return _global_calibrator


# ─────────────────────────────────────────────────────────
#  일일 cron 진입점
# ─────────────────────────────────────────────────────────
def run_daily_validation(
    days_back: int = 45, limit: int = 500, refit_calibrator: bool = True
) -> Dict:
    """
    일일 실행: 과거 신호 평가 + 칼리브레이터 재학습.

    Returns: 처리 통계 + 칼리브레이터 상태
    """
    eval_stats = evaluate_past_signals(days_back=days_back, limit=limit)

    calibrator_status = None
    if refit_calibrator:
        calib = get_calibrator()
        calib.refit(days_back=180)
        calibrator_status = calib.status()

    return {
        "evaluation": eval_stats,
        "calibrator": calibrator_status,
    }


if __name__ == "__main__":
    # 수동 실행 테스트
    print("=" * 60)
    print("Signal Tracker — 수동 실행")
    print("=" * 60)

    print("\n1) 과거 신호 평가 실행 중...")
    stats = evaluate_past_signals(days_back=45, limit=100)
    print(f"  처리: {stats['processed']}, 업데이트: {stats['updated']}")
    print(f"  엔트리가 없음: {stats['skipped_no_entry']}, 에러: {stats['errors']}")

    print("\n2) 7일 horizon 정확도 통계...")
    acc = get_accuracy_stats(horizon=7, days_back=180)
    print(f"  총 평가: {acc['total_evaluated']}건")
    print(f"  승률: {acc['win_rate_pct']}% (평균 수익 {acc['avg_return_pct']}%)")
    for sig, s in acc["by_signal"].items():
        if s["total"]:
            print(f"    {sig}: {s['win_rate_pct']}% (n={s['total']})")

    print("\n3) 신뢰도 칼리브레이터 재학습...")
    calib = get_calibrator()
    calib.refit()
    print(f"  상태: {calib.status()}")
