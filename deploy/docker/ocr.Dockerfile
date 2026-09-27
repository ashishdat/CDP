# Worker image for page/field OCR consumers (standard_form_extraction,
# unstructured_extraction). Built off the `[ocr]` extras group only
# (paddleocr + paddlepaddle, CPU) -- not the full `[ml]` group.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2

# libglib2.0-0: required at import time by opencv-python-headless.
# libgomp1: required at import time by paddlepaddle (OpenMP runtime).
# libgl1/libsm6/libxext6: paddleocr/paddlex pull in full opencv-contrib.
# tesseract: cascade fill / digits engine.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    libgl1 \
    libsm6 \
    libxext6 \
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

RUN pip install --no-cache-dir ".[ocr]"

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app

USER appuser

STOPSIGNAL SIGTERM
ENTRYPOINT []

LABEL org.opencontainers.image.title="cdp-ocr" \
      org.opencontainers.image.description="CDP OCR Kafka workers (Paddle/Tesseract)"
