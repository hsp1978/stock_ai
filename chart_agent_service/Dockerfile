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
COPY chart_agent_service/requirements.txt ./req-agent.txt
# stock_analyzer/multi_agent.py 가 동적 import 하는 의존성:
#   google-generativeai, openai, pykrx, finance-datareader, beautifulsoup4
# (streamlit/plotly 등 WebUI 전용 라이브러리는 제외하여 이미지 비대화 방지)
RUN pip install --upgrade pip \
    && pip install -r req-agent.txt \
    && pip install --no-cache-dir \
        'google-generativeai>=0.3.0' \
        'openai>=1.0.0' \
        'pykrx>=1.0.0' \
        'finance-datareader>=0.9.0' \
        'beautifulsoup4>=4.11.0' \
        'requests>=2.31.0' \
        'pytz>=2024.1'

# ─── Runtime ──────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    NV_LIB=/opt/venv/lib/python3.12/site-packages/nvidia
# TF[and-cuda]가 깔린 nvidia/* 패키지의 .so 들을 dlopen 가능하게 LD_LIBRARY_PATH 등록.
# 안 하면 pip 로 깔린 cuDNN/cuda_runtime/cuBLAS 등이 위치는 있으나 TF가 못 찾음.
ENV LD_LIBRARY_PATH=${NV_LIB}/cublas/lib:${NV_LIB}/cuda_cupti/lib:${NV_LIB}/cuda_nvrtc/lib:${NV_LIB}/cuda_runtime/lib:${NV_LIB}/cudnn/lib:${NV_LIB}/cufft/lib:${NV_LIB}/curand/lib:${NV_LIB}/cusolver/lib:${NV_LIB}/cusparse/lib:${NV_LIB}/nccl/lib:${NV_LIB}/nvjitlink/lib

# 런타임 필요 native libs:
# - libgomp1: lightgbm/xgboost OpenMP
# - curl/ca-certs: healthcheck + 외부 API
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY chart_agent_service/ ./chart_agent_service/
# multi_agent.py 및 그 동적 import 대상(dual_node_config, ml_pipeline_fix,
# enhanced_decision_maker, korean_stocks, ticker_*, signal_tracker 등)을
# 함께 포함시켜야 /multi-agent/{ticker} 가 503으로 떨어지지 않음.
COPY stock_analyzer/ ./stock_analyzer/

WORKDIR /app/chart_agent_service

RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

EXPOSE 8100

CMD ["python", "service.py"]
