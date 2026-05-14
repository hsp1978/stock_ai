#!/usr/bin/env python3
"""
차트 분석 에이전트 서비스 (Mac Studio 전용)
- FastAPI: REST API 제공
- APScheduler: 30분 주기 자동 분석
- 텔레그램: 기준치 도달 시 즉시 알림

실행:
    python service.py
    # 또는
    uvicorn service:app --host 0.0.0.0 --port 8100
"""
import json
import os as _os
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import sys
import time
import subprocess
from datetime import datetime
from typing import Dict, List, Optional

import httpx
import uvicorn
import math
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import BaseModel

from config import (
    API_HOST, API_PORT, SCAN_INTERVAL_MINUTES,
    WATCHLIST, OLLAMA_BASE_URL, OLLAMA_MODEL,
    BUY_THRESHOLD, SELL_THRESHOLD, MIN_CONFIDENCE,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OUTPUT_DIR,
    COOLING_OFF_DAYS, TRADING_STYLE,
)
from data_collector import fetch_ohlcv, calculate_indicators, fetch_fundamentals, fetch_options_pcr, fetch_insider_trades
from analysis_tools import ChartAnalysisAgent, generate_agent_chart
from backtest_engine import run_all_backtests
from ml_predictor import run_ml_prediction
from portfolio_optimizer import (
    markowitz_optimize, risk_parity_optimize,
    compute_factor_ranking, compute_correlation_beta,
)
from paper_trader import (
    get_portfolio_status, execute_paper_order,
    process_agent_signal, update_position_prices,
    reset_paper_trading,
)
from news_analyzer import fetch_news_with_sentiment
from chart_pattern import detect_chart_patterns
from sector_compare import compare_sector
from macro_context import fetch_macro_context
from db import init_db, insert_scan, get_scan_logs, get_scan_logs_by_ticker, \
    get_scan_log_latest, get_scan_log_date_range, \
    get_weekly_summary, get_weekly_ticker
from signal_tracker import insert_signal_outcome

# Multi-Agent import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "stock_analyzer"))
try:
    from multi_agent import MultiAgentOrchestrator
except ImportError:
    MultiAgentOrchestrator = None
    print("[WARNING] Multi-Agent module not available")


def _try_insert_group_outcomes(ticker: str, result: dict) -> None:
    """multi-agent 결과의 그룹별 신호를 signal_outcomes에 개별 row로 기록한다."""
    group_results: dict = result.get("group_results") or {}
    if not group_results:
        return
    price = float(
        result.get("current_price")
        or result.get("price")
        or 0.0
    )
    if price <= 0:
        return
    regime = result.get("regime")
    signal_std = result.get("signal_std")
    agreement_level = result.get("agreement_level")
    for group_name, gr in group_results.items():
        signal = gr.get("signal", "neutral")
        if signal not in ("buy", "sell"):
            continue
        try:
            insert_signal_outcome(
                ticker=ticker,
                signal_type=signal,
                signal_source=f"group_{group_name}",
                conviction=float(gr.get("confidence") or 0.0),
                price_at_signal=price,
                regime=regime,
                signal_std=signal_std,
                agreement_level=agreement_level,
            )
        except Exception as exc:
            print(f"  [{ticker}] group_outcome insert 실패({group_name}): {exc}")


def _try_insert_signal_outcome(ticker: str, result: dict) -> None:
    """스캔 결과로부터 signal_outcomes에 row를 생성한다 (실패 시 무시)."""
    try:
        signal = (result.get("final_signal") or "HOLD").upper()
        if signal not in ("BUY", "SELL"):
            return
        price = float(
            result.get("current_price")
            or result.get("price")
            or (result.get("entry_plan") or {}).get("limit_price")
            or 0.0
        )
        if price <= 0:
            return
        insert_signal_outcome(
            ticker=ticker,
            signal_type=signal.lower(),
            signal_source="scan_agent",
            conviction=float(result.get("confidence") or 0.0),
            price_at_signal=price,
        )
    except Exception as exc:
        print(f"  [{ticker}] signal_outcome insert 실패: {exc}")


# ═══════════════════════════════════════════════════════════════
#  전역 상태 저장소
# ═══════════════════════════════════════════════════════════════

# 최신 분석 결과 캐시 {ticker: {result, timestamp, alert_sent}}
latest_results: dict = {}

# 분석 히스토리 (최근 100건)
scan_history: list = []

# 냉각기 추적 {ticker: {"signal": "SELL", "triggered_at": isoformat}}
cooling_off_state: dict = {}


# ═══════════════════════════════════════════════════════════════
#  텔레그램 알림
# ═══════════════════════════════════════════════════════════════

def send_telegram(text: str, parse_mode: str = "HTML") -> bool:
    """텔레그램 메시지 전송"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[텔레그램] 미설정. 알림 건너뜀.")
        return False
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[텔레그램 오류] {e}")
        return False


def send_telegram_image(image_path: str, caption: str = "") -> bool:
    """텔레그램 이미지 전송"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    if not os.path.exists(image_path):
        return False
    try:
        with open(image_path, 'rb') as f:
            resp = httpx.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": f},
                timeout=30,
            )
        return resp.status_code == 200
    except Exception as e:
        print(f"[텔레그램 이미지 오류] {e}")
        return False


def format_alert_message(ticker: str, result: dict) -> str:
    """알림 메시지 포매팅"""
    signal = result.get("final_signal", "?")
    score = result.get("composite_score", 0)
    confidence = result.get("confidence", 0)
    dist = result.get("signal_distribution", {})

    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(signal, "⚪")

    msg = (
        f"{emoji} <b>{ticker} 에이전트 알림</b>\n\n"
        f"<b>신호:</b> {signal}\n"
        f"<b>점수:</b> {score:+.2f} / 10\n"
        f"<b>신뢰도:</b> {confidence} / 10\n"
        f"<b>분포:</b> 매수 {dist.get('buy', 0)} | 매도 {dist.get('sell', 0)} | 중립 {dist.get('neutral', 0)}\n\n"
    )

    # 상위 3개 tool 결과
    summaries = result.get("tool_summaries", [])
    sorted_tools = sorted(summaries, key=lambda x: abs(x.get("score", 0)), reverse=True)[:3]
    msg += "<b>주요 근거:</b>\n"
    for s in sorted_tools:
        t_emoji = "📈" if s["score"] > 0 else ("📉" if s["score"] < 0 else "➖")
        msg += f"  {t_emoji} {s['name']}: {s['signal']} ({s['score']:+.1f})\n"

    # LLM 판단 요약 (앞 300자)
    llm = result.get("llm_conclusion", "")
    if llm and not llm.startswith("[오류]"):
        # 첫 줄만 추출 (종합 판단 부분)
        first_section = llm.split("\n\n")[0][:300]
        msg += f"\n<b>LLM 판단:</b>\n{first_section}"

    msg += f"\n\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    return msg


# ═══════════════════════════════════════════════════════════════
#  분석 실행 엔진
# ═══════════════════════════════════════════════════════════════

