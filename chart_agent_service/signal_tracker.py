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

# 마지막 horizon이 도래한 뒤 이만큼 더 기다려도 시세가 없으면 종결 처리한다.
# 존재하지 않는 심볼(예: 057050.KS — yfinance 404, 실제로는 .KQ)로 적립된 행이
# 매일 재시도되며 잔량·경고를 영구히 붙잡고 있는 것을 막는다.
_UNRESOLVED_GRACE_DAYS = 14
_STATE_UNRESOLVED = "unresolved"


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


# 시장 벤치마크 — 절대 수익만 보면 '시장이 올라서 오른 것'과 '신호가 맞아서
# 오른 것'을 구분할 수 없다. 종목의 시장을 따라 지수를 고른다.
_BENCHMARKS = {"KQ": "^KQ11", "KS": "^KS11", "US": "^GSPC"}


def benchmark_for(ticker: str) -> str:
    """종목의 벤치마크 지수 심볼."""
    upper = (ticker or "").upper()
    if upper.endswith(".KQ"):
        return _BENCHMARKS["KQ"]
    if upper.endswith(".KS"):
        return _BENCHMARKS["KS"]
    return _BENCHMARKS["US"]


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


# data_collector 의 period 는 **오늘 기준 과거 구간**이다. 따라서 필요한 것은
# target 들의 폭(span)이 아니라 **가장 오래된 target 이 며칠 전인지**다.
# span 으로 잡으면 85일 전에 몰린 배치가 "3mo"(≈92일)로 요청돼 경계에서 샌다.
_PERIOD_BY_LOOKBACK = ((25, "3mo"), (80, "6mo"), (280, "1y"), (550, "2y"))


def _period_for_lookback(lookback_days: float) -> str:
    """lookback_days 만큼의 과거를 여유 있게 덮는 period 문자열."""
    for limit, period in _PERIOD_BY_LOOKBACK:
        if lookback_days <= limit:
            return period
    return "5y"


