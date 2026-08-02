# Lightweight page-routing worker. Page classification only needs printed
# anchor phrases and OpenCV form geometry, so it deliberately excludes
# PaddleOCR/PaddlePaddle and their multi-gigabyte runtime footprint.
FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY packages ./packages
COPY apps ./apps
COPY workers ./workers
COPY config ./config

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 1000 appuser
USER appuser

ENTRYPOINT []
