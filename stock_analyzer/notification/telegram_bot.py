"""
텔레그램 봇 모듈
- 분석 리포트를 텔레그램으로 전송
- 차트 이미지 첨부
- 텔레그램 명령어로 분석 요청 (봇 모드)
"""
import httpx
import os
from typing import Optional
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class TelegramBot:
    """텔레그램 알림 및 봇"""

    BASE_URL = "https://api.telegram.org/bot{token}"

    def __init__(self, token: str = "", chat_id: str = ""):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.api_url = self.BASE_URL.format(token=self.token)

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    # ── 메시지 전송 ──────────────────────────────────────────

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """텍스트 메시지 전송 (최대 4096자, 초과 시 분할)"""
        if not self.is_configured:
            print("  [경고] 텔레그램 미설정. TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 확인.")
            return False

        chunks = self._split_message(text, 4096)
        success = True
        for chunk in chunks:
            try:
                resp = httpx.post(
                    f"{self.api_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": chunk,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                )
                if resp.status_code != 200:
                    print(f"  [오류] 텔레그램 전송 실패: {resp.text}")
                    success = False
            except Exception as e:
                print(f"  [오류] 텔레그램 연결 실패: {e}")
                success = False
        return success

    def send_photo(self, photo_path: str, caption: str = "") -> bool:
        """이미지 전송 (차트)"""
        if not self.is_configured:
            return False

        if not os.path.exists(photo_path):
            print(f"  [경고] 이미지 파일 없음: {photo_path}")
            return False

        try:
            with open(photo_path, "rb") as f:
                resp = httpx.post(
                    f"{self.api_url}/sendPhoto",
                    data={
                        "chat_id": self.chat_id,
                        "caption": caption[:1024],  # 캡션 최대 1024자
                        "parse_mode": "HTML",
                    },
                    files={"photo": ("chart.png", f, "image/png")},
                    timeout=30,
                )
            if resp.status_code != 200:
                print(f"  [오류] 이미지 전송 실패: {resp.text}")
                return False
            return True
        except Exception as e:
            print(f"  [오류] 이미지 전송 실패: {e}")
            return False

    def send_document(self, file_path: str, caption: str = "") -> bool:
        """파일 전송 (JSON 리포트 등)"""
        if not self.is_configured:
            return False

        if not os.path.exists(file_path):
            return False

        try:
            filename = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                resp = httpx.post(
                    f"{self.api_url}/sendDocument",
                    data={
                        "chat_id": self.chat_id,
                        "caption": caption[:1024],
                        "parse_mode": "HTML",
                    },
                    files={"document": (filename, f)},
                    timeout=30,
                )
            return resp.status_code == 200
        except Exception as e:
            print(f"  [오류] 파일 전송 실패: {e}")
            return False

    # ── 리포트 포맷팅 ────────────────────────────────────────

    @staticmethod
    def format_report(
        ticker: str,
        indicators: dict,
        fundamentals: dict,
        risk_report: dict,
        options_data: Optional[dict] = None,
        macro_data: Optional[dict] = None,
        ai_result: Optional[str] = None,
    ) -> str:
        """분석 결과를 텔레그램 HTML 포맷으로 변환"""

        price = indicators.get("price", {})
        trend = indicators.get("trend", {})
        momentum = indicators.get("momentum", {})
        volatility = indicators.get("volatility", {})
        stops = risk_report.get("stops", {})
        position = risk_report.get("position", {})

        # 방향 이모지
        change = price.get("change_pct", 0)
        if change > 0:
            arrow = "🟢"
        elif change < 0:
            arrow = "🔴"
        else:
            arrow = "⚪"

        # RSI 상태
        rsi_val = momentum.get("RSI", 0)
        rsi_signal = momentum.get("RSI_signal", "neutral")
        if rsi_signal == "overbought":
            rsi_icon = "🔥"
        elif rsi_signal == "oversold":
            rsi_icon = "❄️"
        else:
            rsi_icon = "➖"

        # 추세 강도
        strength = trend.get("trend_strength", "N/A")
        strength_map = {
            "very_strong": "💪💪 매우 강함",
            "strong": "💪 강함",
            "weak": "〰️ 약함",
            "no_trend": "😐 추세 없음",
        }
        strength_text = strength_map.get(strength, strength)

        lines = []

        # ── 헤더 ─────────────────────────────────────────────
        company = fundamentals.get("company_name", ticker)
        lines.append(f"<b>📊 {company} ({ticker}) 분석 리포트</b>")
        lines.append("")

        # ── 가격 ─────────────────────────────────────────────
        lines.append(f"{arrow} <b>현재가:</b> ${price.get('close', 'N/A')} ({change:+.2f}%)")
        vol_ratio = price.get("volume_vs_avg", 1)
        vol_icon = "📈" if vol_ratio > 1.5 else "📉" if vol_ratio < 0.5 else "📊"
        lines.append(f"{vol_icon} <b>거래량:</b> {price.get('volume', 0):,} (평균 대비 {vol_ratio:.1f}배)")
        lines.append("")

        # ── 기술 지표 ────────────────────────────────────────
        lines.append("<b>━━ 기술 지표 ━━</b>")
        lines.append(f"{rsi_icon} RSI: {rsi_val:.1f} ({rsi_signal})")
        lines.append(f"📐 추세 강도: {strength_text}")

        # 이동평균 위치
        for p in [20, 50, 200]:
            key = f"price_vs_SMA_{p}"
            if key in trend:
                pos = "위 ✅" if trend[key] == "above" else "아래 ❌"
                lines.append(f"   SMA {p}: 가격 {pos}")

        # MACD
        macd_hist = trend.get("MACD_histogram", None)
        if macd_hist is not None:
            macd_icon = "🟢" if macd_hist > 0 else "🔴"
            lines.append(f"{macd_icon} MACD 히스토그램: {macd_hist:.4f}")

        # 볼린저
        bb_pos = volatility.get("BB_position", "N/A")
        bb_map = {"above_upper": "상단 돌파 ⚠️", "below_lower": "하단 돌파 ⚠️", "inside": "밴드 내 ✅"}
        lines.append(f"📏 볼린저 밴드: {bb_map.get(bb_pos, bb_pos)}")
        lines.append(f"📊 ATR: ${volatility.get('ATR', 'N/A')} ({volatility.get('ATR_pct', 'N/A')}%)")
        lines.append("")

        # ── 리스크 관리 ──────────────────────────────────────
        lines.append("<b>━━ 리스크 관리 ━━</b>")
        lines.append(f"🛑 손절가: ${stops.get('stop_loss', 'N/A')} (-{stops.get('stop_distance_pct', 'N/A')}%)")
        lines.append(f"🎯 익절가: ${stops.get('take_profit', 'N/A')} (+{stops.get('target_distance_pct', 'N/A')}%)")
        lines.append(f"⚖️ R:R 비율: {stops.get('risk_reward_ratio', 'N/A')}")
        lines.append(f"📦 권장 수량: {position.get('shares', 0)}주 (${position.get('position_value', 0):,.2f})")
        lines.append(f"💰 포지션 비중: {position.get('position_pct', 0)}%")
        lines.append(f"⚠️ 리스크 금액: ${position.get('risk_amount', 0):,.2f} ({position.get('risk_pct', 0)}%)")

        # 경고
        warnings = risk_report.get("warnings", [])
        if warnings:
            lines.append("")
            for w in warnings:
                lines.append(f"🚨 {w}")
        lines.append("")

        # ── 옵션 시장 ────────────────────────────────────────
        if options_data:
            lines.append("<b>━━ 옵션 시장 ━━</b>")
            pc_vol = options_data.get("put_call_ratio_volume")
            if pc_vol is not None:
                pc_icon = "🐻" if pc_vol > 1.0 else "🐂" if pc_vol < 0.7 else "➖"
                lines.append(f"{pc_icon} P/C Ratio (거래량): {pc_vol:.2f}")
            pc_oi = options_data.get("put_call_ratio_oi")
            if pc_oi is not None:
                lines.append(f"   P/C Ratio (미결제): {pc_oi:.2f}")
            iv = options_data.get("atm_implied_volatility")
            if iv is not None:
                lines.append(f"📈 내재변동성(IV): {iv:.1%}")
            lines.append("")

        # ── 거시경제 ─────────────────────────────────────────
        if macro_data:
            lines.append("<b>━━ 거시경제 ━━</b>")
            if "fed_funds_rate" in macro_data:
                lines.append(f"🏦 기준금리: {macro_data['fed_funds_rate']['value']}%")
            if "treasury_10y" in macro_data:
                lines.append(f"📄 10Y 국채: {macro_data['treasury_10y']['value']}%")
            if "yield_spread_10y_2y" in macro_data:
                spread = macro_data["yield_spread_10y_2y"]["value"]
                spread_icon = "🟢" if spread > 0 else "🔴"
                lines.append(f"{spread_icon} 장단기 스프레드: {spread}%")
            if "vix" in macro_data:
                vix = macro_data["vix"]["value"]
                vix_icon = "😱" if vix > 30 else "😰" if vix > 20 else "😌"
                lines.append(f"{vix_icon} VIX: {vix}")
            lines.append("")

        # ── 펀더멘털 요약 ────────────────────────────────────
        pe = fundamentals.get("pe_trailing")
        roe = fundamentals.get("roe")
        margin = fundamentals.get("profit_margin")
        if any([pe, roe, margin]):
            lines.append("<b>━━ 펀더멘털 ━━</b>")
            if pe:
                lines.append(f"💵 P/E: {pe:.1f}")
            fwd_pe = fundamentals.get("pe_forward")
            if fwd_pe:
                lines.append(f"   Forward P/E: {fwd_pe:.1f}")
            if roe:
                lines.append(f"📊 ROE: {roe:.1%}")
            if margin:
                lines.append(f"📊 순이익률: {margin:.1%}")
            de = fundamentals.get("debt_to_equity")
            if de:
                lines.append(f"📊 부채비율: {de:.1f}%")
            lines.append("")

        # ── AI 분석 ──────────────────────────────────────────
        if ai_result:
            lines.append("<b>━━ AI 분석 결과 ━━</b>")
            # HTML 태그 충돌 방지
            safe_ai = ai_result.replace("<", "&lt;").replace(">", "&gt;")
            # 마크다운 ## 헤더를 볼드로 변환
            for line in safe_ai.split("\n"):
                stripped = line.strip()
                if stripped.startswith("## "):
                    lines.append(f"\n<b>{stripped[3:]}</b>")
                elif stripped.startswith("- "):
                    lines.append(f"  • {stripped[2:]}")
                elif stripped:
                    lines.append(stripped)

        return "\n".join(lines)

    # ── 전체 리포트 전송 ─────────────────────────────────────

    def send_full_report(
        self,
        ticker: str,
        indicators: dict,
        fundamentals: dict,
        risk_report: dict,
        chart_path: Optional[str] = None,
        options_data: Optional[dict] = None,
        macro_data: Optional[dict] = None,
        ai_result: Optional[str] = None,
        json_path: Optional[str] = None,
    ) -> bool:
        """전체 분석 리포트를 텔레그램으로 전송"""
        if not self.is_configured:
            print("  [경고] 텔레그램 미설정. 전송 건너뜀.")
            return False

        success = True

        # 1) 차트 이미지 전송
        if chart_path and os.path.exists(chart_path):
            caption = f"📊 {ticker} 기술 분석 차트"
            if not self.send_photo(chart_path, caption):
                success = False

        # 2) 텍스트 리포트 전송
        report_text = self.format_report(
            ticker, indicators, fundamentals, risk_report,
            options_data, macro_data, ai_result
        )
        if not self.send_message(report_text):
            success = False

        # 3) JSON 리포트 파일 전송 (선택)
        if json_path and os.path.exists(json_path):
            self.send_document(json_path, f"{ticker} 상세 데이터")

        return success

    # ── 유틸리티 ─────────────────────────────────────────────

    @staticmethod
    def _split_message(text: str, max_len: int = 4096) -> list:
        """긴 메시지를 분할 (HTML 태그 깨지지 않도록 줄 단위)"""
        if len(text) <= max_len:
            return [text]

        chunks = []
        current = ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > max_len:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line
        if current:
            chunks.append(current)
        return chunks

    def get_updates(self, offset: int = 0) -> list:
        """봇에 수신된 메시지 확인 (명령어 봇 모드용)"""
        try:
            resp = httpx.get(
                f"{self.api_url}/getUpdates",
                params={"offset": offset, "timeout": 1},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("result", [])
        except Exception:
            pass
        return []

    def get_chat_id_from_updates(self) -> Optional[str]:
        """최근 메시지에서 chat_id 추출 (초기 설정용)"""
        updates = self.get_updates()
        if updates:
            last = updates[-1]
            msg = last.get("message", {})
            chat = msg.get("chat", {})
            return str(chat.get("id", ""))
        return None