def _fetch_history(ticker: str, start: datetime, end: datetime):
    """구간을 덮는 OHLCV — 설정된 데이터 소스 체인을 그대로 쓴다.

    Why: 사후 평가만 yfinance 를 직접 호출하고 있었다. 시스템의 다른 모든 경로는
    `data_collector`(설정 소스 → 한국 pykrx/FDR/yfinance → 미국 yfinance/FDR)를
    타는데, 평가만 우회한 탓에 Toss·pykrx 로는 받아지는 종목이 여기서만 404 로
    죽었다 (`057050.KS` 53건 종결, 2026-09-10). 소스가 갈리면 평가에 쓰는 가격이
    시스템이 실제로 본 가격과 달라질 수 있다는 문제도 함께 남는다.

    yfinance 직접 호출은 data_collector 를 import 할 수 없는 환경의 폴백으로만 남긴다.
    """
    lookback_days = (
        max((datetime.now(timezone.utc) - start).days, (end - start).days, 0)
        + _PRICE_WINDOW_BEFORE_DAYS
    )
    try:
        from data_collector import fetch_ohlcv
    except Exception:
        import yfinance as yf

        return yf.Ticker(ticker).history(start=start.date(), end=end.date())

    frame = fetch_ohlcv(ticker, period=_period_for_lookback(lookback_days))
    if frame is None or frame.empty or "Close" not in frame.columns:
        return None
    return frame


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
        AND eval_state IS NULL
        AND issued_at >= :cutoff
        AND (
              (return_7d  IS NULL AND issued_at <= :due_7)
           OR (return_14d IS NULL AND issued_at <= :due_14)
           OR (return_30d IS NULL AND issued_at <= :due_30)
           -- 수익률은 채워졌는데 시장 수익률이 비어 있는 행도 대상이다
           -- (벤치마크 컬럼 도입 전 평가분 소급 채움).
           OR (return_7d  IS NOT NULL AND benchmark_return_7d  IS NULL)
           OR (return_14d IS NOT NULL AND benchmark_return_14d IS NULL)
           OR (return_30d IS NOT NULL AND benchmark_return_30d IS NULL)
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
          AND eval_state IS NULL
          AND issued_at < :cutoff
          AND (return_7d IS NULL OR return_14d IS NULL OR return_30d IS NULL)
        """,
        {"cutoff": params["cutoff"]},
    ).fetchone()[0]
    unresolved = conn.execute(
        "SELECT COUNT(*) FROM signal_outcomes WHERE eval_state = ?",
        (_STATE_UNRESOLVED,),
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
        # 시세 소스에 심볼이 없어 종결된 행 (재시도 대상 아님, 통계에도 안 들어간다)
        "unresolved_total": int(unresolved or 0),
    }


def _price_needs(rows, now: datetime) -> Dict[str, Tuple[datetime, datetime]]:
    """티커별로 이 런에서 필요한 target 날짜의 최소~최대 구간.

    벤치마크 지수도 같은 방식으로 프리페치한다 — 종목당이 아니라 시장당 1회라
    비용이 거의 없다. 벤치마크 구간은 **발행일부터** 필요하다(수익률 계산 기준점).
    """
    needs: Dict[str, Tuple[datetime, datetime]] = {}

    def _extend(symbol: str, lo: datetime, hi: datetime) -> None:
        prev = needs.get(symbol)
        needs[symbol] = (
            (lo, hi) if prev is None else (min(prev[0], lo), max(prev[1], hi))
        )

    for row in rows:
        if not row["price_at_signal"]:
            continue
        issued_at = _as_utc(row["issued_at"])
        if issued_at is None:
            continue
        targets = [
            issued_at + timedelta(days=h)
            for h in HORIZONS
            if issued_at + timedelta(days=h) <= now
            and (
                row[f"return_{h}d"] is None
                or row[f"benchmark_return_{h}d"] is None
            )
        ]
        if not targets:
            continue
        lo, hi = min(targets), max(targets)
        _extend(row["ticker"], lo, hi)
        # 지수는 발행일 종가가 기준점이므로 구간을 발행일까지 넓힌다.
        _extend(benchmark_for(row["ticker"]), min(issued_at, lo), hi)
    return needs


def _as_utc(value) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _reset_unresolved(conn, now: datetime, days_back: int) -> int:
    """창 안의 종결(unresolved) 행을 다시 대기로 돌린다.

    데이터 소스가 바뀐 뒤(예: 평가 경로를 data_collector 로 통일) 한 번 돌려주면
    종전 소스로만 실패했던 행이 재시도된다. 여전히 시세가 없으면 다시 종결된다.
    """
    cutoff = (now - timedelta(days=days_back)).isoformat()
    cur = conn.execute(
        "UPDATE signal_outcomes SET eval_state=NULL "
        "WHERE eval_state=? AND issued_at >= ?",
        (_STATE_UNRESOLVED, cutoff),
    )
    return cur.rowcount or 0


def evaluate_past_signals(
    days_back: Optional[int] = None,
    limit: Optional[int] = None,
    reset_unresolved: bool = False,
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
    reset_count = _reset_unresolved(conn, now, days_back) if reset_unresolved else 0
    rows = conn.execute(
        f"""
        SELECT signal_id, ticker, signal_type, signal_source,
               issued_at, conviction, price_at_signal,
               price_7d, price_14d, price_30d,
               return_7d, return_14d, return_30d,
               benchmark_symbol,
               benchmark_return_7d, benchmark_return_14d, benchmark_return_30d
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
    benchmark_filled = 0
    marked_unresolved = 0
    unresolved_tickers: set = set()
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

        # ── 같은 기간 시장 수익률 ────────────────────────────────────
        # 절대 수익만으로는 '시장이 올라서 오른 것'과 '신호가 맞아서 오른 것'을
        # 구분할 수 없다. 지수는 시장당 1회 프리페치되므로 비용이 거의 없다.
        bench_symbol = benchmark_for(ticker)
        bench_data: Dict[int, Optional[float]] = {}
        bench_entry = _latest_close_for(bench_symbol, issued_at)
        for h in HORIZONS:
            existing = row[f"benchmark_return_{h}d"]
            if existing is not None:
                bench_data[h] = existing
                continue
            target = issued_at + timedelta(days=h)
            if target > now or bench_entry is None or bench_entry <= 0:
                bench_data[h] = None
                continue
            bench_close = _latest_close_for(bench_symbol, target)
            if bench_close is None:
                bench_data[h] = None
                continue
            bench_data[h] = round(bench_close / bench_entry - 1, 6)
            if bench_data[h] != existing:
                benchmark_filled += 1
                row_updated = True

        if not row_updated:
            # 도래한 horizon만 후보로 뽑으므로, 여기 걸리는 건 시세를 못 받은 경우다.
            # 두 사유를 같은 카운터에 담으면 rate limit 장애가 '평가할 게 없음'으로 읽힌다.
            if price_missing:
                skipped_no_price += 1
                # 마지막 horizon 도래 + grace 를 넘겼는데도 시세가 없다 = 이 심볼로는
                # 영원히 못 채운다. 종결해서 큐와 경고를 붙잡지 않게 하고, 대신
                # unresolved 카운트로 계속 보이게 한다.
                deadline = issued_at + timedelta(
                    days=max(HORIZONS) + _UNRESOLVED_GRACE_DAYS
                )
                if now > deadline:
                    try:
                        conn.execute(
                            "UPDATE signal_outcomes SET eval_state=? WHERE signal_id=?",
                            (_STATE_UNRESOLVED, signal_id),
                        )
                        marked_unresolved += 1
                        unresolved_tickers.add(ticker)
                    except Exception as exc:
                        print(f"[signal_tracker] {ticker} ({signal_id}) 종결 실패: {exc}")
                        errors += 1
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
                    benchmark_symbol=?,
                    benchmark_return_7d=?,
                    benchmark_return_14d=?,
                    benchmark_return_30d=?,
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
                    bench_symbol,
                    bench_data.get(7),
                    bench_data.get(14),
                    bench_data.get(30),
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
        "benchmark_filled": benchmark_filled,
        "marked_unresolved": marked_unresolved,
        "unresolved_tickers": sorted(unresolved_tickers),
        "errors": errors,
        "completed_by_horizon": completed_by_horizon,
        "already_complete_by_horizon": already_complete_by_horizon,
        "candidates": len(rows),
        "reset_unresolved": reset_count,
        "days_back": days_back,
        "limit": limit,
        "prefetch": prefetch,
        "pending_due_before": backlog_before["pending_due"],
        "pending_due": backlog_after["pending_due"],
        "oldest_pending_at": backlog_after["oldest_pending_at"],
        "oldest_pending_days": backlog_after["oldest_pending_days"],
        "expired_unevaluated": backlog_after["expired_unevaluated"],
        "unresolved_total": backlog_after["unresolved_total"],
        "scanned_at": now.isoformat(),
    }


