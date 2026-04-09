"""
로컬 분석 엔진 — chart_agent_service 모듈을 직접 호출
원격 FastAPI 서버 의존 제거, Ollama만 원격(Mac Studio)으로 접근
Multi-LLM 지원: Ollama / OpenAI GPT / Google Gemini
"""
import json
import math
import os
import sys
import time
from datetime import datetime
from typing import Optional

import httpx

_AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chart_agent_service")
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

from dotenv import load_dotenv as _load_dotenv
_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
_load_dotenv(os.path.join(_AGENT_DIR, ".env"), override=True)

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
from config import (
    OLLAMA_MODEL, OLLAMA_BASE_URL, OPENAI_API_KEY,
    BUY_THRESHOLD, SELL_THRESHOLD, MIN_CONFIDENCE,
    SCAN_INTERVAL_MINUTES, TRADING_STYLE,
    COOLING_OFF_DAYS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    OUTPUT_DIR,
)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")


latest_results: dict = {}
scan_history: list = []
cooling_off_state: dict = {}


def _sanitize(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    try:
        import numpy as np
        import pandas as pd
        if isinstance(obj, (pd.Timestamp,)):
            return obj.isoformat()
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
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


def send_telegram(text: str, parse_mode: str = "HTML") -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def check_alert_condition(ticker: str, result: dict) -> Optional[dict]:
    score = result.get("composite_score", 0)
    confidence = result.get("confidence", 0)
    signal = result.get("final_signal", "HOLD")

    should_alert = False
    if confidence >= MIN_CONFIDENCE:
        if score >= BUY_THRESHOLD and signal == "BUY":
            should_alert = True
        elif score <= SELL_THRESHOLD and signal == "SELL":
            should_alert = True

    if not should_alert:
        return None

    if signal == "BUY" and ticker in cooling_off_state:
        cool = cooling_off_state[ticker]
        elapsed_days = (datetime.now() - datetime.fromisoformat(cool["triggered_at"])).total_seconds() / 86400
        if elapsed_days < COOLING_OFF_DAYS:
            return None
        else:
            del cooling_off_state[ticker]

    if signal == "SELL":
        cooling_off_state[ticker] = {"signal": signal, "triggered_at": datetime.now().isoformat()}

    COOLDOWN_SECONDS = 3600
    prev = latest_results.get(ticker, {})
    prev_signal = prev.get("result", {}).get("final_signal")
    prev_time = prev.get("alert_sent_at")
    if prev_signal == signal and prev_time:
        elapsed = (datetime.now() - datetime.fromisoformat(prev_time)).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            return None

    return {"ticker": ticker, "signal": signal, "score": score, "confidence": confidence, "result": result}


def send_summary_alert(alerts: list):
    if not alerts:
        return
    buy_alerts = [a for a in alerts if a["signal"] == "BUY"]
    sell_alerts = [a for a in alerts if a["signal"] == "SELL"]
    msg = f"📊 <b>에이전트 스캔 알림</b> ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n기준치 도달: {len(alerts)}개 종목\n\n"
    if buy_alerts:
        msg += "🟢 <b>매수 신호</b>\n"
        for a in sorted(buy_alerts, key=lambda x: x["score"], reverse=True):
            top_tools = sorted(a["result"].get("tool_summaries", []), key=lambda x: x.get("score", 0), reverse=True)[:2]
            tools_str = ", ".join(f"{t['name']}({t['score']:+.0f})" for t in top_tools)
            msg += f"  <b>{a['ticker']}</b>: {a['score']:+.1f}점 (신뢰도 {a['confidence']}) [{tools_str}]\n"
        msg += "\n"
    if sell_alerts:
        msg += "🔴 <b>매도 신호</b>\n"
        for a in sorted(sell_alerts, key=lambda x: x["score"]):
            top_tools = sorted(a["result"].get("tool_summaries", []), key=lambda x: x.get("score", 0))[:2]
            tools_str = ", ".join(f"{t['name']}({t['score']:+.0f})" for t in top_tools)
            msg += f"  <b>{a['ticker']}</b>: {a['score']:+.1f}점 (신뢰도 {a['confidence']}) [{tools_str}]\n"
    send_telegram(msg)
    for a in alerts:
        ticker = a["ticker"]
        latest_results[ticker] = {**latest_results.get(ticker, {}), "alert_sent_at": datetime.now().isoformat()}


def analyze_ticker(ticker: str, ai_mode: str = "ollama") -> Optional[dict]:
    try:
        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)

        fundamentals = {}
        options_pcr = {}
        insider_trades = []
        try:
            fundamentals = fetch_fundamentals(ticker)
        except Exception:
            pass
        try:
            options_pcr = fetch_options_pcr(ticker)
        except Exception:
            pass
        try:
            insider_trades = fetch_insider_trades(ticker)
        except Exception:
            pass

        agent = ChartAnalysisAgent(ticker, df)
        result = agent.run(mode=ai_mode)

        result["fundamentals"] = fundamentals
        result["options_pcr"] = options_pcr
        result["insider_trades"] = insider_trades

        try:
            chart_path = generate_agent_chart(ticker, df, result)
            result["chart_path"] = chart_path
        except Exception:
            pass

        json_path = os.path.join(OUTPUT_DIR, f"{ticker}_agent_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)

        result["json_path"] = json_path
        result["analyzed_at"] = datetime.now().isoformat()
        return result
    except Exception as e:
        print(f"[{ticker}] analyze failed: {e}")
        return None


def engine_health() -> dict:
    ollama_ok = False
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        ollama_ok = resp.status_code == 200
    except Exception:
        pass
    return {
        "status": "healthy",
        "ollama": "connected" if ollama_ok else "disconnected",
        "ollama_url": OLLAMA_BASE_URL,
        "cached_results": len(latest_results),
        "scan_count": len(scan_history),
    }


def engine_info() -> dict:
    return {
        "service": "local-engine",
        "status": "running",
        "model": OLLAMA_MODEL,
        "trading_style": TRADING_STYLE,
        "scan_interval": f"{SCAN_INTERVAL_MINUTES}분",
        "thresholds": {"buy": BUY_THRESHOLD, "sell": SELL_THRESHOLD, "min_confidence": MIN_CONFIDENCE},
        "cooling_off_days": COOLING_OFF_DAYS,
        "last_scan": scan_history[-1]["timestamp"] if scan_history else None,
        "cached_tickers": list(latest_results.keys()),
    }


def engine_get_all_results() -> dict:
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


def engine_get_ticker_result(ticker: str) -> Optional[dict]:
    ticker = ticker.upper()
    if ticker not in latest_results:
        return None
    data = latest_results[ticker]
    payload = {
        "ticker": ticker,
        "timestamp": data.get("timestamp"),
        "alert_sent_at": data.get("alert_sent_at"),
        **data.get("result", {}),
    }
    return _sanitize(payload)


def engine_scan_ticker(ticker: str, ai_mode: str = "ollama") -> Optional[dict]:
    ticker = ticker.upper()
    result = analyze_ticker(ticker, ai_mode)
    if not result:
        return None
    latest_results[ticker] = {
        "result": result,
        "timestamp": datetime.now().isoformat(),
        "alert_sent_at": latest_results.get(ticker, {}).get("alert_sent_at"),
    }
    alert = check_alert_condition(ticker, result)
    if alert:
        send_summary_alert([alert])
    return _sanitize(result)


def engine_scan_all(tickers: list[str]) -> dict:
    scan_entry = {"timestamp": datetime.now().isoformat(), "tickers": tickers, "results": {}, "alerts": []}
    pending_alerts = []
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
            alert = check_alert_condition(ticker, result)
            if alert:
                pending_alerts.append(alert)
                scan_entry["alerts"].append(ticker)
        time.sleep(2)
    if pending_alerts:
        send_summary_alert(pending_alerts)
    scan_history.append(scan_entry)
    if len(scan_history) > 100:
        scan_history.pop(0)
    return {"status": "completed", "results": engine_get_all_results()}


def engine_get_history(limit: int = 10) -> dict:
    return {"count": len(scan_history), "history": scan_history[-limit:]}


def engine_get_chart_path(ticker: str) -> Optional[str]:
    ticker = ticker.upper()
    data = latest_results.get(ticker, {})
    return data.get("result", {}).get("chart_path")


def engine_backtest(ticker: str) -> Optional[dict]:
    ticker = ticker.upper()
    data = latest_results.get(ticker, {})
    r = data.get("result", {})
    if not r:
        return None
    try:
        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)
        tool_results = r.get("tool_details", [])
        return _sanitize(run_all_backtests(ticker, df, tool_results))
    except Exception as e:
        return {"error": str(e)}


