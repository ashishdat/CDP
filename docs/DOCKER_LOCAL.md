# Local Docker (your machine)

Run the full CDP stack with Docker Desktop / Engine on your laptop.

## Prerequisites

- Docker Desktop (macOS/Windows) or Docker Engine + Compose v2 (Linux)
- ~8 GB RAM free (OCR image is the heavy piece)
- Ports free: `8000`, `8080`, `8100`, `8102`, `8180`, `9000`, `9001`, `3306`, `6379`

## One-command local-dev deploy (recommended)

From the repo root on your machine:

```bash
git checkout feature/cdp-v3
git pull
bash scripts/docker_local_up.sh
```

Or:

```bash
make docker-local
```

This copies `.env.example` → `.env` if needed, builds images, starts
MySQL / MinIO / Redpanda / Redis + APIs + workers, and runs migrations.

### URLs

| Service | URL |
|---|---|
| Ingestion API docs | http://localhost:8000/docs |
| Health / ready | http://localhost:8000/health · `/ready` |
| Human review | http://localhost:8100/ui/review-tasks |
| Output API | http://localhost:8102/docs |
| API gateway | http://localhost:8080 |
| Evaluation UI | http://localhost:8180 |
| MinIO console | http://localhost:9001 (`minioadmin` / `minioadmin`) |

### Stop / logs

```bash
make down          # or: docker compose down
make logs
docker compose ps
```

## Fail-closed “prod-like” local overlay

Uses `docker-compose.prod.yml` + generated secrets (not `minioadmin`):

```bash
bash scripts/docker_local_up.sh --prod
# or: make docker-local-prod
```

See `docs/DOCKER_PRODUCTION.md` for pins and PHI caveats.

## Smoke checks

```bash
curl -sf http://localhost:8000/health && curl -sf http://localhost:8000/ready
curl -sf http://localhost:8100/health
curl -sf http://localhost:8102/health
```

## Notes

- First build pulls base images and compiles OCR deps — expect a long first run.
- This environment is **not PHI-authorized**. Local Docker ≠ production sign-off.
- Hackathon cascade evals (`scripts/run_hackathon_*`) are host-side runners; the
  Compose stack is the platform APIs + Kafka workers.
