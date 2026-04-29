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
# webui는 chart_agent_service/config 도 import 하므로 양쪽 deps 모두 필요
COPY stock_analyzer/requirements.txt ./stock_analyzer/requirements.txt
COPY chart_agent_service/requirements.txt ./chart_agent_service/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r chart_agent_service/requirements.txt \
    && pip install -r stock_analyzer/requirements.txt

# ─── Runtime ──────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    NV_LIB=/opt/venv/lib/python3.12/site-packages/nvidia
# TF[and-cuda] cuDNN/cuda_runtime/cuBLAS 등 dlopen 경로 등록 (chart_agent_service Dockerfile 동일).
ENV LD_LIBRARY_PATH=${NV_LIB}/cublas/lib:${NV_LIB}/cuda_cupti/lib:${NV_LIB}/cuda_nvrtc/lib:${NV_LIB}/cuda_runtime/lib:${NV_LIB}/cudnn/lib:${NV_LIB}/cufft/lib:${NV_LIB}/curand/lib:${NV_LIB}/cusolver/lib:${NV_LIB}/cusparse/lib:${NV_LIB}/nccl/lib:${NV_LIB}/nvjitlink/lib

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
