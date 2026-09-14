"""페이지 공용 컴포넌트 — 차트 기본 레이아웃과 신호 표기.

`webui.py` 분해 (CLAUDE.md §6-10). 여러 페이지가 같은 차트 톤·신호 pill 을 쓰므로
페이지를 옮기기 전에 먼저 내보낸다. 색은 `ui/theme.py` 토큰과 같은 값을 쓴다.
"""

from __future__ import annotations

import re

from ui.tickers import _is_korean_ticker, get_ticker_display_name


def _plotly_base_layout(**overrides) -> dict:
    base = dict(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#06080C",
        font=dict(family="JetBrains Mono, monospace", color="#9BA6B5", size=12),
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(gridcolor="#161C25", zerolinecolor="#161C25"),
        yaxis=dict(gridcolor="#161C25", zerolinecolor="#161C25"),
    )
    base.update(overrides)
    return base


def _signal_pill_html(signal: str) -> str:
    s = signal.upper()
    cls = "buy" if s == "BUY" else ("sell" if s == "SELL" else "hold")
    return f'<span class="signal-pill {cls}"><span class="sp-dot"></span>{s}</span>'


# ═══════════════════════════════════════════════════════════════
#  사이드바
# ═══════════════════════════════════════════════════════════════


def _quant_signal_style(signal: str) -> str:
    s = (signal or "").lower()
    if s == "buy":
        return "buy"
    if s == "sell":
        return "sell"
    return "hold"


def _css_key(symbol: str) -> str:
    """Streamlit 위젯 key는 `.st-key-<key>` 클래스가 되므로 CSS-safe하게 만든다.

    `^GSPC`, `USDKRW=X`처럼 `^`·`=`가 든 심볼을 그대로 쓰면 선택자가 깨진다.
    """
    return re.sub(r"[^A-Za-z0-9_-]", "_", symbol)


def ticker_chip_html(ticker: str) -> str:
    """TickerChip (DS §05) — 티커 우선 + 시장 배지. 회사 명칭은 툴팁.

    명칭을 칩 본문에 넣으면 폭이 들쭉날쭉해져 목록을 훑는 속도가 떨어진다.
    """
    is_kr = _is_korean_ticker(ticker)
    badge = "KR" if is_kr else "US"
    name = get_ticker_display_name(ticker) or ticker
    title = name if name != ticker else ticker
    return (
        f'<span class="wl-chip" title="{title}">'
        f'<span class="tc-badge {"kr" if is_kr else "us"}">{badge}</span>{ticker}</span>'
    )