# ── 표본 단위 (독립성) ──────────────────────────────────────────────
#
# `signal_outcomes` 는 30분 주기 스캔이 종목당 하루 최대 48행을 남긴다. 그 행들은
# 같은 날 같은 종목의 같은 정보이고, 7일 horizon 이면 연속된 날짜끼리도 수익률
# 구간이 겹친다. 그대로 세면 n=3,030 처럼 보이지만 독립 관측은 수백 건 수준이라
# 승률·신뢰구간·칼리브레이션 가중이 전부 과대평가된다 (2026-09-10 진단).
#
#   ticker_day     : (종목, 소스, 발행일) 당 1행 — 하루 안의 반복 스캔을 접는다.
#                    대표는 그날 마지막 행(EOD 상태에 가장 가깝다).
#   ticker_horizon : (종목, 소스, horizon 블록) 당 1행 — 수익률 구간이 겹치지 않는다.
#                    가장 보수적이고 표본이 가장 적다.
#   none           : 원시 행 그대로 (진단·비교용).
SAMPLE_MODES = ("ticker_day", "ticker_horizon", "none")
DEFAULT_SAMPLE_MODE = "ticker_day"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_JULIAN_EPOCH = 2440587.5  # 1970-01-01T00:00Z 의 julian day


def _sample_bucket_sql(dedupe: str, horizon: int) -> Optional[str]:
    """표본 대표를 고를 때 쓸 PARTITION 키. none 이면 표본화하지 않는다."""
    if dedupe == "ticker_day":
        return "substr(issued_at, 1, 10)"
    if dedupe == "ticker_horizon":
        # `_horizon_block()` 과 **같은 경계**를 써야 한다. julianday 를 그대로 나누면
        # 기준점이 기원전 4713년 정오라 블록 경계가 UTC 자정과 어긋나고,
        # 표본 수가 독립 블록 수보다 많아지는 모순이 생긴다 (실측 358 vs 320).
        # 2440587.5 = 1970-01-01T00:00Z 의 julian day.
        return (
            f"CAST((julianday(issued_at) - {_JULIAN_EPOCH}) / {int(horizon)} AS INTEGER)"
        )
    return None


