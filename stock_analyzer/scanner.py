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

    print(f"\nScheduler started. Press Ctrl+C to stop.\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\nScanner stopped.")
