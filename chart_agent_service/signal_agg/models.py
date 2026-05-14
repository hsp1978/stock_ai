"""
SignalAggregator 도메인 모델 (Step 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class AgentSignal:
    """에이전트 신호 (aggregator 입력)."""

    agent_name: str
    signal: Literal["buy", "sell", "neutral"]
    confidence: float  # 0–10


@dataclass
class MLPrediction:
    """ML 앙상블 예측 결과."""

    model_name: str
    score: float  # 0–1 (확률 또는 정규화 점수)
    direction: Literal["buy", "sell", "neutral"] = "neutral"


@dataclass
class ToolResult:
    """분석 도구 결과."""

    name: str
    score: float  # 임의 부동소수
    flags: list[str] = field(default_factory=list)


@dataclass
class Position:
    """보유 포지션."""

    ticker: str
    qty: int
    entry_price: float
    opened_at: datetime
    sector: str = "unknown"
    currency: str = "USD"
    conviction: float = 0.0  # 진입 시 conviction


@dataclass
class Decision:
    """SignalAggregator 최종 판단."""

    ticker: str
    action: Literal["buy", "sell", "wait", "resize"]
    qty: int  # 발주 수량 (0이면 wait)
    conviction: float
    reason: str
    flags: list[str] = field(default_factory=list)
