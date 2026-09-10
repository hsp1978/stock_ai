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
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from db import _get_conn

# 평가 horizon (영업일 기준 근사: 7/14/30 캘린더 일)
HORIZONS = [7, 14, 30]

# outcome 판정 threshold (±%)
OUTCOME_THRESHOLD_PCT = 2.0

# 가격 조회 창 — target 하루 전부터 7일 뒤까지에서 첫 거래일 종가를 찾는다.
_PRICE_WINDOW_BEFORE_DAYS = 1
_PRICE_WINDOW_AFTER_DAYS = 7


def _eval_setting(name: str, default: int) -> int:
    """평가 큐 파라미터를 config에서 읽는다 (config 없이 import되는 테스트 환경 대비)."""
    try:
        from config import settings

        value = getattr(settings, name, default)
        return int(value) if value is not None else default
    except Exception:
        return default


def insert_signal_outcome(
    ticker: str,
    signal_type: str,
    signal_source: str,
    conviction: float,
    price_at_signal: float,
    market_context: Optional[Dict] = None,
    regime: Optional[str] = None,
    signal_std: Optional[float] = None,
    agreement_level: Optional[str] = None,
) -> str:
    """
    시그널 발주 시점에 signal_outcomes에 row를 생성한다.

    Step 12: signal_std, agreement_level 추가.
    Returns: 생성된 signal_id (UUID4)
    """
    signal_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        """INSERT INTO signal_outcomes
           (signal_id, ticker, signal_type, signal_source,
            issued_at, conviction, price_at_signal,
            market_context, regime, signal_std, agreement_level)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            signal_std,
            agreement_level,
        ),
    )
    conn.commit()
    conn.close()
    return signal_id


# 런(run) 스코프 가격 캐시 — 스레드별로 분리한다.
# 스케줄러 잡과 수동 엔드포인트가 동시에 돌 수 있고, 프레임을 런 밖으로 들고 가면
# 어제 내려받은 데이터로 오늘의 horizon을 채우는 stale 평가가 된다.
_PRICE_CACHE = threading.local()


def _cache_frames() -> Optional[dict]:
    return getattr(_PRICE_CACHE, "frames", None)


def _select_close(hist, target_date: datetime) -> Optional[float]:
    """조회 창 안에서 target_date와 같거나 이후인 첫 종가. 없으면 창의 마지막 종가."""
    if hist is None or hist.empty:
        return None
    for idx in hist.index:
        idx_naive = (
            idx.tz_localize(None)
            if hasattr(idx, "tz_localize") and idx.tzinfo
            else idx
        )
        if idx_naive.to_pydatetime().date() >= target_date.date():
            return float(hist.loc[idx, "Close"])
    return float(hist["Close"].iloc[-1])


def _window_bounds(target_date: datetime) -> Tuple[datetime, datetime]:
    return (
        target_date - timedelta(days=_PRICE_WINDOW_BEFORE_DAYS),
        target_date + timedelta(days=_PRICE_WINDOW_AFTER_DAYS),
    )


def _fetch_history(ticker: str, start: datetime, end: datetime):
    import yfinance as yf

    return yf.Ticker(ticker).history(start=start.date(), end=end.date())


def _slice_window(frame, target_date: datetime):
    """캐시된 프레임에서 이 target의 조회 창만 잘라낸다 (선택 규칙을 창 밖으로 넓히지 않기 위함)."""
    if frame is None or frame.empty:
        return None
    import pandas as pd

    start, end = _window_bounds(target_date)
    index = frame.index
    naive = index.tz_localize(None) if getattr(index, "tz", None) is not None else index
    mask = (naive >= pd.Timestamp(start.date())) & (naive < pd.Timestamp(end.date()))
    sliced = frame[mask]
    return None if sliced.empty else sliced


def _latest_close_for(ticker: str, target_date: datetime) -> Optional[float]:
    """
    target_date 이후 첫 거래일의 종가 반환 (yfinance/FDR 사용).
    주말/휴장일은 다음 거래일로 자동 조정.

    런 스코프 캐시(`prefetch_price_history`)가 warm이면 네트워크를 타지 않는다.
    캐시 미스는 실패가 아니므로 종전처럼 개별 조회로 폴백한다.
    """
    frames = _cache_frames()
    if frames is not None and ticker in getattr(_PRICE_CACHE, "requested", ()):
        frame = frames.get(ticker)
        if frame is None:
            # 배치 조회가 이미 실패한 티커 — 개별 조회로 수천 회 되돌리지 않는다.
            # 다음 런에서 다시 시도한다.
            return None
        sliced = _slice_window(frame, target_date)
        if sliced is None:
            # 이 창에 거래일 데이터가 없다 = 아직 시세가 없거나 상장폐지.
            return None
        try:
            return _select_close(sliced, target_date)
        except Exception:
            return None
    try:
        start, end = _window_bounds(target_date)
        return _select_close(_fetch_history(ticker, start, end), target_date)
    except Exception:
        return None


def prefetch_price_history(needs: Dict[str, Tuple[datetime, datetime]]) -> Dict:
    """티커별로 필요한 전체 구간을 한 번씩만 내려받아 런 스코프 캐시에 적재한다.

    Why: 종전에는 (행 x horizon)마다 `history()`를 호출했다. 백로그 4,000행이면
    1만 회 이상 왕복이라 야간 배치 안에 끝나지 않고, rate limit에 걸린 실패가
    '평가할 게 없음'과 구별되지 않는다 (2026-09 진단).
    """
    frames: dict = {}
    failed: list = []
    for ticker, (start, end) in needs.items():
        try:
            frame = _fetch_history(
                ticker,
                start - timedelta(days=_PRICE_WINDOW_BEFORE_DAYS),
                end + timedelta(days=_PRICE_WINDOW_AFTER_DAYS),
            )
            if frame is None or frame.empty:
                failed.append(ticker)
                continue
            frames[ticker] = frame
        except Exception as exc:  # 개별 티커 실패가 런 전체를 죽이지 않게 한다
            print(f"[signal_tracker] {ticker} 시세 배치 조회 실패: {exc}")
            failed.append(ticker)
    _PRICE_CACHE.frames = frames
    _PRICE_CACHE.requested = set(needs)
    return {
        "tickers_requested": len(needs),
        "tickers_cached": len(frames),
        "tickers_failed": failed,
    }


def clear_price_history_cache() -> None:
    _PRICE_CACHE.frames = None
    _PRICE_CACHE.requested = set()


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


def get_tracking_health(days_back: int = 7) -> Dict:
    """signal_outcomes 기록 파이프라인 생존 확인.

    2026-07 감사에서 83일간 무기록 버그(중첩 키·가격 부재)가 무음으로
    방치된 재발 방지용. 방향성 신호(스캔 BUY/SELL)가 발생했는데 최근
    outcomes가 0건이면 'silent'로 판정한다.

    Returns:
        {status: ok|silent|no_signals, outcomes_recent, directional_scans_recent, days_back}
    """
    import sqlite3

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    conn = _get_conn()
    try:
        outcomes = conn.execute(
            "SELECT COUNT(*) FROM signal_outcomes WHERE issued_at >= ?", (cutoff,)
        ).fetchone()[0]
        try:
            directional_scans = conn.execute(
                "SELECT COUNT(*) FROM scan_log "
                "WHERE UPPER(signal) IN ('BUY', 'SELL') AND scanned_at >= ?",
                (cutoff,),
            ).fetchone()[0]
        except sqlite3.OperationalError:
            # scan_log 테이블이 없는 환경(테스트 등)에서는 판정 불가
            directional_scans = None
    finally:
        conn.close()

    if outcomes > 0:
        status = "ok"
    elif directional_scans:
        status = "silent"  # 신호는 발생했는데 기록 0 → 추적 파이프라인 사망 의심
    else:
        status = "no_signals"  # 방향성 신호 자체가 없었음 (정상 가능)

    return {
        "status": status,
        "outcomes_recent": outcomes,
        "directional_scans_recent": directional_scans,
        "days_back": days_back,
    }


# 도래한 horizon이 하나라도 남아 있는 행만 고른다.
# 종전 조건(`return_7d IS NULL OR ...`)은 **발행 직후 행까지 후보로 잡았고**,
# 정렬이 issued_at DESC 였다. 하루 100건 이상 적립되는 현재 규모에서는 매 런마다
# 최신 5일치 500건만 뽑히고 그 전부가 7일 미도래 → 4,201건이 영구 대기했다
# (2026-09-10 진단: processed 0 / skipped_not_due 500, 08-06 이후 평가 0건).
_DUE_FILTER = """
        price_at_signal IS NOT NULL
        AND issued_at >= :cutoff
        AND (
              (return_7d  IS NULL AND issued_at <= :due_7)
           OR (return_14d IS NULL AND issued_at <= :due_14)
           OR (return_30d IS NULL AND issued_at <= :due_30)
        )