def analyze_ticker(ticker: str, ai_mode: str = "ollama") -> Optional[dict]:
    """단일 종목 에이전트 분석"""
    try:
        print(f"  [{ticker}] 데이터 수집...")
        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)

        print(f"  [{ticker}] 펀더멘털/옵션/내부자 데이터 수집...")
        fundamentals = {}
        options_pcr = {}
        insider_trades = []
        try:
            fundamentals = fetch_fundamentals(ticker)
        except Exception as e:
            print(f"  [{ticker}] 펀더멘털 수집 실패: {e}")
        try:
            options_pcr = fetch_options_pcr(ticker)
        except Exception as e:
            print(f"  [{ticker}] 옵션 PCR 수집 실패: {e}")
        try:
            insider_trades = fetch_insider_trades(ticker)
        except Exception as e:
            print(f"  [{ticker}] 내부자 거래 수집 실패: {e}")

        print(f"  [{ticker}] 16개 기법 분석...")
        agent = ChartAnalysisAgent(ticker, df)
        result = agent.run(mode=ai_mode)

        result["fundamentals"] = fundamentals
        result["options_pcr"] = options_pcr
        result["insider_trades"] = insider_trades

        chart_path = None
        try:
            chart_path = generate_agent_chart(ticker, df, result)
            result["chart_path"] = chart_path
        except Exception as e:
            print(f"  [{ticker}] 차트 생성 실패: {e}")

        json_path = os.path.join(OUTPUT_DIR, f"{ticker}_agent_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)

        result["json_path"] = json_path
        result["analyzed_at"] = datetime.now().isoformat()

        print(f"  [{ticker}] 완료: {result.get('final_signal')} (점수: {result.get('composite_score')})")
        return result

    except Exception as e:
        print(f"  [{ticker}] 분석 실패: {e}")
        return None


def check_alert_condition(ticker: str, result: dict) -> Optional[dict]:
    """기준치 체크. 알림 대상이면 dict 반환, 아니면 None"""
    score = result.get("composite_score", 0)
    confidence = result.get("confidence", 0)
    signal = result.get("final_signal", "HOLD")

    # 1) 임계값 체크 (상향 조정: 기본 5.0 / -5.0)
    should_alert = False
    if confidence >= MIN_CONFIDENCE:
        if score >= BUY_THRESHOLD and signal == "BUY":
            should_alert = True
        elif score <= SELL_THRESHOLD and signal == "SELL":
            should_alert = True

    if not should_alert:
        reason = []
        if confidence < MIN_CONFIDENCE:
            reason.append(f"신뢰도 부족({confidence}<{MIN_CONFIDENCE})")
        if SELL_THRESHOLD < score < BUY_THRESHOLD:
            reason.append(f"점수 범위 밖({SELL_THRESHOLD}<{score}<{BUY_THRESHOLD})")
        print(f"  [{ticker}] 알림 조건 미충족: {', '.join(reason)}")
        return None

    # 1.5) 냉각기 체크 — 손절(SELL) 알림 이후 COOLING_OFF_DAYS 동안 BUY 알림 억제
    if signal == "BUY" and ticker in cooling_off_state:
        cool = cooling_off_state[ticker]
        elapsed_days = (datetime.now() - datetime.fromisoformat(cool["triggered_at"])).total_seconds() / 86400
        if elapsed_days < COOLING_OFF_DAYS:
            remaining = COOLING_OFF_DAYS - elapsed_days
            print(f"  [{ticker}] 냉각기 활성 중 ({remaining:.1f}일 남음, SELL 이후 BUY 억제)")
            return None
        else:
            del cooling_off_state[ticker]

    if signal == "SELL":
        cooling_off_state[ticker] = {
            "signal": signal,
            "triggered_at": datetime.now().isoformat(),
        }

    # 2) 중복 알림 억제 (동일 종목 + 동일 신호 → 1시간 내 1회만)
    COOLDOWN_SECONDS = 1 * 3600  # 1시간
    prev = latest_results.get(ticker, {})
    prev_signal = prev.get("result", {}).get("final_signal")
    prev_time = prev.get("alert_sent_at")

    if prev_signal == signal and prev_time:
        elapsed = (datetime.now() - datetime.fromisoformat(prev_time)).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            print(f"  [{ticker}] 중복 알림 억제 ({signal}, {elapsed/3600:.1f}시간 전 발송)")
            return None

    print(f"  [{ticker}] ⚡ 기준치 도달! {signal} (점수: {score}, 신뢰도: {confidence})")
    return {
        "ticker": ticker,
        "signal": signal,
        "score": score,
        "confidence": confidence,
        "result": result,
    }


def send_summary_alert(alerts: list):
    """스캔 완료 후 기준치 도달 종목을 요약 1건으로 텔레그램 전송.

    Sprint 3 업그레이드: 풍부한 포맷(telegram_bot.send_daily_digest) 사용.
    """
    if not alerts:
        return

    try:
        from telegram_bot import send_daily_digest

        digest_rows: List[Dict] = []
        for a in alerts:
            r = a.get("result") or {}
            digest_rows.append({
                "ticker": a.get("ticker"),
                "company_name": r.get("company_name"),
                "signal": (a.get("signal") or "").lower(),
                "score": a.get("score", 0),
                "confidence": a.get("confidence", 0),
                "entry_plan": r.get("entry_plan") or (r.get("final_decision") or {}).get("entry_plan"),
            })
        send_daily_digest(digest_rows, top_n=10, min_confidence=0.0)
    except Exception:
        # 새 모듈 실패 시 기본 포맷으로 폴백
        buy_alerts = [a for a in alerts if a["signal"] == "BUY"]
        sell_alerts = [a for a in alerts if a["signal"] == "SELL"]
        msg = f"📊 <b>에이전트 스캔 알림</b> ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n"
        msg += f"기준치 도달: {len(alerts)}개 종목\n\n"
        if buy_alerts:
            msg += "🟢 <b>매수 신호</b>\n"
            for a in sorted(buy_alerts, key=lambda x: x["score"], reverse=True):
                msg += f"  <b>{a['ticker']}</b>: {a['score']:+.1f}점 (신뢰도 {a['confidence']})\n"
            msg += "\n"
        if sell_alerts:
            msg += "🔴 <b>매도 신호</b>\n"
            for a in sorted(sell_alerts, key=lambda x: x["score"]):
                msg += f"  <b>{a['ticker']}</b>: {a['score']:+.1f}점 (신뢰도 {a['confidence']})\n"
        send_telegram(msg)

    # 알림 발송 시간 기록 (중복 억제용)
    for a in alerts:
        ticker = a["ticker"]
        latest_results[ticker] = {
            **latest_results.get(ticker, {}),
            "alert_sent_at": datetime.now().isoformat(),
        }


def _load_watchlist_files() -> list[str]:
    """stock_analyzer/watchlist.txt 단일 소스 로드 (WebUI에서 관리)"""
    seen = set()
    tickers = []
    # 단일 소스: stock_analyzer/watchlist.txt
    wl_file = os.path.join(os.path.dirname(__file__), "..", "stock_analyzer", "watchlist.txt")
    if os.path.exists(wl_file):
        with open(wl_file, 'r') as f:
            for line in f:
                t = line.strip().upper()
                if t and not t.startswith('#') and t not in seen:
                    tickers.append(t)
                    seen.add(t)
    return tickers


_WL_FILE = os.path.join(os.path.dirname(__file__), "..", "stock_analyzer", "watchlist.txt")


def _save_watchlist_file(tickers: list[str]):
    """watchlist.txt에 종목 목록 기록"""
    with open(_WL_FILE, 'w') as f:
        f.write("# 관심 종목 리스트 (한 줄에 하나, #은 주석)\n")
        f.write("# 빈 줄과 주석은 무시됨\n\n")
        for t in tickers:
            f.write(f"{t.upper()}\n")


def run_scheduled_scan(override_tickers: "list[str] | None" = None):
    """
    스케줄된 전체 종목 스캔.

    속도 최적화:
    1. 스캔 시작 전 yfinance 배치 사전 다운로드 (모든 종목 OHLCV 한 번에)
    2. LLM 분석은 SCAN_PARALLEL_WORKERS 수 만큼 병렬 실행
    3. 스캔 완료 후 OHLCV 캐시 초기화 (stale 방지)

    SCAN_PARALLEL_WORKERS 환경변수로 병렬 수 조정 (기본 3).
    Ollama OLLAMA_NUM_PARALLEL도 동일하게 설정 권장.
    """
    tickers = override_tickers if override_tickers else _load_watchlist_files()
    max_workers = int(_os.getenv("SCAN_PARALLEL_WORKERS", "3"))

    t_scan_start = time.time()
    print(f"\n{'='*60}")
    print(f"  스캔 시작: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  종목: {len(tickers)}개 - {', '.join(tickers)}")
    print(f"  병렬 워커: {max_workers}개")
    print(f"  임계값: 매수≥{BUY_THRESHOLD}, 매도≤{SELL_THRESHOLD}, 신뢰도≥{MIN_CONFIDENCE}")
    print(f"{'='*60}\n")

    # ── 단계 1: yfinance 배치 사전 다운로드 ──────────────────
    from data_collector import prefetch_ohlcv_batch, clear_ohlcv_cache
    clear_ohlcv_cache()
    prefetch_ohlcv_batch(tickers)

    scan_entry = {
        "timestamp": datetime.now().isoformat(),
        "tickers": tickers,
        "results": {},
        "alerts": [],
    }
    pending_alerts = []
    results_lock = __import__('threading').Lock()

    # ── 단계 2: 병렬 LLM 분석 ────────────────────────────────
    def _scan_one(ticker: str):
        """단일 종목 스캔 — ThreadPoolExecutor 워커 함수."""
        result = analyze_ticker(ticker)
        return ticker, result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_scan_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                ticker, result = future.result()
            except Exception as e:
                print(f"  [{ticker}] 오류: {e}")
                result = None

            if result:
                with results_lock:
                    latest_results[ticker] = {
                        "result": result,
                        "timestamp": datetime.now().isoformat(),
                        "alert_sent_at": latest_results.get(ticker, {}).get("alert_sent_at"),
                    }
                    scan_entry["results"][ticker] = {
                        "signal": result.get("final_signal"),
                        "score": result.get("composite_score"),
                        "confidence": result.get("confidence"),
                    }

                alert = check_alert_condition(ticker, result)
                if alert:
                    with results_lock:
                        pending_alerts.append(alert)
                        scan_entry["alerts"].append(ticker)

                insert_scan(ticker, result, alert_sent=(alert is not None))
                _try_insert_signal_outcome(ticker, result)

    # ── 단계 3: 캐시 정리 ─────────────────────────────────────
    clear_ohlcv_cache()

    elapsed = time.time() - t_scan_start
    avg = elapsed / len(tickers) if tickers else 0
    print(f"\n  ✅ 스캔 완료: {len(tickers)}개 종목 / {elapsed:.1f}s "
          f"(종목당 평균 {avg:.1f}s)")

    # 스캔 완료 후 기준치 도달 종목을 요약 1건으로 전송
    if pending_alerts:
        print(f"\n  📨 알림 대상: {len(pending_alerts)}개 종목")
        send_summary_alert(pending_alerts)
    else:
        print(f"\n  알림 대상 없음")

    # 히스토리 저장 (최근 100건)
    scan_history.append(scan_entry)
    if len(scan_history) > 100:
        scan_history.pop(0)

    print(f"\n  스캔 완료: {datetime.now().strftime('%H:%M')}")
    print(f"{'='*60}\n")


def _sanitize(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    try:
        import numpy as np
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            v = float(obj)
            return None if math.isnan(v) or math.isinf(v) else v
        if isinstance(obj, np.ndarray):
            return _sanitize(obj.tolist())
    except (ImportError, TypeError):
        pass
    return obj


# ═══════════════════════════════════════════════════════════════
#  FastAPI 앱
# ═══════════════════════════════════════════════════════════════

app = FastAPI(
    title="Chart Analysis Agent",
    description="16개 기법 차트 분석 에이전트 + 퀀트 시스템 API",
    version="1.0.0",
)


# ── GlobalKillSwitch 미들웨어 ─────────────────────────────────────────

class KillSwitchMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from safety.kill_switch import _is_kill_switch_protected, get_kill_switch
        if _is_kill_switch_protected(request.url.path):
            blocked, reason = get_kill_switch().is_blocked()
            if blocked:
                return JSONResponse(
                    status_code=423,
                    content={"detail": "kill_switch_active", "reason": reason},
                )
        return await call_next(request)


app.add_middleware(KillSwitchMiddleware)


@app.get("/")
def root():
    return {
        "service": "chart-analysis-agent",
        "status": "running",
        "model": OLLAMA_MODEL,
        "trading_style": TRADING_STYLE,
        "watchlist": WATCHLIST,
        "scan_interval": f"{SCAN_INTERVAL_MINUTES}분",
        "thresholds": {
            "buy": BUY_THRESHOLD,
            "sell": SELL_THRESHOLD,
            "min_confidence": MIN_CONFIDENCE,
        },
        "cooling_off_days": COOLING_OFF_DAYS,
        "cooling_off_active": {k: v for k, v in cooling_off_state.items()},
        "last_scan": scan_history[-1]["timestamp"] if scan_history else None,
        "cached_tickers": list(latest_results.keys()),
    }


@app.get("/results")
def get_all_results():
    """전체 최신 결과 조회"""
    summary = {}
    for ticker, data in latest_results.items():
        r = data.get("result", {})
        summary[ticker] = {
            "signal": r.get("final_signal"),
            "score": r.get("composite_score"),
            "confidence": r.get("confidence"),
            "signal_distribution": r.get("signal_distribution"),
            "analyzed_at": data.get("timestamp"),
            "alert_sent_at": data.get("alert_sent_at"),
        }
    return {"count": len(summary), "results": summary}


@app.get("/results/{ticker}")
def get_ticker_result(ticker: str):
    """특정 종목 상세 결과"""
    ticker = ticker.upper()
    if ticker not in latest_results:
        raise HTTPException(404, f"{ticker}: 분석 결과 없음. /scan/{ticker} 로 분석 실행 가능.")
    data = latest_results[ticker]
    payload = {
        "ticker": ticker,
        "timestamp": data.get("timestamp"),
        "alert_sent_at": data.get("alert_sent_at"),
        **data.get("result", {}),
    }
    return JSONResponse(content=_sanitize(payload))


@app.post("/scan/{ticker}")
def scan_ticker(ticker: str, ai_mode: str = "ollama"):
    """단일 종목 즉시 분석"""
    ticker = ticker.upper()
    result = analyze_ticker(ticker, ai_mode)
    if not result:
        raise HTTPException(500, f"{ticker}: 분석 실패")

    latest_results[ticker] = {
        "result": result,
        "timestamp": datetime.now().isoformat(),
        "alert_sent_at": latest_results.get(ticker, {}).get("alert_sent_at"),
    }
    alert = check_alert_condition(ticker, result)
    alert_sent = False
    if alert:
        send_summary_alert([alert])
        alert_sent = True
    insert_scan(ticker, result, alert_sent=alert_sent)
    _try_insert_signal_outcome(ticker, result)
    return result


@app.post("/scan")
def scan_all(ai_mode: str = "ollama", tickers: str = ""):
    """전체 watchlist 즉시 스캔. tickers 쿼리로 종목 지정 가능 (콤마 구분)."""
    override = [t.strip().upper() for t in tickers.split(",") if t.strip()] if tickers else None
    run_scheduled_scan(override_tickers=override)
    return {"status": "completed", "results": get_all_results()}


@app.get("/history")
def get_history(limit: int = 10):
    """스캔 히스토리 조회"""
    return {"count": len(scan_history), "history": scan_history[-limit:]}


@app.get("/chart/{ticker}")
def get_chart(ticker: str):
    """최신 차트 이미지 반환"""
    ticker = ticker.upper()
    data = latest_results.get(ticker, {})
    chart_path = data.get("result", {}).get("chart_path")
    if chart_path and os.path.exists(chart_path):
        return FileResponse(chart_path, media_type="image/png")
    raise HTTPException(404, f"{ticker}: 차트 없음")


@app.get("/health")
def health():
    """헬스 체크"""
    ollama_ok = False
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        ollama_ok = resp.status_code == 200
    except Exception:
        pass

    # Step 11: market session 메타 추가
    krx_session = nyse_session = "unknown"
    try:
        from market_cal.market_calendar import get_market_session
        krx_session = get_market_session("KRX")
        nyse_session = get_market_session("NYSE")
    except Exception:
        pass

    return {
        "status": "healthy",
        "ollama": "connected" if ollama_ok else "disconnected",
        "cached_results": len(latest_results),
        "scan_count": len(scan_history),
        "uptime_scans": len(scan_history),
        "market_session": {
            "KRX": krx_session,
            "NYSE": nyse_session,
        },
    }


@app.get("/backtest/{ticker}")
def get_backtest(ticker: str):
    """단일 종목 백테스트 결과"""
    ticker = ticker.upper()
    data = latest_results.get(ticker, {})
    r = data.get("result", {})
    if not r:
        raise HTTPException(404, f"{ticker}: 분석 결과 없음. 먼저 /scan/{ticker} 실행 필요.")
    try:
        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)
        tool_results = r.get("tool_details", [])
        return run_all_backtests(ticker, df, tool_results)
    except Exception as e:
        raise HTTPException(500, f"백테스트 실패: {e}")


@app.get("/ml/{ticker}")
def get_ml_prediction(ticker: str):
    """ML 방향 예측"""
    ticker = ticker.upper()
    try:
        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)
        return run_ml_prediction(ticker, df)
    except Exception as e:
        raise HTTPException(500, f"ML 예측 실패: {e}")


