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

from local_engine import engine_scan_all
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


if __name__ == "__main__":
    print(f"Stock AI Background Scanner")
    print(f"Interval: {SCAN_INTERVAL_MINUTES} minutes")
    print(f"Starting initial scan...\n")

    run_scan()

    scheduler = BlockingScheduler()
    scheduler.add_job(run_scan, 'interval', minutes=SCAN_INTERVAL_MINUTES, id='watchlist_scan')
    print(f"\n[Scheduler] Registered {SCAN_INTERVAL_MINUTES}min interval scan")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\nScanner stopped.")
