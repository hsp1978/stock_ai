"""리서치 도구의 데이터 모델. 모두 불변(frozen)이다."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Holding(BaseModel):
    """운영자가 직접 입력한 보유 종목."""

    model_config = ConfigDict(frozen=True)

    ticker: str = Field(min_length=1, max_length=20)
    qty: float = Field(gt=0)
    avg_price: float = Field(gt=0)
    stop_price: Optional[float] = Field(default=None, gt=0)
    target_price: Optional[float] = Field(default=None, gt=0)
    note: str = Field(default="", max_length=200)

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


#: 각 데이터 조각의 상태. 'ok' 가 아닌 것은 화면·브리핑에 사유와 함께 나온다.
PartStatus = Literal["ok", "unavailable", "not_applicable"]


class Disclosure(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: str
    title: str
    kind: str = ""
    url: str


class BriefingItem(BaseModel):
    """종목 1개의 점검 결과. 판단(매수·매도)은 담지 않는다 — 사실과 거리만."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    market: Literal["KRX", "NYSE"]
    is_holding: bool

    # 가격 — 마지막 '완결된' 거래일 기준. 장중이면 bar_state 가 그렇다고 말한다.
    close: Optional[float] = None
    prev_close: Optional[float] = None
    change_pct: Optional[float] = None
    bar_date: Optional[str] = None
    bar_state: str = "unknown"
    bar_note: str = ""  # 장중 등 상태 안내 — '볼 것'(flags)이 아니다
    volume_ratio: Optional[float] = None  # 완결 봉에서만 계산 (장중 봉은 과소)
    price_check: str = "unknown"  # verify_latest_close 상태
    price_check_detail: str = ""

    # 보유 — 직접 입력값 기준
    qty: Optional[float] = None
    avg_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    to_stop_pct: Optional[float] = None    # 현재가 → 손절가 (음수 = 아래로)
    to_target_pct: Optional[float] = None  # 현재가 → 목표가

    days_to_earnings: Optional[float] = None
    earnings_status: PartStatus = "unavailable"
    earnings_note: str = ""  # 'unavailable' 사유 — 예: 소스가 한국 종목 실적일을 주지 않음

    disclosures: tuple[Disclosure, ...] = ()
    disclosure_status: PartStatus = "not_applicable"

    flags: tuple[str, ...] = ()        # 사람이 먼저 볼 것 (임계 기반, 판단 아님)
    errors: tuple[str, ...] = ()       # 수집 실패 사유 — 숨기지 않는다


class Briefing(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: str
    items: tuple[BriefingItem, ...]
