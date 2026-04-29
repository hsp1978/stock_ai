#!/usr/bin/env python3
"""
백그라운드 스케줄 스캐너 — WebUI와 별도 프로세스로 실행
APScheduler로 주기적 자동 스캔 + 텔레그램 알림

실행:
    python scanner.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from local_engine import engine_scan_all, engine_portfolio_rebalance
from apscheduler.schedulers.blocking import BlockingScheduler

_AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chart_agent_service")
sys.path.insert(0, _AGENT_DIR)
from config import SCAN_INTERVAL_MINUTES


def load_watchlist() -> list[str]:
    wl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.txt")
    if not os.path.exists(wl_path):
        return []
    with open(wl_path, 'r') as f:
        return [line.strip().upper() for line in f if line.strip() and not line.startswith('#')]


def run_scan():
    """주기적 watchlist 스캔"""
    tickers = load_watchlist()
    if not tickers:
        print(f"[{datetime.now():%H:%M}] Watchlist empty, skipping scan")
        return
    print(f"\n{'='*60}")
    print(f"  Scheduled scan: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"  Tickers: {len(tickers)} - {', '.join(tickers)}")
    print(f"{'='*60}\n")
    engine_scan_all(tickers)
    print(f"\n  Scan complete: {datetime.now():%H:%M}\n")


def run_telegram_callbacks():
    """텔레그램 인라인 버튼 콜백 폴링 처리 (워치리스트 추가/무시)"""
    try:
        from telegram_bot import process_callback_updates
        # handler는 service.py에서 제공되지만, 배치에서도 간단히 처리
        import os as _os
        WATCHLIST_PATH = _os.path.join(
            _os.path.dirname(_os.path.abspath(__file__)), "watchlist.txt"
        )

        def _watch(ticker: str) -> str:
            try:
                existing = set()
                if _os.path.exists(WATCHLIST_PATH):
                    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                existing.add(line.upper())
                t = ticker.upper().strip()
                if t in existing:
                    return f"{t} 이미 있음"
                existing.add(t)
                header = (
                    "# 관심 종목 리스트 (SSOT: WebUI/백엔드/배치 스크립트 공용)\n"
                    "# 한 줄에 하나, #은 주석, 빈 줄은 무시됨\n\n"
                )
                with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
                    f.write(header)
                    for t2 in sorted(existing):
                        f.write(t2 + "\n")
                return f"✅ {t} 워치리스트 추가"
            except Exception:
                return "실패"

        def _mute(ticker: str) -> str:
            return f"🚫 {ticker.upper()} 당분간 무시"

        result = process_callback_updates({"watch": _watch, "mute": _mute})
        if result.get("processed", 0) > 0:
            print(f"[Telegram] 콜백 {result['processed']}건 처리")
    except Exception as e:
        print(f"[Telegram] 콜백 처리 실패: {e}")


def run_market_close_digest():
    """장 마감 후 당일 스캔 요약 다이제스트 발송 (미국장 기준 17:00 KST)"""
    try:
        import httpx
        from config import API_HOST, API_PORT
        host = "localhost" if API_HOST == "0.0.0.0" else API_HOST
        url = f"http://{host}:{API_PORT}/telegram/daily-digest?top_n=5&min_confidence=6.0"
        resp = httpx.post(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print(f"[Telegram] 일일 다이제스트 발송: sent={data.get('sent')}, "
                  f"총 스캔 {data.get('total_scans', 0)}건")
        else:
            print(f"[Telegram] 다이제스트 실패: {resp.status_code}")
    except Exception as e:
        print(f"[Telegram] 다이제스트 오류: {e}")


def run_kr_screener():
    """
    한국 주식 기술적 스크리너 (일일 15:35 KST 실행).
    시총 2,000억 이상 종목 → 상위 20개 선별 → DB 저장.
    """
    print(f"\n{'='*60}")
    print(f"  한국 주식 스크리너: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*60}\n")
    try:
        import httpx
        import os as _os
        port = _os.getenv("API_PORT", "8100")
        # 장 마감 후 실행이므로 시총 기준 2천억 기본값
        r = httpx.post(
            f"http://localhost:{port}/screener/run?min_market_cap_bn=2000&top_n=20",
            timeout=600,
        )
        if r.status_code == 200:
            data = r.json()
            results = data.get("results", [])
            print(f"  ✓ 스크리너 완료: {len(results)}종목 선별")
            print(f"  ✓ 유니버스 {data.get('universe_size', 0)}개 분석")
            print(f"  ✓ 소요 {data.get('elapsed_seconds', 0)}s")
            if results:
                top5 = results[:5]
                print(f"\n  TOP 5:")
                for r_ in top5:
                    print(f"    {r_['rank']:2}. {r_['name'][:15]:15} "
                          f"점수 {r_['score']:.1f} ({r_['grade']}등급)")
        else:
            print(f"  ✗ API 실패: {r.status_code}")
    except Exception as e:
        print(f"  ✗ 스크리너 실행 실패: {e}")
    print(f"\n{'='*60}\n")


def run_signal_validation():
    """일일 신호 사후 평가 + 신뢰도 칼리브레이션 재학습"""
    print(f"\n{'='*60}")
    print(f"  Daily signal validation: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*60}\n")
    try:
        from signal_tracker import run_daily_validation
        result = run_daily_validation(days_back=45, limit=500, refit_calibrator=True)
        ev = result.get("evaluation", {})
        calib = result.get("calibrator") or {}
        print(f"  ✓ 평가: 처리 {ev.get('processed')}, 업데이트 {ev.get('updated')}")
        print(f"  ✓ 칼리브레이터: active={calib.get('active')}, 표본={calib.get('total_samples')}")
    except Exception as e:
        print(f"  ✗ 검증 실패: {e}")
    print(f"\n{'='*60}\n")


def run_rebalancing():
    """주기적 포트폴리오 리밸런싱 (V2.0)"""
    print(f"\n{'='*60}")
    print(f"  Scheduled rebalancing: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*60}\n")

    result = engine_portfolio_rebalance(
        method="markowitz",
        interval_days=7,
        drift_threshold=0.05,
        dry_run=False
    )

    status = result.get("status", "unknown")
    reason = result.get("reason", "N/A")

    if status == "executed":
        orders = result.get("orders", [])
        cost = result.get("total_transaction_cost", 0)
        drift = result.get("drift", 0)

        print(f"  ✓ 리밸런싱 실행")
        print(f"  - 사유: {reason}")
        print(f"  - Drift: {drift:.2%}")
        print(f"  - 주문: {len(orders)}개")
        print(f"  - 거래비용: ${cost:.2f}")

        for order in orders:
            print(f"    • {order['action']} {order['ticker']} {order['qty']}주 @ ${order['price']:.2f}")
            print(f"      ({order['current_weight']:.1%} → {order['target_weight']:.1%})")

    elif status == "skipped":
        print(f"  ○ 리밸런싱 스킵: {reason}")
        print(f"  - 현재 Drift: {result.get('drift', 0):.2%}")

    else:
        print(f"  ✗ 리밸런싱 실패: {reason}")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    print(f"Stock AI Background Scanner + Rebalancer (V2.0)")
    print(f"Scan Interval: {SCAN_INTERVAL_MINUTES} minutes")
    print(f"Rebalancing: Every Monday 09:30")
    print(f"Starting initial scan...\n")

    run_scan()

    scheduler = BlockingScheduler()

    # 1. Watchlist 스캔 (주기적)
    scheduler.add_job(
        run_scan,
        'interval',
        minutes=SCAN_INTERVAL_MINUTES,
        id='watchlist_scan'
    )
    print(f"\n[Scheduler] Registered {SCAN_INTERVAL_MINUTES}min interval scan")

    # 2. 포트폴리오 리밸런싱 (매주 월요일 09:30) - V2.0
    scheduler.add_job(
        run_rebalancing,
        'cron',
        day_of_week='mon',
        hour=9,
        minute=30,
        id='portfolio_rebalancing'
    )
    print(f"[Scheduler] Registered weekly rebalancing (Mon 09:30)")

    # 3. 일일 신호 검증 + 칼리브레이션 재학습 (매일 03:00)
    scheduler.add_job(
        run_signal_validation,
        'cron',
        hour=3,
        minute=0,
        id='daily_signal_validation'
    )
    print(f"[Scheduler] Registered daily signal validation (03:00)")

    # 3-1. 한국 주식 스크리너 (평일 15:35 KST — 장 마감 직후)
    scheduler.add_job(
        run_kr_screener,
        'cron',
        day_of_week='mon-fri',
        hour=15,
        minute=35,
        id='kr_screener_daily'
    )
    print(f"[Scheduler] Registered KR screener (Mon-Fri 15:35)")

    # 4. 텔레그램 콜백 폴링 (5분 주기)
    scheduler.add_job(
        run_telegram_callbacks,
        'interval',
        minutes=5,
        id='telegram_callback_poll'
    )
    print(f"[Scheduler] Registered Telegram callback polling (5min)")

    # 5. 장 마감 후 일일 다이제스트 (미국장 기준 평일 17:00 KST)
    scheduler.add_job(
        run_market_close_digest,
        'cron',
        day_of_week='mon-fri',
        hour=17,
        minute=0,
        id='daily_digest'
    )
    print(f"[Scheduler] Registered daily digest (Mon-Fri 17:00)")

    print(f"\nScheduler started. Press Ctrl+C to stop.\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\nScanner stopped.")
