"""
페이퍼 트레이딩(모의매매) 시뮬레이터
- 에이전트 시그널 기반 자동 모의매매
- 포지션 추적, P&L 계산, 히스토리 관리
- Trailing Stop (NautilusTrader/Freqtrade 스타일)
- 시간 기반 청산 (Time-based Exit)
- 실제 주문 집행 없음 (시뮬레이션 전용)
- 한국 주식 원화(₩) 표시 지원
"""
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from config import ACCOUNT_SIZE, OUTPUT_DIR
from currency_utils import (
    is_korean_stock,
    get_currency_symbol,
    format_price,
    format_amount
)


PAPER_STATE_FILE = os.path.join(OUTPUT_DIR, "paper_trading_state.json")


def _load_state() -> dict:
    if os.path.exists(PAPER_STATE_FILE):
        try:
            with open(PAPER_STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "account_size": ACCOUNT_SIZE,
        "cash": ACCOUNT_SIZE,
        "positions": {},
        "closed_trades": [],
        "order_history": [],
        "created_at": datetime.now().isoformat(),
    }


def _save_state(state: dict):
    with open(PAPER_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, default=str)


def get_portfolio_status() -> dict:
    state = _load_state()
    positions = state.get("positions", {})
    cash = state.get("cash", ACCOUNT_SIZE)

    total_position_value = sum(
        p.get("qty", 0) * p.get("current_price", p.get("entry_price", 0))
        for p in positions.values()
    )
    total_equity = cash + total_position_value
    initial = state.get("account_size", ACCOUNT_SIZE)
    total_pnl = total_equity - initial
    total_pnl_pct = (total_pnl / initial * 100) if initial > 0 else 0

    closed = state.get("closed_trades", [])
    realized_pnl = sum(t.get("pnl", 0) for t in closed)
    unrealized_pnl = sum(
        (p.get("current_price", p.get("entry_price", 0)) - p.get("entry_price", 0)) * p.get("qty", 0)
        for p in positions.values()
    )

    win_trades = [t for t in closed if t.get("pnl", 0) > 0]
    loss_trades = [t for t in closed if t.get("pnl", 0) <= 0]
    win_rate = len(win_trades) / len(closed) * 100 if closed else 0

    return {
        "total_equity": round(total_equity, 2),
        "cash": round(cash, 2),
        "position_value": round(total_position_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "open_positions": len(positions),
        "total_closed_trades": len(closed),
        "win_rate_pct": round(win_rate, 1),
        "positions": {
            ticker: {
                "qty": p["qty"],
                "entry_price": p["entry_price"],
                "current_price": p.get("current_price", p["entry_price"]),
                "pnl": round((p.get("current_price", p["entry_price"]) - p["entry_price"]) * p["qty"], 2),
                "pnl_pct": round((p.get("current_price", p["entry_price"]) / p["entry_price"] - 1) * 100, 2),
                "entry_date": p.get("entry_date", ""),
                # 자동 청산 조건 및 trailing 추적 (Virtual Trade 페이지용)
                "stop_loss_price": p.get("stop_loss_price", 0),
                "take_profit_price": p.get("take_profit_price", 0),
                "trailing_stop_pct": p.get("trailing_stop_pct", 0),
                "time_stop_days": p.get("time_stop_days", 0),
                "peak_price": p.get("peak_price", p["entry_price"]),
            }
            for ticker, p in positions.items()
        },
        "recent_trades": closed[-10:] if closed else [],
    }


def execute_paper_order(ticker: str, action: str, qty: int,
                        price: float, reason: str = "",
                        trailing_stop_pct: float = 0.0,
                        time_stop_days: int = 0,
                        stop_loss_price: float = 0.0,
                        take_profit_price: float = 0.0) -> dict:
    """페이퍼 트레이딩 주문 실행

    Args:
        trailing_stop_pct: Trailing stop 비율 (0~1, 예: 0.05 = 5%)
        time_stop_days: 시간 기반 청산 일수 (0 = 비활성)
        stop_loss_price: 고정 손절가 (0 = 비활성)
        take_profit_price: 고정 익절가 (0 = 비활성)
    """
    state = _load_state()
    positions = state.get("positions", {})
    cash = state.get("cash", ACCOUNT_SIZE)

    order = {
        "ticker": ticker,
        "action": action,
        "qty": qty,
        "price": price,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "status": "pending",
    }

    if action == "BUY":
        cost = qty * price
        if cost > cash:
            max_qty = int(cash / price)
            if max_qty <= 0:
                order["status"] = "rejected"
                # 한국 주식 여부에 따라 통화 표시 변경
                currency = get_currency_symbol(ticker)
                order["reject_reason"] = f"잔고 부족 (필요: {currency}{cost:,.0f}, 보유: {currency}{cash:,.0f})"
                state["order_history"].append(order)
                _save_state(state)
                return order
            qty = max_qty
            cost = qty * price
            order["qty"] = qty

        if ticker in positions:
            existing = positions[ticker]
            total_qty = existing["qty"] + qty
            avg_price = (existing["entry_price"] * existing["qty"] + price * qty) / total_qty
            positions[ticker] = {
                "qty": total_qty,
                "entry_price": round(avg_price, 4),
                "current_price": price,
                "peak_price": max(existing.get("peak_price", price), price),
                "entry_date": existing.get("entry_date", datetime.now().isoformat()),
                "trailing_stop_pct": trailing_stop_pct or existing.get("trailing_stop_pct", 0.0),
                "time_stop_days": time_stop_days or existing.get("time_stop_days", 0),
                "stop_loss_price": stop_loss_price or existing.get("stop_loss_price", 0.0),
                "take_profit_price": take_profit_price or existing.get("take_profit_price", 0.0),
            }
        else:
            positions[ticker] = {
                "qty": qty,
                "entry_price": price,
                "current_price": price,
                "peak_price": price,
                "entry_date": datetime.now().isoformat(),
                "trailing_stop_pct": trailing_stop_pct,
                "time_stop_days": time_stop_days,
                "stop_loss_price": stop_loss_price,
                "take_profit_price": take_profit_price,
            }

        state["cash"] = cash - cost
        order["status"] = "filled"
        order["cost"] = round(cost, 2)

    elif action == "SELL":
        if ticker not in positions:
            order["status"] = "rejected"
            order["reject_reason"] = f"{ticker} 포지션 없음"
            state["order_history"].append(order)
            _save_state(state)
            return order

        pos = positions[ticker]
        sell_qty = min(qty, pos["qty"])
        order["qty"] = sell_qty
        proceeds = sell_qty * price
        pnl = (price - pos["entry_price"]) * sell_qty

        closed_trade = {
            "ticker": ticker,
            "entry_price": pos["entry_price"],
            "exit_price": price,
            "qty": sell_qty,
            "pnl": round(pnl, 2),
            "pnl_pct": round((price / pos["entry_price"] - 1) * 100, 2),
            "entry_date": pos.get("entry_date", ""),
            "exit_date": datetime.now().isoformat(),
            "reason": reason,
        }
        state["closed_trades"].append(closed_trade)

        remaining = pos["qty"] - sell_qty
        if remaining > 0:
            positions[ticker]["qty"] = remaining
            positions[ticker]["current_price"] = price
        else:
            del positions[ticker]

        state["cash"] = cash + proceeds
        order["status"] = "filled"
        order["proceeds"] = round(proceeds, 2)
        order["pnl"] = round(pnl, 2)

    state["positions"] = positions
    state["order_history"].append(order)
    _save_state(state)
    return order


def process_agent_signal(ticker: str, result: dict, current_price: float) -> Optional[dict]:
    signal = result.get("final_signal", "HOLD")
    score = result.get("composite_score", 0)
    confidence = result.get("confidence", 0)

    if signal == "HOLD" or confidence < 5:
        return None

    risk_tool = None
    for td in result.get("tool_details", []):
        if td.get("tool") == "risk_position_sizing":
            risk_tool = td
            break

    qty = risk_tool.get("recommended_qty", 0) if risk_tool else 0

    if signal == "BUY" and qty > 0:
        split = risk_tool.get("split_entry", []) if risk_tool else []
        first_tranche_qty = split[0]["qty"] if split else qty
        if first_tranche_qty <= 0:
            first_tranche_qty = max(1, qty // 3)
        return execute_paper_order(
            ticker, "BUY", first_tranche_qty, current_price,
            reason=f"에이전트 BUY (점수: {score:+.1f}, 신뢰도: {confidence})"
        )

    elif signal == "SELL":
        state = _load_state()
        pos = state.get("positions", {}).get(ticker)
        if pos:
            return execute_paper_order(
                ticker, "SELL", pos["qty"], current_price,
                reason=f"에이전트 SELL (점수: {score:+.1f}, 신뢰도: {confidence})"
            )

    return None


def update_position_prices(prices: dict[str, float]) -> list[dict]:
    """포지션 가격 업데이트 + Trailing Stop/시간 기반 자동 청산

    Returns:
        자동 청산된 주문 목록
    """
    state = _load_state()
    positions = state.get("positions", {})
    auto_closed = []

    for ticker, price in prices.items():
        if ticker not in positions:
            continue

        pos = positions[ticker]
        pos["current_price"] = price

        # Peak price 업데이트 (trailing stop 기준)
        peak = pos.get("peak_price", pos.get("entry_price", price))
        if price > peak:
            pos["peak_price"] = price
            peak = price

        # 1. Trailing Stop 체크
        trailing_pct = pos.get("trailing_stop_pct", 0.0)
        if trailing_pct > 0:
            trailing_stop_price = peak * (1 - trailing_pct)
            if price <= trailing_stop_price:
                # 한국 주식용 통화 표시
                result = execute_paper_order(
                    ticker, "SELL", pos["qty"], price,
                    reason=f"Trailing Stop: {trailing_pct:.1%} 이탈 (고점 {format_price(peak, ticker)} → {format_price(price, ticker)})"
                )
                auto_closed.append(result)
                continue  # 다음 종목으로

        # 2. 고정 손절가 체크
        stop_loss = pos.get("stop_loss_price", 0.0)
        if stop_loss > 0 and price <= stop_loss:
            result = execute_paper_order(
                ticker, "SELL", pos["qty"], price,
                reason=f"Stop Loss: {format_price(stop_loss, ticker)}"
            )
            auto_closed.append(result)
            continue

        # 3. 고정 익절가 체크
        take_profit = pos.get("take_profit_price", 0.0)
        if take_profit > 0 and price >= take_profit:
            result = execute_paper_order(
                ticker, "SELL", pos["qty"], price,
                reason=f"Take Profit: {format_price(take_profit, ticker)}"
            )
            auto_closed.append(result)
            continue

        # 4. 시간 기반 청산 체크
        time_stop_days = pos.get("time_stop_days", 0)
        if time_stop_days > 0:
            entry_date_str = pos.get("entry_date", "")
            if entry_date_str:
                try:
                    entry_date = datetime.fromisoformat(entry_date_str.replace("Z", "+00:00"))
                    days_held = (datetime.now() - entry_date).days
                    if days_held >= time_stop_days:
                        result = execute_paper_order(
                            ticker, "SELL", pos["qty"], price,
                            reason=f"Time Stop: {days_held}일 경과 (설정: {time_stop_days}일)"
                        )
                        auto_closed.append(result)
                        continue
                except Exception:
                    pass

    # 상태 저장
    state["positions"] = positions
    _save_state(state)

    return auto_closed


def reset_paper_trading() -> dict:
    state = {
        "account_size": ACCOUNT_SIZE,
        "cash": ACCOUNT_SIZE,
        "positions": {},
        "closed_trades": [],
        "order_history": [],
        "created_at": datetime.now().isoformat(),
    }
    _save_state(state)
    return {"status": "reset", "account_size": ACCOUNT_SIZE}
