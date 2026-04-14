"""
스캔 로그 SQLite 저장소
- scan_log 테이블: 개별 종목 스캔 기록
- 주간 요약 쿼리 함수 제공
"""
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from config import OUTPUT_DIR

DB_PATH = os.path.join(OUTPUT_DIR, "scan_log.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS scan_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL,
    signal      TEXT,
    score       REAL,
    confidence  REAL,
    buy_count   INTEGER DEFAULT 0,
    sell_count  INTEGER DEFAULT 0,
    neutral_count INTEGER DEFAULT 0,
    alert_sent  INTEGER DEFAULT 0,
    scanned_at  TEXT    NOT NULL
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_scan_log_ticker  ON scan_log(ticker);
CREATE INDEX IF NOT EXISTS idx_scan_log_date    ON scan_log(scanned_at);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """테이블 생성 (서비스 시작 시 1회 호출)"""
    conn = _get_conn()
    conn.execute(_CREATE_TABLE)
    conn.executescript(_CREATE_INDEX)
    conn.commit()
    conn.close()
    print(f"[DB] 초기화 완료: {DB_PATH}")


# ─── 기록 ───────────────────────────────────────────────

def insert_scan(ticker: str, result: dict, alert_sent: bool = False):
    """스캔 결과 1건 DB 기록"""
    dist = result.get("signal_distribution", {})
    conn = _get_conn()
    conn.execute(
        """INSERT INTO scan_log
           (ticker, signal, score, confidence,
            buy_count, sell_count, neutral_count,
            alert_sent, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ticker.upper(),
            result.get("final_signal"),
            result.get("composite_score"),
            result.get("confidence"),
            dist.get("buy", 0),
            dist.get("sell", 0),
            dist.get("neutral", 0),
            1 if alert_sent else 0,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


# ─── 조회: scan-log ────────────────────────────────────

def get_scan_logs(limit: int = 50, offset: int = 0) -> dict:
    """최근 스캔 로그 조회 (페이지네이션)"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM scan_log").fetchone()[0]
    rows = conn.execute(
        "SELECT * FROM scan_log ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    conn.close()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": [dict(r) for r in rows],
    }


def get_scan_logs_by_ticker(ticker: str, limit: int = 30) -> dict:
    """종목별 스캔 로그"""
    ticker = ticker.upper()
    conn = _get_conn()
    total = conn.execute(
        "SELECT COUNT(*) FROM scan_log WHERE ticker = ?", (ticker,)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT * FROM scan_log WHERE ticker = ? ORDER BY id DESC LIMIT ?",
        (ticker, limit),
    ).fetchall()
    conn.close()
    return {
        "ticker": ticker,
        "total": total,
        "logs": [dict(r) for r in rows],
    }


def get_scan_log_latest() -> dict:
    """가장 최근 스캔 라운드의 결과 (같은 시각 ±60초 묶음)"""
    conn = _get_conn()
    last = conn.execute(
        "SELECT scanned_at FROM scan_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not last:
        conn.close()
        return {"count": 0, "logs": []}

    last_ts = datetime.fromisoformat(last[0])
    window_start = (last_ts - timedelta(seconds=120)).isoformat()

    rows = conn.execute(
        "SELECT * FROM scan_log WHERE scanned_at >= ? ORDER BY score DESC",
        (window_start,),
    ).fetchall()
    conn.close()
    return {"count": len(rows), "logs": [dict(r) for r in rows]}


def get_scan_log_date_range(start: str, end: str) -> dict:
    """날짜 범위 조회 (YYYY-MM-DD)"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM scan_log WHERE DATE(scanned_at) BETWEEN ? AND ? ORDER BY scanned_at DESC",
        (start, end),
    ).fetchall()
    conn.close()
    return {"start": start, "end": end, "count": len(rows), "logs": [dict(r) for r in rows]}


# ─── 조회: weekly ───────────────────────────────────────

def get_weekly_summary(weeks_ago: int = 0) -> dict:
    """주간 요약 리포트
    weeks_ago=0 → 이번 주, weeks_ago=1 → 지난 주
    """
    today = datetime.now().date()
    # 이번 주 월요일 기준
    monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks_ago)
    sunday = monday + timedelta(days=6)
    start = monday.isoformat()
    end = sunday.isoformat()

    conn = _get_conn()

    # 1) 기간 내 전체 통계
    total_scans = conn.execute(
        "SELECT COUNT(*) FROM scan_log WHERE DATE(scanned_at) BETWEEN ? AND ?",
        (start, end),
    ).fetchone()[0]

    signal_dist = conn.execute(
        """SELECT signal, COUNT(*) as cnt
           FROM scan_log WHERE DATE(scanned_at) BETWEEN ? AND ?
           GROUP BY signal""",
        (start, end),
    ).fetchall()

    alert_count = conn.execute(
        "SELECT COUNT(*) FROM scan_log WHERE DATE(scanned_at) BETWEEN ? AND ? AND alert_sent = 1",
        (start, end),
    ).fetchone()[0]

    # 2) 종목별 요약 (평균 점수, 최신 신호, 스캔 횟수)
    ticker_summary = conn.execute(
        """SELECT ticker,
                  COUNT(*) as scan_count,
                  ROUND(AVG(score), 2) as avg_score,
                  ROUND(AVG(confidence), 1) as avg_confidence,
                  SUM(CASE WHEN signal='BUY' THEN 1 ELSE 0 END) as buy_cnt,
                  SUM(CASE WHEN signal='SELL' THEN 1 ELSE 0 END) as sell_cnt,
                  SUM(CASE WHEN signal='HOLD' THEN 1 ELSE 0 END) as hold_cnt,
                  SUM(alert_sent) as alerts
           FROM scan_log
           WHERE DATE(scanned_at) BETWEEN ? AND ?
           GROUP BY ticker
           ORDER BY avg_score DESC""",
        (start, end),
    ).fetchall()

    # 3) 일별 스캔 횟수
    daily_counts = conn.execute(
        """SELECT DATE(scanned_at) as day, COUNT(*) as cnt
           FROM scan_log WHERE DATE(scanned_at) BETWEEN ? AND ?
           GROUP BY day ORDER BY day""",
        (start, end),
    ).fetchall()

    # 4) 상위/하위 종목
    top_buy = conn.execute(
        """SELECT ticker, MAX(score) as best_score, confidence
           FROM scan_log
           WHERE DATE(scanned_at) BETWEEN ? AND ? AND signal = 'BUY'
           GROUP BY ticker ORDER BY best_score DESC LIMIT 5""",
        (start, end),
    ).fetchall()

    top_sell = conn.execute(
        """SELECT ticker, MIN(score) as worst_score, confidence
           FROM scan_log
           WHERE DATE(scanned_at) BETWEEN ? AND ? AND signal = 'SELL'
           GROUP BY ticker ORDER BY worst_score ASC LIMIT 5""",
        (start, end),
    ).fetchall()

    conn.close()

    return {
        "week_start": start,
        "week_end": end,
        "total_scans": total_scans,
        "signal_distribution": {row["signal"]: row["cnt"] for row in signal_dist},
        "alert_count": alert_count,
        "tickers": [dict(r) for r in ticker_summary],
        "daily_scans": [dict(r) for r in daily_counts],
        "top_buy": [dict(r) for r in top_buy],
        "top_sell": [dict(r) for r in top_sell],
    }


def get_weekly_ticker(ticker: str, weeks_ago: int = 0) -> dict:
    """특정 종목의 주간 상세"""
    ticker = ticker.upper()
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks_ago)
    sunday = monday + timedelta(days=6)
    start = monday.isoformat()
    end = sunday.isoformat()

    conn = _get_conn()

    stats = conn.execute(
        """SELECT COUNT(*) as scan_count,
                  ROUND(AVG(score), 2) as avg_score,
                  ROUND(MIN(score), 2) as min_score,
                  ROUND(MAX(score), 2) as max_score,
                  ROUND(AVG(confidence), 1) as avg_confidence,
                  SUM(CASE WHEN signal='BUY' THEN 1 ELSE 0 END) as buy_cnt,
                  SUM(CASE WHEN signal='SELL' THEN 1 ELSE 0 END) as sell_cnt,
                  SUM(CASE WHEN signal='HOLD' THEN 1 ELSE 0 END) as hold_cnt,
                  SUM(alert_sent) as alert_count
           FROM scan_log
           WHERE ticker = ? AND DATE(scanned_at) BETWEEN ? AND ?""",
        (ticker, start, end),
    ).fetchone()

    logs = conn.execute(
        """SELECT * FROM scan_log
           WHERE ticker = ? AND DATE(scanned_at) BETWEEN ? AND ?
           ORDER BY scanned_at DESC""",
        (ticker, start, end),
    ).fetchall()

    # 점수 추이 (일별)
    daily_trend = conn.execute(
        """SELECT DATE(scanned_at) as day,
                  ROUND(AVG(score), 2) as avg_score,
                  signal
           FROM scan_log
           WHERE ticker = ? AND DATE(scanned_at) BETWEEN ? AND ?
           GROUP BY day ORDER BY day""",
        (ticker, start, end),
    ).fetchall()

    conn.close()

    return {
        "ticker": ticker,
        "week_start": start,
        "week_end": end,
        "stats": dict(stats) if stats else {},
        "daily_trend": [dict(r) for r in daily_trend],
        "logs": [dict(r) for r in logs],
    }
