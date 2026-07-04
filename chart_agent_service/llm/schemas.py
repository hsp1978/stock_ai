"""
LLM 응답 Pydantic 스키마 (Step 9 + DecisionMaker 통일).

AgentLLMResponse      : 8개 분석 에이전트 공통 신호 출력
DecisionMakerResponse : 최종 의사결정자 종합 판단 출력
NewsSentimentResponse : 뉴스 감성 분석 출력
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


def _normalize_signal(v: object) -> str:
    """
    신호 정규화 — SSOT(decision_context.normalize_trade_signal)에 위임한다.

    chart_agent_service 가 sys.path 에 있으면 항상 import 가능하다. 만약 import
    가 불가능한 예외 상황이면, 동일 규칙의 최소 fallback 으로 degrade 한다.
    """
    try:
        from decision_context import normalize_trade_signal

        return normalize_trade_signal(v)
    except Exception:
        s = str(v or "").strip().replace("-", "_").replace(" ", "_").lower()
        if s in ("buy", "strong_buy", "buy_now", "buy_on_dip", "accumulate",
                 "bullish", "bull", "long", "매수", "강한_매수", "상승"):
            return "buy"
        if s in ("sell", "strong_sell", "reduce", "bearish", "bear", "short",
                 "매도", "강한_매도", "하락"):
            return "sell"
        return "neutral"


class AgentLLMResponse(BaseModel):
    """에이전트 LLM 공통 응답 스키마 — 환각 방지용 구조화 출력."""

    signal: Literal["buy", "sell", "neutral"]
    confidence: Annotated[float, Field(ge=0.0, le=10.0)]
    reasoning: Annotated[str, Field(max_length=500)]
    key_evidence: Annotated[list[str], Field(max_length=5)] = Field(
        default_factory=list
    )
    risk_flags: list[str] = Field(default_factory=list)

    @field_validator("reasoning")
    @classmethod
    def strip_reasoning(cls, v: str) -> str:
        return v.strip()

    @field_validator("signal", mode="before")
    @classmethod
    def normalize_signal(cls, v: object) -> str:
        return _normalize_signal(v)


class DecisionMakerResponse(BaseModel):
    """
    DecisionMaker LLM 응답 스키마.

    기존 _parse_decision() 필드명과 1:1 대응하여
    _call_llm() 교체 후에도 하위 로직 무수정.
    """

    final_signal: Literal["buy", "sell", "neutral"] = "neutral"
    final_confidence: Annotated[float, Field(ge=0.0, le=10.0)] = 0.0
    consensus: str = ""
    conflicts: str = "None"
    reasoning: Annotated[str, Field(max_length=600)] = ""
    key_risks: list[str] = Field(default_factory=list)

    @field_validator("final_signal", mode="before")
    @classmethod
    def normalize_final_signal(cls, v: object) -> str:
        return _normalize_signal(v)

    @field_validator("reasoning", "consensus", "conflicts", mode="before")
    @classmethod
    def strip_text(cls, v: object) -> str:
        return str(v).strip() if v else ""


class NewsSentimentResponse(BaseModel):
    """뉴스 감성 분석 응답 스키마."""

    sentiment: Literal["bullish", "bearish", "neutral"] = "neutral"
    score: Annotated[float, Field(ge=-10.0, le=10.0)] = 0.0
    summary: Annotated[str, Field(max_length=300)] = ""
    keywords: list[str] = Field(default_factory=list)

    @field_validator("sentiment", mode="before")
    @classmethod
    def normalize_sentiment(cls, v: object) -> str:
        if isinstance(v, str):
            v = v.lower().strip()
            if v in ("positive", "bullish", "매수"):
                return "bullish"
            if v in ("negative", "bearish", "매도"):
                return "bearish"
        return "neutral"
