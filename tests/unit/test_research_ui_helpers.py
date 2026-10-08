"""리서치 화면 보조 함수.

- 브리핑 표: 숫자와 '' 를 한 열에 섞으면 Arrow 직렬화가 실패했다 (2026-10-08, column 실적 D)
- 보유 저장: 422 본문을 사람이 읽을 사유로 바꾼다
"""

import os
import sys

import pandas as pd
import pyarrow as pa

_ANALYZER_DIR = os.path.join(os.path.dirname(__file__), "../../stock_analyzer")
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _ANALYZER_DIR)

from ui.pages.research_briefing import _num  # noqa: E402
from ui.pages.research_holdings import _reason  # noqa: E402


def test_cells_are_strings_so_arrow_accepts_mixed_missing():
    col = [_num(None, "{:.1f}"), _num(13.8, "{:.1f}"), _num(None)]
    assert col == ["", "13.8", ""]
    pa.Table.from_pandas(pd.DataFrame({"실적 D": col}))   # 예외 없음


def test_number_formats():
    assert _num(1234.5) == "1,234.50"
    assert _num(-4.812, "{:+.2f}") == "-4.81"


def test_422_reason_is_readable():
    body = {"detail": [{"type": "greater_than", "loc": ["body", "qty"], "msg": "x"},
                       {"type": "missing", "loc": ["body", "avg_price"], "msg": "Field required"}]}
    assert _reason(body) == "수량: 0보다 커야 합니다 · 평단가: Field required"


def test_non_422_reason_passthrough():
    assert _reason({"detail": "PLTR: 보유 목록에 없음"}) == "PLTR: 보유 목록에 없음"
    assert _reason("연결 실패") == "연결 실패"
