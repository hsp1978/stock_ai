"""
Mac Studio 에이전트 API 클라이언트
testdev 서버에서 Mac Studio의 분석 결과를 조회

사용법:
    python agent_client.py                    # 전체 결과 조회
    python agent_client.py AAPL               # 특정 종목 상세
    python agent_client.py --scan AAPL        # 즉시 분석 요청
    python agent_client.py --scan-all         # 전체 스캔 요청
    python agent_client.py --health           # 서비스 상태 확인
"""
import argparse
import json
import sys
import os

import httpx

# Mac Studio API 주소 (.env 또는 환경변수에서 로드)
from dotenv import load_dotenv
load_dotenv()

AGENT_API_URL = os.getenv("AGENT_API_URL", "http://mac-studio.local:8100")


def print_json(data: dict):
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def get_health():
    """서비스 상태 확인"""
    try:
        resp = httpx.get(f"{AGENT_API_URL}/health", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        print(f"상태: {data.get('status')}")
        print(f"Ollama: {data.get('ollama')}")
        print(f"캐시 결과: {data.get('cached_results')}개")
        print(f"스캔 횟수: {data.get('scan_count')}")
    except httpx.ConnectError:
        print(f"[오류] Mac Studio 연결 실패: {AGENT_API_URL}")
        print(f"  AGENT_API_URL 환경변수 또는 .env 설정 확인.")
    except Exception as e:
        print(f"[오류] {e}")


def get_all_results():
    """전체 최신 결과 조회"""
    try:
        resp = httpx.get(f"{AGENT_API_URL}/results", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", {})

        if not results:
            print("분석 결과 없음. Mac Studio에서 스캔이 실행되지 않았을 수 있음.")
            return

        print(f"\n{'='*70}")
        print(f"  에이전트 분석 결과 ({data.get('count', 0)}개 종목)")
        print(f"{'='*70}\n")
        print(f"  {'종목':<8} {'신호':<6} {'점수':>8} {'신뢰도':>8} {'분석시간':<20}")
        print(f"  {'-'*60}")

        for ticker, r in sorted(results.items()):
            signal = r.get("signal", "?")
            score = r.get("score", 0)
            confidence = r.get("confidence", 0)
            analyzed = r.get("analyzed_at", "")[:16]
            emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(signal, "⚪")
            print(f"  {emoji} {ticker:<6} {signal:<6} {score:>+7.2f} {confidence:>7.1f} {analyzed}")

        print(f"\n  소스: {AGENT_API_URL}")

    except httpx.ConnectError:
        print(f"[오류] Mac Studio 연결 실패: {AGENT_API_URL}")
    except Exception as e:
        print(f"[오류] {e}")


def get_ticker_result(ticker: str):
    """특정 종목 상세 결과"""
    ticker = ticker.upper()
    try:
        resp = httpx.get(f"{AGENT_API_URL}/results/{ticker}", timeout=10)
        if resp.status_code == 404:
            print(f"{ticker}: 분석 결과 없음.")
            print(f"  --scan {ticker} 으로 즉시 분석 요청 가능.")
            return
        resp.raise_for_status()
        data = resp.json()

        signal = data.get("final_signal", "?")
        score = data.get("composite_score", 0)
        confidence = data.get("confidence", 0)

        print(f"\n{'='*60}")
        print(f"  {ticker} 에이전트 분석 상세")
        print(f"{'='*60}\n")
        print(f"  신호: {signal}")
        print(f"  점수: {score:+.2f} / 10")
        print(f"  신뢰도: {confidence} / 10")
        print(f"  분석: {data.get('analyzed_at', '')[:16]}")

        dist = data.get("signal_distribution", {})
        print(f"  분포: 매수 {dist.get('buy',0)} | 매도 {dist.get('sell',0)} | 중립 {dist.get('neutral',0)}")

        print(f"\n  {'도구':<14} {'신호':<8} {'점수':>6}  {'요약'}")
        print(f"  {'-'*58}")
        for s in data.get("tool_summaries", []):
            name = s.get("name", "")[:12]
            sig = s.get("signal", "?")
            sc = s.get("score", 0)
            detail = s.get("detail", "")[:40]
            print(f"  {name:<14} {sig:<8} {sc:>+5.1f}  {detail}")

        llm = data.get("llm_conclusion", "")
        if llm and not llm.startswith("[오류]"):
            print(f"\n── LLM 종합 판단 ──")
            print(llm[:500])

    except httpx.ConnectError:
        print(f"[오류] Mac Studio 연결 실패: {AGENT_API_URL}")
    except Exception as e:
        print(f"[오류] {e}")


def request_scan(ticker: str):
    """즉시 분석 요청"""
    ticker = ticker.upper()
    print(f"{ticker} 분석 요청 중... (소요시간: 1~3분)")
    try:
        resp = httpx.post(f"{AGENT_API_URL}/scan/{ticker}", timeout=300)
        resp.raise_for_status()
        data = resp.json()
        print(f"  신호: {data.get('final_signal')}")
        print(f"  점수: {data.get('composite_score')}")
        print(f"  신뢰도: {data.get('confidence')}")
    except httpx.ConnectError:
        print(f"[오류] Mac Studio 연결 실패: {AGENT_API_URL}")
    except Exception as e:
        print(f"[오류] {e}")


def request_scan_all():
    """전체 스캔 요청"""
    print(f"전체 watchlist 스캔 요청 중... (종목 수에 따라 5~20분 소요)")
    try:
        resp = httpx.post(f"{AGENT_API_URL}/scan", timeout=1200)
        resp.raise_for_status()
        print("스캔 완료.")
        get_all_results()
    except httpx.ConnectError:
        print(f"[오류] Mac Studio 연결 실패: {AGENT_API_URL}")
    except Exception as e:
        print(f"[오류] {e}")


def main():
    parser = argparse.ArgumentParser(description="Mac Studio 에이전트 API 클라이언트")
    parser.add_argument("ticker", nargs="?", default=None, help="종목 티커")
    parser.add_argument("--scan", metavar="TICKER", help="즉시 분석 요청")
    parser.add_argument("--scan-all", action="store_true", help="전체 watchlist 스캔 요청")
    parser.add_argument("--health", action="store_true", help="서비스 상태 확인")
    parser.add_argument("--url", default=None, help="에이전트 API URL 지정")

    args = parser.parse_args()

    global AGENT_API_URL
    if args.url:
        AGENT_API_URL = args.url

    if args.health:
        get_health()
    elif args.scan:
        request_scan(args.scan)
    elif args.scan_all:
        request_scan_all()
    elif args.ticker:
        get_ticker_result(args.ticker)
    else:
        get_all_results()


if __name__ == "__main__":
    main()