@app.get("/risk/{ticker}")
def get_risk_metrics(ticker: str, method: str = "historical", nav: float = 100_000.0):
    """VaR/CVaR 일별 리스크 지표 (P2). method: historical|parametric|cornish_fisher."""
    ticker = ticker.upper()
    try:
        from risk_management import PortfolioRiskCalculator

        df = fetch_ohlcv(ticker)
        returns = df["Close"].pct_change().dropna()
        if len(returns) < 20:
            raise HTTPException(400, f"{ticker}: 수익률 데이터 부족 (최소 20일 필요)")

        calc = PortfolioRiskCalculator(returns, nav=nav)
        result = calc.compute_all(method=method)
        result["ticker"] = ticker
        return _sanitize(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"리스크 계산 실패: {exc}")


@app.get("/calibration/status")
def get_calibration_status():
    """LLM conviction 보정기 상태 조회 (P2)."""
    try:
        from llm_calibrator import get_calibrator
        return get_calibrator().status()
    except Exception as exc:
        raise HTTPException(500, f"보정기 상태 조회 실패: {exc}")


@app.post("/calibration/fit")
def fit_calibration():
    """LLM conviction 보정기 재학습 (P2). signal_outcomes 60일+ 누적 필요."""
    try:
        from llm_calibrator import get_calibrator
        return get_calibrator().fit()
    except Exception as exc:
        raise HTTPException(500, f"보정기 학습 실패: {exc}")


