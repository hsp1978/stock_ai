"""
AI 분석 모듈
- OpenAI GPT-4o: 멀티모달 차트 분석
- Ollama 로컬 LLM: 텍스트 기반 분석
- 하이브리드 전략 지원
"""
import json
import base64
import os
from typing import Optional
import httpx
from config.settings import OPENAI_API_KEY, OLLAMA_BASE_URL, OLLAMA_MODEL


class AIAnalyzer:
    """AI 기반 주식 분석 엔진"""

    def __init__(self):
        self.openai_available = bool(OPENAI_API_KEY)
        self.ollama_available = self._check_ollama()

    def _check_ollama(self) -> bool:
        """Ollama 서버 가용성 체크"""
        try:
            resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    # ── GPT-4o 멀티모달 분석 ─────────────────────────────────

    def analyze_with_gpt4o(
        self,
        ticker: str,
        indicators_summary: dict,
        fundamentals: dict,
        risk_report: dict,
        chart_image_path: Optional[str] = None,
        macro_data: Optional[dict] = None,
        options_data: Optional[dict] = None,
    ) -> str:
        """GPT-4o를 사용한 종합 분석"""
        if not self.openai_available:
            return "[오류] OPENAI_API_KEY가 설정되지 않음."

        messages = [{"role": "system", "content": self._build_system_prompt()}]

        # 텍스트 데이터 구성
        user_content = []
        user_content.append({
            "type": "text",
            "text": self._build_analysis_prompt(
                ticker, indicators_summary, fundamentals,
                risk_report, macro_data, options_data
            )
        })

        # 차트 이미지 첨부 (멀티모달)
        if chart_image_path and os.path.exists(chart_image_path):
            with open(chart_image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img_b64}",
                    "detail": "high"
                }
            })
            user_content[0]["text"] += (
                "\n\n[첨부된 차트 이미지를 분석에 활용하라. "
                "차트에서 지지/저항선, 패턴(헤드앤숄더, 더블바텀 등), "
                "추세의 시각적 강도를 파악하라.]"
            )

        messages.append({"role": "user", "content": user_content})

        # API 호출
        try:
            resp = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o",
                    "messages": messages,
                    "max_tokens": 4096,
                    "temperature": 0.3,
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[GPT-4o 분석 오류] {e}"

    # ── Ollama 로컬 LLM 분석 ─────────────────────────────────

    def analyze_with_ollama(
        self,
        ticker: str,
        indicators_summary: dict,
        fundamentals: dict,
        risk_report: dict,
        macro_data: Optional[dict] = None,
        options_data: Optional[dict] = None,
    ) -> str:
        """Ollama 로컬 LLM을 사용한 텍스트 기반 분석"""
        if not self.ollama_available:
            return "[오류] Ollama 서버에 연결할 수 없음."

        prompt = (
            self._build_system_prompt() + "\n\n"
            + self._build_analysis_prompt(
                ticker, indicators_summary, fundamentals,
                risk_report, macro_data, options_data
            )
        )

        try:
            resp = httpx.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 4096},
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json().get("response", "[응답 없음]")
        except Exception as e:
            return f"[Ollama 분석 오류] {e}"

    # ── 프롬프트 빌더 ────────────────────────────────────────

    @staticmethod
    def _build_system_prompt() -> str:
        return """당신은 미국 주식 시장 전문 분석가이다. 제공된 데이터를 기반으로 냉정하고 객관적인 분석을 수행한다.

분석 규칙:
1. 감정적 표현 금지. 수치와 근거에 기반한 분석만 수행.
2. 매수/매도/관망 중 하나의 의견을 반드시 제시하되, 신뢰도(1-10)를 부여.
3. 리스크 요인을 반드시 명시.
4. 차트 이미지가 제공된 경우, 시각적으로 확인 가능한 패턴과 지지/저항선을 식별.
5. 단기(1-5일), 중기(1-4주), 장기(1-6개월) 전망을 구분하여 제시.
6. 분석은 한국어로 작성.

출력 형식:
## 종합 판단
[매수/매도/관망] (신뢰도: X/10)

## 기술적 분석
[추세, 모멘텀, 변동성 분석]

## 펀더멘털 분석
[재무 건전성, 가치 평가]

## 리스크 관리
[손절/익절 가격, 포지션 크기 권고]

## 시장 환경
[거시경제 영향, 섹터 동향]

## 핵심 리스크 요인
[주의해야 할 리스크 목록]"""

    @staticmethod
    def _build_analysis_prompt(
        ticker: str,
        indicators: dict,
        fundamentals: dict,
        risk_report: dict,
        macro_data: Optional[dict] = None,
        options_data: Optional[dict] = None,
    ) -> str:
        sections = [f"# {ticker} 종합 분석 데이터\n"]

        sections.append("## 기술 지표 현황")
        sections.append(json.dumps(indicators, indent=2, ensure_ascii=False))

        sections.append("\n## 기업 펀더멘털")
        # None 값 필터링
        filtered_fund = {k: v for k, v in fundamentals.items() if v is not None}
        sections.append(json.dumps(filtered_fund, indent=2, ensure_ascii=False))

        sections.append("\n## 리스크 분석")
        sections.append(json.dumps(risk_report, indent=2, ensure_ascii=False))

        if macro_data:
            sections.append("\n## 거시경제 환경")
            sections.append(json.dumps(macro_data, indent=2, ensure_ascii=False))

        if options_data:
            sections.append("\n## 옵션 시장 데이터")
            sections.append(json.dumps(options_data, indent=2, ensure_ascii=False))

        sections.append(
            "\n위 데이터를 종합하여 분석하라. "
            "시스템 프롬프트의 출력 형식을 정확히 따르라."
        )

        return "\n".join(sections)
