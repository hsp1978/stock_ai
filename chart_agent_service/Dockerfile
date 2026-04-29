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
COPY chart_agent_service/requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

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

WORKDIR /app/chart_agent_service

RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

EXPOSE 8100

CMD ["python", "service.py"]
