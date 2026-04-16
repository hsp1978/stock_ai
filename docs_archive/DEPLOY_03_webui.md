# webui.py 수정 (3곳)

경로: `stock_analyzer/webui.py`

---

## 수정 A: 상단 import (9~34행)

**기존:**
```python
import json
import os
from datetime import datetime

import httpx
import yfinance as yf
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import load_dotenv

load_dotenv()

AGENT_API_URL = os.getenv("AGENT_API_URL", "http://100.108.11.20:8100")
```

**변경:**
```python
import json
import os
import sys
from datetime import datetime

import httpx
import yfinance as yf
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import load_dotenv

load_dotenv()

# ── local_engine 연결 (직접 import 우선, HTTP fallback) ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from local_engine import (
        engine_dispatch_get, engine_dispatch_post, engine_get_chart_path,
    )
    _USE_LOCAL_ENGINE = True
except ImportError:
    _USE_LOCAL_ENGINE = False

AGENT_API_URL = os.getenv("AGENT_API_URL", "http://100.108.11.20:8100")
```

변경점: `import sys` 추가, local_engine import 블록 추가

---

## 수정 B: api_get / api_post / get_chart_url 함수

**기존:**
```python
def api_get(path: str, timeout: int = 10):
    try:
        resp = httpx.get(f"{AGENT_API_URL}{path}", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except Exception as e:
        st.error(f"API Error: {e}")
        return None


def api_post(path: str, timeout: int = 300):
    try:
        resp = httpx.post(f"{AGENT_API_URL}{path}", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except Exception as e:
        st.error(f"API Error: {e}")
        return None


def get_chart_url(ticker: str) -> str:
    return f"{AGENT_API_URL}/chart/{ticker}"
```

**변경:**
```python
def api_get(path: str, timeout: int = 10):
    if _USE_LOCAL_ENGINE:
        return engine_dispatch_get(path)
    try:
        resp = httpx.get(f"{AGENT_API_URL}{path}", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except Exception as e:
        st.error(f"API Error: {e}")
        return None


def api_post(path: str, timeout: int = 300):
    if _USE_LOCAL_ENGINE:
        return engine_dispatch_post(path)
    try:
        resp = httpx.post(f"{AGENT_API_URL}{path}", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        return None
    except Exception as e:
        st.error(f"API Error: {e}")
        return None


def get_chart_url(ticker: str) -> str:
    """local_engine 모드: 파일 경로 반환 / HTTP 모드: URL 반환"""
    if _USE_LOCAL_ENGINE:
        return engine_get_chart_path(ticker) or ""
    return f"{AGENT_API_URL}/chart/{ticker}"
```

변경점: 각 함수 상단에 `if _USE_LOCAL_ENGINE:` 분기 추가

---

## 수정 C: 차트 이미지 로딩 (render_detail 함수 내)

**기존:**
```python
    chart_url = get_chart_url(selected)
    try:
        resp = httpx.get(chart_url, timeout=5)
        if resp.status_code == 200:
            st.image(resp.content, use_container_width=True)
        else:
            st.caption("No chart image available")
    except Exception:
        st.caption("Chart load failed")
```

**변경:**
```python
    chart_ref = get_chart_url(selected)
    if _USE_LOCAL_ENGINE:
        if chart_ref and os.path.exists(chart_ref):
            st.image(chart_ref, use_container_width=True)
        else:
            st.caption("No chart image available")
    else:
        try:
            resp = httpx.get(chart_ref, timeout=5)
            if resp.status_code == 200:
                st.image(resp.content, use_container_width=True)
            else:
                st.caption("No chart image available")
        except Exception:
            st.caption("Chart load failed")
```

변경점: 로컬 파일 경로 / HTTP URL 분기 처리
