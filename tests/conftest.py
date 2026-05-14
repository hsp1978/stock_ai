"""pytest 공통 설정 — chart_agent_service를 sys.path에 추가."""
import sys
import os

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "..", "chart_agent_service")
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)
