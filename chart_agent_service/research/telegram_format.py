"""브리핑 → 텔레그램 HTML. 판단 문구(매수·매도·관망)는 쓰지 않는다."""

from __future__ import annotations

from html import escape

from research.models import Briefing, BriefingItem

#: 텔레그램 메시지 한도 4096자 — 넘치면 잘라내고 잘랐다고 적는다.
_MAX_CHARS = 3900


def _price(v: float | None, item: BriefingItem) -> str:
    if v is None:
        return "—"
    return f"₩{v:,.0f}" if item.market == "KRX" else f"${v:,.2f}"


def _line(item: BriefingItem) -> str:
    head = f"<b>{escape(item.ticker)}</b> {_price(item.close, item)}"
    if item.change_pct is not None:
        head += f" ({item.change_pct:+.2f}%)"
    if item.is_holding and item.pnl_pct is not None:
        head += f" · 손익 {item.pnl_pct:+.1f}%"
    lines = [head]
    for flag in item.flags:
        lines.append(f"  • {escape(flag)}")
    for d in item.disclosures[:3]:
        lines.append(f'  📄 <a href="{escape(d.url)}">{escape(d.title)}</a>')
    if item.errors:
        lines.append(f"  ⚠️ 수집 실패 {len(item.errors)}건: {escape(item.errors[0])}")
    return "\n".join(lines)


def format_briefing(b: Briefing, date_label: str) -> str:
    holdings = [i for i in b.items if i.is_holding]
    # 관심 종목은 볼 거리가 있을 때만 — 매일 같은 줄이 쌓이면 아무도 안 읽는다
    watch = [i for i in b.items if not i.is_holding and (i.flags or i.errors)]
    quiet = sum(1 for i in b.items if not i.is_holding and not (i.flags or i.errors))

    parts = [f"📋 <b>일일 브리핑</b> — {escape(date_label)}"]
    parts.append("<b>보유 종목</b>" if holdings else "<b>보유 종목</b> 없음 (직접 입력 전)")
    parts += [_line(i) for i in holdings]
    if watch:
        parts.append("<b>관심 종목 — 볼 것</b>")
        parts += [_line(i) for i in watch]
    if quiet:
        parts.append(f"관심 종목 {quiet}개는 특이사항 없음")
    parts.append("<i>사실·거리만 표시합니다. 매수·매도 판단이 아닙니다.</i>")

    text = "\n\n".join(parts)
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "\n\n…(길이 제한으로 잘림 — 화면에서 전체 확인)"
    return text
