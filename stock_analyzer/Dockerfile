# ─── Builder ──────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libgomp1 libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /build
# webui는 chart_agent_service/config 등 모듈 import 하므로 양쪽 deps 필요.
# 단, tensorflow[and-cuda] 는 webui 에서 protobuf 충돌(streamlit protobuf 5 vs
# TF gencode 6)로 import 자체 실패. + nvidia/* (~4.1GB). 양쪽 모두 webui 에선
# 무용지물이므로 빌드 시 제외. ml_predictor.run_ml_prediction 의 LSTM 학습은
# try/except 로 graceful skip → RF/GB/LightGBM/XGBoost 4모델 앙상블 그대로.
# GPU/LSTM 활용은 agent-api 의 /ml/{ticker} 엔드포인트로 일원화.
COPY stock_analyzer/requirements.txt ./stock_analyzer/requirements.txt
COPY chart_agent_service/requirements.txt ./chart_agent_service/requirements.txt
RUN sed '/^tensorflow/d' chart_agent_service/requirements.txt > /tmp/req-base.txt \
    && pip install --upgrade pip \
    && pip install -r /tmp/req-base.txt \
    && pip install -r stock_analyzer/requirements.txt

# ─── Runtime ──────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
# webui 는 TF 미설치 (protobuf 충돌로 어차피 import 불가했음).
# nvidia/* 패키지가 없으므로 LD_LIBRARY_PATH 도 미설정. agent-api Dockerfile 만 등록.

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY chart_agent_service/ ./chart_agent_service/
COPY stock_analyzer/ ./stock_analyzer/

WORKDIR /app/stock_analyzer

RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

EXPOSE 8501

CMD ["streamlit", "run", "webui.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