def engine_ml_predict(ticker: str) -> Optional[dict]:
    ticker = ticker.upper()
    try:
        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)
        return _sanitize(run_ml_prediction(ticker, df))
    except Exception as e:
        return {"error": str(e)}


def engine_portfolio_optimize(method: str = "markowitz") -> Optional[dict]:
    tickers = list(latest_results.keys())
    if len(tickers) < 2:
        return {"error": "최소 2개 종목 분석 결과 필요"}
    try:
        if method == "risk_parity":
            return _sanitize(risk_parity_optimize(tickers))
        return _sanitize(markowitz_optimize(tickers))
    except Exception as e:
        return {"error": str(e)}


def engine_correlation_beta() -> Optional[dict]:
    tickers = list(latest_results.keys())
    if not tickers:
        return {"error": "분석 결과 없음"}
    try:
        return _sanitize(compute_correlation_beta(tickers))
    except Exception as e:
        return {"error": str(e)}


def engine_factor_ranking() -> dict:
    try:
        ranking = compute_factor_ranking(latest_results)
        return _sanitize({"count": len(ranking), "ranking": ranking})
    except Exception as e:
        return {"error": str(e)}


def engine_paper_status() -> dict:
    return _sanitize(get_portfolio_status())


def engine_paper_order(ticker: str, action: str, qty: int, price: float, reason: str = "") -> dict:
    return _sanitize(execute_paper_order(ticker.upper(), action.upper(), qty, price, reason))