@app.get("/ic-weights")
def get_ic_weights(days: int = 90):
    """소스별 IC(Information Coefficient) 가중치 현황 (P2)."""
    try:
        from ic_ensemble import get_ic_summary
        return get_ic_summary(days=days)
    except Exception as exc:
        raise HTTPException(500, f"IC 계산 실패: {exc}")


@app.get("/portfolio/optimize")
def get_portfolio_optimization(method: str = "markowitz"):
    """포트폴리오 최적화 (마코위츠/리스크패리티)"""
    tickers = list(latest_results.keys())
    if len(tickers) < 2:
        raise HTTPException(400, "최소 2개 종목 분석 결과 필요")
    if method == "risk_parity":
        return risk_parity_optimize(tickers)
    return markowitz_optimize(tickers)


@app.get("/portfolio/correlation")
def get_correlation_beta():
    """종목 간 상관관계/베타 분석"""
    tickers = list(latest_results.keys())
    if not tickers:
        raise HTTPException(400, "분석 결과 없음")
    return compute_correlation_beta(tickers)


@app.get("/ranking")
def get_factor_ranking():
    """팩터 기반 크로스섹션 종목 랭킹"""
    ranking = compute_factor_ranking(latest_results)
    return {"count": len(ranking), "ranking": ranking}


@app.get("/paper")
def get_paper_status():
    """페이퍼 트레이딩 포트폴리오 현황"""
    return get_portfolio_status()


@app.post("/paper/order")
def paper_order(ticker: str, action: str, qty: int, price: float, reason: str = "",
                stop_loss_price: float = 0.0, take_profit_price: float = 0.0,
                trailing_stop_pct: float = 0.0, time_stop_days: int = 0):
    """페이퍼 트레이딩 수동 주문 (손절/익절/trailing 지정 가능)."""
    ticker = ticker.upper()
    action = action.upper()
    if action not in ("BUY", "SELL"):
        raise HTTPException(400, "action은 BUY 또는 SELL")
    return execute_paper_order(
        ticker, action, qty, price, reason,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
        trailing_stop_pct=trailing_stop_pct,
        time_stop_days=time_stop_days,
    )


