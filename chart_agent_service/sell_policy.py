"""매도 신호를 행동으로 쓸지 — 단일 판정 지점.

`SELL_SIGNAL_MODE=advisory`(기본)에서는 매도 판정·기록은 그대로 두고, 청산·냉각기를
걸지 않으며 표시를 '리스크 경고(참고용)'로 바꾼다. 근거는 config.SELL_SIGNAL_MODE 주석.
"""

from __future__ import annotations

from config import SELL_SIGNAL_MODE

#: 알림·리포트에 붙이는 한 줄 설명.
ADVISORY_NOTE = "매도 신호는 검증된 우위가 없어 참고용 — 청산 신호 아님"


def sell_is_actionable() -> bool:
    """매도 신호로 청산·냉각기 같은 행동을 해도 되는가."""
    return SELL_SIGNAL_MODE == "actionable"


def sell_label() -> str:
    """사람이 읽는 매도 신호 이름."""
    return "매도" if sell_is_actionable() else "리스크 경고(매도·참고용)"


def sell_icon() -> str:
    return "🔴" if sell_is_actionable() else "⚠️"
