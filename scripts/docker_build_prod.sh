#!/usr/bin/env bash
# Build production Docker images for CDP APIs + workers.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TAG="${CDP_IMAGE_TAG:-latest}"
REGISTRY="${CDP_IMAGE_REGISTRY:-}"
# REGISTRY may be "ghcr.io/org/" (with trailing slash) or empty.
prefix="${REGISTRY}"

echo "Building cdp-app:${TAG}"
docker build -f deploy/docker/app.Dockerfile -t "${prefix}cdp-app:${TAG}" .

echo "Building cdp-ocr:${TAG}"
docker build -f deploy/docker/ocr.Dockerfile -t "${prefix}cdp-ocr:${TAG}" .

echo "Building cdp-routing:${TAG}"
docker build -f deploy/docker/routing.Dockerfile -t "${prefix}cdp-routing:${TAG}" .

echo "Building convenience root Dockerfile → ${prefix}cdp-app:${TAG}-root (optional alias)"
docker build -f Dockerfile -t "${prefix}cdp-app:${TAG}" .

echo "Done. Images:"
docker images --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -E 'cdp-(app|ocr|routing)' || true