class VirtualBuyBody(BaseModel):
    """가상 매수 요청 (수동 진입용 — 분석 결과 연동 포함)."""
    ticker: str
    qty: int
    price: float                              # 사용자가 지정한 진입가
    reason: Optional[str] = None              # 진입 근거 메모
    stop_loss_price: Optional[float] = None   # 손절가 (선택)
    take_profit_price: Optional[float] = None # 익절가 (선택)
    trailing_stop_pct: Optional[float] = None # trailing stop 비율 (0~1)
    time_stop_days: Optional[int] = None      # 시간 기반 청산 일수


@app.post("/paper/virtual-buy")
def api_virtual_buy(body: VirtualBuyBody):
    """
    수동 가상 매수 — 사용자가 정한 시점/가격/수량으로 포지션 생성.
    Multi-Agent 분석의 entry_plan 데이터도 이 엔드포인트로 보낼 수 있음.
    """
    return execute_paper_order(
        ticker=body.ticker.upper(),
        action="BUY",
        qty=body.qty,
        price=body.price,
        reason=body.reason or "수동 가상 매수",
        stop_loss_price=body.stop_loss_price or 0.0,
        take_profit_price=body.take_profit_price or 0.0,
        trailing_stop_pct=body.trailing_stop_pct or 0.0,
        time_stop_days=body.time_stop_days or 0,
    )


class PartialCloseBody(BaseModel):
    ticker: str
    close_pct: float = 100.0  # 청산 비율 (0~100)
    price: Optional[float] = None  # None이면 현재가 자동 조회
    reason: Optional[str] = None


@app.post("/paper/partial-close")
def api_partial_close(body: PartialCloseBody):
    """
    포지션 부분/전량 청산.
    close_pct: 100 = 전량, 50 = 절반, 등
    price: 미지정 시 현재가(yfinance) 자동 조회
    """
    ticker = body.ticker.upper()
    state = _get_paper_state()
    pos = state.get("positions", {}).get(ticker)
    if not pos:
        raise HTTPException(404, f"{ticker} 포지션 없음")

    close_pct = max(0.01, min(100.0, body.close_pct))
    close_qty = max(1, int(pos["qty"] * close_pct / 100))
    close_qty = min(close_qty, pos["qty"])

    price = body.price
    if price is None or price <= 0:
        try:
            df = fetch_ohlcv(ticker, period="5d")
            price = float(df["Close"].iloc[-1])
        except Exception:
            raise HTTPException(400, "현재가 조회 실패. price를 명시하세요.")

    return execute_paper_order(
        ticker=ticker, action="SELL", qty=close_qty, price=float(price),
        reason=body.reason or f"수동 부분 청산 ({close_pct:.0f}%)",
    )


def _get_paper_state():
    """paper_trader 내부 상태 참조용 (부분청산 qty 계산 필요)."""
    from paper_trader import _load_state
    return _load_state()


@app.get("/paper/quote/{ticker}")
def api_paper_quote(ticker: str):
    """
    현재가 + 호가단위 조회 (수동 진입 시 참고용).
    """
    ticker = ticker.upper()
    try:
        df = fetch_ohlcv(ticker, period="5d")
        if df is None or df.empty:
            raise HTTPException(404, f"{ticker} 데이터 없음")
        latest = df.iloc[-1]
        current = float(latest["Close"])
        day_high = float(latest["High"])
        day_low = float(latest["Low"])
        prev_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else current

        from tick_size import round_to_tick, tick_size_for
        tick = tick_size_for(ticker, current)

        return {
            "ticker": ticker,
            "current_price": current,
            "day_high": day_high,
            "day_low": day_low,
            "prev_close": prev_close,
            "change_pct": round((current / prev_close - 1) * 100, 2) if prev_close else 0,
            "tick_size": tick,
            "suggested_limit_up": round_to_tick(current * 1.001, ticker, side="up"),
            "suggested_limit_down": round_to_tick(current * 0.999, ticker, side="down"),
            "as_of": str(df.index[-1])[:19],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"조회 실패: {str(e)[:100]}")


@app.post("/paper/update-prices")
def api_update_prices():
    """
    보유 포지션의 현재가를 일괄 갱신 + trailing/time/SL/TP 체크.
    WebUI에서 "가격 갱신" 버튼으로 수동 호출 가능.
    """
    state = _get_paper_state()
    tickers = list(state.get("positions", {}).keys())
    if not tickers:
        return {"updated": 0, "auto_closed": [], "positions": {}}

    prices = {}
    for t in tickers:
        try:
            df = fetch_ohlcv(t, period="5d")
            if df is not None and not df.empty:
                prices[t] = float(df["Close"].iloc[-1])
        except Exception:
            continue

    auto_closed = update_position_prices(prices)
    return {
        "updated": len(prices),
        "prices": prices,
        "auto_closed": auto_closed,
    }


@app.post("/paper/auto")
def paper_auto_trade():
    """최신 분석 결과 기반 자동 모의매매 실행"""
    orders = []
    for ticker, data in latest_results.items():
        r = data.get("result", {})
        if not r:
            continue
        try:
            price = float(r.get("tool_details", [{}])[0].get("entry_price", 0))
            if price <= 0:
                df = fetch_ohlcv(ticker)
                price = float(df["Close"].iloc[-1])
        except Exception:
            continue
        update_position_prices({ticker: price})
        order = process_agent_signal(ticker, r, price)
        if order:
            orders.append(order)
    return {"executed": len(orders), "orders": orders}


@app.post("/paper/reset")
def paper_reset():
    """페이퍼 트레이딩 초기화"""
    return reset_paper_trading()


# ═══════════════════════════════════════════════════════════════
#  확장 API: 뉴스, 차트 패턴, 섹터 비교, 매크로
# ═══════════════════════════════════════════════════════════════

@app.get("/news/{ticker}")
def get_news(ticker: str):
    """종목 뉴스 수집 + Ollama 감성 분석"""
    ticker = ticker.upper()
    try:
        result = fetch_news_with_sentiment(ticker)
        return JSONResponse(content=_sanitize(result))
    except Exception as e:
        raise HTTPException(500, f"뉴스 수집 실패: {e}")


@app.get("/chart-pattern/{ticker}")
def get_chart_pattern(ticker: str):
    """알고리즘 기반 차트 패턴 인식"""
    ticker = ticker.upper()
    try:
        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)
        # 기존 캐시된 차트 경로 활용
        chart_path = latest_results.get(ticker, {}).get("result", {}).get("chart_path")
        result = detect_chart_patterns(ticker, df, chart_path)
        return JSONResponse(content=_sanitize(result))
    except Exception as e:
        raise HTTPException(500, f"차트 패턴 분석 실패: {e}")


@app.get("/sector/{ticker}")
def get_sector_compare(ticker: str):
    """섹터/산업 내 상대 위치 비교"""
    ticker = ticker.upper()
    try:
        result = compare_sector(ticker)
        return JSONResponse(content=_sanitize(result))
    except Exception as e:
        raise HTTPException(500, f"섹터 비교 실패: {e}")


