#!/usr/bin/env python3
"""
Portfolio Auto-Rebalancing Module (V2.0 Week 4)

주기적 또는 조건 충족 시 포트폴리오 자동 리밸런싱
- 매주 월요일 정기 리밸런싱
- Drift 5% 초과 시 즉시 리밸런싱
- 거래비용 0.1% 반영
- Paper Trading 연동
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from config import OUTPUT_DIR
from paper_trader import get_portfolio_status, execute_paper_order, update_position_prices
from portfolio_optimizer import markowitz_optimize, risk_parity_optimize


# 상태 파일
REBALANCE_STATE_FILE = os.path.join(OUTPUT_DIR, "rebalance_state.json")
TRANSACTION_COST_PCT = 0.001  # 0.1% per trade


def _load_rebalance_state() -> dict:
    """리밸런싱 상태 로드"""
    if os.path.exists(REBALANCE_STATE_FILE):
        try:
            with open(REBALANCE_STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass

    return {
        "last_rebalance_date": None,
        "rebalance_count": 0,
        "total_transaction_costs": 0.0,
        "target_weights": {},
        "history": []
    }


def _save_rebalance_state(state: dict):
    """리밸런싱 상태 저장"""
    with open(REBALANCE_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


def compute_drift(current_weights: Dict[str, float], target_weights: Dict[str, float]) -> float:
    """
    목표 비중 대비 현재 비중 drift 계산

    Args:
        current_weights: 현재 포지션 비중 {ticker: weight}
        target_weights: 목표 비중 {ticker: weight}

    Returns:
        총 drift (0.0 ~ 2.0, 0에 가까울수록 일치)
    """
    drift = 0.0
    all_tickers = set(current_weights.keys()) | set(target_weights.keys())

    for ticker in all_tickers:
        current = current_weights.get(ticker, 0.0)
        target = target_weights.get(ticker, 0.0)
        drift += abs(current - target)

    return drift


def should_rebalance(
    last_rebalance_date: Optional[str],
    drift: float,
    rebalance_interval_days: int = 7,
    drift_threshold: float = 0.05
) -> Tuple[bool, str]:
    """
    리밸런싱 필요 여부 판단

    Args:
        last_rebalance_date: 마지막 리밸런싱 일자 (ISO format)
        drift: 현재 drift 값
        rebalance_interval_days: 리밸런싱 주기 (기본 7일)
        drift_threshold: Drift 임계값 (기본 5%)

    Returns:
        (bool: 필요 여부, str: 사유)
    """

    # 1. 주기적 리밸런싱
    if last_rebalance_date:
        try:
            last_date = datetime.fromisoformat(last_rebalance_date)
            days_since = (datetime.now() - last_date).days

            if days_since >= rebalance_interval_days:
                return True, f"주기 도래 ({days_since}일 경과)"
        except ValueError:
            pass
    else:
        return True, "최초 리밸런싱"

    # 2. Drift 임계값 초과
    if drift > drift_threshold:
        return True, f"Drift 초과 ({drift:.2%} > {drift_threshold:.0%})"

    return False, "리밸런싱 불필요"


def compute_rebalancing_orders(
    current_positions: Dict[str, dict],
    target_weights: Dict[str, float],
    total_equity: float,
    current_prices: Dict[str, float]
) -> List[dict]:
    """
    리밸런싱 주문 계산

    Args:
        current_positions: 현재 포지션 {ticker: {qty, avg_price, current_price, ...}}
        target_weights: 목표 비중 {ticker: weight}
        total_equity: 총 자산
        current_prices: 현재 가격 {ticker: price}

    Returns:
        주문 리스트 [{ticker, action, qty, price, target_weight, ...}]
    """
    orders = []

    # 현재 비중 계산
    current_weights = {}
    for ticker, pos in current_positions.items():
        qty = pos.get("qty", 0)
        price = current_prices.get(ticker, pos.get("current_price", 0))
        value = qty * price
        current_weights[ticker] = value / total_equity if total_equity > 0 else 0.0

    # 목표 비중 대비 차이
    all_tickers = set(current_weights.keys()) | set(target_weights.keys())

    for ticker in all_tickers:
        current_w = current_weights.get(ticker, 0.0)
        target_w = target_weights.get(ticker, 0.0)
        delta_w = target_w - current_w

        # 1% 미만 차이는 무시
        if abs(delta_w) < 0.01:
            continue

        # 금액 차이
        delta_value = delta_w * total_equity
        price = current_prices.get(ticker, 0)

        if price <= 0:
            continue

        # 수량 계산
        delta_qty = int(delta_value / price)

        if delta_qty > 0:
            action = "BUY"
        elif delta_qty < 0:
            action = "SELL"
            delta_qty = abs(delta_qty)
        else:
            continue

        # 거래비용 계산
        transaction_cost = abs(delta_value) * TRANSACTION_COST_PCT

        orders.append({
            "ticker": ticker,
            "action": action,
            "qty": delta_qty,
            "price": price,
            "target_weight": round(target_w, 4),
            "current_weight": round(current_w, 4),
            "delta_weight": round(delta_w, 4),
            "delta_value": round(delta_value, 2),
            "transaction_cost": round(transaction_cost, 2),
            "reason": "Auto Rebalancing"
        })

    return orders


def execute_rebalancing(
    method: str = "markowitz",
    rebalance_interval_days: int = 7,
    drift_threshold: float = 0.05,
    dry_run: bool = False
) -> dict:
    """
    포트폴리오 자동 리밸런싱 실행

    Args:
        method: "markowitz" or "risk_parity"
        rebalance_interval_days: 리밸런싱 주기 (일)
        drift_threshold: Drift 임계값 (0.05 = 5%)
        dry_run: True면 실제 주문 없이 시뮬레이션만

    Returns:
        리밸런싱 결과
    """

    state = _load_rebalance_state()

    # 1. 현재 포지션 조회
    portfolio = get_portfolio_status()
    current_positions = portfolio.get("positions", {})
    total_equity = portfolio.get("total_equity", 0)

    if not current_positions:
        return {
            "status": "skipped",
            "reason": "포지션 없음",
            "timestamp": datetime.now().isoformat()
        }

    if total_equity <= 0:
        return {
            "status": "skipped",
            "reason": "자산 없음",
            "timestamp": datetime.now().isoformat()
        }

    # 2. 목표 비중 계산
    tickers = list(current_positions.keys())

    try:
        if method == "risk_parity":
            opt_result = risk_parity_optimize(tickers)
        else:
            opt_result = markowitz_optimize(tickers)

        if opt_result.get("error"):
            return {
                "status": "failed",
                "reason": opt_result["error"],
                "timestamp": datetime.now().isoformat()
            }

        target_weights = opt_result.get("weights", {})

    except Exception as e:
        return {
            "status": "failed",
            "reason": f"최적화 실패: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }

    # 3. Drift 계산
    current_weights = {}
    for ticker, pos in current_positions.items():
        qty = pos.get("qty", 0)
        price = pos.get("current_price", 0)
        value = qty * price
        current_weights[ticker] = value / total_equity if total_equity > 0 else 0.0

    drift = compute_drift(current_weights, target_weights)

    # 4. 리밸런싱 필요 여부 판단
    need_rebalance, reason = should_rebalance(
        state.get("last_rebalance_date"),
        drift,
        rebalance_interval_days,
        drift_threshold
    )

    if not need_rebalance:
        return {
            "status": "skipped",
            "reason": reason,
            "drift": round(drift, 4),
            "current_weights": current_weights,
            "target_weights": target_weights,
            "timestamp": datetime.now().isoformat()
        }

    # 5. 리밸런싱 주문 계산
    current_prices = {ticker: pos.get("current_price", 0) for ticker, pos in current_positions.items()}
    orders = compute_rebalancing_orders(current_positions, target_weights, total_equity, current_prices)

    if not orders:
        return {
            "status": "skipped",
            "reason": "주문 필요 없음 (모든 비중 1% 이내)",
            "drift": round(drift, 4),
            "timestamp": datetime.now().isoformat()
        }

    # 6. 주문 실행
    executed_orders = []
    total_cost = 0.0

    if not dry_run:
        for order in orders:
            try:
                result = execute_paper_order(
                    ticker=order["ticker"],
                    action=order["action"],
                    qty=order["qty"],
                    price=order["price"],
                    reason=order["reason"]
                )
                executed_orders.append(result)
                total_cost += order["transaction_cost"]

            except Exception as e:
                executed_orders.append({
                    "ticker": order["ticker"],
                    "status": "failed",
                    "error": str(e)
                })

        # 상태 업데이트
        state["last_rebalance_date"] = datetime.now().isoformat()
        state["rebalance_count"] += 1
        state["total_transaction_costs"] += total_cost
        state["target_weights"] = target_weights

        # 히스토리 추가
        state["history"].append({
            "timestamp": datetime.now().isoformat(),
            "method": method,
            "drift": round(drift, 4),
            "orders_count": len(orders),
            "transaction_cost": round(total_cost, 2),
            "reason": reason
        })

        # 최근 100개만 유지
        if len(state["history"]) > 100:
            state["history"] = state["history"][-100:]

        _save_rebalance_state(state)

    return {
        "status": "executed" if not dry_run else "dry_run",
        "reason": reason,
        "drift": round(drift, 4),
        "method": method,
        "orders": orders,
        "executed_orders": executed_orders if not dry_run else [],
        "total_transaction_cost": round(total_cost, 2),
        "current_weights": {k: round(v, 4) for k, v in current_weights.items()},
        "target_weights": {k: round(v, 4) for k, v in target_weights.items()},
        "rebalance_count": state["rebalance_count"] if not dry_run else state["rebalance_count"],
        "timestamp": datetime.now().isoformat()
    }


def get_rebalance_history(limit: int = 10) -> dict:
    """리밸런싱 히스토리 조회"""
    state = _load_rebalance_state()
    history = state.get("history", [])

    return {
        "count": len(history),
        "total_rebalances": state.get("rebalance_count", 0),
        "total_costs": state.get("total_transaction_costs", 0),
        "last_rebalance": state.get("last_rebalance_date"),
        "history": history[-limit:]
    }


def get_rebalance_status() -> dict:
    """현재 리밸런싱 상태"""
    state = _load_rebalance_state()
    portfolio = get_portfolio_status()

    current_positions = portfolio.get("positions", {})
    total_equity = portfolio.get("total_equity", 0)
    target_weights = state.get("target_weights", {})

    # 현재 비중
    current_weights = {}
    for ticker, pos in current_positions.items():
        value = pos.get("qty", 0) * pos.get("current_price", 0)
        current_weights[ticker] = value / total_equity if total_equity > 0 else 0.0

    # Drift 계산
    drift = compute_drift(current_weights, target_weights) if target_weights else 0.0

    # 다음 리밸런싱 예상일
    next_rebalance = None
    if state.get("last_rebalance_date"):
        try:
            last_date = datetime.fromisoformat(state["last_rebalance_date"])
            next_rebalance = (last_date + timedelta(days=7)).isoformat()
        except ValueError:
            pass

    return {
        "last_rebalance_date": state.get("last_rebalance_date"),
        "next_rebalance_date": next_rebalance,
        "rebalance_count": state.get("rebalance_count", 0),
        "total_transaction_costs": state.get("total_transaction_costs", 0),
        "current_drift": round(drift, 4),
        "current_weights": {k: round(v, 4) for k, v in current_weights.items()},
        "target_weights": {k: round(v, 4) for k, v in target_weights.items()},
        "drift_threshold": 0.05,
        "needs_rebalance": drift > 0.05
    }


# ═══════════════════════════════════════════════════════════════
#  테스트
# ═══════════════════════════════════════════════════════════════

def test_rebalancing():
    """리밸런싱 테스트"""
    print("=" * 70)
    print("Portfolio Rebalancing Test")
    print("=" * 70)

    # Dry-run 테스트
    print("\n1. Dry-Run 테스트...")
    result = execute_rebalancing(method="markowitz", dry_run=True)

    print(f"  상태: {result['status']}")
    print(f"  사유: {result['reason']}")
    print(f"  Drift: {result.get('drift', 0):.2%}")

    if result.get("orders"):
        print(f"\n  주문 {len(result['orders'])}개:")
        for order in result['orders']:
            print(f"    - {order['action']} {order['ticker']} {order['qty']}주 @ ${order['price']:.2f}")
            print(f"      (현재 {order['current_weight']:.1%} → 목표 {order['target_weight']:.1%})")

    # 상태 조회
    print("\n2. 리밸런싱 상태...")
    status = get_rebalance_status()
    print(f"  총 리밸런싱: {status['rebalance_count']}회")
    print(f"  총 거래비용: ${status['total_transaction_costs']:.2f}")
    print(f"  현재 Drift: {status['current_drift']:.2%}")
    print(f"  리밸런싱 필요: {status['needs_rebalance']}")

    # 히스토리
    print("\n3. 리밸런싱 히스토리...")
    history = get_rebalance_history(limit=5)
    print(f"  총 히스토리: {history['count']}건")
    for h in history['history'][-3:]:
        print(f"    - {h['timestamp'][:19]}: {h['method']}, drift={h['drift']:.2%}, 주문={h['orders_count']}개")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_rebalancing()