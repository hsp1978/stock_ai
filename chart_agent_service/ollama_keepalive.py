"""Ollama 모델 유지 시간 — 헬스 프로브가 모델을 붙잡지 않게.

Ollama 는 요청마다 그 모델의 언로드 시각을 '지금 + keep_alive'로 **다시 잡는다**.
keep_alive 를 빼면 서버 기본값(5분)이 적용된다. 헬스 프로브는 15초마다 적재된 모델에
1토큰 생성을 보내므로, 그대로 두면 모델이 영영 내려가지 않는다 — 2026-10-08 실측:
RTX 의 qwen3:14b 언로드 시각이 15초마다 5분 뒤로 밀렸고, 아무도 쓰지 않아도 VRAM
10 GB 를 계속 점유했다.

프로브는 **남아 있던 유지 시간 그대로**를 keep_alive 로 보낸다. 연장도 단축도 하지 않는다.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional


def remaining_keep_alive(expires_at: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    """`/api/ps` 의 expires_at → 남은 시간 'Ns'. 모르면 None (호출자가 프로브를 건너뛴다).

    expires_at 은 서버 시간대로 온다 (예: '2026-10-08T14:07:29.4+09:00') — aware 로 비교한다.
    이미 지났으면 '1s' — 곧 내려갈 모델을 붙잡지 않는다.
    """
    if not expires_at:
        return None
    try:
        # Ollama 는 나노초(9자리)까지 준다 — fromisoformat 은 마이크로초까지만 받는다.
        # 소수부 숫자만 6자리로 자르고 시간대(+09:00)는 그대로 둔다.
        expires_at = re.sub(r"(\.\d{1,6})\d*", r"\1", expires_at, count=1)
        exp = datetime.fromisoformat(expires_at)
    except ValueError:
        return None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    left = (exp - (now or datetime.now(timezone.utc))).total_seconds()
    return f"{max(1, int(left))}s"
