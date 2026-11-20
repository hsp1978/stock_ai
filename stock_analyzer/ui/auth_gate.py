"""Password gate for the Streamlit web UI.

The UI is reachable from the tailnet, so it must not be open without a credential.
The password lives only in `.env` (`WEBUI_PASSWORD`). The gate fails closed: when the
variable is unset, the UI refuses to render instead of falling back to open access.
"""

from __future__ import annotations

import hmac
import os

import streamlit as st

from app_logging import get_logger

logger = get_logger("stock_auto.ui.auth_gate")

_SESSION_KEY = "_webui_auth_ok"


def require_password() -> None:
    """Stop the script run unless this session has entered the correct password."""
    expected = os.environ.get("WEBUI_PASSWORD", "")
    if not expected:
        logger.error("WEBUI_PASSWORD is not set; refusing to render the UI")
        st.error("접근 차단: WEBUI_PASSWORD 가 설정되지 않았습니다 (.env).")
        st.stop()

    if st.session_state.get(_SESSION_KEY):
        return

    entered = st.text_input("비밀번호", type="password", key="_webui_pw")
    if entered:
        if hmac.compare_digest(entered.encode("utf-8"), expected.encode("utf-8")):
            st.session_state[_SESSION_KEY] = True
            st.session_state.pop("_webui_pw", None)
            st.rerun()
        logger.warning("webui login failed")
        st.error("비밀번호가 올바르지 않습니다.")
    st.stop()
