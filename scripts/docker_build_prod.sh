#!/usr/bin/env bash
# Build production Docker images for CDP APIs + workers.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TAG="${CDP_IMAGE_TAG:-latest}"
REGISTRY="${CDP_IMAGE_REGISTRY:-}"
prefix="${REGISTRY}"

DOCKER="${DOCKER:-docker}"
if ! command -v "$DOCKER" >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
  else
    echo "ERROR: docker not available"
    exit 1
  fi
fi

echo "Building ${prefix}cdp-app:${TAG} (deploy/docker/app.Dockerfile)"
$DOCKER build -f deploy/docker/app.Dockerfile -t "${prefix}cdp-app:${TAG}" .

echo "Building ${prefix}cdp-ocr:${TAG}"
$DOCKER build -f deploy/docker/ocr.Dockerfile -t "${prefix}cdp-ocr:${TAG}" .

echo "Building ${prefix}cdp-routing:${TAG}"
$DOCKER build -f deploy/docker/routing.Dockerfile -t "${prefix}cdp-routing:${TAG}" .

# Keep root Dockerfile in sync as an alias of cdp-app (same content family).
echo "Tagging root Dockerfile build as ${prefix}cdp-app:${TAG}-root (alias check)"
$DOCKER build -f Dockerfile -t "${prefix}cdp-app:${TAG}-root" .

echo "Verifying migrations + GT are inside cdp-app image..."
$DOCKER run --rm --entrypoint python "${prefix}cdp-app:${TAG}" - <<'PY'
from pathlib import Path
mig = Path("/app/deploy/mysql/migrations")
gt = Path("/app/docs/gt/hackathon_agent_field_truth.json")
assert mig.is_dir() and any(mig.glob("*.sql")), f"missing migrations under {mig}"
assert gt.is_file(), f"missing field truth {gt}"
print(f"ok migrations={len(list(mig.glob('*.sql')))} gt_bytes={gt.stat().st_size}")
PY

echo "Done. Images:"
$DOCKER images --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}' \
  | grep -E 'cdp-(app|ocr|routing)' || true
