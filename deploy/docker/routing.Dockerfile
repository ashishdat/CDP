# Lightweight page-routing worker. Page classification only needs printed
# anchor phrases and OpenCV form geometry, so it deliberately excludes
# PaddleOCR/PaddlePaddle and their multi-gigabyte runtime footprint.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    tesseract-ocr \
    tesseract-ocr-eng \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY packages ./packages
COPY apps ./apps
COPY workers ./workers
COPY config ./config
COPY scripts ./scripts
COPY deploy/mysql ./deploy/mysql
COPY docs/gt ./docs/gt

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app

USER appuser

STOPSIGNAL SIGTERM
ENTRYPOINT []

LABEL org.opencontainers.image.title="cdp-routing" \
      org.opencontainers.image.description="CDP page-detection Kafka worker"
