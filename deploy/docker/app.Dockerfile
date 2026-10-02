# Shared application image for apps/* and workers/* (Phase 1-3 CPU-only
# services). GPU/ML-heavy services (LayoutLMv3, VLM) get their own image
# in later phases (see docs/IMPLEMENTATION_PLAN.md Phase 4) built off the
# `[ml]` extras group instead of this one.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# libglib2.0-0: required at import time by opencv-python-headless on slim
# Debian images even though it doesn't need a display.
# curl: optional health/debug in ops shells (APIs use python urllib healthchecks).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY packages ./packages
COPY apps ./apps
COPY workers ./workers
COPY config ./config
COPY scripts ./scripts
# MySQL migrations (scripts/apply_mysql_migrations.py) + shared agent GT
COPY deploy/mysql ./deploy/mysql
COPY docs/gt ./docs/gt

RUN pip install --no-cache-dir .

# Non-root runtime user
RUN useradd --create-home --uid 1000 appuser

# /data holds append-only local sinks (OCR call audit log, correction
# memory) written by workers/apps at runtime; must be writable by appuser.
RUN mkdir -p /data && chown -R appuser:appuser /data /app

USER appuser

EXPOSE 8000 8001 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

STOPSIGNAL SIGTERM
ENTRYPOINT []

# Default: ingestion API. Compose/Helm override command for other services.
CMD ["uvicorn", "apps.ingestion_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

LABEL org.opencontainers.image.title="cdp-app" \
      org.opencontainers.image.description="CDP APIs and CPU Kafka workers"
