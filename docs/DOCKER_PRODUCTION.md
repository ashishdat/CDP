# Docker production deployment

Status: **production-hardened Docker path**. Does **not** authorize PHI
processing — see `PRODUCTION_READINESS.md`.

## What you get

| Image | Dockerfile | Services |
|---|---|---|
| `cdp-app` | `deploy/docker/app.Dockerfile` (also root `Dockerfile`) | ingestion / human-review / output APIs + CPU workers |
| `cdp-ocr` | `deploy/docker/ocr.Dockerfile` | standard-form + unstructured extraction workers |
| `cdp-routing` | `deploy/docker/routing.Dockerfile` | page-detection worker |

Orchestration:

- **Single-node / staging:** `docker-compose.yml` + `docker-compose.prod.yml`
- **Kubernetes:** Helm charts under `deploy/helm/` + KEDA under `deploy/keda/`

## Quick start (Compose prod overlay)

One-shot on a machine with Docker Engine / Desktop:

```bash
make docker-local-prod
# = scripts/docker_local_up.sh --prod
# creates .env.production with strong secrets, builds images, ups stack, migrates
```

Manual steps:

```bash
# 0. Packaging sanity (no daemon required)
make docker-deploy-check

# 1. Secrets (never commit)
cp .env.production.example .env.production
# Edit: MYSQL_*, OBJECT_STORE_*, MINIO_ROOT_* (not minioadmin)

# 2. Build images (app + ocr + routing; verifies migrations + GT in image)
make docker-prod-build
# or: CDP_IMAGE_TAG=$(git rev-parse --short HEAD) make docker-prod-build

# 3. Start platform + APIs + workers
make docker-prod-up

# 4. Migrations (SQL files are baked into cdp-app at /app/deploy/mysql/migrations)
make docker-prod-migrate

# 5. Fail-closed smoke (host Python with same env pins)
export $(grep -v '^#' .env.production | xargs)
make prod-smoke

# 6. Health
curl -sf http://localhost:8000/health && curl -sf http://localhost:8000/ready
curl -sf http://localhost:8100/health   # human-review (host port)
curl -sf http://localhost:8102/health   # output API (host port)
curl -sf http://localhost:8080/health   # gateway (if up)
```

Stop:

```bash
make docker-prod-down
```

## Fail-closed production pins

When `CDP_ENV=production` the process refuses to start if:

- `USE_IN_MEMORY_BUS=true`
- `DATABASE_URL` is sqlite
- object-store credentials missing or `minioadmin`/`minioadmin`
- `OBJECT_STORE_BACKEND=filesystem`
- VLM / AI gateway enabled without PHI approvals

APIs expose `/health` (liveness) and `/ready` (readiness).

## Image contents (baked in)

| Path in image | Purpose |
|---|---|
| `/app/apps`, `/app/packages`, `/app/workers` | Runtime code |
| `/app/config` | Runtime profiles + product contracts |
| `/app/deploy/mysql/migrations` | `make docker-prod-migrate` |
| `/app/docs/gt` | Shared agent field truth (`CDP_FIELD_TRUTH`) |
| `/app/scripts` | Ops scripts (migrate, smoke) |

Images run as UID 1000 (`appuser`), expose `/health` + `/ready`, and refuse
unsafe defaults when `CDP_ENV=production`.

## Image-only run (ingestion API)

```bash
docker build -t cdp-app:latest -f deploy/docker/app.Dockerfile .
# Needs MySQL + MinIO + Kafka for /ready; /health is process-local.
docker run --rm -p 8000:8000 --env-file .env.production \
  -e CDP_ENV=development \
  cdp-app:latest
```

Override command for workers:

```bash
docker run --rm --env-file .env.production cdp-app:latest \
  python -m workers.document_preparation.consumer
```

## Kubernetes

```bash
# Create secret from .env.production (example — use sealed-secrets/ESO in real prod)
kubectl create secret generic cdp-runtime --from-env-file=.env.production

helm upgrade --install cdp-ingestion deploy/helm/ingestion-api \
  --set image.repository=cdp-app --set image.tag=$TAG \
  --set secretName=cdp-runtime

helm upgrade --install cdp-review deploy/helm/human-review-api ...
helm upgrade --install cdp-output deploy/helm/output-api ...
helm upgrade --install cdp-workers deploy/helm/cdp-worker-pools ...
```

See `deploy/helm/README.md` and `docs/CDP_VNEXT_DEPLOYMENT_GUIDE.md`.

## Registry push

```bash
export CDP_IMAGE_REGISTRY=ghcr.io/YOUR_ORG/
export CDP_IMAGE_TAG=$(git rev-parse --short HEAD)
make docker-prod-build
docker push ${CDP_IMAGE_REGISTRY}cdp-app:${CDP_IMAGE_TAG}
docker push ${CDP_IMAGE_REGISTRY}cdp-ocr:${CDP_IMAGE_TAG}
docker push ${CDP_IMAGE_REGISTRY}cdp-routing:${CDP_IMAGE_TAG}
```

## Local vs prod Compose

| | `make run` | `make docker-prod-up` |
|---|---|---|
| Env file | `.env` (dev defaults OK) | `.env.production` (required) |
| `CDP_ENV` | unset / development | `production` |
| MinIO creds | `minioadmin` | must be changed |
| Eval UI / shadows | available | off unless `--profile ui` |

## PHI authorization still required

Docker readiness ≠ PHI authorization. Close holdout, IdP/RBAC, BAA/region,
and signed promotion via `docs/PRODUCTION_CLOSEOUT_CHECKLIST.md` before
processing production healthcare data.
