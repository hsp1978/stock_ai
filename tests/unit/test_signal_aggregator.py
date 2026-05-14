"""
SignalAggregator 단위 테스트 (EXECUTION_PLAN Step 2)

테스트 시나리오:
- 신규 BUY → position 생성
- 동일 ticker 3일 내 재BUY (conviction 동일) → 차단
- 동일 ticker 3일 내 재BUY (conviction +0.3) → resize 허용
- 4 에이전트 mixed signal → conviction 가중 합산 정확성
- per_ticker 10% 초과 사이즈 → 자동 축소
- conviction < threshold → action="wait"
"""

import os
import sys
from datetime import datetime, timedelta, timezone

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

from signal_agg.aggregator import SignalAggregator  # noqa: E402
from signal_agg.models import AgentSignal, MLPrediction, Position, ToolResult  # noqa: E402


# ── 공통 픽스처 ───────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {"agent_ensemble": 0.4, "ml_ensemble": 0.4, "tool_score": 0.2}

AGG = SignalAggregator(
    weights=DEFAULT_WEIGHTS,
    conflict_window_days=3,
    conviction_threshold=0.5,
)

_NAV = 100_000.0
_PRICE = 100.0
_ATR = 2.0  # $2


def _buy_signals(n: int = 4, conf: float = 8.0) -> list[AgentSignal]:
    return [
        AgentSignal(agent_name=f"Agent{i}", signal="buy", confidence=conf)
        for i in range(n)
    ]


def _ml(n: int = 2, score: float = 0.7) -> list[MLPrediction]:
    return [MLPrediction(model_name=f"Model{i}", score=score) for i in range(n)]


def _tools(score: float = 3.0) -> dict[str, ToolResult]:
    return {"rsi": ToolResult(name="rsi", score=score)}


def _pos(ticker: str, days_ago: int = 0, conviction: float = 0.6) -> Position:
    opened = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return Position(
        ticker=ticker,
        qty=10,
        entry_price=_PRICE,
        opened_at=opened,
        conviction=conviction,
    )


# ── 신규 BUY ─────────────────────────────────────────────────────────


def test_new_buy_creates_decision():
    """신규 BUY 시그널 → action='buy', qty > 0."""
    decision = AGG.aggregate(
        ticker="AAPL",
        agent_signals=_buy_signals(),
        ml_signals=_ml(),
        tool_outputs=_tools(),
        active_positions={},
        atr=_ATR,
        price=_PRICE,
        nav=_NAV,
    )
    assert decision.action == "buy"
    assert decision.qty > 0
    assert decision.conviction >= 0.5


# ── 동일 ticker 3일 내 재BUY 차단 ────────────────────────────────────


def test_conflict_window_blocks_repeat_buy():
    """동일 ticker 2일 내 재BUY, conviction 동일 → wait."""
    existing = {"AAPL": _pos("AAPL", days_ago=2, conviction=0.65)}
    decision = AGG.aggregate(
        ticker="AAPL",
        agent_signals=_buy_signals(),
        ml_signals=_ml(),
        tool_outputs=_tools(),
        active_positions=existing,
        atr=_ATR,
        price=_PRICE,
        nav=_NAV,
        existing_conviction=0.65,
    )
    assert decision.action == "wait"
    assert "SINGLE_POSITION_RULE" in decision.flags


def test_conflict_window_expired_allows_new_buy():
    """5일 지난 포지션 → conflict window 초과 → 새 BUY 허용."""
    existing = {"AAPL": _pos("AAPL", days_ago=5)}
    decision = AGG.aggregate(
        ticker="AAPL",
        agent_signals=_buy_signals(),
        ml_signals=_ml(),
        tool_outputs=_tools(),
        active_positions=existing,
        atr=_ATR,
        price=_PRICE,
        nav=_NAV,
        existing_conviction=0.6,
    )
    assert decision.action in ("buy", "resize")


# ── conviction +0.3 → resize 허용 ────────────────────────────────────


