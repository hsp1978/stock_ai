#!/usr/bin/env python3
"""
스캔 결과 SQLite 로거

테이블 구조:
  scan_log      — 스캔 1건 = 1행 (종목/신호/점수/LLM결론/전체JSON 등)
  tool_results  — 스캔 1건당 16행 (도구별 신호/점수/상세)

사용:
  from scan_logger import log_scan_result, query_scan_log, get_scan_stats
"""
import json
import os
import sqlite3
from datetime import datetime
from typing import Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_DIR = os.path.join(_THIS_DIR, "data")
os.makedirs(_DB_DIR, exist_ok=True)

DB_PATH = os.path.join(_DB_DIR, "scan_history.db")


# ═══════════════════════════════════════════════════════════════
#  DB 초기화
# ═══════════════════════════════════════════════════════════════

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """테이블 및 인덱스 생성 (멱등)"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scan_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at      TEXT    NOT NULL,
            ticker          TEXT    NOT NULL,
            final_signal    TEXT,
            composite_score REAL,
            confidence      REAL,
            tool_count      INTEGER,
            buy_votes       INTEGER DEFAULT 0,
            sell_votes      INTEGER DEFAULT 0,
            neutral_votes   INTEGER DEFAULT 0,
            llm_conclusion  TEXT,
            llm_model       TEXT,
            chart_path      TEXT,
            json_path       TEXT,
            fundamentals    TEXT,
            options_pcr     TEXT,
            insider_trades  TEXT,
            raw_result      TEXT
        );

        CREATE TABLE IF NOT EXISTS tool_results (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id   INTEGER NOT NULL,
            tool_key  TEXT    NOT NULL,
            tool_name TEXT    NOT NULL,
            signal    TEXT,
            score     REAL,
            detail    TEXT,
            FOREIGN KEY (scan_id) REFERENCES scan_log(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_scan_ticker    ON scan_log(ticker);
        CREATE INDEX IF NOT EXISTS idx_scan_time      ON scan_log(scanned_at);
        CREATE INDEX IF NOT EXISTS idx_scan_signal    ON scan_log(final_signal);
        CREATE INDEX IF NOT EXISTS idx_tool_scan_id   ON tool_results(scan_id);
    """)
    conn.commit()
    conn.close()


# 모듈 로드 시 자동 초기화
init_db()


# ═══════════════════════════════════════════════════════════════
#  쓰기
# ═══════════════════════════════════════════════════════════════

def _safe_json(obj) -> str:
    """JSON 직렬화 (실패 시 빈 문자열)"""
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return ""


def _extract_llm_model(llm_text: str) -> str:
    """<!-- llm_meta:ModelName --> 에서 모델명 추출"""
    if not llm_text:
        return ""
    if llm_text.startswith("<!-- llm_meta:"):
        end = llm_text.find(" -->")
        if end > 0:
            return llm_text[14:end]
    return ""


