from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DecisionContext(BaseModel):
    """Kill switch 평가에 필요한 컨텍스트."""

    portfolio_pnl_pct: float = 0.0
    vix: float = 15.0
    vix_prev: float = 0.0  # 0 이면 스파이크 계산 생략
    data_freshness_hours: float = 0.0
    consecutive_losses: int = 0
    weekly_drawdown_pct: float = 0.0
    trailing_peak_dd_pct: float = 0.0
    metadata: dict = Field(default_factory=dict)


TriggerType = Literal[
    "daily_loss_alert",
    "daily_loss_halt",
    "weekly_drawdown_halt",
    "trailing_dd_halt",
    "consecutive_loss_halt",
    "vix_halt",
    "vix_spike_halt",
    "data_stale_halt",
    "manual_halt",
]

ActionType = Literal["alert", "halt", "cool_down"]


class KillSwitchEvent(BaseModel):
    """Kill switch 이벤트 기록."""

    triggered_at: datetime
    trigger_type: TriggerType
    trigger_value: float
    portfolio_pnl_pct: Optional[float] = None
    action: ActionType
    cool_down_until: Optional[datetime] = None
    metadata: dict = Field(default_factory=dict)


class KillSwitchStatus(BaseModel):
    """현재 kill switch 상태."""

    is_blocked: bool
    reason: Optional[str] = None
    cool_down_until: Optional[str] = None
