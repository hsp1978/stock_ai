"""
토스증권 Open API OAuth2 토큰 매니저.

토스 Open API는 OAuth2 Client Credentials Grant로 access token을 발급받아
`Authorization: Bearer {token}` 헤더로 모든 호출에 사용한다.
Alpaca(정적 키 헤더)와 달리 토큰에 만료가 있으므로 발급/캐시/갱신을 전담.

브로커(`toss_broker.py`)와 데이터소스(`toss_source.py`)가 동일 매니저를 공유한다.

자격증명/토큰은 절대 로그·예외 메시지에 평문 노출하지 않는다 (CLAUDE.md Critical Don'ts #2).
"""
from __future__ import annotations

import base64
import os
import threading
import time
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


# 토큰 발급 엔드포인트 — 표준 OAuth2 (RFC6749). /api/v1/* 게이트웨이 외부 경로.
_TOKEN_PATH = "/oauth2/token"
# 만료 N초 전에 미리 갱신 (clock skew / 호출 지연 흡수)
_REFRESH_MARGIN_SECONDS = 60
# 명세상 TTL 미제공 시 보수적 기본값 (초)
_DEFAULT_TTL_SECONDS = 1800


def mask_secret(value: Optional[str]) -> str:
    """시크릿 마스킹 — 디버깅 출력용. 앞 4자리만 남기고 가린다."""
    if not value:
        return "<unset>"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 4)}"


class TossAuthError(RuntimeError):
    """토큰 발급/갱신 실패 (메시지에 시크릿 미포함)."""


class TossTokenManager:
    """
    토스 Open API access token 발급·캐시·갱신 매니저 (thread-safe).

    - `get_token()` : 유효 토큰 문자열 반환 (필요 시 자동 발급/갱신).
    - `auth_header()`: `{"Authorization": "Bearer ..."}` 반환.
    - `invalidate()` : 401 수신 시 캐시 무효화 (다음 호출에서 강제 재발급).
    """

    def __init__(self,
                 app_key: Optional[str] = None,
                 app_secret: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: float = 10.0):
        self.app_key = app_key if app_key is not None else os.getenv("TOSS_APP_KEY", "")
        self.app_secret = (
            app_secret if app_secret is not None else os.getenv("TOSS_APP_SECRET", "")
        )
        self.base_url = (base_url or os.getenv(
            "TOSS_BASE_URL", "https://openapi.tossinvest.com"
        )).rstrip("/")
        self.timeout = timeout

        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._expires_at: float = 0.0  # epoch seconds

    # ─── 공개 API ──────────────────────────────────────
    def credentials_present(self) -> bool:
        return bool(self.app_key and self.app_secret)

    def get_token(self) -> str:
        """유효 토큰 반환. 만료(또는 임박)면 발급/갱신. 실패 시 TossAuthError."""
        if not self.credentials_present():
            raise TossAuthError("토스 자격증명 미설정 (TOSS_APP_KEY / TOSS_APP_SECRET)")

        with self._lock:
            if self._token and time.time() < (self._expires_at - _REFRESH_MARGIN_SECONDS):
                return self._token
            self._token, self._expires_at = self._issue_token()
            return self._token

    def auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_token()}"}

    def invalidate(self) -> None:
        """401 등 인증 실패 시 호출 — 캐시 비우고 다음 호출에서 재발급."""
        with self._lock:
            self._token = None
            self._expires_at = 0.0

    # ─── 내부 ──────────────────────────────────────────
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=5),
           reraise=True)
    def _issue_token(self) -> tuple[str, float]:
        """
        Client Credentials Grant로 토큰 발급 (표준 OAuth2).

        - 엔드포인트: POST /oauth2/token
        - 자격증명: HTTP Basic Auth 헤더 (client_id:client_secret base64)
        - 본문: application/x-www-form-urlencoded, grant_type=client_credentials

        반환: (access_token, expires_at_epoch).
        실패 시 TossAuthError (시크릿 미포함 메시지).
        """
        basic = base64.b64encode(
            f"{self.app_key}:{self.app_secret}".encode()
        ).decode()
        try:
            resp = httpx.post(
                f"{self.base_url}{_TOKEN_PATH}",
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            # 예외 문자열에 시크릿이 섞이지 않도록 타입명만 노출
            raise TossAuthError(f"토큰 발급 네트워크 오류: {type(e).__name__}") from None

        if resp.status_code != 200:
            raise TossAuthError(
                f"토큰 발급 실패 [{resp.status_code}] (key={mask_secret(self.app_key)})"
            )

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise TossAuthError("토큰 발급 응답에 access_token 없음")
        ttl = int(data.get("expires_in", _DEFAULT_TTL_SECONDS) or _DEFAULT_TTL_SECONDS)
        return token, time.time() + ttl
