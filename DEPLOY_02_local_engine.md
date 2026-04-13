# local_engine.py (신규 생성)

경로: `stock_analyzer/local_engine.py`

Mac Studio의 `stock_analyzer/local_engine.py` 전체를 testdev의 동일 경로에 복사.

```
scp mac-studio:~/stock_auto/stock_ai/stock_analyzer/local_engine.py \
    ~/stock_auto/stock_ai/stock_analyzer/local_engine.py
```

또는 아래 전체 코드를 파일로 저장:

```python
#!/usr/bin/env python3
"""
로컬 엔진 — WebUI와 chart_agent_service를 연결하는 브릿지 모듈

연결 방식:
  - 직접 import: chart_agent_service/ 모듈을 sys.path로 추가하여 Python 함수 직접 호출
    (16개 분석 도구, 백테스트, ML, 포트폴리오, 페이퍼트레이딩)
  - HTTP API: Mac Studio FastAPI로 뉴스/차트패턴/섹터/매크로 (직접 import 실패 시 fallback)
  - Multi-LLM: Gemini → Ollama → OpenAI fallback 파이프라인
"""
import os
import sys
import json
import math
import time
from datetime import datetime
from typing import Optional

# ═══════════════════════════════════════════════════════════════
#  .env 로드 (chart_agent_service 모듈 import 전에 실행)
# ═══════════════════════════════════════════════════════════════

from dotenv import load_dotenv

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SERVICE_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "chart_agent_service"))

# chart_agent_service/.env 로드
_service_env = os.path.join(_SERVICE_DIR, ".env")
if os.path.exists(_service_env):
    load_dotenv(_service_env)

# stock_analyzer/.env 보조 로드 (기존 값 유지)
_local_env = os.path.join(_THIS_DIR, ".env")
if os.path.exists(_local_env):
    load_dotenv(_local_env, override=False)

# ═══════════════════════════════════════════════════════════════
#  chart_agent_service 모듈 직접 import
# ═══════════════════════════════════════════════════════════════

if _SERVICE_DIR not in sys.path:
    sys.path.insert(0, _SERVICE_DIR)

import httpx

from config import (
    OLLAMA_BASE_URL, OLLAMA_MODEL, OPENAI_API_KEY,
    GEMINI_API_KEY, GEMINI_MODEL,
    BUY_THRESHOLD, SELL_THRESHOLD, MIN_CONFIDENCE,
    SCAN_INTERVAL_MINUTES, TRADING_STYLE, WATCHLIST,
    COOLING_OFF_DAYS, ACCOUNT_SIZE, OUTPUT_DIR,
)
from data_collector import (
    fetch_ohlcv, calculate_indicators,
    fetch_fundamentals, fetch_options_pcr, fetch_insider_trades,
)
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

# ── 뉴스/차트패턴/섹터/매크로: 직접 import 우선, HTTP fallback ──
_DIRECT_NEWS = False
_DIRECT_CHART_PATTERN = False
_DIRECT_SECTOR = False
_DIRECT_MACRO = False

try:
    from news_analyzer import fetch_news_with_sentiment
    _DIRECT_NEWS = True
except ImportError as e:
    print(f"[local_engine] news_analyzer import 실패 (HTTP fallback): {e}")

try:
    from chart_pattern import detect_chart_patterns
    _DIRECT_CHART_PATTERN = True
except ImportError as e:
    print(f"[local_engine] chart_pattern import 실패 (HTTP fallback): {e}")

try:
    from sector_compare import compare_sector
    _DIRECT_SECTOR = True
except ImportError as e:
    print(f"[local_engine] sector_compare import 실패 (HTTP fallback): {e}")

try:
    from macro_context import fetch_macro_context
    _DIRECT_MACRO = True
except ImportError as e:
    print(f"[local_engine] macro_context import 실패 (HTTP fallback): {e}")


# Mac Studio API URL (HTTP fallback용)
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://100.108.11.20:8100")


# ═══════════════════════════════════════════════════════════════
#  전역 상태
# ═══════════════════════════════════════════════════════════════

latest_results: dict = {}
scan_history: list = []
cooling_off_state: dict = {}


# ═══════════════════════════════════════════════════════════════
#  유틸리티
# ═══════════════════════════════════════════════════════════════

def _sanitize(obj):
    """NaN/Inf → None, numpy → Python native 변환"""
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


def _http_get(path: str, timeout: int = 30) -> Optional[dict]:
    """Mac Studio API HTTP GET fallback"""
    try:
        resp = httpx.get(f"{AGENT_API_URL}{path}", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[HTTP fallback 오류] {path}: {e}")
        return None


def _load_watchlist_files() -> list[str]:
    """WebUI가 관리하는 stock_analyzer/watchlist.txt 단일 소스 로드"""
    wl_file = os.path.join(_THIS_DIR, "watchlist.txt")
    tickers = []
    seen = set()
    if os.path.exists(wl_file):
        with open(wl_file, 'r') as f:
            for line in f:
                t = line.strip().upper()
                if t and not t.startswith('#') and t not in seen:
                    tickers.append(t)
                    seen.add(t)
    return tickers


# ═══════════════════════════════════════════════════════════════
#  핵심 엔진 함수 (24개)
# ═══════════════════════════════════════════════════════════════

def engine_health() -> dict:
    """시스템 상태 확인"""
    ollama_ok = False
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        ollama_ok = resp.status_code == 200
    except Exception:
        pass

    return {
        "status": "healthy",
        "ollama": "connected" if ollama_ok else "disconnected",
        "gemini": "configured" if GEMINI_API_KEY else "not_configured",
        "openai": "configured" if OPENAI_API_KEY else "not_configured",
        "cached_results": len(latest_results),
        "scan_count": len(scan_history),
    }


def engine_info() -> dict:
    """서비스 설정 정보"""
    return {
        "service": "local-engine",
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


def engine_scan_ticker(ticker: str, ai_mode: str = "ollama") -> Optional[dict]:
    """단일 종목 에이전트 분석 (16개 기법)"""
    ticker = ticker.upper()
    try:
        print(f"  [{ticker}] 데이터 수집...")
        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)

        print(f"  [{ticker}] 펀더멘털/옵션/내부자 데이터...")
        fundamentals, options_pcr, insider_trades = {}, {}, []
        try:
            fundamentals = fetch_fundamentals(ticker)
        except Exception as e:
            print(f"  [{ticker}] 펀더멘털 실패: {e}")
        try:
            options_pcr = fetch_options_pcr(ticker)
        except Exception as e:
            print(f"  [{ticker}] 옵션 PCR 실패: {e}")
        try:
            insider_trades = fetch_insider_trades(ticker)
        except Exception as e:
            print(f"  [{ticker}] 내부자거래 실패: {e}")

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

        json_path = os.path.join(
            OUTPUT_DIR,
            f"{ticker}_agent_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
        )
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)

        result["json_path"] = json_path
        result["analyzed_at"] = datetime.now().isoformat()

        # 캐시 저장
        latest_results[ticker] = {
            "result": result,
            "timestamp": datetime.now().isoformat(),
            "alert_sent_at": latest_results.get(ticker, {}).get("alert_sent_at"),
        }

        print(f"  [{ticker}] 완료: {result.get('final_signal')} ({result.get('composite_score')})")
        return _sanitize(result)

    except Exception as e:
        print(f"  [{ticker}] 분석 실패: {e}")
        return {"error": str(e)}


def engine_scan_all(tickers: Optional[list] = None) -> dict:
    """전체 watchlist 스캔"""
    tickers = tickers or _load_watchlist_files()

    print(f"\n{'='*60}")
    print(f"  스캔 시작: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  종목: {len(tickers)}개 — {', '.join(tickers)}")
    print(f"{'='*60}\n")

    scan_entry = {
        "timestamp": datetime.now().isoformat(),
        "tickers": tickers,
        "results": {},
        "alerts": [],
    }

    for ticker in tickers:
        result = engine_scan_ticker(ticker)
        if result and not result.get("error"):
            scan_entry["results"][ticker] = {
                "signal": result.get("final_signal"),
                "score": result.get("composite_score"),
                "confidence": result.get("confidence"),
            }
        time.sleep(3)  # API 부하 방지

    scan_history.append(scan_entry)
    if len(scan_history) > 100:
        scan_history.pop(0)

    print(f"\n  스캔 완료: {datetime.now().strftime('%H:%M')}")
    return {"status": "completed", "results": engine_get_all_results()}


def engine_get_all_results() -> dict:
    """캐시된 전체 결과 요약"""
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
    """종목별 상세 결과"""
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


def engine_get_history(limit: int = 10) -> dict:
    """스캔 히스토리"""
    return {"count": len(scan_history), "history": scan_history[-limit:]}


def engine_get_chart_path(ticker: str) -> Optional[str]:
    """최신 차트 이미지 경로 반환"""
    ticker = ticker.upper()
    data = latest_results.get(ticker, {})
    chart_path = data.get("result", {}).get("chart_path")
    if chart_path and os.path.exists(chart_path):
        return chart_path
    return None


# ═══════════════════════════════════════════════════════════════
#  확장 분석 모듈 (직접 import)
# ═══════════════════════════════════════════════════════════════

def engine_backtest(ticker: str) -> dict:
    """백테스트 실행"""
    ticker = ticker.upper()
    try:
        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)
        data = latest_results.get(ticker, {})
        tool_results = data.get("result", {}).get("tool_details", [])
        return _sanitize(run_all_backtests(ticker, df, tool_results))
    except Exception as e:
        return {"error": str(e)}


def engine_ml_predict(ticker: str) -> dict:
    """ML 방향 예측"""
    ticker = ticker.upper()
    try:
        df = fetch_ohlcv(ticker)
        df = calculate_indicators(df)
        return _sanitize(run_ml_prediction(ticker, df))
    except Exception as e:
        return {"error": str(e)}


def engine_portfolio_optimize(method: str = "markowitz") -> dict:
    """포트폴리오 최적화"""
    tickers = list(latest_results.keys())
    if len(tickers) < 2:
        return {"error": "최소 2개 종목 분석 결과 필요"}
    try:
        if method == "risk_parity":
            return _sanitize(risk_parity_optimize(tickers))
        return _sanitize(markowitz_optimize(tickers))
    except Exception as e:
        return {"error": str(e)}


def engine_correlation_beta() -> dict:
    """상관관계/베타 분석"""
    tickers = list(latest_results.keys())
    if not tickers:
        return {"error": "분석 결과 없음"}
    try:
        return _sanitize(compute_correlation_beta(tickers))
    except Exception as e:
        return {"error": str(e)}


def engine_factor_ranking() -> dict:
    """팩터 기반 크로스섹션 랭킹"""
    try:
        ranking = compute_factor_ranking(latest_results)
        return _sanitize({"count": len(ranking), "ranking": ranking})
    except Exception as e:
        return {"error": str(e)}


def engine_paper_status() -> dict:
    """페이퍼 트레이딩 현황"""
    try:
        return _sanitize(get_portfolio_status())
    except Exception as e:
        return {"error": str(e)}


def engine_paper_order(ticker: str, action: str, qty: int,
                       price: float, reason: str = "") -> dict:
    """페이퍼 트레이딩 수동 주문"""
    try:
        return _sanitize(
            execute_paper_order(ticker.upper(), action.upper(), qty, price, reason)
        )
    except Exception as e:
        return {"error": str(e)}


def engine_paper_auto() -> dict:
    """최신 신호 기반 자동 모의매매"""
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
    """페이퍼 트레이딩 초기화"""
    try:
        return _sanitize(reset_paper_trading())
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  뉴스/차트패턴/섹터/매크로 (직접 import 우선 → HTTP fallback)
# ═══════════════════════════════════════════════════════════════

def engine_fetch_news(ticker: str) -> dict:
    """뉴스 수집 + 감성 분석"""
    ticker = ticker.upper()
    if _DIRECT_NEWS:
        try:
            return _sanitize(fetch_news_with_sentiment(ticker))
        except Exception as e:
            print(f"[news 직접호출 실패, HTTP fallback] {e}")
    return _http_get(f"/news/{ticker}", timeout=120) or {"error": "뉴스 수집 실패"}


def engine_chart_pattern(ticker: str) -> dict:
    """차트 패턴 인식"""
    ticker = ticker.upper()
    if _DIRECT_CHART_PATTERN:
        try:
            df = fetch_ohlcv(ticker)
            df = calculate_indicators(df)
            chart_path = latest_results.get(ticker, {}).get("result", {}).get("chart_path")
            return _sanitize(detect_chart_patterns(ticker, df, chart_path))
        except Exception as e:
            print(f"[chart_pattern 직접호출 실패, HTTP fallback] {e}")
    return _http_get(f"/chart-pattern/{ticker}", timeout=60) or {"error": "차트 패턴 분석 실패"}


def engine_sector_compare(ticker: str) -> dict:
    """섹터/산업 비교"""
    ticker = ticker.upper()
    if _DIRECT_SECTOR:
        try:
            return _sanitize(compare_sector(ticker))
        except Exception as e:
            print(f"[sector 직접호출 실패, HTTP fallback] {e}")
    return _http_get(f"/sector/{ticker}", timeout=30) or {"error": "섹터 비교 실패"}


def engine_macro_context() -> dict:
    """매크로 경제 지표"""
    if _DIRECT_MACRO:
        try:
            return _sanitize(fetch_macro_context())
        except Exception as e:
            print(f"[macro 직접호출 실패, HTTP fallback] {e}")
    return _http_get("/macro", timeout=15) or {"error": "매크로 데이터 수집 실패"}


# ═══════════════════════════════════════════════════════════════
#  Multi-LLM 해석 파이프라인
# ═══════════════════════════════════════════════════════════════

def engine_available_llm() -> dict:
    """사용 가능한 LLM 목록"""
    available = {}
    if GEMINI_API_KEY:
        available["gemini"] = {"model": GEMINI_MODEL, "status": "configured"}
    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            available["ollama"] = {
                "model": OLLAMA_MODEL, "status": "connected", "models": models,
            }
    except Exception:
        pass
    if OPENAI_API_KEY:
        available["openai"] = {"model": "gpt-4o", "status": "configured"}
    return available


def _call_gemini(prompt: str) -> Optional[str]:
    """Gemini API 호출 (REST)"""
    if not GEMINI_API_KEY:
        return None
    try:
        resp = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 4096,
                },
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return f"<!-- llm_meta:{GEMINI_MODEL} -->\n{text}"
    except Exception as e:
        print(f"[Gemini 오류] {e}")
        return None


def _call_ollama(prompt: str) -> Optional[str]:
    """Ollama 로컬 LLM 호출"""
    try:
        resp = httpx.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 4096},
            },
            timeout=120,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
        if text:
            return f"<!-- llm_meta:Ollama {OLLAMA_MODEL} -->\n{text}"
        return None
    except Exception as e:
        print(f"[Ollama 오류] {e}")
        return None


def _call_openai(prompt: str) -> Optional[str]:
    """OpenAI GPT-4o 호출"""
    if not OPENAI_API_KEY:
        return None
    try:
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o",
                "messages": [
                    {"role": "system",
                     "content": "당신은 미국 주식 시장 전문 분석가이다. 한국어로 분석하라."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 4096,
                "temperature": 0.3,
            },
            timeout=60,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        return f"<!-- llm_meta:GPT-4o -->\n{text}"
    except Exception as e:
        print(f"[OpenAI 오류] {e}")
        return None


def _call_llm(prompt: str, provider: str = "auto") -> str:
    """
    Multi-LLM 호출.
    provider="auto" → Gemini → Ollama → OpenAI fallback chain
    """
    if provider == "gemini":
        return _call_gemini(prompt) or "[오류] Gemini 호출 실패"
    elif provider == "ollama":
        return _call_ollama(prompt) or "[오류] Ollama 호출 실패"
    elif provider == "openai":
        return _call_openai(prompt) or "[오류] OpenAI 호출 실패"

    # auto: fallback chain
    for fn, name in [
        (_call_gemini, "Gemini"),
        (_call_ollama, "Ollama"),
        (_call_openai, "OpenAI"),
    ]:
        result = fn(prompt)
        if result:
            return result
        print(f"  [{name}] 실패, 다음 LLM으로 전환...")

    return "[오류] 모든 LLM 호출 실패"


def _build_tool_interpret_prompt(ticker: str, tool_result: dict) -> str:
    """개별 도구 AI 해석 프롬프트"""
    return (
        f"다음은 {ticker}의 기술 분석 도구 결과이다. "
        f"이 결과를 해석하여 투자 의사결정에 도움이 되는 분석을 제공하라.\n\n"
        f"## 도구 결과\n"
        f"{json.dumps(tool_result, indent=2, ensure_ascii=False, default=str)}\n\n"
        f"## 해석 규칙\n"
        f"1. 수치의 의미를 설명하라\n"
        f"2. 현재 시장 상황에서의 시사점을 제시하라\n"
        f"3. 주의해야 할 리스크 요인을 명시하라\n"
        f"4. 마크다운 형식으로 응답하라"
    )


def _build_full_report_prompt(ticker: str, result: dict,
                              extra_context: str = "") -> str:
    """종합 리포트 프롬프트 조립"""
    tool_summaries = result.get("tool_summaries", [])
    fundamentals = result.get("fundamentals", {})
    options_pcr = result.get("options_pcr", {})

    prompt = (
        f"# {ticker} 종합 분석 리포트\n\n"
        f"## 에이전트 분석 결과 (16개 기법)\n"
        f"- 최종 신호: {result.get('final_signal', '?')}\n"
        f"- 종합 점수: {result.get('composite_score', 0):+.2f} / 10\n"
        f"- 신뢰도: {result.get('confidence', 0)} / 10\n"
        f"- 분포: {json.dumps(result.get('signal_distribution', {}), ensure_ascii=False)}\n\n"
        f"## 도구별 요약\n"
        f"{json.dumps(tool_summaries, indent=2, ensure_ascii=False, default=str)}\n\n"
        f"## 펀더멘털\n"
        f"{json.dumps({k: v for k, v in fundamentals.items() if v is not None}, indent=2, ensure_ascii=False, default=str)}\n\n"
        f"## 옵션 PCR\n"
        f"{json.dumps(options_pcr, indent=2, ensure_ascii=False, default=str)}\n"
    )

    if extra_context:
        prompt += f"\n## 추가 컨텍스트 (뉴스/매크로/섹터/차트패턴)\n{extra_context}\n"

    prompt += (
        "\n## 분석 요청\n"
        "위 데이터를 종합하여 다음 형식으로 분석하라:\n\n"
        "### 종합 판단\n[매수/매도/관망] (신뢰도: X/10)\n\n"
        "### 기술적 분석 요약\n[16개 도구 결과 해석]\n\n"
        "### 펀더멘털 분석\n[재무 건전성, 밸류에이션]\n\n"
        "### 리스크 관리\n[손절/익절, 포지션 크기]\n\n"
        "### 시장 환경\n[거시경제, 섹터 동향]\n\n"
        "### 핵심 리스크 요인\n[주의 사항 목록]\n\n"
        "한국어로, 마크다운 형식으로 응답하라."
    )
    return prompt


def _gather_extra_context(ticker: str) -> str:
    """뉴스+매크로+차트패턴+섹터 수집"""
    parts = []

    news = engine_fetch_news(ticker)
    if news and not news.get("error"):
        sentiment = news.get("overall_sentiment", "?")
        score = news.get("overall_score", 0)
        count = news.get("news_count", 0)
        parts.append(f"**뉴스 감성:** {sentiment} ({score:+.1f}), {count}건")
        for a in (news.get("articles") or [])[:3]:
            parts.append(f"  - {a.get('title', '')} ({a.get('sentiment', '')})")

    macro = engine_macro_context()
    if macro and not macro.get("error"):
        vix = macro.get("vix", {})
        regime = macro.get("market_regime", "?")
        parts.append(f"**매크로:** VIX={vix.get('value', '?')}, 시장체제={regime}")

    pattern = engine_chart_pattern(ticker)
    if pattern and not pattern.get("error"):
        patterns = pattern.get("patterns", [])
        if patterns:
            parts.append(
                f"**차트 패턴:** "
                f"{', '.join(p.get('name_kr', p.get('name', '?')) for p in patterns[:3])}"
            )

    sector = engine_sector_compare(ticker)
    if sector and not sector.get("error"):
        relative = sector.get("relative_strength", "?")
        parts.append(f"**섹터:** {sector.get('sector', '?')} / 상대강도={relative}")

    return "\n".join(parts)


def engine_interpret_tool(ticker: str, tool_key: str,
                          provider: str = "auto") -> str:
    """개별 도구 AI 해석"""
    ticker = ticker.upper()
    result = engine_get_ticker_result(ticker)
    if not result:
        return f"[오류] {ticker} 분석 결과 없음"

    tool_details = result.get("tool_details", [])
    target = None
    for td in tool_details:
        if td.get("tool") == tool_key or td.get("name") == tool_key:
            target = td
            break

    if not target:
        return f"[오류] 도구 '{tool_key}' 결과 없음"

    prompt = _build_tool_interpret_prompt(ticker, target)
    return _call_llm(prompt, provider)


def engine_interpret_full_report(ticker: str, provider: str = "auto") -> str:
    """
    종합 AI 리포트 생성.
    1. engine_get_ticker_result → 16개 도구 결과
    2. _build_full_report_prompt → 프롬프트 조립
    3. _gather_extra_context → 뉴스+매크로+차트패턴+섹터 수집
    4. _call_llm(prompt, provider)
       - auto: Gemini → Ollama → OpenAI fallback
    5. 응답 상단에 LLM 모델명 메타데이터 삽입
    """
    ticker = ticker.upper()
    result = engine_get_ticker_result(ticker)
    if not result:
        return f"[오류] {ticker} 분석 결과 없음"

    extra_context = _gather_extra_context(ticker)
    prompt = _build_full_report_prompt(ticker, result, extra_context)
    return _call_llm(prompt, provider)


# ═══════════════════════════════════════════════════════════════
#  디스패처 — webui.py의 api_get/api_post 호환 레이어
# ═══════════════════════════════════════════════════════════════

def engine_dispatch_get(path: str) -> Optional[dict]:
    """GET 요청 경로를 로컬 엔진 함수로 라우팅"""
    try:
        if path == "/health":
            return engine_health()
        elif path == "/":
            return engine_info()
        elif path == "/results":
            return engine_get_all_results()
        elif path.startswith("/results/"):
            ticker = path.split("/results/")[1].split("?")[0]
            return engine_get_ticker_result(ticker)
        elif path.startswith("/history"):
            limit = 10
            if "limit=" in path:
                try:
                    limit = int(path.split("limit=")[1].split("&")[0])
                except ValueError:
                    pass
            return engine_get_history(limit)
        elif path.startswith("/backtest/"):
            ticker = path.split("/backtest/")[1].split("?")[0]
            return engine_backtest(ticker)
        elif path.startswith("/ml/"):
            ticker = path.split("/ml/")[1].split("?")[0]
            return engine_ml_predict(ticker)
        elif path.startswith("/portfolio/optimize"):
            method = "markowitz"
            if "method=" in path:
                method = path.split("method=")[1].split("&")[0]
            return engine_portfolio_optimize(method)
        elif path == "/portfolio/correlation":
            return engine_correlation_beta()
        elif path == "/ranking":
            return engine_factor_ranking()
        elif path == "/paper":
            return engine_paper_status()
        elif path.startswith("/news/"):
            ticker = path.split("/news/")[1].split("?")[0]
            return engine_fetch_news(ticker)
        elif path.startswith("/chart-pattern/"):
            ticker = path.split("/chart-pattern/")[1].split("?")[0]
            return engine_chart_pattern(ticker)
        elif path.startswith("/sector/"):
            ticker = path.split("/sector/")[1].split("?")[0]
            return engine_sector_compare(ticker)
        elif path == "/macro":
            return engine_macro_context()
    except Exception as e:
        print(f"[dispatch_get 오류] {path}: {e}")
        return {"error": str(e)}
    return None


def engine_dispatch_post(path: str) -> Optional[dict]:
    """POST 요청 경로를 로컬 엔진 함수로 라우팅"""
    try:
        if path.startswith("/scan/"):
            ticker = path.split("/scan/")[1].split("?")[0]
            return engine_scan_ticker(ticker)
        elif path.startswith("/scan"):
            tickers_str = ""
            if "tickers=" in path:
                tickers_str = path.split("tickers=")[1].split("&")[0]
            tickers = (
                [t.strip().upper() for t in tickers_str.split(",") if t.strip()]
                if tickers_str else None
            )
            return engine_scan_all(tickers)
        elif path == "/paper/auto":
            return engine_paper_auto()
        elif path.startswith("/paper/order"):
            params = {}
            if "?" in path:
                qs = path.split("?")[1]
                for pair in qs.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        params[k] = v
            return engine_paper_order(
                params.get("ticker", ""),
                params.get("action", "BUY"),
                int(params.get("qty", "0")),
                float(params.get("price", "0")),
                params.get("reason", ""),
            )
        elif path == "/paper/reset":
            return engine_paper_reset()
        elif path == "/restart":
            return {
                "status": "restarting",
                "message": "Local engine — restart not applicable",
            }
    except Exception as e:
        print(f"[dispatch_post 오류] {path}: {e}")
        return {"error": str(e)}
```
