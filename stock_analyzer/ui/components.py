"""페이지 공용 컴포넌트 — 차트 기본 레이아웃과 신호 표기.

`webui.py` 분해 (CLAUDE.md §6-10). 여러 페이지가 같은 차트 톤·신호 pill 을 쓰므로
페이지를 옮기기 전에 먼저 내보낸다. 색은 `ui/theme.py` 토큰과 같은 값을 쓴다.
"""

from __future__ import annotations


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