@app.get("/macro")
def get_macro():
    """매크로 경제 지표 및 시장 분위기"""
    try:
        result = fetch_macro_context()
        return JSONResponse(content=_sanitize(result))
    except Exception as e:
        raise HTTPException(500, f"매크로 데이터 수집 실패: {e}")


@app.get("/regime")
def get_regime():
    """현재 시장 체제 감지 (VIX·ATR%·VHF·ADX·20d 모멘텀 기반)."""
    try:
        from regime.detector import detect_market_regime, fetch_market_features
        from regime.models import MacroContext

        macro = fetch_macro_context()
        vix_val = (macro.get("vix") or {}).get("value") or 20.0
        ctx = MacroContext(vix=float(vix_val))
        mkt = fetch_market_features()
        regime = detect_market_regime(ctx, mkt)

        return {
            "regime": regime.value,
            "inputs": {
                "vix": vix_val,
                "vhf": round(mkt.vhf, 4),
                "adx": round(mkt.adx, 2),
                "atr_pct": round(mkt.atr_pct, 3),
                "kospi_momentum_20d": round(mkt.kospi_momentum_20d, 4),
                "spx_momentum_20d": round(mkt.spx_momentum_20d, 4),
            },
        }
    except Exception as exc:
        raise HTTPException(500, f"regime 감지 실패: {exc}")


# ═══════════════════════════════════════════════════════════════
#  Watchlist 관리 API
# ═══════════════════════════════════════════════════════════════

@app.get("/watchlist")
def api_get_watchlist():
    """watchlist 조회"""
    tickers = _load_watchlist_files()
    return {"count": len(tickers), "tickers": tickers}


@app.post("/watchlist/add")
def api_watchlist_add(ticker: str):
    """종목 추가"""
    ticker = ticker.upper()
    current = _load_watchlist_files()
    if ticker in current:
        return {"ok": False, "msg": f"{ticker} 이미 존재", "tickers": current}
    current.append(ticker)
    _save_watchlist_file(current)
    return {"ok": True, "msg": f"{ticker} 추가됨", "tickers": current}


@app.post("/watchlist/remove")
def api_watchlist_remove(ticker: str):
    """종목 제거"""
    ticker = ticker.upper()
    current = _load_watchlist_files()
    if ticker not in current:
        return {"ok": False, "msg": f"{ticker} 없음", "tickers": current}
    current.remove(ticker)
    _save_watchlist_file(current)
    return {"ok": True, "msg": f"{ticker} 제거됨", "tickers": current}


@app.post("/watchlist/set")
def api_watchlist_set(tickers: str):
    """watchlist 전체 교체 (콤마 구분)"""
    clean = list(dict.fromkeys(t.strip().upper() for t in tickers.split(",") if t.strip()))
    _save_watchlist_file(clean)
    return {"ok": True, "msg": f"{len(clean)}개 종목 설정됨", "tickers": clean}


# ═══════════════════════════════════════════════════════════════
#  Multi-Agent API (V2.0)
# ═══════════════════════════════════════════════════════════════

@app.get("/multi-agent/{ticker}")
def get_multi_agent_analysis(ticker: str):
    """Multi-Agent 분석 (V2.0) - 5개 에이전트 병렬 분석"""
    ticker = ticker.upper()

    if MultiAgentOrchestrator is None:
        raise HTTPException(503, "Multi-Agent module not available")

    try:
        print(f"\n[Multi-Agent] Starting analysis for {ticker}")

        # Multi-Agent 분석 실행
        orchestrator = MultiAgentOrchestrator()
        result = orchestrator.analyze(ticker)

        print(f"[Multi-Agent] Analysis complete for {ticker}")

        # 그룹별 시그널 signal_outcomes에 기록
        _try_insert_group_outcomes(ticker, result)

        # 결과 정제
        sanitized_result = _sanitize(result)

        return JSONResponse(content=sanitized_result)

    except Exception as e:
        print(f"[Multi-Agent] Error analyzing {ticker}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Multi-Agent 분석 실패: {e}")


# ═══════════════════════════════════════════════════════════════
#  스캔 로그 / 주간 요약 API
# ═══════════════════════════════════════════════════════════════

@app.get("/scan-log")
def api_scan_log(limit: int = 50, offset: int = 0):
    """스캔 로그 조회 (페이지네이션)"""
    return get_scan_logs(limit, offset)


@app.get("/scan-log/latest")
def api_scan_log_latest():
    """가장 최근 스캔 라운드 결과"""
    return get_scan_log_latest()


@app.get("/scan-log/range")
def api_scan_log_range(start: str, end: str):
    """날짜 범위 조회 (?start=2026-04-07&end=2026-04-13)"""
    return get_scan_log_date_range(start, end)


@app.get("/scan-log/{ticker}")
def api_scan_log_ticker(ticker: str, limit: int = 30):
    """종목별 스캔 로그"""
    return get_scan_logs_by_ticker(ticker, limit)


@app.get("/weekly")
def api_weekly(weeks_ago: int = 0):
    """주간 요약 리포트 (?weeks_ago=0 이번주, 1 지난주)"""
    return get_weekly_summary(weeks_ago)


@app.get("/weekly/{ticker}")
def api_weekly_ticker(ticker: str, weeks_ago: int = 0):
    """종목별 주간 상세"""
    return get_weekly_ticker(ticker, weeks_ago)


# ─── Phase 2.1: 주문 실행 API ──────────────────────────


class OrderSubmitBody(BaseModel):
    ticker: str
    entry_plan: Optional[Dict] = None
    position_pct: Optional[float] = None
    source: str = "manual"
    reason: Optional[str] = None


@app.get("/trading/mode")
def api_get_trading_mode():
    """현재 TRADING_MODE 조회."""
    from brokers import get_trading_mode
    from brokers.safety import get_safety
    return {
        "mode": get_trading_mode(),
        "safety": get_safety().get_status(),
    }


@app.post("/trading/mode")
def api_set_trading_mode(mode: str):
    """
    런타임에 TRADING_MODE 변경.
    유효값: paper | dry_run | approval | live
    """
    from brokers import get_trading_mode, VALID_MODES  # type: ignore
    from brokers.factory import VALID_MODES as _valid
    if mode.lower() not in _valid:
        return {"ok": False, "error": f"invalid mode: {mode}. Must be one of {_valid}"}
    os.environ["TRADING_MODE"] = mode.lower()
    return {"ok": True, "mode": mode.lower()}


@app.post("/trading/kill-switch/activate")
def api_activate_kill_switch(reason: str = "manual"):
    """긴급 중지 활성화."""
    from brokers.safety import get_safety
    safety = get_safety()
    safety.activate_kill_switch(reason=reason)
    return {"ok": True, "active": safety.is_kill_switch_active()}


@app.post("/trading/kill-switch/deactivate")
def api_deactivate_kill_switch(reason: str = "manual"):
    """긴급 중지 해제."""
    from brokers.safety import get_safety
    safety = get_safety()
    safety.deactivate_kill_switch(reason=reason)
    return {"ok": True, "active": safety.is_kill_switch_active()}


