"""
SignalAggregator — 종목당 단일 active position 규칙 + conviction 합성 (Step 2).

aggregate() 호출 흐름:
1. 종목당 단일 active position 규칙 검사
2. conviction 합성 (agent × 0.4 + ml × 0.4 + tool × 0.2)
3. conviction 임계값 체크
4. ATR 기반 position sizing
5. 노출 한도 (per_ticker 10% / per_sector 25% / per_currency 60%) 검증
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import settings
from signal_agg.models import AgentSignal, Decision, MLPrediction, Position, ToolResult

logger = logging.getLogger(__name__)

# 노출 한도 기본값 (환경변수로 재정의 가능)
_MAX_TICKER_PCT = 10.0
_MAX_SECTOR_PCT = 25.0
_MAX_CURRENCY_PCT = 60.0


class SignalAggregator:
    """
    다중 소스 신호를 합성하고 발주 여부·수량을 결정한다.

    weights 예시:
        {"agent_ensemble": 0.4, "ml_ensemble": 0.4, "tool_score": 0.2}
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        conflict_window_days: int = 3,
        conviction_threshold: float = 0.5,
    ) -> None:
        self.weights = weights or {
            "agent_ensemble": 0.4,
            "ml_ensemble": 0.4,
            "tool_score": 0.2,
        }
        self.window = conflict_window_days
        self.threshold = conviction_threshold

    # ── 내부 헬퍼 ────────────────────────────────────────────────────

    @staticmethod
    def _signal_to_num(signal: str) -> float:
        return {"buy": 1.0, "sell": -1.0, "neutral": 0.0}.get(signal.lower(), 0.0)

    def _compute_conviction(
        self,
        agent_signals: list[AgentSignal],
        ml_signals: list[MLPrediction],
        tool_outputs: dict[str, ToolResult],
    ) -> float:
        """세 소스의 가중 합산 conviction (0–1 스케일)."""
        w_a = self.weights.get("agent_ensemble", 0.4)
        w_m = self.weights.get("ml_ensemble", 0.4)
        w_t = self.weights.get("tool_score", 0.2)

        # 에이전트 앙상블 (신뢰도 가중 신호 방향, 0–10 → 0–1 정규화)
        agent_conf = 0.0
        if agent_signals:
            total_conf = sum(s.confidence for s in agent_signals if s.confidence > 0)
            if total_conf > 0:
                weighted_dir = sum(
                    self._signal_to_num(s.signal) * s.confidence for s in agent_signals
                )
                # 방향 × 정규화 신뢰도 → 0–1
                agent_conf = (weighted_dir / total_conf + 1) / 2  # -1~1 → 0~1

        # ML 앙상블 평균 score
        ml_conf = 0.0
        if ml_signals:
            ml_conf = sum(s.score for s in ml_signals) / len(ml_signals)
            ml_conf = max(0.0, min(1.0, ml_conf))

        # Tool score 정규화 (–10~10 → 0~1)
        tool_score = 0.0
        if tool_outputs:
            raw = sum(r.score for r in tool_outputs.values()) / len(tool_outputs)
            tool_score = (raw / 10 + 1) / 2  # –10~10 → 0~1
            tool_score = max(0.0, min(1.0, tool_score))

        conviction = w_a * agent_conf + w_m * ml_conf + w_t * tool_score
        return round(conviction, 4)

    def _size_position(self, conviction: float, atr: float, nav: float) -> int:
        """ATR 기반 position size 계산 (conviction 0.5~1.0 선형 스케일)."""
        if conviction < self.threshold or atr <= 0 or nav <= 0:
            return 0
        risk_per_trade_pct = getattr(settings, "RISK_PER_TRADE_PCT", 1.0)
        atr_stop_mult = getattr(settings, "ATR_STOP_MULTIPLIER", 2.0)
        risk_amount = nav * risk_per_trade_pct / 100
        scale = min((conviction - self.threshold) / (1.0 - self.threshold), 1.0)
        raw = int(risk_amount * scale / (atr * atr_stop_mult))
        return max(0, raw)

    def _check_exposure(
        self,
        ticker: str,
        qty: int,
        price: float,
        nav: float,
        active_positions: dict[str, Position],
        sector: str = "unknown",
        currency: str = "USD",
    ) -> int:
        """노출 한도 초과 시 수량을 자동 축소한다."""
        if qty <= 0 or nav <= 0:
            return qty

        proposed_value = qty * price

        # per_ticker 한도
        existing_ticker = active_positions.get(ticker)
        existing_ticker_value = (
            existing_ticker.qty * existing_ticker.entry_price
            if existing_ticker
            else 0.0
        )
        if (existing_ticker_value + proposed_value) / nav * 100 > _MAX_TICKER_PCT:
            allowed = (
                max(0, _MAX_TICKER_PCT / 100 * nav - existing_ticker_value) / price
            )
            qty = min(qty, int(allowed))
            logger.info("per_ticker 한도 조정: %s → %d", ticker, qty)

        # per_sector 한도
        sector_value = sum(
            p.entry_price * p.qty
            for p in active_positions.values()
            if p.sector == sector
        )
        if (sector_value + qty * price) / nav * 100 > _MAX_SECTOR_PCT:
            allowed = max(0, _MAX_SECTOR_PCT / 100 * nav - sector_value) / price
            qty = min(qty, int(allowed))
            logger.info("per_sector 한도 조정: %s → %d", ticker, qty)

        # per_currency 한도
        currency_value = sum(
            p.entry_price * p.qty
            for p in active_positions.values()
            if p.currency == currency
        )
        if (currency_value + qty * price) / nav * 100 > _MAX_CURRENCY_PCT:
            allowed = max(0, _MAX_CURRENCY_PCT / 100 * nav - currency_value) / price
            qty = min(qty, int(allowed))
            logger.info("per_currency 한도 조정: %s → %d", ticker, qty)

        return max(0, qty)

    # ── 공개 API ─────────────────────────────────────────────────────

    def aggregate(
        self,
        ticker: str,
        agent_signals: list[AgentSignal],
        ml_signals: list[MLPrediction],
        tool_outputs: dict[str, ToolResult],
        active_positions: dict[str, Position],
        atr: float = 0.0,
        price: float = 0.0,
        nav: float = 0.0,
        sector: str = "unknown",
        currency: str = "USD",
        existing_conviction: float = 0.0,
    ) -> Decision:
        """
        신호를 종합하여 발주 판단을 반환한다.

        Args:
            ticker:             분석 종목
            agent_signals:      에이전트 신호 목록
            ml_signals:         ML 예측 목록
            tool_outputs:       도구 결과 dict
            active_positions:   현재 보유 포지션 {ticker: Position}
            atr:                현재 ATR (position sizing용)
            price:              현재가
            nav:                포트폴리오 순자산
            sector:             섹터 (노출 한도용)
            currency:           통화 (노출 한도용)
            existing_conviction: 기존 포지션의 conviction (resize 판단용)
        """
        conviction = self._compute_conviction(agent_signals, ml_signals, tool_outputs)
        flags: list[str] = []

        # 1. 종목당 단일 active position 규칙
        existing = active_positions.get(ticker)
        if existing is not None:
            age = (
                datetime.now(timezone.utc)
                - existing.opened_at.replace(
                    tzinfo=timezone.utc
                    if existing.opened_at.tzinfo is None
                    else existing.opened_at.tzinfo
                )
            ).days
            if age <= self.window:
                # conviction이 기존보다 +0.2 이상이면 resize 허용
                if conviction >= existing_conviction + 0.2:
                    flags.append("RESIZE_ALLOWED")
                    action = "resize"
                else:
                    return Decision(
                        ticker=ticker,
                        action="wait",
                        qty=0,
                        conviction=conviction,
                        reason=f"active_position_conflict (age={age}d)",
                        flags=["SINGLE_POSITION_RULE"],
                    )

        # 2. conviction 임계값 체크
        if conviction < self.threshold:
            return Decision(
                ticker=ticker,
                action="wait",
                qty=0,
                conviction=conviction,
                reason=f"conviction={conviction:.3f} < threshold={self.threshold}",
                flags=["LOW_CONVICTION"],
            )

        # 3. 신호 방향 결정
        agent_dir = sum(
            self._signal_to_num(s.signal) * s.confidence for s in agent_signals
        )
        if agent_dir > 0.1:
            action = "buy" if not flags else action  # resize 유지
        elif agent_dir < -0.1:
            action = "sell" if not flags else action
        else:
            return Decision(
                ticker=ticker,
                action="wait",
                qty=0,
                conviction=conviction,
                reason="신호 방향 중립",
                flags=["NEUTRAL_DIRECTION"],
            )

        # 4. Position sizing
        qty = self._size_position(conviction, atr, nav)

        # 5. 노출 한도 검증 및 수량 조정
        qty = self._check_exposure(
            ticker, qty, price, nav, active_positions, sector, currency
        )

        if qty == 0:
            return Decision(
                ticker=ticker,
                action="wait",
                qty=0,
                conviction=conviction,
                reason="노출 한도 초과로 수량=0",
                flags=["EXPOSURE_LIMIT"],
            )

        return Decision(
            ticker=ticker,
            action=action,
            qty=qty,
            conviction=conviction,
            reason=f"conviction={conviction:.3f}, qty={qty}",
            flags=flags,
        )
