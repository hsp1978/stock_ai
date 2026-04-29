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
    scanned_at  TEXT    NOT NULL,
    entry_price REAL
);
"""

# 신호 사후 평가 테이블 — 스캔 로그의 신호가 실제로 얼마나 적중했는지 추적
_CREATE_OUTCOMES_TABLE = """
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_log_id   INTEGER NOT NULL,
    ticker        TEXT    NOT NULL,
    signal        TEXT,
    score         REAL,
    confidence    REAL,
    scanned_at    TEXT    NOT NULL,
    entry_price   REAL,
    -- 미래 N일 후 실제 가격과 수익률
    price_7d      REAL,
    return_7d_pct REAL,
    outcome_7d    TEXT,       -- "win" | "loss" | "neutral"
    price_14d     REAL,
    return_14d_pct REAL,
    outcome_14d   TEXT,
    price_30d     REAL,
    return_30d_pct REAL,
    outcome_30d   TEXT,
    evaluated_at  TEXT,
    UNIQUE(scan_log_id)
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_scan_log_ticker  ON scan_log(ticker);
CREATE INDEX IF NOT EXISTS idx_scan_log_date    ON scan_log(scanned_at);
CREATE INDEX IF NOT EXISTS idx_outcomes_ticker  ON signal_outcomes(ticker);
CREATE INDEX IF NOT EXISTS idx_outcomes_signal  ON signal_outcomes(signal);
CREATE INDEX IF NOT EXISTS idx_outcomes_date    ON signal_outcomes(scanned_at);
CREATE INDEX IF NOT EXISTS idx_screener_run    ON screener_results(run_id);
CREATE INDEX IF NOT EXISTS idx_screener_ticker ON screener_results(ticker);
"""

# 스크리너 결과 테이블 — 기존 scan_log와 완전 분리 (SSOT, 스키마 오염 방지)
_CREATE_SCREENER_TABLE = """
CREATE TABLE IF NOT EXISTS screener_results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT    NOT NULL,         -- 같은 실행 묶음 (YYYYMMDD_HHMM)
    rank           INTEGER NOT NULL,         -- 1~20
    ticker         TEXT    NOT NULL,
    name           TEXT,                      -- 종목명 (한글)
    market         TEXT,                      -- KOSPI | KOSDAQ
    market_cap     REAL,                      -- 시총 (원)
    current_price  REAL,                      -- 실행 시점 종가
    score          REAL    NOT NULL,         -- 0~100
    grade          TEXT,                      -- S | A | B | C | D
    breakdown      TEXT,                      -- JSON: {macd: 30, ma: 20, ...}
    penalties      TEXT,                      -- JSON: [{"name": "deadcross", "points": -20}]
    market_regime  TEXT,                      -- 실행 시점 시장 국면 (참고용, V3에서 채움)
    scanned_at     TEXT    NOT NULL
);
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
    conn.execute(_CREATE_OUTCOMES_TABLE)
    conn.execute(_CREATE_SCREENER_TABLE)
    # entry_price 컬럼 마이그레이션 (기존 DB 호환)
    try:
        conn.execute("ALTER TABLE scan_log ADD COLUMN entry_price REAL")
    except sqlite3.OperationalError:
        pass  # 이미 존재
    conn.executescript(_CREATE_INDEX)
    conn.commit()
    conn.close()
    print(f"[DB] 초기화 완료: {DB_PATH}")


# ─── 기록 ───────────────────────────────────────────────

def insert_scan(ticker: str, result: dict, alert_sent: bool = False):
    """스캔 결과 1건 DB 기록"""
    dist = result.get("signal_distribution", {})
    # entry_price 추출 우선순위: 직접 필드 → entry_plan → current_price
    entry_price = (
        result.get("entry_price")
        or (result.get("entry_plan") or {}).get("limit_price")
        or result.get("current_price")
        or result.get("price")
    )
    conn = _get_conn()
    conn.execute(
        """INSERT INTO scan_log
           (ticker, signal, score, confidence,
            buy_count, sell_count, neutral_count,
            alert_sent, scanned_at, entry_price)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            entry_price,
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


# ─── 스크리너 결과 저장/조회 ────────────────────────────────────

def insert_screener_results(run_id: str, results: list):
    """
    스크리너 실행 결과 저장 (상위 N개 한 번에).

    results: [{rank, ticker, name, market, market_cap, current_price,
               score, grade, breakdown(dict), penalties(list)}, ...]
    """
    import json
    if not results:
        return
    conn = _get_conn()
    rows = []
    scanned_at = datetime.now().isoformat()
    for r in results:
        rows.append((
            run_id,
            r.get("rank", 0),
            r.get("ticker", ""),
            r.get("name"),
            r.get("market"),
            r.get("market_cap"),
            r.get("current_price"),
            r.get("score", 0.0),
            r.get("grade"),
            json.dumps(r.get("breakdown", {}), ensure_ascii=False),
            json.dumps(r.get("penalties", []), ensure_ascii=False),
            r.get("market_regime"),
            scanned_at,
        ))
    conn.executemany(
        """INSERT INTO screener_results
           (run_id, rank, ticker, name, market, market_cap, current_price,
            score, grade, breakdown, penalties, market_regime, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()


def get_screener_latest(limit: int = 20) -> dict:
    """가장 최근 스크리너 실행 결과."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT run_id, scanned_at FROM screener_results ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        conn.close()
        return {"run_id": None, "scanned_at": None, "count": 0, "results": []}

    run_id = row["run_id"]
    results = conn.execute(
        "SELECT * FROM screener_results WHERE run_id = ? ORDER BY rank ASC LIMIT ?",
        (run_id, limit),
    ).fetchall()
    conn.close()
    return {
        "run_id": run_id,
        "scanned_at": row["scanned_at"],
        "count": len(results),
        "results": [dict(r) for r in results],
    }


def get_screener_history(days_back: int = 30) -> dict:
    """최근 N일 스크리너 실행 이력 (run_id별 요약)."""
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
    conn = _get_conn()
    runs = conn.execute(
        """SELECT run_id, scanned_at, COUNT(*) as count,
                  ROUND(AVG(score), 1) as avg_score,
                  SUM(CASE WHEN grade IN ('S','A') THEN 1 ELSE 0 END) as top_grades
           FROM screener_results
           WHERE scanned_at >= ?
           GROUP BY run_id ORDER BY scanned_at DESC""",
        (cutoff,),
    ).fetchall()
    conn.close()
    return {"runs": [dict(r) for r in runs]}