@app.get("/trading/broker-health")
def api_broker_health():
    """현재 브로커 연결 상태."""
    from brokers import get_broker
    broker = get_broker()
    return {
        "broker": broker.name,
        "health": broker.health_check(),
        "market_open": broker.is_market_open(),
    }


@app.get("/trading/broker-health/{broker_name}")
def api_broker_health_specific(broker_name: str):
    """특정 브로커 연결 상태 (alpaca/paper/dry_run)."""
    bn = broker_name.lower()
    if bn == "alpaca":
        from brokers.alpaca_broker import AlpacaBroker
        broker = AlpacaBroker()
    elif bn == "paper":
        from brokers.paper_broker import PaperBroker
        broker = PaperBroker()
    elif bn == "dry_run":
        from brokers.dry_run_broker import DryRunBroker
        broker = DryRunBroker()
    else:
        return {"ok": False, "error": f"unknown broker: {broker_name}"}
    return {
        "broker": broker.name,
        "health": broker.health_check(),
        "market_open": broker.is_market_open(),
    }


@app.get("/data-source")
def api_data_source_status():
    """현재 데이터 소스 상태 조회."""
    from data_sources import get_data_source, get_data_source_name
    source = get_data_source()
    return {
        "configured": get_data_source_name(),
        "active": source.name,
        "health": source.health_check(),
    }


@app.get("/trading/account")
def api_trading_account():
    """브로커 계좌 정보."""
    from brokers import get_broker
    return get_broker().get_account()


@app.get("/trading/positions")
def api_trading_positions():
    """현재 포지션."""
    from brokers import get_broker
    return {"positions": get_broker().get_positions()}


@app.post("/trading/orders")
def api_submit_order(body: OrderSubmitBody):
    """
    주문 제출 (entry_plan 기반).
    TRADING_MODE 따라 paper 즉시 체결 / dry_run 로깅만 / approval 큐 / live 실제 제출.
    """
    from execution.order_router import route_entry_plan

    if not body.entry_plan:
        return {"ok": False, "error": "entry_plan required"}

    result = route_entry_plan(
        ticker=body.ticker.upper(),
        entry_plan=body.entry_plan,
        position_pct=body.position_pct,
        source=body.source,
        reason=body.reason,
    )
    return {"ok": True, **result.to_dict()}


@app.get("/trading/orders/recent")
def api_recent_orders(limit: int = 50, ticker: Optional[str] = None):
    """최근 주문 감사 로그."""
    from execution import get_audit_log
    return {"orders": get_audit_log().get_recent(limit=limit, ticker=ticker)}


@app.get("/trading/orders/stats")
def api_order_stats(days_back: int = 7):
    """주문 통계."""
    from execution import get_audit_log
    return get_audit_log().get_stats(days_back=days_back)


@app.get("/trading/approval/pending")
def api_approval_pending():
    """승인 대기 중인 주문."""
    from execution import get_approval_queue
    queue = get_approval_queue()
    queue.expire_old()  # 기회에 만료 처리
    return {"pending": queue.get_pending(), "stats": queue.stats()}


@app.post("/trading/approval/{queue_id}/approve")
def api_approve_order(queue_id: int):
    """승인 큐 주문 승인 + 실제 실행."""
    from execution.order_router import OrderRouter
    router = OrderRouter()
    result = router.execute_approved(queue_id)
    return {"executed": result.success, "result": result.to_dict()}


@app.post("/trading/approval/{queue_id}/reject")
def api_reject_order(queue_id: int):
    """승인 큐 주문 거절."""
    from execution import get_approval_queue
    ok = get_approval_queue().reject(queue_id, responder="api")
    return {"ok": ok}


# ─── Telegram 알림 API (Sprint 3) ──────────────────────
@app.post("/telegram/rich-signal/{ticker}")
def api_telegram_rich_signal(ticker: str, webui_base_url: Optional[str] = None):
    """
    풍부한 신호 알림 발송. 사전에 해당 ticker 분석이 완료되어 있어야 함.
    - ticker: 종목 티커
    - webui_base_url: deep link 용 (선택)
    """
    from telegram_bot import send_rich_signal_alert
    from signal_tracker import get_accuracy_stats

    ticker = ticker.upper()
    cached = latest_results.get(ticker)
    if not cached:
        return {"sent": False, "error": "해당 종목의 분석 결과가 없습니다. 먼저 /scan/{ticker} 호출 필요."}

    result = cached.get("result") or {}
    # Multi-Agent 결과라면 final_decision 포함
    final_decision = result.get("final_decision") or {
        "final_signal": result.get("final_signal"),
        "final_confidence": result.get("confidence"),
        "consensus": f"점수 {result.get('composite_score', 0):+.2f}",
        "reasoning": (result.get("llm_conclusion") or "")[:300],
        "key_risks": [],
        "entry_plan": result.get("entry_plan"),
    }

    try:
        acc = get_accuracy_stats(horizon=7, days_back=180)
    except Exception:
        acc = None

    sent = send_rich_signal_alert(
        ticker=ticker,
        final_decision=final_decision,
        company_name=result.get("company_name"),
        accuracy_stats=acc,
        webui_base_url=webui_base_url,
    )
    return {"sent": sent, "ticker": ticker}


@app.post("/telegram/daily-digest")
def api_telegram_daily_digest(top_n: int = 5, min_confidence: float = 6.0):
    """
    latest_results의 현재 스캔 요약을 일일 다이제스트 형식으로 발송.
    """
    from telegram_bot import send_daily_digest

    scan_rows: List[Dict] = []
    for ticker, entry in (latest_results or {}).items():
        r = entry.get("result") or {}
        if not r:
            continue
        # Multi-Agent or Single LLM 정규화
        if r.get("final_decision"):
            fd = r["final_decision"]
            scan_rows.append({
                "ticker": ticker,
                "company_name": r.get("company_name"),
                "signal": (fd.get("final_signal") or "").lower(),
                "score": r.get("composite_score") or 0,
                "confidence": fd.get("final_confidence") or 0,
                "entry_plan": fd.get("entry_plan"),
            })
        else:
            scan_rows.append({
                "ticker": ticker,
                "signal": (r.get("final_signal") or "").lower(),
                "score": r.get("composite_score") or 0,
                "confidence": r.get("confidence") or 0,
                "entry_plan": r.get("entry_plan"),
            })

    sent = send_daily_digest(scan_rows, top_n=top_n, min_confidence=min_confidence)
    return {"sent": sent, "total_scans": len(scan_rows)}


