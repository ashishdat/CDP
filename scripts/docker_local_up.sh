#!/usr/bin/env bash
# Bring up CDP on a local Docker Desktop / Engine host.
# Usage (from repo root):
#   bash scripts/docker_local_up.sh           # local-dev compose (.env)
#   bash scripts/docker_local_up.sh --prod    # fail-closed prod overlay (.env.production)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="dev"
if [[ "${1:-}" == "--prod" ]]; then
  MODE="prod"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found. Install Docker Desktop (or Engine + Compose v2) first."
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: 'docker compose' (v2) required."
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker daemon not running. Start Docker Desktop / dockerd."
  exit 1
fi

if [[ "$MODE" == "dev" ]]; then
  if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "created .env from .env.example"
  fi
  echo "Building + starting local-dev stack (docker-compose.yml)..."
  docker compose --env-file .env up -d --build --wait
  echo "Applying MySQL migrations..."
  docker compose --env-file .env exec -T ingestion-api \
    python scripts/apply_mysql_migrations.py || {
      echo "WARN: migrate failed — retry: docker compose exec ingestion-api python scripts/apply_mysql_migrations.py"
    }
  echo ""
  echo "Local Docker stack is up."
  echo "  Ingestion API:   http://localhost:8000/docs"
  echo "  Health/ready:    http://localhost:8000/health  http://localhost:8000/ready"
  echo "  Human review:    http://localhost:8100/ui/review-tasks"
  echo "  Output API:      http://localhost:8102/docs"
  echo "  Gateway:         http://localhost:8080"
  echo "  Evaluation UI:   http://localhost:8180"
  echo "  MinIO console:   http://localhost:9001  (minioadmin / minioadmin)"
  echo ""
  echo "Stop:  make down   (or: docker compose down)"
  echo "Logs:  make logs"
  exit 0
fi

# --- prod overlay ---
if [[ ! -f .env.production ]]; then
  cp .env.production.example .env.production
  python3 - <<'PY'
import secrets
from pathlib import Path

p = Path(".env.production")
text = p.read_text(encoding="utf-8")
mysql_pw = secrets.token_hex(16)
root_pw = secrets.token_hex(16)
access = secrets.token_hex(12)
secret = secrets.token_hex(24)
text = text.replace("CHANGE_ME_STRONG_PASSWORD", mysql_pw)
text = text.replace("CHANGE_ME_ROOT_PASSWORD", root_pw)
text = text.replace("CHANGE_ME_ACCESS_KEY", access)
text = text.replace("CHANGE_ME_SECRET_KEY", secret)
# Ensure DATABASE_URL matches MYSQL_PASSWORD
import re
text = re.sub(
    r"^DATABASE_URL=.*$",
    f"DATABASE_URL=mysql+pymysql://idp:{mysql_pw}@mysql:3306/idp",
    text,
    flags=re.M,
)
p.write_text(text, encoding="utf-8")
print("created .env.production with generated local secrets (gitignored)")
PY
fi

if grep -qE 'CHANGE_ME_|OBJECT_STORE_ACCESS_KEY=minioadmin|MINIO_ROOT_USER=minioadmin' .env.production; then
  echo "ERROR: .env.production still has placeholders or minioadmin."
  echo "Edit secrets, then re-run: bash scripts/docker_local_up.sh --prod"
  exit 1
fi

echo "Building production images..."
bash scripts/docker_build_prod.sh
echo "Starting prod overlay..."
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build --wait
echo "Applying MySQL migrations..."
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml exec -T ingestion-api \
  python scripts/apply_mysql_migrations.py
echo ""
echo "Local Docker (prod overlay) is up."
echo "  Ingestion:     http://localhost:8000/health"
echo "  Human review:  http://localhost:8100/health"
echo "  Output API:    http://localhost:8102/health"
echo "  Gateway:       http://localhost:8080"
echo ""
echo "Stop: make docker-prod-down"
echo "Docs: docs/DOCKER_PRODUCTION.md / docs/DOCKER_LOCAL.md"