def _horizon_block(issued_at: str, horizon: int) -> Optional[int]:
    """수익률 구간이 겹치지 않는 블록 인덱스."""
    parsed = _as_utc(issued_at)
    if parsed is None:
        return None
    return int((parsed - _EPOCH).days // max(horizon, 1))


def _wilson_ci(wins: int, n: int, z: float = 1.96) -> List[float]:
    """Wilson 95% 신뢰구간 (%). n 은 **독립 표본 수**를 넣어야 의미가 있다."""
    if n <= 0:
        return [0.0, 0.0]
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return [round(max(0.0, center - margin) * 100, 1), round(min(1.0, center + margin) * 100, 1)]


def load_sampled_outcomes(
    conn, horizon: int, days_back: int, dedupe: str = DEFAULT_SAMPLE_MODE
) -> Tuple[List, int]:
    """평가 완료 행에서 표본 대표만 뽑는다. (표본 행, 표본화 전 행 수)"""
    ret_col = f"return_{horizon}d"
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    base_where = f"{ret_col} IS NOT NULL AND issued_at >= ?"
    raw_total = conn.execute(
        f"SELECT COUNT(*) FROM signal_outcomes WHERE {base_where}", (cutoff,)
    ).fetchone()[0]

    columns = (
        "signal_id, ticker, signal_source, signal_type, conviction, issued_at, "
        f"{ret_col} AS ret, benchmark_return_{horizon}d AS bench_ret, "
        "benchmark_symbol"
    )
    bucket = _sample_bucket_sql(dedupe, horizon)
    if bucket is None:
        rows = conn.execute(
            f"SELECT {columns} FROM signal_outcomes WHERE {base_where}", (cutoff,)
        ).fetchall()
        return rows, int(raw_total or 0)

    rows = conn.execute(
        f"""
        WITH ranked AS (
            SELECT {columns},
                   ROW_NUMBER() OVER (
                       PARTITION BY ticker, signal_source, {bucket}
                       ORDER BY issued_at DESC
                   ) AS rn
            FROM signal_outcomes
            WHERE {base_where}
        )
        SELECT * FROM ranked WHERE rn = 1
        """,
        (cutoff,),
    ).fetchall()
    return rows, int(raw_total or 0)


def signed_return(signal_type: str, ret: float) -> Optional[float]:
    """방향 보정 수익률 — 매수는 +ret, 매도는 -ret.

    Why: 원시 평균수익률은 **매도 신호가 맞을수록 내려간다**. 그 값을 성과 지표로
    읽으면 잘 맞춘 구간이 손실처럼 보인다 (2026-09-10: 전체 -0.352%인데 매도 신호는
    맞고 있었다). 방향이 없는 neutral 은 부호를 붙일 수 없으므로 None — 평균에서
    제외하고, 제외했다는 사실을 표본 수로 함께 보고한다.
    """
    sig = (signal_type or "").lower()
    if sig == "buy":
        return ret
    if sig == "sell":
        return -ret
    return None


def _row_value(row, key: str):
    """sqlite3.Row 는 .get 이 없고 없는 키는 IndexError 를 낸다."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _outcome_of(signal_type: str, ret: float) -> str:
    threshold = OUTCOME_THRESHOLD_PCT / 100.0
    sig = (signal_type or "").lower()
    if sig == "buy":
        return "win" if ret > threshold else ("loss" if ret < -threshold else "neutral")
    if sig == "sell":
        return "win" if ret < -threshold else ("loss" if ret > threshold else "neutral")
    return "win" if abs(ret) <= threshold else "loss"


def _tally(rows: List) -> Dict:
    total = len(rows)
    wins = sum(1 for r in rows if _outcome_of(r["signal_type"], r["ret"]) == "win")
    losses = sum(1 for r in rows if _outcome_of(r["signal_type"], r["ret"]) == "loss")
    raw_avg = (sum(r["ret"] for r in rows) / total * 100.0) if total else 0.0
    signed = [
        v
        for v in (signed_return(r["signal_type"], r["ret"]) for r in rows)
        if v is not None
    ]
    signed_avg = (sum(signed) / len(signed) * 100.0) if signed else 0.0

    # 시장 대비 초과수익 — 절대 수익은 '시장이 올라서'와 '신호가 맞아서'를
    # 구분하지 못한다. 매도 신호는 시장보다 더 떨어져야 이긴 것이므로 부호를
    # 종목과 같은 방식으로 뒤집는다 (excess = signed(stock) - signed(bench)).
    excess: List[float] = []
    for r in rows:
        bench = _row_value(r, "bench_ret")
        if bench is None:
            continue
        s_stock = signed_return(r["signal_type"], r["ret"])
        s_bench = signed_return(r["signal_type"], bench)
        if s_stock is None or s_bench is None:
            continue
        excess.append(s_stock - s_bench)
    excess_avg = (sum(excess) / len(excess) * 100.0) if excess else 0.0
    beat = sum(1 for v in excess if v > 0)
    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "neutrals": total - wins - losses,
        "win_rate_pct": round((wins / total * 100) if total else 0, 1),
        # 성과 지표는 방향 보정본이다. 원시값은 진단용으로만 함께 낸다.
        "avg_signed_return_pct": round(signed_avg, 3),
        "avg_raw_return_pct": round(raw_avg, 3),
        "signed_sample": len(signed),
        # 시장 대비. benchmark_sample 이 0이면 초과수익을 말할 수 없다.
        "avg_excess_return_pct": round(excess_avg, 3),
        "beat_benchmark_rate_pct": round(beat / len(excess) * 100, 1) if excess else 0.0,
        "benchmark_sample": len(excess),
    }


def get_accuracy_stats(
    horizon: int = 7,
    min_confidence: float = 0.0,
    signal: Optional[str] = None,
    days_back: int = 180,
    dedupe: str = DEFAULT_SAMPLE_MODE,
) -> Dict:
    """
    신뢰도·신호 조합별 정확도 집계.

    `dedupe` 기본값 때문에 반환되는 건수는 원시 행 수보다 작다 — 30분 스캔이
    같은 날 같은 종목을 반복 기록하기 때문이다. 원시 수는 `sampling.rows_raw`로
    함께 반환하니 두 값을 같이 보라.

    Returns: {
      "horizon_days": int,
      "total_evaluated": int,           # 표본화 후
      "win_count": int, "loss_count": int, "neutral_count": int,
      "win_rate_pct": float, "win_rate_ci95": [lo, hi],
      "avg_signed_return_pct": float,   # 매수 +ret / 매도 -ret (성과 지표)
      "avg_raw_return_pct": float,      # 부호 그대로 (진단용)
      "signed_sample": int,             # 방향이 있는 신호 수 (neutral 제외)
      "by_signal": {...}, "by_confidence_band": [...], "by_source": {...},
      "sample_size": int,
      "independent_blocks": int,        # horizon 겹침까지 제거한 수
      "sampling": {...},                # 표본화 진단
    }
    """
    if horizon not in HORIZONS:
        horizon = 7
    if dedupe not in SAMPLE_MODES:
        dedupe = DEFAULT_SAMPLE_MODE

    conn = _get_conn()
    sampled, raw_total = load_sampled_outcomes(conn, horizon, days_back, dedupe)
    conn.close()

    sig_filter = (signal or "").lower() or None

    def _select(rows, *, min_conf=None, conf_band=None, use_signal_filter=True):
        out = []
        for r in rows:
            conviction = r["conviction"] if r["conviction"] is not None else 0.0
            if min_conf is not None and conviction < min_conf:
                continue
            if conf_band is not None and not (conf_band[0] <= conviction < conf_band[1]):
                continue
            if use_signal_filter and sig_filter and (r["signal_type"] or "").lower() != sig_filter:
                continue
            out.append(r)
        return out

    scoped = _select(sampled, min_conf=min_confidence)
    overall = _tally(scoped)

    # 독립 블록 수 — 신뢰구간은 이 수로 계산한다 (행 수로 계산하면 구간이 거짓으로 좁아진다)
    blocks = {
        (r["ticker"], r["signal_source"], _horizon_block(r["issued_at"], horizon))
        for r in scoped
    }
    independent_blocks = len(blocks)
    block_wins_ratio = overall["wins"] / overall["total"] if overall["total"] else 0.0
    ci = _wilson_ci(round(block_wins_ratio * independent_blocks), independent_blocks)

    # 신호별 (신호 필터와 무관하게 3종 모두 — 종전 동작 유지)
    by_signal: Dict[str, Dict] = {}
    for sig in ("buy", "sell", "neutral"):
        rows = [
            r
            for r in _select(sampled, min_conf=min_confidence, use_signal_filter=False)
            if (r["signal_type"] or "").lower() == sig
        ]
        t = _tally(rows)
        by_signal[sig] = {
            "total": t["total"],
            "wins": t["wins"],
            "win_rate_pct": t["win_rate_pct"],
            "avg_signed_return_pct": t["avg_signed_return_pct"],
            "avg_raw_return_pct": t["avg_raw_return_pct"],
            "signed_sample": t["signed_sample"],
            "avg_excess_return_pct": t["avg_excess_return_pct"],
            "benchmark_sample": t["benchmark_sample"],
        }

    # 신뢰도 구간별 (종전과 동일하게 min_confidence·signal 필터를 적용하지 않는다)
    bands: List[Dict] = []
    for lo, hi in [(0, 2), (2, 4), (4, 6), (6, 8), (8, 10.1)]:
        t = _tally(_select(sampled, conf_band=(lo, hi), use_signal_filter=False))
        bands.append(
            {
                "band": f"{lo:.1f}-{min(hi, 10.0):.1f}",
                "total": t["total"],
                "wins": t["wins"],
                "win_rate_pct": t["win_rate_pct"],
                "avg_signed_return_pct": t["avg_signed_return_pct"],
                "avg_raw_return_pct": t["avg_raw_return_pct"],
            }
        )

    by_source: Dict[str, Dict] = {}
    source_names = {r["signal_source"] or "unknown" for r in scoped}
    for name in source_names:
        rows = [r for r in scoped if (r["signal_source"] or "unknown") == name]
        t = _tally(rows)
        by_source[name] = {
            "total": t["total"],
            "wins": t["wins"],
            "win_rate_pct": t["win_rate_pct"],
            "avg_signed_return_pct": t["avg_signed_return_pct"],
            "avg_raw_return_pct": t["avg_raw_return_pct"],
            "signed_sample": t["signed_sample"],
            "avg_excess_return_pct": t["avg_excess_return_pct"],
            "benchmark_sample": t["benchmark_sample"],
        }
    by_source = dict(
        sorted(by_source.items(), key=lambda kv: kv[1]["total"], reverse=True)
    )

    dominant = max(by_source.items(), key=lambda kv: kv[1]["total"], default=None)
    dominant_share = (
        round(dominant[1]["total"] / overall["total"] * 100, 1)
        if dominant and overall["total"]
        else 0.0
    )

    return {
        "horizon_days": horizon,
        "min_confidence_filter": min_confidence,
        "days_back": days_back,
        "total_evaluated": overall["total"],
        "win_count": overall["wins"],
        "loss_count": overall["losses"],
        "neutral_count": overall["neutrals"],
        "win_rate_pct": overall["win_rate_pct"],
        "win_rate_ci95": ci,
        # `avg_return_pct` 는 없앴다 — 방향 보정이 없어 매도가 맞을수록 내려가는
        # 값이었고, 이름만 봐서는 그 사실을 알 수 없었다. 이름을 갈라 둘 다 낸다.
        "avg_signed_return_pct": overall["avg_signed_return_pct"],
        "avg_raw_return_pct": overall["avg_raw_return_pct"],
        "signed_sample": overall["signed_sample"],
        "avg_excess_return_pct": overall["avg_excess_return_pct"],
        "beat_benchmark_rate_pct": overall["beat_benchmark_rate_pct"],
        "benchmark_sample": overall["benchmark_sample"],
        "by_signal": by_signal,
        "by_confidence_band": bands,
        "by_source": by_source,
        "sample_size": overall["total"],
        "independent_blocks": independent_blocks,
        "sampling": {
            "mode": dedupe,
            "rows_raw": raw_total,
            "rows_sampled": len(sampled),
            "rows_scoped": overall["total"],
            "collapse_ratio": (
                round(raw_total / len(sampled), 2) if sampled else 0.0
            ),
            "independent_blocks": independent_blocks,
            "dominant_source": dominant[0] if dominant else None,
            "dominant_source_share_pct": dominant_share,
            "note": (
                "30분 스캔이 같은 종목·같은 날을 반복 기록하므로 원시 행 수는 독립 표본이 "
                "아니다. win_rate_ci95 는 independent_blocks(수익률 구간이 겹치지 않는 "
                "블록 수) 기준이다."
            ),
        },
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
    reset_unresolved: bool = False,
) -> Dict:
    """
    일일 실행: 과거 신호 평가 + 칼리브레이터 재학습.

    Returns: 처리 통계 + 칼리브레이터 상태
    """
    eval_stats = evaluate_past_signals(
        days_back=days_back, limit=limit, reset_unresolved=reset_unresolved
    )

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
    print(
        f"  승률: {acc['win_rate_pct']}% "
        f"(방향보정 기대값 {acc['avg_signed_return_pct']}%, "
        f"원시 {acc['avg_raw_return_pct']}%)"
    )
    for sig, s in acc["by_signal"].items():
        if s["total"]:
            print(f"    {sig}: {s['win_rate_pct']}% (n={s['total']})")

    print("\n3) 신뢰도 칼리브레이터 재학습...")
    calib = get_calibrator()
    calib.refit()
    print(f"  상태: {calib.status()}")