@app.post("/telegram/process-callbacks")
def api_telegram_process_callbacks():
    """
    보류 중인 인라인 버튼 콜백(워치리스트 추가/무시) 처리.
    스케줄러가 주기적으로 호출하거나 수동 실행.
    """
    from telegram_bot import process_callback_updates

    def _watch_handler(ticker: str) -> str:
        # watchlist.txt에 티커 추가 (stock_analyzer 쪽)
        try:
            wl_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "stock_analyzer", "watchlist.txt"
            )
            existing = set()
            if os.path.exists(wl_path):
                with open(wl_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            existing.add(line.upper())
            t = ticker.upper().strip()
            if t in existing:
                return f"{t} 이미 워치리스트에 있음"
            existing.add(t)
            header = (
                "# 관심 종목 리스트 (SSOT: WebUI/백엔드/배치 스크립트 공용)\n"
                "# 한 줄에 하나, #은 주석, 빈 줄은 무시됨\n\n"
            )
            with open(wl_path, "w", encoding="utf-8") as f:
                f.write(header)
                for t2 in sorted(existing):
                    f.write(t2 + "\n")
            return f"✅ {t} 워치리스트 추가됨"
        except Exception:
            return "워치리스트 업데이트 실패"

    def _mute_handler(ticker: str) -> str:
        # 간단히 쿨다운 테이블에 mark (이미 cooling_off 있음)
        try:
            cooling_off_state[ticker.upper()] = {
                "signal": "MUTED",
                "triggered_at": datetime.now().isoformat(),
            }
            return f"🚫 {ticker} 당분간 무시됨"
        except Exception:
            return "설정 실패"

    def _approve_handler(queue_id_str: str) -> str:
        """Phase 2.1: 주문 승인 콜백."""
        try:
            from execution.order_router import OrderRouter
            queue_id = int(queue_id_str)
            router = OrderRouter()
            result = router.execute_approved(queue_id)
            if result.success:
                return f"✅ 주문 {queue_id} 실행됨 ({result.status})"
            return f"❌ 실행 실패: {result.error_message or result.status}"
        except Exception as e:
            return f"승인 처리 실패: {str(e)[:50]}"

    def _reject_handler(queue_id_str: str) -> str:
        """Phase 2.1: 주문 거절 콜백."""
        try:
            from execution import get_approval_queue
            queue_id = int(queue_id_str)
            ok = get_approval_queue().reject(queue_id, responder="telegram")
            return f"❌ 주문 {queue_id} 거절됨" if ok else "이미 처리됨"
        except Exception as e:
            return f"거절 처리 실패: {str(e)[:50]}"

    handlers = {
        "watch": _watch_handler,
        "mute": _mute_handler,
        "approve": _approve_handler,
        "reject": _reject_handler,
    }
    return process_callback_updates(handlers)


# ─── Screener (한국 주식 기술적 스크리너 V1) ──────────
@app.post("/screener/run")
def api_screener_run(min_market_cap_bn: float = 2000, top_n: int = 20):
    """
    한국 주식 스크리너 수동 실행.
    - min_market_cap_bn: 최소 시총 (억원 단위, 기본 2000 = 2천억)
    - top_n: 상위 몇 개 반환 (기본 20)
    """
    from screener import run_screener
    # 억원 → 원
    min_cap = float(min_market_cap_bn) * 1e8
    return run_screener(min_market_cap=min_cap, top_n=int(top_n), save_db=True)


@app.get("/screener/latest")
def api_screener_latest(limit: int = 20):
    """가장 최근 스크리너 실행 결과 조회 (DB)."""
    from db import get_screener_latest
    return get_screener_latest(limit=limit)


@app.get("/screener/history")
def api_screener_history(days_back: int = 30):
    """최근 N일 스크리너 실행 이력 (run별 요약)."""
    from db import get_screener_history
    return get_screener_history(days_back=days_back)


@app.post("/screener/pipeline")
def api_screener_pipeline(
    min_market_cap_bn: float = 2000,
    top_n: int = 20,
    analyze_top: int = 5,
):
    """
    스크리너 → Multi-Agent 자동 파이프라인.

    - min_market_cap_bn: 최소 시총 (억원, 기본 2000)
    - top_n: 스크리너 상위 몇 개 (기본 20)
    - analyze_top: 그 중 Multi-Agent 자동 심층 분석할 상위 개수 (기본 5)

    소요: 약 5~7분 (스크리너 2분 + Multi-Agent 5개 × 1분 병렬)
    """
    from screener import run_screener_with_multiagent
    min_cap = float(min_market_cap_bn) * 1e8
    return run_screener_with_multiagent(
        min_market_cap=min_cap,
        top_n=int(top_n),
        analyze_top=int(analyze_top),
        save_db=True,
    )


# ─── 신호 정확도 / 칼리브레이션 (Sprint 2) ──────────────
@app.get("/signal-accuracy")
def api_signal_accuracy(horizon: int = 7, min_confidence: float = 0.0,
                         signal: str = None, days_back: int = 180):
    """
    신호 정확도 통계 조회.
    - horizon: 7, 14, 30 (평가 기간 일수)
    - min_confidence: 이 값 이상만 집계 (0~10)
    - signal: "buy"|"sell"|"neutral" (선택)
    - days_back: 최근 N일 데이터만 대상
    """
    from signal_tracker import get_accuracy_stats
    return get_accuracy_stats(
        horizon=horizon, min_confidence=min_confidence,
        signal=signal, days_back=days_back
    )


@app.post("/signal-accuracy/evaluate")
def api_signal_evaluate(days_back: int = 45, limit: int = 500):
    """과거 신호에 대한 실제 결과 평가를 수동 실행."""
    from signal_tracker import run_daily_validation
    return run_daily_validation(days_back=days_back, limit=limit)


@app.get("/signal-accuracy/calibrator")
def api_calibrator_status():
    """신뢰도 칼리브레이터 현재 상태."""
    from signal_tracker import get_calibrator
    calib = get_calibrator()
    return calib.status()


@app.post("/restart")
def restart_service():
    """서비스 자체 재시작. 현재 프로세스를 동일 인자로 다시 실행."""
    print(f"\n{'='*60}")
    print(f"  재시작 요청 수신: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    def _restart():
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    import threading
    threading.Thread(target=_restart, daemon=True).start()
    return {"status": "restarting", "message": "Service will restart in 1 second."}


# ═══════════════════════════════════════════════════════════════
#  메인 실행
# ═══════════════════════════════════════════════════════════════

def main():
    print(f"\n{'='*60}")
    print(f"  차트 분석 에이전트 서비스 시작")
    print(f"  API: http://{API_HOST}:{API_PORT}")
    print(f"  모델: {OLLAMA_MODEL}")
    print(f"  스캔 주기: {SCAN_INTERVAL_MINUTES}분")
    print(f"  종목: {WATCHLIST}")
    print(f"  매수 임계: ≥{BUY_THRESHOLD}, 매도 임계: ≤{SELL_THRESHOLD}")
    print(f"{'='*60}\n")

    # DB 초기화
    init_db()

    # 스케줄러 시작
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scheduled_scan,
        'interval',
        minutes=SCAN_INTERVAL_MINUTES,
        id='watchlist_scan',
        next_run_time=datetime.now(),  # 시작 즉시 1회 실행
    )
    scheduler.start()
    print(f"[스케줄러] {SCAN_INTERVAL_MINUTES}분 간격 스캔 등록 완료\n")

    # FastAPI 서버 시작
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")


if __name__ == "__main__":
    main()
