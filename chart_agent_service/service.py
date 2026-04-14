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
import os
import sys
import time
import subprocess
from datetime import datetime
from typing import Optional

import httpx
import uvicorn
import math
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler

from config import (
    API_HOST, API_PORT, SCAN_INTERVAL_MINUTES,
    WATCHLIST, OLLAMA_MODEL,
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
    """스캔 완료 후 기준치 도달 종목을 요약 1건으로 텔레그램 전송"""
    if not alerts:
        return

    buy_alerts = [a for a in alerts if a["signal"] == "BUY"]
    sell_alerts = [a for a in alerts if a["signal"] == "SELL"]

    msg = f"📊 <b>에이전트 스캔 알림</b> ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n"
    msg += f"기준치 도달: {len(alerts)}개 종목\n\n"

    if buy_alerts:
        msg += "🟢 <b>매수 신호</b>\n"
        for a in sorted(buy_alerts, key=lambda x: x["score"], reverse=True):
            top_tools = sorted(
                a["result"].get("tool_summaries", []),
                key=lambda x: x.get("score", 0), reverse=True
            )[:2]
            tools_str = ", ".join(f"{t['name']}({t['score']:+.0f})" for t in top_tools)
            msg += f"  <b>{a['ticker']}</b>: {a['score']:+.1f}점 (신뢰도 {a['confidence']}) [{tools_str}]\n"
        msg += "\n"

    if sell_alerts:
        msg += "🔴 <b>매도 신호</b>\n"
        for a in sorted(sell_alerts, key=lambda x: x["score"]):
            top_tools = sorted(
                a["result"].get("tool_summaries", []),
                key=lambda x: x.get("score", 0)
            )[:2]
            tools_str = ", ".join(f"{t['name']}({t['score']:+.0f})" for t in top_tools)
            msg += f"  <b>{a['ticker']}</b>: {a['score']:+.1f}점 (신뢰도 {a['confidence']}) [{tools_str}]\n"

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


def run_scheduled_scan(override_tickers: "list[str] | None" = None):
    """스케줄된 전체 종목 스캔. override_tickers가 주어지면 해당 목록만 스캔."""
    tickers = override_tickers if override_tickers else _load_watchlist_files()

    print(f"\n{'='*60}")
    print(f"  스캔 시작: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  종목: {len(tickers)}개 - {', '.join(tickers)}")
    print(f"  임계값: 매수≥{BUY_THRESHOLD}, 매도≤{SELL_THRESHOLD}, 신뢰도≥{MIN_CONFIDENCE}")
    print(f"{'='*60}\n")

    scan_entry = {
        "timestamp": datetime.now().isoformat(),
        "tickers": tickers,
        "results": {},
        "alerts": [],
    }

    pending_alerts = []  # 알림 대상 수집

    for ticker in tickers:
        result = analyze_ticker(ticker)
        if result:
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

            # 개별 전송하지 않고 수집만
            alert = check_alert_condition(ticker, result)
            if alert:
                pending_alerts.append(alert)
                scan_entry["alerts"].append(ticker)

            # DB 기록
            insert_scan(ticker, result, alert_sent=(alert is not None))

        time.sleep(3)  # API 부하 방지

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
        resp = httpx.get(f"http://localhost:11434/api/tags", timeout=3)
        ollama_ok = resp.status_code == 200
    except Exception:
        pass

    return {
        "status": "healthy",
        "ollama": "connected" if ollama_ok else "disconnected",
        "cached_results": len(latest_results),
        "scan_count": len(scan_history),
        "uptime_scans": len(scan_history),
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
def paper_order(ticker: str, action: str, qty: int, price: float, reason: str = ""):
    """페이퍼 트레이딩 수동 주문"""
    ticker = ticker.upper()
    action = action.upper()
    if action not in ("BUY", "SELL"):
        raise HTTPException(400, "action은 BUY 또는 SELL")
    return execute_paper_order(ticker, action, qty, price, reason)


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