def engine_paper_auto() -> dict:
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
    return _sanitize({"executed": len(orders), "orders": orders})


def engine_paper_reset() -> dict:
    return _sanitize(reset_paper_trading())


# ═══════════════════════════════════════════════════════════════
#  Multi-LLM 리포트 해석 엔진
# ═══════════════════════════════════════════════════════════════

def _available_llm_providers() -> list[str]:
    providers = []
    if GOOGLE_API_KEY:
        providers.append("gemini")
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if resp.status_code == 200:
            providers.append("ollama")
    except Exception:
        pass
    if OPENAI_API_KEY:
        providers.append("openai")
    return providers


def engine_available_llm() -> dict:
    providers = _available_llm_providers()
    return {"providers": providers, "default": providers[0] if providers else None}


def _call_llm(prompt: str, provider: str = "auto") -> str:
    if provider == "auto":
        providers = _available_llm_providers()
        if not providers:
            return "[LLM 없음] OPENAI_API_KEY, GOOGLE_API_KEY 또는 Ollama 서버를 설정하세요."
        provider = providers[0]

    if provider == "openai":
        return _call_openai(prompt)
    elif provider == "gemini":
        return _call_gemini(prompt)
    elif provider == "ollama":
        return _call_ollama(prompt)
    return f"[오류] 지원하지 않는 provider: {provider}"


def _call_openai(prompt: str) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "당신은 주식 기술적/퀀트 분석 전문가입니다. 지표 수치를 구체적으로 해석하고 한국어로 답변하세요. 마크다운 형식을 사용하세요."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=4096,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"[OpenAI 오류] {e}"


def _call_gemini(prompt: str) -> str:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")
        resp = model.generate_content(
            f"당신은 주식 기술적/퀀트 분석 전문가입니다. 지표 수치를 구체적으로 해석하고 한국어로 답변하세요. 마크다운 형식을 사용하세요.\n\n{prompt}",
            generation_config=genai.types.GenerationConfig(temperature=0.3, max_output_tokens=4096),
        )
        return resp.text
    except Exception as e:
        return f"[Gemini 오류] {e}"


def _call_ollama(prompt: str) -> str:
    try:
        resp = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": f"당신은 주식 기술적/퀀트 분석 전문가입니다. 지표 수치를 구체적으로 해석하고 한국어로 답변하세요.\n\n{prompt}",
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 4096},
            },
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json().get("response", "[응답 없음]")
    except Exception as e:
        return f"[Ollama 오류] {e}"


def _build_tool_interpret_prompt(ticker: str, td: dict) -> str:
    tool_name = td.get("name", td.get("tool", ""))
    signal = td.get("signal", "neutral")
    score = td.get("score", 0)
    detail = td.get("detail", "")

    filtered = {k: v for k, v in td.items() if k not in ("tool", "name", "signal", "score", "detail") and v is not None}
    metrics_str = json.dumps(filtered, ensure_ascii=False, indent=2, default=str)

    return f"""## {ticker} — {tool_name} 분석 해석 요청

**신호**: {signal} | **점수**: {score:+.1f}/10
**요약**: {detail}

**상세 지표**:
```json
{metrics_str}
```

위 분석 결과를 아래 형식으로 해석해주세요:

### 핵심 해석
- 각 지표 수치가 의미하는 바를 구체적으로 설명 (예: RSI 72 → 과매수 구간 진입, 단기 조정 가능성)
- 현재 시장 상황에서 이 신호가 갖는 의미

### 매매 시사점
- 이 지표 기반의 구체적 매매 전략 제안
- 주의할 리스크 요인

### 신뢰도 평가
- 이 신호의 신뢰성을 높이거나 낮추는 요인"""


