"""한국장 도구 모듈의 선택적 import — 없으면 홈 패널만 비활성화된다.

`webui.py` 에 있던 try/except 블록을 옮긴 것이다. 소비자가 홈 페이지 하나뿐이라
페이지 모듈에 그대로 복사할 수도 있었지만, 그러면 '왜 비활성인지'가 화면 코드에
섞인다. 여기서는 **실패 사유를 버리지 않는다** (CLAUDE.md §13-1): 종전 코드는
`print("[WARNING] ...")` 로 ImportError 를 삼켜서, 모듈이 없는 것인지 모듈 안에서
깨진 것인지 구분할 수 없었다.

`ticker_manager` 를 게이트에 함께 둔 것은 의도다 — 종전 동작과 같게 유지한다.
둘 중 하나만 있어도 패널이 반쯤 동작하는 상태를 만들지 않는다.
"""

from __future__ import annotations

KOREAN_STOCKS_AVAILABLE: bool
KOREAN_STOCKS_UNAVAILABLE_REASON: str | None = None

try:
    from korean_stocks import KoreanStockData, get_market_indices as get_kr_indices
    from ticker_manager import (  # noqa: F401  게이트 유지용 (종전 동작과 동일)
        TickerManager,
        detect_market,
        format_price,
        get_stock_info,
        normalize_ticker,
    )

    KOREAN_STOCKS_AVAILABLE = True
except ImportError as exc:  # 사유를 남긴다 — '없음'과 '깨짐'은 다르다
    KoreanStockData = None  # type: ignore[assignment]
    get_kr_indices = None  # type: ignore[assignment]
    KOREAN_STOCKS_AVAILABLE = False
    KOREAN_STOCKS_UNAVAILABLE_REASON = f"{type(exc).__name__}: {exc}"
