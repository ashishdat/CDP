# Convenience root image for CDP application services (APIs + CPU workers).
# Prefer targeting a specific service at runtime via CMD override.
#
#   docker build -t cdp-app:latest .
#   docker run --rm -p 8000:8000 --env-file .env.production cdp-app:latest
#
# OCR / routing workers use deploy/docker/ocr.Dockerfile and routing.Dockerfile.
# Full stack: docs/DOCKER_PRODUCTION.md

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

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

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app

USER appuser

EXPOSE 8000 8001 8002

# Default: ingestion API. Override for other services, e.g.
#   command: ["uvicorn", "apps.human_review_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
#   command: ["python", "-m", "workers.document_preparation.consumer"]
CMD ["uvicorn", "apps.ingestion_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

LABEL org.opencontainers.image.title="cdp-app" \
      org.opencontainers.image.description="CDP claims platform APIs and CPU workers" \
      org.opencontainers.image.source="https://github.com/ashishdat/CDP"