def _build_full_report_prompt(ticker: str, detail: dict) -> str:
    signal = detail.get("final_signal", "?")
    score = detail.get("composite_score", 0)
    confidence = detail.get("confidence", 0)
    dist = detail.get("signal_distribution", {})

    tool_details = detail.get("tool_details", [])
    tools_text = ""
    for td in tool_details:
        name = td.get("name", td.get("tool", "?"))
        s = td.get("signal", "neutral")
        sc = td.get("score", 0)
        d = td.get("detail", "")
        tools_text += f"- **{name}**: {s} ({sc:+.1f}) — {d}\n"

    fund = detail.get("fundamentals", {})
    fund_text = ""
    if fund:
        fund_text = f"""
**펀더멘털**: P/E={fund.get('pe_ratio','N/A')}, Forward P/E={fund.get('forward_pe','N/A')}, PEG={fund.get('peg_ratio','N/A')}, P/B={fund.get('price_to_book','N/A')}, Beta={fund.get('beta','N/A')}, 매출성장={fund.get('revenue_growth','N/A')}, 이익률={fund.get('profit_margin','N/A')}, D/E={fund.get('debt_to_equity','N/A')}
"""

    pcr = detail.get("options_pcr", {})
    pcr_text = ""
    if pcr and pcr.get("put_call_ratio_oi") is not None:
        pcr_text = f"**옵션 PCR**: OI={pcr.get('put_call_ratio_oi')}, Vol={pcr.get('put_call_ratio_vol')}\n"

    return f"""## {ticker} 종합 분석 리포트 작성 요청

**종합 신호**: {signal} | **점수**: {score:+.2f}/10 | **신뢰도**: {confidence}/10
**분포**: 매수 {dist.get('buy',0)}개, 매도 {dist.get('sell',0)}개, 중립 {dist.get('neutral',0)}개

### 16개 분석 도구 결과
{tools_text}
{fund_text}{pcr_text}

위 데이터를 기반으로 아래 섹션별 종합 리포트를 한국어로 작성하세요:

## 1. 종합 판단
- 매수/매도/관망 판단과 확신도
- 판단의 핵심 근거 3~5개

## 2. 기술적 분석 종합
- 추세(이평선 배열, 골든/데드크로스), 모멘텀(RSI, MACD), 변동성(볼린저, ATR), 거래량 흐름 종합 해석
- 각 지표 수치를 구체적으로 언급하며 해석

## 3. 퀀트 분석 종합
- 피보나치, 지지/저항, 평균회귀, 모멘텀 순위, 상관관계, 변동성 체제 종합
- 통계적 에지 유무 판단

## 4. 리스크 분석
- 포지션 사이징 권장사항 (진입가, 손절가, 익절가)
- 켈리 기준 최적 비율
- 베타/상관관계 기반 포트폴리오 리스크

## 5. 펀더멘털 & 센티먼트
- 밸류에이션(P/E, PEG 등) 평가
- 옵션 PCR, 내부자 거래 시사점

## 6. 구체적 매매 전략
- 진입 시점, 분할 매수 계획
- 손절/익절 기준, 포지션 크기
- 향후 1주/1개월 시나리오"""


def engine_interpret_tool(ticker: str, tool_key: str, provider: str = "auto") -> str:
    ticker = ticker.upper()
    data = latest_results.get(ticker, {})
    tool_details = data.get("result", {}).get("tool_details", [])
    td = next((t for t in tool_details if t.get("tool") == tool_key), None)
    if not td:
        return f"[오류] {ticker}의 {tool_key} 분석 결과를 찾을 수 없습니다."
    prompt = _build_tool_interpret_prompt(ticker, td)
    return _call_llm(prompt, provider)


def engine_interpret_full_report(ticker: str, provider: str = "auto") -> str:
    ticker = ticker.upper()
    detail = engine_get_ticker_result(ticker)
    if not detail:
        return f"[오류] {ticker}의 분석 결과가 없습니다. 먼저 스캔을 실행하세요."
    prompt = _build_full_report_prompt(ticker, detail)
    return _call_llm(prompt, provider)
