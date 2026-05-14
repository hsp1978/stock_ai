"""
주1회 signal_outcomes 배치 평가 job (Step 4).

실행:
    python -m chart_agent_service.jobs.evaluate_signal_outcomes
    또는 scripts/cron/weekly_signal_outcomes.sh 를 통해 cron으로 호출.

평가 로직:
    issued_at + 30일이 지났지만 evaluated_at IS NULL 인 행을 대상으로
    7 / 14 / 30일 후 가격과 최대 드로우다운을 계산해 업데이트.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

# chart_agent_service 디렉터리를 경로에 추가 (단독 실행 지원)
_SVC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SVC_DIR not in sys.path:
    sys.path.insert(0, _SVC_DIR)

from db import _get_conn  # noqa: E402


# ── 가격 조회 헬퍼 ────────────────────────────────────────────────────


def _fetch_price_at(ticker: str, target_date: datetime) -> Optional[float]:
    """target_date 이후 첫 영업일 종가 반환."""
    try:
        import yfinance as yf

        end = target_date + timedelta(days=7)
        hist = yf.Ticker(ticker).history(
            start=target_date.date(), end=end.date(), auto_adjust=True
        )
        if hist is None or hist.empty:
            return None
        for idx in hist.index:
            if idx.date() >= target_date.date():
                return float(hist.loc[idx, "Close"])
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def _compute_max_dd(ticker: str, start: datetime, days: int = 30) -> Optional[float]:
    """start 이후 days일간 최대 드로우다운 (음수, e.g. -0.12 = -12%)."""
    try:
        import yfinance as yf

        end = start + timedelta(days=days)
        hist = yf.Ticker(ticker).history(
            start=start.date(), end=end.date(), auto_adjust=True
        )
        if hist is None or hist.empty:
            return None
        closes = hist["Close"]
        peak = closes.expanding().max()
        dd = (closes - peak) / peak
        return float(dd.min())
    except Exception:
        return None


# ── 메인 평가 함수 ────────────────────────────────────────────────────


def evaluate_pending_outcomes(db_path: Optional[str] = None) -> dict:
    """
    issued_at + 30일 경과 & evaluated_at IS NULL 행들을 일괄 평가한다.

    Returns:
        처리 통계 dict
    """
    conn = _get_conn() if db_path is None else sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    pending = conn.execute(
        """
        SELECT signal_id, ticker, issued_at, price_at_signal, signal_type
        FROM signal_outcomes
        WHERE evaluated_at IS NULL
          AND datetime(issued_at, '+30 days') < datetime('now')
        """
    ).fetchall()

    now = datetime.now(timezone.utc)
    processed = 0
    skipped = 0
    errors = 0

    for row in pending:
        signal_id = row["signal_id"]
        ticker = row["ticker"]
        price_at_signal = row["price_at_signal"]

        if not price_at_signal:
            skipped += 1
            continue

        try:
            issued_at = datetime.fromisoformat(row["issued_at"])
            if issued_at.tzinfo is None:
                issued_at = issued_at.replace(tzinfo=timezone.utc)

            p7 = _fetch_price_at(ticker, issued_at + timedelta(days=7))
            p14 = _fetch_price_at(ticker, issued_at + timedelta(days=14))
            p30 = _fetch_price_at(ticker, issued_at + timedelta(days=30))

            r7 = (p7 / price_at_signal - 1) if p7 else None
            r14 = (p14 / price_at_signal - 1) if p14 else None
            r30 = (p30 / price_at_signal - 1) if p30 else None
            max_dd = _compute_max_dd(ticker, issued_at, days=30)

            conn.execute(
                """UPDATE signal_outcomes
                   SET price_7d=?, price_14d=?, price_30d=?,
                       return_7d=?, return_14d=?, return_30d=?,
                       max_drawdown_30d=?, evaluated_at=?
                   WHERE signal_id=?""",
                (p7, p14, p30, r7, r14, r30, max_dd, now.isoformat(), signal_id),
            )
            processed += 1
        except Exception as exc:
            print(f"[evaluate] {ticker} ({signal_id}): {exc}")
            errors += 1

    conn.commit()
    conn.close()

    result = {
        "pending_found": len(pending),
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "evaluated_at": now.isoformat(),
    }
    print(f"[evaluate_signal_outcomes] {result}")
    return result


def get_performance_summary(db_path: Optional[str] = None) -> pd.DataFrame:
    """signal_performance_summary VIEW를 DataFrame으로 반환."""
    conn = _get_conn() if db_path is None else sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM signal_performance_summary", conn)
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


# ── 진입점 ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("signal_outcomes 배치 평가 시작")
    print("=" * 60)
    stats = evaluate_pending_outcomes()
    print(f"\n결과: {stats}")
    print("\nsignal_performance_summary:")
    summary = get_performance_summary()
    if not summary.empty:
        print(summary.to_string(index=False))
    else:
        print("  (데이터 없음 — 30일 경과 후 갱신)")
