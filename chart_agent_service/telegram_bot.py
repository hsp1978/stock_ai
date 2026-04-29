"""
Telegram 알림 강화 모듈 (Sprint 3 · #6)

기존 단순 텍스트 알림을 풍부한 카드·요약·차트로 확장.
httpx 직접 호출(python-telegram-bot 미필요)로 경량 구현.

제공 기능:
- send_rich_signal_alert(): 진입 계획 + 과거 적중률 포함 카드
- send_daily_digest(): 당일 스캔 TOP N 요약
- send_error_alert(): 관리자 에러 알림
- inline_keyboard(): 인라인 버튼 생성 (공식 Bot API 스펙)
- get_pending_updates(): 사용자 버튼 콜백 폴링
"""
from __future__ import annotations

import json as _json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def _api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def _is_kr_ticker(ticker: str) -> bool:
    t = (ticker or "").upper()
    return t.endswith(".KS") or t.endswith(".KQ")


def _fmt_price(value: Optional[float], ticker: str) -> str:
    if value is None:
        return "—"
    if _is_kr_ticker(ticker):
        return f"₩{value:,.0f}"
    return f"${value:,.2f}"


def _escape_html(s: str) -> str:
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_telegram_html(text: str, reply_markup: Optional[Dict] = None) -> bool:
    """HTML 파싱 + 선택적 인라인 키보드."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        payload: Dict[str, Any] = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = _json.dumps(reply_markup)
        resp = httpx.post(_api_url("sendMessage"), json=payload, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def inline_keyboard(buttons: List[List[Dict]]) -> Dict:
    """
    인라인 키보드 빌더.
    buttons: [[{"text": "...", "callback_data": "..."} or {"text": "...", "url": "..."}]]
    """
    return {"inline_keyboard": buttons}


# ─────────────────────────────────────────────────────────
#  1) 풍부한 신호 알림 (진입 계획 + 과거 적중률)
# ─────────────────────────────────────────────────────────
def send_rich_signal_alert(
    ticker: str,
    final_decision: Dict,
    company_name: Optional[str] = None,
    accuracy_stats: Optional[Dict] = None,
    webui_base_url: Optional[str] = None,
) -> bool:
    """
    멀티에이전트 결과를 받아 풍부한 카드 알림을 발송.

    Args:
        ticker: 종목 티커
        final_decision: Decision Maker 출력 (entry_plan 포함 가정)
        company_name: 회사명 (없으면 ticker만 표시)
        accuracy_stats: get_accuracy_stats() 결과 (옵션)
        webui_base_url: deep link 용 WebUI 주소
    """
    signal = (final_decision.get("final_signal") or "neutral").upper()
    confidence = float(final_decision.get("final_confidence") or 0)
    raw_conf = final_decision.get("raw_confidence")
    consensus = final_decision.get("consensus", "")
    reasoning = final_decision.get("reasoning", "")
    risks = final_decision.get("key_risks") or []
    entry_plan = final_decision.get("entry_plan") or {}
    calibrated = final_decision.get("calibration_applied", False)

    icon = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}.get(signal, "⚪")
    sig_label = {"BUY": "매수", "SELL": "매도", "NEUTRAL": "관망"}.get(signal, signal)

    name_part = _escape_html(company_name) if company_name else ""
    header = f"{icon} <b>{_escape_html(ticker)}</b>"
    if name_part:
        header += f" ({name_part})"

    lines: List[str] = []
    lines.append(header)
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    # 신호 + 신뢰도
    conf_str = f"{confidence:.1f}/10"
    if calibrated and raw_conf is not None:
        conf_str = f"{confidence:.1f}/10 (보정 전 {raw_conf:.1f})"
    lines.append(f"📊 <b>신호</b>: {sig_label} (신뢰도 {conf_str})")

    # 진입 계획
    if signal == "BUY" and entry_plan and entry_plan.get("entry_timing") != "wait":
        order_type_kr = {"market": "시장가", "limit": "지정가", "wait": "대기"}.get(
            entry_plan.get("order_type"), entry_plan.get("order_type", "?")
        )
        timing_kr = {"immediate": "즉시", "pullback": "풀백 대기",
                     "breakout_confirm": "돌파 확인 후", "wait": "대기"}.get(
            entry_plan.get("entry_timing"), ""
        )
        lines.append(f"📋 <b>주문</b>: {order_type_kr} · {timing_kr}")
        if entry_plan.get("limit_price"):
            lines.append(f"💰 <b>진입가</b>: {_fmt_price(entry_plan['limit_price'], ticker)}")
        if entry_plan.get("stop_loss"):
            lines.append(f"🛑 <b>손절</b>: {_fmt_price(entry_plan['stop_loss'], ticker)}")
        if entry_plan.get("take_profit"):
            lines.append(f"🎯 <b>익절</b>: {_fmt_price(entry_plan['take_profit'], ticker)}")
        if entry_plan.get("expected_holding_days"):
            lines.append(f"⏱ <b>예상 보유</b>: {entry_plan['expected_holding_days']}일")

        # 분할 진입 요약 (1줄)
        splits = entry_plan.get("split_entry") or []
        if splits:
            parts = []
            for s in splits:
                if s.get("pct", 0) > 0 and s.get("price"):
                    parts.append(f"{s['pct']}% @ {_fmt_price(s['price'], ticker)}")
            if parts:
                lines.append(f"📊 <b>분할</b>: " + " → ".join(parts))
    elif entry_plan and entry_plan.get("entry_timing") == "wait":
        notes = entry_plan.get("notes") or []
        wait_reason = notes[0] if notes else "조건 미충족"
        lines.append(f"⏸ <b>진입 보류</b>: {_escape_html(wait_reason)}")

    # 의견 분포
    if consensus:
        lines.append(f"👥 <b>합의</b>: {_escape_html(consensus)[:80]}")

    # 판단 근거
    if reasoning:
        lines.append(f"\n💡 {_escape_html(reasoning)[:200]}")

    # 핵심 리스크
    if risks:
        lines.append("\n⚠️ <b>리스크</b>:")
        for r in risks[:3]:
            lines.append(f"  • {_escape_html(str(r))[:80]}")

    # 과거 적중률 (선택)
    if accuracy_stats and accuracy_stats.get("sample_size", 0) > 10:
        # 해당 신호 구간 통계 찾기
        by_sig = (accuracy_stats.get("by_signal") or {}).get(signal.lower(), {})
        if by_sig.get("total", 0) >= 10:
            lines.append(
                f"\n📈 <b>과거 적중률</b>: {by_sig['win_rate_pct']:.0f}% "
                f"(n={by_sig['total']}, 평균수익 {by_sig['avg_return_pct']:+.2f}%)"
            )

    lines.append(f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    text = "\n".join(lines)

    # 인라인 버튼
    buttons_row: List[Dict] = []
    if webui_base_url:
        buttons_row.append({
            "text": "📊 상세 보기",
            "url": f"{webui_base_url.rstrip('/')}?ticker={ticker}",
        })
    buttons_row.append({"text": "✅ 워치리스트", "callback_data": f"watch:{ticker}"})
    buttons_row.append({"text": "🚫 무시", "callback_data": f"mute:{ticker}"})

    markup = inline_keyboard([buttons_row]) if buttons_row else None
    return send_telegram_html(text, reply_markup=markup)


# ─────────────────────────────────────────────────────────
#  2) 일일 요약 (스캔 완료 후 TOP N)
# ─────────────────────────────────────────────────────────
def send_daily_digest(
    scan_results: List[Dict],
    top_n: int = 5,
    min_confidence: float = 6.0,
) -> bool:
    """
    스캔 완료 후 당일 TOP 신호 요약 발송.
    매일 장 마감 후 호출 권장.

    Args:
        scan_results: [{"ticker", "signal", "score", "confidence", "entry_plan"?}, ...]
        top_n: 상위 몇 개까지 표시
        min_confidence: 이 값 이상만 포함
    """
    if not scan_results:
        return False

    # 신뢰도 필터 + 신호별 분리 + 정렬
    filtered = [r for r in scan_results if (r.get("confidence") or 0) >= min_confidence]

    buy_list = [r for r in filtered if (r.get("signal") or "").lower() == "buy"]
    sell_list = [r for r in filtered if (r.get("signal") or "").lower() == "sell"]

    buy_list.sort(key=lambda x: (x.get("confidence", 0), x.get("score", 0)), reverse=True)
    sell_list.sort(key=lambda x: (x.get("confidence", 0), -x.get("score", 0)), reverse=True)

    lines: List[str] = []
    lines.append(f"📊 <b>일일 스캔 요약</b> — {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"전체 스캔: {len(scan_results)}개 · 신뢰도 {min_confidence:.1f}+ 필터: {len(filtered)}개")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    if buy_list:
        lines.append(f"🟢 <b>매수 상위 {min(top_n, len(buy_list))}</b>")
        for r in buy_list[:top_n]:
            ticker = _escape_html(r.get("ticker", "?"))
            conf = r.get("confidence", 0)
            score = r.get("score", 0)
            name = r.get("company_name") or ""
            entry = r.get("entry_plan") or {}
            price_str = ""
            if entry.get("limit_price"):
                price_str = f" @ {_fmt_price(entry['limit_price'], r.get('ticker', ''))}"
            name_str = f" {_escape_html(name)[:15]}" if name else ""
            lines.append(
                f"  • <b>{ticker}</b>{name_str} — 신뢰도 {conf:.1f}"
                f" (점수 {score:+.1f}){price_str}"
            )
    else:
        lines.append("🟢 매수 신호 없음 (필터 기준)")

    lines.append("")
    if sell_list:
        lines.append(f"🔴 <b>매도 상위 {min(top_n, len(sell_list))}</b>")
        for r in sell_list[:top_n]:
            ticker = _escape_html(r.get("ticker", "?"))
            conf = r.get("confidence", 0)
            score = r.get("score", 0)
            name = r.get("company_name") or ""
            name_str = f" {_escape_html(name)[:15]}" if name else ""
            lines.append(
                f"  • <b>{ticker}</b>{name_str} — 신뢰도 {conf:.1f} (점수 {score:+.1f})"
            )
    else:
        lines.append("🔴 매도 신호 없음 (필터 기준)")

    return send_telegram_html("\n".join(lines))


# ─────────────────────────────────────────────────────────
#  3) 관리자 에러 알림
# ─────────────────────────────────────────────────────────
def send_error_alert(title: str, detail: str, severity: str = "warning") -> bool:
    """
    시스템 에러/이상 상태를 관리자에게 알림.
    severity: "info" | "warning" | "error" | "critical"
    """
    icons = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "critical": "🚨"}
    icon = icons.get(severity, "ℹ️")

    text = (
        f"{icon} <b>{_escape_html(title)}</b>\n\n"
        f"{_escape_html(detail)[:800]}\n\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send_telegram_html(text)


# ─────────────────────────────────────────────────────────
#  4) 사용자 콜백 폴링 (인라인 버튼 처리)
# ─────────────────────────────────────────────────────────
def get_pending_updates(offset: Optional[int] = None, timeout: int = 0) -> List[Dict]:
    """
    getUpdates로 보류 중인 인라인 버튼 콜백 조회.
    webhook 미사용 환경에서 주기적 폴링용.

    Returns: [{"update_id", "callback_query": {"data", "from": {...}}}, ...]
    """
    if not TELEGRAM_BOT_TOKEN:
        return []
    try:
        params: Dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        resp = httpx.get(_api_url("getUpdates"), params=params, timeout=timeout + 5)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not data.get("ok"):
            return []
        return data.get("result", [])
    except Exception:
        return []


def answer_callback_query(callback_query_id: str, text: Optional[str] = None) -> bool:
    """콜백 쿼리에 응답 (버튼 누른 사용자에게 toast 표시)."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    try:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
            payload["show_alert"] = False
        resp = httpx.post(_api_url("answerCallbackQuery"), json=payload, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def process_callback_updates(handlers: Optional[Dict[str, Any]] = None) -> Dict:
    """
    보류 중인 콜백을 처리.

    handlers = {
      "watch": callable(ticker: str) -> str,  # watchlist 추가. 반환값은 사용자 토스트 메시지
      "mute": callable(ticker: str) -> str,
    }

    Returns: {"processed": int, "last_update_id": int}
    """
    handlers = handlers or {}
    updates = get_pending_updates()
    if not updates:
        return {"processed": 0, "last_update_id": None}

    processed = 0
    last_id = None
    for u in updates:
        last_id = u.get("update_id")
        cq = u.get("callback_query")
        if not cq:
            continue
        data = cq.get("data") or ""
        cq_id = cq.get("id")
        if ":" in data:
            action, ticker = data.split(":", 1)
            handler = handlers.get(action)
            if handler:
                try:
                    toast = handler(ticker) or f"{action} 처리 완료"
                except Exception:
                    toast = "처리 중 오류"
                answer_callback_query(cq_id, toast)
                processed += 1
            else:
                answer_callback_query(cq_id, "지원하지 않는 액션")

    # 확인된 update는 offset+1로 표시하여 제거
    if last_id is not None:
        try:
            httpx.get(_api_url("getUpdates"), params={"offset": last_id + 1}, timeout=5)
        except Exception:
            pass

    return {"processed": processed, "last_update_id": last_id}