def test_high_conviction_allows_resize():
    """3일 내 재BUY, conviction이 기존보다 +0.3 이상 → resize 허용."""
    existing = {"AAPL": _pos("AAPL", days_ago=1, conviction=0.55)}
    # 매우 강한 BUY 신호로 conviction 0.85+ 유도
    strong_signals = [AgentSignal(f"A{i}", "buy", 10.0) for i in range(4)]
    strong_ml = [MLPrediction(f"M{i}", 0.95) for i in range(3)]
    strong_tools = {"rsi": ToolResult("rsi", 10.0), "macd": ToolResult("macd", 10.0)}
    decision = AGG.aggregate(
        ticker="AAPL",
        agent_signals=strong_signals,
        ml_signals=strong_ml,
        tool_outputs=strong_tools,
        active_positions=existing,
        atr=_ATR,
        price=_PRICE,
        nav=_NAV,
        existing_conviction=0.55,
    )
    # conviction이 0.55 + 0.2 = 0.75 이상이면 resize
    assert decision.action in ("resize", "buy")
    assert "RESIZE_ALLOWED" in decision.flags or decision.conviction >= 0.75


# ── conviction 가중 합산 정확성 ─────────────────────────────────────


def test_conviction_computation_buy_dominant():
    """BUY 에이전트 4명 (conf=8) → conviction > 0.5."""
    decision = AGG.aggregate(
        ticker="TSLA",
        agent_signals=_buy_signals(4, 8.0),
        ml_signals=_ml(2, 0.8),
        tool_outputs=_tools(5.0),
        active_positions={},
        atr=_ATR,
        price=_PRICE,
        nav=_NAV,
    )
    assert decision.conviction > 0.5


def test_conviction_mixed_signals():
    """BUY 2 + SELL 2 (동일 confidence) → conviction ≈ 0.5 (중립)."""
    mixed = [
        AgentSignal("A1", "buy", 7.0),
        AgentSignal("A2", "buy", 7.0),
        AgentSignal("A3", "sell", 7.0),
        AgentSignal("A4", "sell", 7.0),
    ]
    decision = AGG.aggregate(
        ticker="MSFT",
        agent_signals=mixed,
        ml_signals=[MLPrediction("M1", 0.5)],
        tool_outputs={"rsi": ToolResult("rsi", 0.0)},
        active_positions={},
        atr=_ATR,
        price=_PRICE,
        nav=_NAV,
    )
    # 중립 → wait
    assert decision.action == "wait" or decision.conviction <= 0.6


# ── per_ticker 10% 초과 → 자동 축소 ─────────────────────────────────


def test_per_ticker_exposure_limit():
    """기존 포지션 8%NAV + 새 발주 5%NAV → 10% 한도 초과 → 수량 축소."""
    existing_qty = int(_NAV * 0.08 / _PRICE)  # 8% 보유
    existing = {
        "AAPL": Position(
            ticker="AAPL",
            qty=existing_qty,
            entry_price=_PRICE,
            opened_at=datetime.now(timezone.utc) - timedelta(days=10),
            conviction=0.6,
        )
    }
    # 강한 BUY 신호로 큰 발주량 요청
    decision = AGG.aggregate(
        ticker="AAPL",
        agent_signals=_buy_signals(4, 10.0),
        ml_signals=_ml(2, 1.0),
        tool_outputs=_tools(10.0),
        active_positions=existing,
        atr=_ATR,
        price=_PRICE,
        nav=_NAV,
    )
    # 10% 한도 내로 수량 제한
    total_value = (existing_qty + decision.qty) * _PRICE
    assert total_value / _NAV * 100 <= 10.0 + 0.01 or decision.action == "wait"


# ── conviction < threshold → wait ────────────────────────────────────


def test_low_conviction_returns_wait():
    """conviction < 0.5 → action='wait'."""
    weak_signals = [AgentSignal(f"A{i}", "neutral", 1.0) for i in range(4)]
    weak_ml = [MLPrediction("M1", 0.1)]
    weak_tools = {"rsi": ToolResult("rsi", -5.0)}
    decision = AGG.aggregate(
        ticker="SPY",
        agent_signals=weak_signals,
        ml_signals=weak_ml,
        tool_outputs=weak_tools,
        active_positions={},
        atr=_ATR,
        price=_PRICE,
        nav=_NAV,
    )
    assert decision.action == "wait"
    assert decision.qty == 0