def log_scan_result(ticker: str, result: dict) -> Optional[int]:
    """
    분석 결과 1건을 DB에 기록.
    반환: scan_log.id (실패 시 None)
    """
    if not result or result.get("error"):
        return None

    ticker = ticker.upper()
    now = result.get("analyzed_at", datetime.now().isoformat())
    signal = result.get("final_signal", "")
    score = result.get("composite_score", 0)
    confidence = result.get("confidence", 0)
    tool_count = result.get("tool_count", 0)

    dist = result.get("signal_distribution", {})
    buy_v = dist.get("buy", 0)
    sell_v = dist.get("sell", 0)
    neutral_v = dist.get("neutral", 0)

    llm_text = result.get("llm_conclusion", "")
    llm_model = _extract_llm_model(llm_text)

    chart_path = result.get("chart_path", "")
    json_path = result.get("json_path", "")

    fundamentals = _safe_json(result.get("fundamentals", {}))
    options_pcr = _safe_json(result.get("options_pcr", {}))
    insider_trades = _safe_json(result.get("insider_trades", []))
    raw_result = _safe_json(result)

    tool_summaries = result.get("tool_summaries", [])
    tool_details = result.get("tool_details", [])

    try:
        conn = _get_conn()
        cur = conn.execute("""
            INSERT INTO scan_log (
                scanned_at, ticker, final_signal, composite_score,
                confidence, tool_count, buy_votes, sell_votes, neutral_votes,
                llm_conclusion, llm_model, chart_path, json_path,
                fundamentals, options_pcr, insider_trades, raw_result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now, ticker, signal, score,
            confidence, tool_count, buy_v, sell_v, neutral_v,
            llm_text, llm_model, chart_path, json_path,
            fundamentals, options_pcr, insider_trades, raw_result,
        ))
        scan_id = cur.lastrowid

        # tool_details 우선, 없으면 tool_summaries 사용
        tools = tool_details if tool_details else tool_summaries
        for td in tools:
            tool_key = td.get("tool", "")
            tool_name = td.get("name", tool_key)
            t_signal = td.get("signal", "")
            t_score = td.get("score", 0)
            t_detail = td.get("detail", "")
            conn.execute("""
                INSERT INTO tool_results
                    (scan_id, tool_key, tool_name, signal, score, detail)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (scan_id, tool_key, tool_name, t_signal, t_score, t_detail))

        conn.commit()
        conn.close()
        return scan_id

    except Exception as e:
        print(f"[scan_logger] DB 기록 실패: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  읽기 — 다양한 조회 함수
# ═══════════════════════════════════════════════════════════════

def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def query_scan_log(
    ticker: str = "",
    signal: str = "",
    from_date: str = "",
    to_date: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """
    스캔 로그 조회 (필터 조합 가능).
    날짜 형식: YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM:SS
    """
    conditions = []
    params = []

    if ticker:
        conditions.append("ticker = ?")
        params.append(ticker.upper())
    if signal:
        conditions.append("final_signal = ?")
        params.append(signal.upper())
    if from_date:
        conditions.append("scanned_at >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("scanned_at <= ?")
        params.append(to_date)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    conn = _get_conn()

    # 총 건수
    count_row = conn.execute(
        f"SELECT COUNT(*) as cnt FROM scan_log {where}", params
    ).fetchone()
    total = count_row["cnt"]

    # 데이터 (raw_result 제외 — 크기 절약)
    rows = conn.execute(f"""
        SELECT id, scanned_at, ticker, final_signal, composite_score,
               confidence, tool_count, buy_votes, sell_votes, neutral_votes,
               llm_model, chart_path, json_path
        FROM scan_log {where}
        ORDER BY scanned_at DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()

    conn.close()
    return {"total": total, "limit": limit, "offset": offset, "rows": _rows_to_dicts(rows)}


def get_scan_detail(scan_id: int) -> Optional[dict]:
    """스캔 1건 상세 (tool_results 포함)"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM scan_log WHERE id = ?", (scan_id,)).fetchone()
    if not row:
        conn.close()
        return None

    tools = conn.execute(
        "SELECT tool_key, tool_name, signal, score, detail FROM tool_results WHERE scan_id = ? ORDER BY id",
        (scan_id,)
    ).fetchall()

    conn.close()

    result = dict(row)
    result["tool_results"] = _rows_to_dicts(tools)

    # raw_result 파싱
    raw = result.get("raw_result", "")
    if raw:
        try:
            result["raw_result"] = json.loads(raw)
        except Exception:
            pass

    # fundamentals / options_pcr / insider_trades 파싱
    for key in ("fundamentals", "options_pcr", "insider_trades"):
        val = result.get(key, "")
        if val:
            try:
                result[key] = json.loads(val)
            except Exception:
                pass

    return result


def get_ticker_history(ticker: str, limit: int = 50) -> list[dict]:
    """특정 종목의 스캔 이력 (시계열 분석용)"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT id, scanned_at, final_signal, composite_score,
               confidence, buy_votes, sell_votes, neutral_votes, llm_model
        FROM scan_log
        WHERE ticker = ?
        ORDER BY scanned_at DESC
        LIMIT ?
    """, (ticker.upper(), limit)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def get_scan_stats() -> dict:
    """전체 통계 요약"""
    conn = _get_conn()

    total = conn.execute("SELECT COUNT(*) as cnt FROM scan_log").fetchone()["cnt"]
    if total == 0:
        conn.close()
        return {"total_scans": 0}

    signal_dist = _rows_to_dicts(conn.execute("""
        SELECT final_signal, COUNT(*) as cnt,
               ROUND(AVG(composite_score), 2) as avg_score,
               ROUND(AVG(confidence), 1) as avg_confidence
        FROM scan_log
        GROUP BY final_signal
    """).fetchall())

    ticker_stats = _rows_to_dicts(conn.execute("""
        SELECT ticker, COUNT(*) as scan_count,
               ROUND(AVG(composite_score), 2) as avg_score,
               MIN(scanned_at) as first_scan,
               MAX(scanned_at) as last_scan
        FROM scan_log
        GROUP BY ticker
        ORDER BY scan_count DESC
    """).fetchall())

    daily_counts = _rows_to_dicts(conn.execute("""
        SELECT DATE(scanned_at) as date, COUNT(*) as cnt
        FROM scan_log
        GROUP BY DATE(scanned_at)
        ORDER BY date DESC
        LIMIT 30
    """).fetchall())

    recent = _rows_to_dicts(conn.execute("""
        SELECT id, scanned_at, ticker, final_signal, composite_score, confidence
        FROM scan_log ORDER BY scanned_at DESC LIMIT 10
    """).fetchall())

    conn.close()

    return {
        "total_scans": total,
        "signal_distribution": signal_dist,
        "ticker_stats": ticker_stats,
        "daily_counts": daily_counts,
        "recent_scans": recent,
        "db_path": DB_PATH,
    }


def get_signal_changes(ticker: str, limit: int = 20) -> list[dict]:
    """종목의 신호 변경 이력 (BUY->HOLD->SELL 등 전환 시점 추적)"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT id, scanned_at, final_signal, composite_score, confidence
        FROM scan_log
        WHERE ticker = ?
        ORDER BY scanned_at DESC
        LIMIT ?
    """, (ticker.upper(), limit * 3)).fetchall()  # 충분히 가져와서 변경점만 필터
    conn.close()

    history = _rows_to_dicts(rows)
    if not history:
        return []

    changes = [history[0]]  # 최신 항상 포함
    for i in range(1, len(history)):
        if history[i]["final_signal"] != history[i - 1]["final_signal"]:
            changes.append(history[i])
        if len(changes) >= limit:
            break

    return changes


# ═══════════════════════════════════════════════════════════════
#  주간 분석 — 1주 단위 집계/비교/트렌드
# ═══════════════════════════════════════════════════════════════

def get_weekly_summary(ticker: str = "", weeks: int = 8) -> list[dict]:
    """
    주간 집계 데이터.
    ticker 지정 시 해당 종목만, 미지정 시 전체.
    반환: [{"week": "2026-W15", "week_start": "2026-04-07", ...}, ...]
    """
    conn = _get_conn()

    where = "WHERE ticker = ?" if ticker else ""
    params = [ticker.upper()] if ticker else []

    rows = conn.execute(f"""
        SELECT
            strftime('%Y-W%W', scanned_at)       AS week,
            MIN(DATE(scanned_at))                 AS week_start,
            MAX(DATE(scanned_at))                 AS week_end,
            COUNT(*)                              AS scan_count,
            ROUND(AVG(composite_score), 3)        AS avg_score,
            ROUND(AVG(confidence), 2)             AS avg_confidence,
            SUM(CASE WHEN final_signal='BUY'  THEN 1 ELSE 0 END) AS buy_count,
            SUM(CASE WHEN final_signal='SELL' THEN 1 ELSE 0 END) AS sell_count,
            SUM(CASE WHEN final_signal='HOLD' THEN 1 ELSE 0 END) AS hold_count,
            ROUND(AVG(buy_votes), 1)              AS avg_buy_votes,
            ROUND(AVG(sell_votes), 1)             AS avg_sell_votes,
            ROUND(AVG(neutral_votes), 1)          AS avg_neutral_votes,
            ROUND(MIN(composite_score), 3)        AS min_score,
            ROUND(MAX(composite_score), 3)        AS max_score
        FROM scan_log
        {where}
        GROUP BY week
        ORDER BY week DESC
        LIMIT ?
    """, params + [weeks]).fetchall()
    conn.close()

    return _rows_to_dicts(rows)


def get_weekly_comparison(ticker: str = "", weeks: int = 8) -> dict:
    """
    주간 비교 데이터 (WoW: Week-over-Week 변화).
    반환: {
        "weeks": [...],           ← 주별 raw 집계
        "comparisons": [...],     ← 인접 주간 변화량 (delta)
        "trend": {...},           ← 전체 추세 판단
    }
    """
    weekly = get_weekly_summary(ticker, weeks)
    if not weekly:
        return {"weeks": [], "comparisons": [], "trend": {}}

    # 시간순 정렬 (오래된 → 최신)
    weekly.sort(key=lambda w: w["week"])

    comparisons = []
    for i in range(1, len(weekly)):
        prev = weekly[i - 1]
        curr = weekly[i]

        prev_score = prev["avg_score"] or 0
        curr_score = curr["avg_score"] or 0
        prev_conf = prev["avg_confidence"] or 0
        curr_conf = curr["avg_confidence"] or 0

        comparisons.append({
            "week": curr["week"],
            "week_start": curr["week_start"],
            "prev_week": prev["week"],
            # 점수 변화
            "score_delta": round(curr_score - prev_score, 3),
            "score_pct_change": round(
                (curr_score - prev_score) / abs(prev_score) * 100, 2
            ) if prev_score != 0 else 0,
            "confidence_delta": round(curr_conf - prev_conf, 2),
            # 신호 분포 변화
            "buy_delta": (curr.get("buy_count") or 0) - (prev.get("buy_count") or 0),
            "sell_delta": (curr.get("sell_count") or 0) - (prev.get("sell_count") or 0),
            # 현재 주 요약
            "avg_score": curr_score,
            "avg_confidence": curr_conf,
            "scan_count": curr["scan_count"],
            "buy_count": curr.get("buy_count", 0),
            "sell_count": curr.get("sell_count", 0),
            "hold_count": curr.get("hold_count", 0),
        })

    # 전체 추세 판단
    trend = _compute_trend(weekly, comparisons)

    return {
        "ticker": ticker.upper() if ticker else "ALL",
        "weeks": weekly,
        "comparisons": comparisons,
        "trend": trend,
    }


def _compute_trend(weekly: list[dict], comparisons: list[dict]) -> dict:
    """주간 데이터에서 추세 판단"""
    if len(weekly) < 2:
        return {"direction": "insufficient_data", "strength": 0, "description": ""}

    scores = [w["avg_score"] or 0 for w in weekly]
    latest = scores[-1]
    oldest = scores[0]

    # 선형 추세
    n = len(scores)
    mean_x = (n - 1) / 2
    mean_y = sum(scores) / n
    numerator = sum((i - mean_x) * (s - mean_y) for i, s in enumerate(scores))
    denominator = sum((i - mean_x) ** 2 for i in range(n))
    slope = numerator / denominator if denominator != 0 else 0

    # 최근 3주 추세 (가용 시)
    recent_3 = scores[-3:] if len(scores) >= 3 else scores
    recent_slope = (recent_3[-1] - recent_3[0]) / max(len(recent_3) - 1, 1)

    # 연속 상승/하락 카운트
    streak = 0
    if len(comparisons) >= 1:
        direction = 1 if comparisons[-1]["score_delta"] > 0 else -1
        for c in reversed(comparisons):
            if (c["score_delta"] > 0 and direction > 0) or \
               (c["score_delta"] < 0 and direction < 0):
                streak += 1
            else:
                break
        streak *= direction

    # 종합 판단
    if slope > 0.3:
        trend_dir = "strongly_bullish"
    elif slope > 0.05:
        trend_dir = "bullish"
    elif slope < -0.3:
        trend_dir = "strongly_bearish"
    elif slope < -0.05:
        trend_dir = "bearish"
    else:
        trend_dir = "sideways"

    # 설명 텍스트 (LLM 프롬프트용)
    total_change = latest - oldest
    desc_parts = []
    desc_parts.append(f"{len(weekly)}주간 점수 추세: {oldest:+.2f} → {latest:+.2f} (변화: {total_change:+.2f})")
    desc_parts.append(f"기울기: {slope:+.3f}/주, 최근 3주 기울기: {recent_slope:+.3f}/주")
    if streak > 0:
        desc_parts.append(f"{abs(streak)}주 연속 상승")
    elif streak < 0:
        desc_parts.append(f"{abs(streak)}주 연속 하락")

    # 신호 분포 추세
    if comparisons:
        latest_comp = comparisons[-1]
        desc_parts.append(
            f"최근 주: BUY {latest_comp['buy_count']}건, "
            f"SELL {latest_comp['sell_count']}건, "
            f"HOLD {latest_comp['hold_count']}건"
        )

    return {
        "direction": trend_dir,
        "slope": round(slope, 4),
        "recent_slope": round(recent_slope, 4),
        "streak": streak,
        "total_change": round(total_change, 3),
        "latest_score": round(latest, 3),
        "description": " | ".join(desc_parts),
    }


def get_weekly_tool_trend(ticker: str, weeks: int = 4) -> list[dict]:
    """
    종목의 도구별 주간 점수 추이.
    반환: [{"week": ..., "tool_key": "rsi", "avg_score": ..., "dominant_signal": ...}, ...]
    """
    conn = _get_conn()
    rows = conn.execute("""
        SELECT
            strftime('%Y-W%W', s.scanned_at) AS week,
            t.tool_key,
            t.tool_name,
            ROUND(AVG(t.score), 3) AS avg_score,
            COUNT(*) AS cnt,
            SUM(CASE WHEN t.signal='buy'  THEN 1 ELSE 0 END) AS buy_cnt,
            SUM(CASE WHEN t.signal='sell' THEN 1 ELSE 0 END) AS sell_cnt
        FROM tool_results t
        JOIN scan_log s ON s.id = t.scan_id
        WHERE s.ticker = ?
        GROUP BY week, t.tool_key
        ORDER BY week DESC, t.tool_key
        LIMIT ?
    """, (ticker.upper(), weeks * 20)).fetchall()
    conn.close()

    result = []
    for r in _rows_to_dicts(rows):
        buy = r.get("buy_cnt", 0)
        sell = r.get("sell_cnt", 0)
        dominant = "buy" if buy > sell else ("sell" if sell > buy else "neutral")
        r["dominant_signal"] = dominant
        result.append(r)
    return result


def get_weekly_context_for_prompt(ticker: str, weeks: int = 4) -> str:
    """
    LLM 프롬프트에 삽입할 주간 트렌드 요약 텍스트.
    데이터 부족 시 빈 문자열 반환.
    """
    comp = get_weekly_comparison(ticker, weeks)
    if not comp.get("weeks") or len(comp["weeks"]) < 2:
        return ""

    trend = comp.get("trend", {})
    weeks_data = comp.get("weeks", [])
    comparisons = comp.get("comparisons", [])

    lines = []
    lines.append(f"### {ticker} 주간 트렌드 ({len(weeks_data)}주)")
    lines.append(f"- 추세: {trend.get('direction', '?')} (기울기: {trend.get('slope', 0):+.3f}/주)")

    streak = trend.get("streak", 0)
    if streak > 0:
        lines.append(f"- {streak}주 연속 상승")
    elif streak < 0:
        lines.append(f"- {abs(streak)}주 연속 하락")

    lines.append(f"- 전체 변화: {trend.get('total_change', 0):+.3f}")
    lines.append("")

    # 주별 테이블
    lines.append("| 주차 | 스캔 | 평균점수 | 신뢰도 | BUY | SELL | HOLD | 점수변화 |")
    lines.append("|------|------|----------|--------|-----|------|------|----------|")

    # 주별 데이터 (시간순 정렬됨)
    delta_map = {c["week"]: c for c in comparisons}
    for w in weeks_data:
        week = w["week"]
        d = delta_map.get(week)
        delta_str = f"{d['score_delta']:+.2f}" if d else "—"
        lines.append(
            f"| {week} | {w['scan_count']} | {(w['avg_score'] or 0):+.2f} | "
            f"{(w['avg_confidence'] or 0):.1f} | {w.get('buy_count', 0)} | "
            f"{w.get('sell_count', 0)} | {w.get('hold_count', 0)} | {delta_str} |"
        )

    # 도구별 추이 (선택적)
    tool_trend = get_weekly_tool_trend(ticker, min(weeks, 3))
    if tool_trend:
        # 최신 주의 도구별 데이터만
        latest_week = weeks_data[-1]["week"] if weeks_data else ""
        latest_tools = [t for t in tool_trend if t["week"] == latest_week]
        if latest_tools:
            lines.append("")
            lines.append(f"#### 최신 주({latest_week}) 도구별 평균 점수")
            for t in sorted(latest_tools, key=lambda x: abs(x["avg_score"]), reverse=True):
                sig_icon = "+" if t["dominant_signal"] == "buy" else ("-" if t["dominant_signal"] == "sell" else "=")
                lines.append(f"  {sig_icon} {t['tool_name']}: {t['avg_score']:+.2f} ({t['dominant_signal']})")

    return "\n".join(lines)


def export_to_csv(filepath: str = "", ticker: str = "",
                  from_date: str = "", to_date: str = "") -> str:
    """스캔 로그를 CSV로 내보내기"""
    import csv

    if not filepath:
        filepath = os.path.join(_DB_DIR, f"scan_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    conditions = []
    params = []
    if ticker:
        conditions.append("s.ticker = ?")
        params.append(ticker.upper())
    if from_date:
        conditions.append("s.scanned_at >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("s.scanned_at <= ?")
        params.append(to_date)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    conn = _get_conn()
    rows = conn.execute(f"""
        SELECT s.scanned_at, s.ticker, s.final_signal, s.composite_score,
               s.confidence, s.tool_count, s.buy_votes, s.sell_votes, s.neutral_votes,
               s.llm_model
        FROM scan_log s
        {where}
        ORDER BY s.scanned_at DESC
    """, params).fetchall()
    conn.close()

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "scanned_at", "ticker", "signal", "score", "confidence",
            "tool_count", "buy_votes", "sell_votes", "neutral_votes", "llm_model",
        ])
        for r in rows:
            writer.writerow([
                r["scanned_at"], r["ticker"], r["final_signal"],
                r["composite_score"], r["confidence"], r["tool_count"],
                r["buy_votes"], r["sell_votes"], r["neutral_votes"],
                r["llm_model"],
            ])

    return filepath
