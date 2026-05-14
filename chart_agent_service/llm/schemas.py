"""
LLM 응답 Pydantic 스키마 (Step 9).

AgentLLMResponse  : 에이전트 공통 신호 출력
NewsSentimentResponse: 뉴스 감성 분석 출력
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


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
        if isinstance(v, str):
            v = v.lower().strip()
            if v in ("buy", "매수", "bullish"):
                return "buy"
            if v in ("sell", "매도", "bearish"):
                return "sell"
            return "neutral"
        return str(v)


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
