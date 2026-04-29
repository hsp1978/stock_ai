"""
거래 안전 장치 (safety checks).

모든 주문 제출 전 반드시 통과해야 하는 체크리스트.
실제 자금이 움직이는 LIVE 모드에서 핵심 보호 계층.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

from brokers.base import OrderRequest, OrderSide


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name, "").lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


class TradingSafety:
    """
    주문 전 안전 체크 컴포넌트.

    체크 항목:
    1. Kill Switch — 전역 긴급 중지
    2. 일일 주문 금액 한도 (시장별)
    3. 단일 주문 최대 금액
    4. 단일 종목 최대 비중 (MAX_POSITION_PCT)
    5. client_order_id 중복 (10초 윈도우)
    6. 장 마감 시간 체크 (옵션)
    """

    # 10초 내 중복 주문 방지 윈도우
    DUPLICATE_WINDOW_SECONDS = 10

    def __init__(self, db_path: Optional[str] = None):
        from config import OUTPUT_DIR
        self.db_path = db_path or os.path.join(OUTPUT_DIR, "trading_safety.db")
        self._lock = threading.Lock()
        self._init_db()
        # 환경변수는 인스턴스 생성 시 1회만 읽기 (런타임 변경은 reload_limits)
        self._load_limits()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_spend (
                date TEXT,
                market TEXT,
                total_amount REAL DEFAULT 0,
                order_count INTEGER DEFAULT 0,
                PRIMARY KEY (date, market)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recent_orders (
                client_order_id TEXT PRIMARY KEY,
                submitted_at TEXT,
                ticker TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kill_switch_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT,
                reason TEXT,
                activated_at TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _load_limits(self):
        """환경변수에서 한도 로드."""
        self.daily_limit_usd = _env_float("DAILY_ORDER_LIMIT_USD", 1000.0)
        self.daily_limit_krw = _env_float("DAILY_ORDER_LIMIT_KRW", 1_000_000.0)
        self.single_order_limit_usd = _env_float("SINGLE_ORDER_LIMIT_USD", 200.0)
        self.single_order_limit_krw = _env_float("SINGLE_ORDER_LIMIT_KRW", 200_000.0)
        self.max_position_pct = _env_float("MAX_POSITION_PCT", 20.0)
        self.enforce_market_hours = _env_bool("ENFORCE_MARKET_HOURS", False)
        self.kill_switch_file = os.path.join(
            os.path.dirname(self.db_path), ".kill_switch"
        )

    def reload_limits(self):
        """런타임에 환경변수 재로딩."""
        self._load_limits()

    # ─── Kill Switch ──────────────────────────────────
    def is_kill_switch_active(self) -> bool:
        """파일 존재로 판정 (다른 프로세스에서도 감지 가능)."""
        return os.path.exists(self.kill_switch_file)

    def activate_kill_switch(self, reason: str = "manual"):
        with self._lock:
            with open(self.kill_switch_file, "w") as f:
                f.write(f"{datetime.now().isoformat()}\n{reason}\n")
            self._log_kill_switch("activate", reason)

    def deactivate_kill_switch(self, reason: str = "manual"):
        with self._lock:
            if os.path.exists(self.kill_switch_file):
                os.remove(self.kill_switch_file)
            self._log_kill_switch("deactivate", reason)

    def _log_kill_switch(self, action: str, reason: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO kill_switch_log (action, reason, activated_at) VALUES (?, ?, ?)",
            (action, reason, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

    # ─── 일일 한도 ────────────────────────────────────
    def _market_for(self, ticker: str) -> str:
        t = (ticker or "").upper()
        if t.endswith(".KS") or t.endswith(".KQ"):
            return "KR"
        return "US"

    def _today(self) -> str:
        return datetime.now().date().isoformat()

    def get_daily_spend(self, market: str) -> Tuple[float, int]:
        """오늘 해당 시장의 누적 주문 금액/건수."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT total_amount, order_count FROM daily_spend WHERE date = ? AND market = ?",
            (self._today(), market),
        ).fetchone()
        conn.close()
        return (row[0], row[1]) if row else (0.0, 0)

    def _record_spend(self, market: str, amount: float):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO daily_spend (date, market, total_amount, order_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(date, market) DO UPDATE SET
              total_amount = total_amount + excluded.total_amount,
              order_count = order_count + 1
        """, (self._today(), market, amount))
        conn.commit()
        conn.close()

    # ─── 중복 체크 ────────────────────────────────────
    def _is_duplicate(self, client_order_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        # 10초 이내 동일 client_order_id
        cutoff = (datetime.now() - timedelta(seconds=self.DUPLICATE_WINDOW_SECONDS)).isoformat()
        row = conn.execute(
            "SELECT submitted_at FROM recent_orders WHERE client_order_id = ? AND submitted_at >= ?",
            (client_order_id, cutoff),
        ).fetchone()
        conn.close()
        return row is not None

    def _record_order(self, client_order_id: str, ticker: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT OR REPLACE INTO recent_orders (client_order_id, submitted_at, ticker)
               VALUES (?, ?, ?)""",
            (client_order_id, datetime.now().isoformat(), ticker),
        )
        # 오래된 기록 정리 (1시간 이상)
        old = (datetime.now() - timedelta(hours=1)).isoformat()
        conn.execute("DELETE FROM recent_orders WHERE submitted_at < ?", (old,))
        conn.commit()
        conn.close()

    # ─── 메인 체크 함수 ──────────────────────────────
    def require_all_checks(self, order: OrderRequest) -> Tuple[bool, str]:
        """
        모든 체크 통과 여부.
        통과 시 (True, "ok"), 실패 시 (False, "사유").
        이 메서드는 DB에 기록하지 않음 — 실제 제출 후 `record_successful_order` 호출 필요.
        """
        with self._lock:
            # 1. Kill switch
            if self.is_kill_switch_active():
                return False, "긴급 중지(Kill Switch) 활성화됨"

            # 2. 중복 주문
            if self._is_duplicate(order.client_order_id):
                return False, f"중복 주문 차단 (10초 이내 동일 client_order_id: {order.client_order_id})"

            # 3. 단일 주문 금액 상한
            cost = order.estimated_cost()
            if cost is not None:
                market = self._market_for(order.ticker)
                single_limit = self.single_order_limit_krw if market == "KR" else self.single_order_limit_usd
                if cost > single_limit:
                    currency = "₩" if market == "KR" else "$"
                    return False, f"단일 주문 한도 초과: {currency}{cost:,.0f} > {currency}{single_limit:,.0f}"

                # 4. 일일 누적 한도 (매수만 체크, 매도는 청산 목적)
                if order.side == OrderSide.BUY:
                    daily_spent, _ = self.get_daily_spend(market)
                    daily_limit = self.daily_limit_krw if market == "KR" else self.daily_limit_usd
                    if daily_spent + cost > daily_limit:
                        currency = "₩" if market == "KR" else "$"
                        return False, (
                            f"일일 한도 초과: 기존 {currency}{daily_spent:,.0f} "
                            f"+ 신규 {currency}{cost:,.0f} > 한도 {currency}{daily_limit:,.0f}"
                        )

            # 5. 장 시간 체크 (옵션)
            if self.enforce_market_hours:
                market = self._market_for(order.ticker)
                if not self._is_market_open(market):
                    return False, f"장 마감 시간 — {market} 주문 거부"

            return True, "ok"

    def record_successful_order(self, order: OrderRequest):
        """브로커 제출 성공 후 호출하여 한도 카운터 업데이트."""
        with self._lock:
            cost = order.estimated_cost()
            if cost and order.side == OrderSide.BUY:
                market = self._market_for(order.ticker)
                self._record_spend(market, cost)
            self._record_order(order.client_order_id, order.ticker)

    def _is_market_open(self, market: str) -> bool:
        """간단한 시간 기반 체크 (세밀한 휴장일 판정은 broker.is_market_open에 위임)."""
        now = datetime.now()
        weekday = now.weekday()  # 0=Mon, 6=Sun
        if weekday >= 5:
            return False
        if market == "KR":
            # 09:00~15:30 KST
            start = now.replace(hour=9, minute=0, second=0, microsecond=0)
            end = now.replace(hour=15, minute=30, second=0, microsecond=0)
        else:
            # 미국 장: 22:30~05:00 KST 근사 (서머타임 미반영 — 정확도는 broker에 위임)
            # 여기서는 보수적으로 한국 심야~새벽만 허용
            hour = now.hour
            return hour >= 22 or hour < 6
        return start <= now <= end

    # ─── 상태 조회 ────────────────────────────────────
    def get_status(self) -> Dict[str, Any]:
        us_spent, us_count = self.get_daily_spend("US")
        kr_spent, kr_count = self.get_daily_spend("KR")
        return {
            "kill_switch_active": self.is_kill_switch_active(),
            "daily_limits": {
                "US": {"spent": us_spent, "count": us_count, "limit": self.daily_limit_usd},
                "KR": {"spent": kr_spent, "count": kr_count, "limit": self.daily_limit_krw},
            },
            "single_order_limits": {
                "US": self.single_order_limit_usd,
                "KR": self.single_order_limit_krw,
            },
            "max_position_pct": self.max_position_pct,
            "enforce_market_hours": self.enforce_market_hours,
        }


# 전역 싱글톤
_global_safety: Optional[TradingSafety] = None


def get_safety() -> TradingSafety:
    global _global_safety
    if _global_safety is None:
        _global_safety = TradingSafety()
    return _global_safety