"""


def _due_params(now: datetime, days_back: int) -> Dict[str, str]:
    params = {"cutoff": (now - timedelta(days=days_back)).isoformat()}
    for h in HORIZONS:
        params[f"due_{h}"] = (now - timedelta(days=h)).isoformat()
    return params


def _backlog_snapshot(conn, now: datetime, days_back: int) -> Dict:
    """평가 대기 잔량. '완료'로 보고되는 런이 실제로는 아무것도 못 했는지 드러낸다."""
    params = _due_params(now, days_back)
    row = conn.execute(
        f"SELECT COUNT(*) AS n, MIN(issued_at) AS oldest FROM signal_outcomes "
        f"WHERE {_DUE_FILTER}",
        params,
    ).fetchone()
    pending = int(row["n"] or 0)
    oldest = row["oldest"]
    expired = conn.execute(
        """
        SELECT COUNT(*) FROM signal_outcomes
        WHERE price_at_signal IS NOT NULL
          AND issued_at < :cutoff
          AND (return_7d IS NULL OR return_14d IS NULL OR return_30d IS NULL)
        """,
        {"cutoff": params["cutoff"]},
    ).fetchone()[0]
    oldest_days = None
    if oldest:
        try:
            issued = datetime.fromisoformat(oldest)
            if issued.tzinfo is None:
                issued = issued.replace(tzinfo=timezone.utc)
            oldest_days = round((now - issued).total_seconds() / 86400, 1)
        except ValueError:
            oldest_days = None
    return {
        "pending_due": pending,
        "oldest_pending_at": oldest,
        "oldest_pending_days": oldest_days,
        # days_back 창을 벗어나 다시는 후보가 되지 않는 행. 창을 늘려야 하는 신호다.
        "expired_unevaluated": int(expired or 0),
    }


def _price_needs(rows, now: datetime) -> Dict[str, Tuple[datetime, datetime]]:
    """티커별로 이 런에서 필요한 target 날짜의 최소~최대 구간."""
    needs: Dict[str, Tuple[datetime, datetime]] = {}
    for row in rows:
        if not row["price_at_signal"]:
            continue
        issued_at = _as_utc(row["issued_at"])
        if issued_at is None:
            continue
        targets = [
            issued_at + timedelta(days=h)
            for h in HORIZONS
            if row[f"return_{h}d"] is None and issued_at + timedelta(days=h) <= now
        ]
        if not targets:
            continue
        lo, hi = min(targets), max(targets)
        prev = needs.get(row["ticker"])
        needs[row["ticker"]] = (
            (lo, hi) if prev is None else (min(prev[0], lo), max(prev[1], hi))
        )
    return needs


def _as_utc(value) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def evaluate_past_signals(
    days_back: Optional[int] = None, limit: Optional[int] = None
) -> Dict:
    """
    과거 signal_outcomes 레코드를 순회하여 실제 수익률을 갱신.

    로직:
    - horizon이 도래했고 아직 수익률이 없는 레코드를 **오래된 것부터** 조회
    - 티커별 시세를 한 번에 프리페치 (행 x horizon 개별 조회 제거)
    - 각 레코드마다 7/14/30일 후 가격으로 수익률 계산 후 UPDATE
    - 잔량(pending_due)을 함께 반환 — 아무것도 못 한 런이 '완료'로 보이지 않게 한다

    Args:
        days_back: 얼마나 오래된 신호까지 재평가할지 (기본 SIGNAL_EVAL_DAYS_BACK)
        limit: 한 번에 처리할 최대 레코드 수 (기본 SIGNAL_EVAL_BATCH_LIMIT)

    Returns:
        처리 통계 dict
    """
    days_back = _eval_setting("SIGNAL_EVAL_DAYS_BACK", 90) if days_back is None else days_back
    limit = _eval_setting("SIGNAL_EVAL_BATCH_LIMIT", 2000) if limit is None else limit
    now = datetime.now(timezone.utc)
    params = _due_params(now, days_back)

    conn = _get_conn()
    rows = conn.execute(
        f"""
        SELECT signal_id, ticker, signal_type, signal_source,
               issued_at, conviction, price_at_signal,
               price_7d, price_14d, price_30d,
               return_7d, return_14d, return_30d
        FROM signal_outcomes
        WHERE {_DUE_FILTER}
        ORDER BY issued_at ASC
        LIMIT :limit
        """,
        {**params, "limit": limit},
    ).fetchall()

    backlog_before = _backlog_snapshot(conn, now, days_back)
    prefetch = prefetch_price_history(_price_needs(rows, now))

    processed = 0
    updated = 0
    skipped_no_entry = 0
    skipped_not_due = 0
    skipped_no_price = 0
    errors = 0
    # 이번 런에서 **새로 채운** horizon 수. 종전에는 이미 채워져 있던 horizon도
    # 여기에 더해져서, 아무것도 안 한 런이 "completed_by_horizon 500"으로 보였다.
    completed_by_horizon = {h: 0 for h in HORIZONS}
    already_complete_by_horizon = {h: 0 for h in HORIZONS}

    for row in rows:
        signal_id = row["signal_id"]
        ticker = row["ticker"]
        issued_at = _as_utc(row["issued_at"])
        entry_price = row["price_at_signal"]
        if issued_at is None or not entry_price:
            skipped_no_entry += 1
            continue

        # 각 horizon별 미래 가격과 outcome 계산
        horizon_data = {}
        row_updated = False
        price_missing = False
        for h in HORIZONS:
            ret_key = f"return_{h}d"
            price_key = f"price_{h}d"
            if row[ret_key] is not None:
                horizon_data[h] = (row[price_key], row[ret_key])
                already_complete_by_horizon[h] += 1
                continue

            target = issued_at + timedelta(days=h)
            if target > now:
                horizon_data[h] = (row[price_key], row[ret_key])
                continue

            future_price = _latest_close_for(ticker, target)
            if future_price is None:
                horizon_data[h] = (row[price_key], row[ret_key])
                price_missing = True
                continue

            ret = future_price / entry_price - 1
            horizon_data[h] = (future_price, round(ret, 6))
            completed_by_horizon[h] += 1
            row_updated = True

        if not row_updated:
            # 도래한 horizon만 후보로 뽑으므로, 여기 걸리는 건 시세를 못 받은 경우다.
            # 두 사유를 같은 카운터에 담으면 rate limit 장애가 '평가할 게 없음'으로 읽힌다.
            if price_missing:
                skipped_no_price += 1
            else:
                skipped_not_due += 1
            continue

        processed += 1

        try:
            conn.execute(
                """
                UPDATE signal_outcomes
                SET price_7d=?, return_7d=?,
                    price_14d=?, return_14d=?,
                    price_30d=?, return_30d=?,
                    evaluated_at=?
                WHERE signal_id=?
                """,
                (
                    horizon_data[7][0],
                    horizon_data[7][1],
                    horizon_data[14][0],
                    horizon_data[14][1],
                    horizon_data[30][0],
                    horizon_data[30][1],
                    now.isoformat(),
                    signal_id,
                ),
            )
            updated += 1
        except Exception as exc:
            print(f"[signal_tracker] {ticker} ({signal_id}) 평가 실패: {exc}")
            errors += 1

    conn.commit()
    backlog_after = _backlog_snapshot(conn, now, days_back)
    conn.close()
    clear_price_history_cache()

    return {
        "processed": processed,
        "updated": updated,
        "skipped_no_entry": skipped_no_entry,
        "skipped_not_due": skipped_not_due,
        "skipped_no_price": skipped_no_price,
        "errors": errors,
        "completed_by_horizon": completed_by_horizon,
        "already_complete_by_horizon": already_complete_by_horizon,
        "candidates": len(rows),
        "days_back": days_back,
        "limit": limit,
        "prefetch": prefetch,
        "pending_due_before": backlog_before["pending_due"],
        "pending_due": backlog_after["pending_due"],
        "oldest_pending_at": backlog_after["oldest_pending_at"],
        "oldest_pending_days": backlog_after["oldest_pending_days"],
        "expired_unevaluated": backlog_after["expired_unevaluated"],
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

    ret_col = f"return_{horizon}d"
    threshold = OUTCOME_THRESHOLD_PCT / 100.0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

    conn = _get_conn()

    # 기본 필터
    where_parts = [
        f"{ret_col} IS NOT NULL",
        "conviction >= ?",
        "issued_at >= ?",
    ]
    params: List = [min_confidence, cutoff]
    if signal:
        where_parts.append("signal_type = ?")
        params.append(signal.lower())
    where = " AND ".join(where_parts)
    outcome_case = f"""
        CASE
          WHEN signal_type='buy' AND {ret_col} > {threshold} THEN 'win'
          WHEN signal_type='buy' AND {ret_col} < -{threshold} THEN 'loss'
          WHEN signal_type='buy' THEN 'neutral'
          WHEN signal_type='sell' AND {ret_col} < -{threshold} THEN 'win'
          WHEN signal_type='sell' AND {ret_col} > {threshold} THEN 'loss'
          WHEN signal_type='sell' THEN 'neutral'
          WHEN ABS({ret_col}) <= {threshold} THEN 'win'
          ELSE 'loss'
        END
    """

    # 전체 집계
    row = conn.execute(
        f"""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN ({outcome_case})='win' THEN 1 ELSE 0 END) AS wins,
          SUM(CASE WHEN ({outcome_case})='loss' THEN 1 ELSE 0 END) AS losses,
          SUM(CASE WHEN ({outcome_case})='neutral' THEN 1 ELSE 0 END) AS neutrals,
          AVG({ret_col}) * 100.0 AS avg_return
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
              SUM(CASE WHEN ({outcome_case})='win' THEN 1 ELSE 0 END) AS wins,
              AVG({ret_col}) * 100.0 AS avg_return
            FROM signal_outcomes
            WHERE {ret_col} IS NOT NULL
              AND signal_type = ?
              AND conviction >= ?
              AND issued_at >= ?
            """,
            (sig, min_confidence, cutoff),
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
              SUM(CASE WHEN ({outcome_case})='win' THEN 1 ELSE 0 END) AS wins,
              AVG({ret_col}) * 100.0 AS avg_return
            FROM signal_outcomes
            WHERE {ret_col} IS NOT NULL
              AND conviction >= ? AND conviction < ?
              AND issued_at >= ?
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

    by_source: Dict[str, Dict] = {}
    source_rows = conn.execute(
        f"""
        SELECT
          signal_source,
          COUNT(*) AS total,
          SUM(CASE WHEN ({outcome_case})='win' THEN 1 ELSE 0 END) AS wins,
          AVG({ret_col}) * 100.0 AS avg_return
        FROM signal_outcomes
        WHERE {where}
        GROUP BY signal_source
        ORDER BY total DESC
        """,
        params,
    ).fetchall()
    for r in source_rows:
        t = r["total"] or 0
        w = r["wins"] or 0
        by_source[r["signal_source"] or "unknown"] = {
            "total": t,
            "wins": w,
            "win_rate_pct": round((w / t * 100) if t else 0, 1),
            "avg_return_pct": round(r["avg_return"] or 0, 3),
        }

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
        "by_source": by_source,
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
    days_back: Optional[int] = None,
    limit: Optional[int] = None,
    refit_calibrator: bool = True,
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
    stats = evaluate_past_signals(limit=100)
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
