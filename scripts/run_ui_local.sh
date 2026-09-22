#!/usr/bin/env bash
# Docker-less Evaluation UI stack: shared sqlite + filesystem object store +
# in-memory bus. Suitable for UI wiring / HITL demos without Compose.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export DATABASE_URL="${DATABASE_URL:-sqlite:////tmp/idp_ui.db}"
export USE_IN_MEMORY_BUS=true
export OBJECT_STORE_BACKEND=filesystem
export OBJECT_STORE_FILESYSTEM_ROOT="${OBJECT_STORE_FILESYSTEM_ROOT:-/tmp/idp-objects}"
export OBJECT_STORE_BUCKET="${OBJECT_STORE_BUCKET:-idp-documents}"
export CORRECTION_MEMORY_PATH="${CORRECTION_MEMORY_PATH:-/tmp/idp-corrections.jsonl}"
# Never treat this local demo stack as production.
unset CDP_ENV || true

mkdir -p "$OBJECT_STORE_FILESYSTEM_ROOT" /tmp/cdp-ui-logs
rm -f /tmp/idp_ui.db

echo "Starting ingestion-api on :8000 ..."
python3 -m uvicorn apps.ingestion_api.main:app --host 0.0.0.0 --port 8000 \
  >/tmp/cdp-ui-logs/ingestion.log 2>&1 &
echo $! >/tmp/cdp-ui-logs/ingestion.pid

echo "Starting human-review-api on :8100 ..."
python3 -m uvicorn apps.human_review_api.main:app --host 0.0.0.0 --port 8100 \
  >/tmp/cdp-ui-logs/review.log 2>&1 &
echo $! >/tmp/cdp-ui-logs/review.pid

echo "Starting evaluation-ui on :8180 ..."
python3 -m uvicorn apps.evaluation_ui.main:app --host 0.0.0.0 --port 8180 \
  >/tmp/cdp-ui-logs/ui.log 2>&1 &
echo $! >/tmp/cdp-ui-logs/ui.pid

for i in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8000/ready >/dev/null \
    && curl -sf http://127.0.0.1:8100/ready >/dev/null \
    && curl -sf http://127.0.0.1:8180/health >/dev/null; then
    break
  fi
  sleep 0.5
done

curl -sf http://127.0.0.1:8000/ready >/dev/null
curl -sf http://127.0.0.1:8100/ready >/dev/null
curl -sf http://127.0.0.1:8180/health >/dev/null

python3 scripts/seed_ui_demo_queue.py

echo ""
echo "Evaluation UI:    http://127.0.0.1:8180"
echo "Ingestion API:    http://127.0.0.1:8000/docs"
echo "Human review API: http://127.0.0.1:8100/ui/review-tasks"
echo "Logs:             /tmp/cdp-ui-logs/"
echo "Stop with:        make ui-down-local"
