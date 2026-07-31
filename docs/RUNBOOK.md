# Operational Runbook

Scope: what exists today (ingestion API, document-preparation worker,
human review API). Sections marked **(future)** describe what will exist
once the corresponding phase lands (see `docs/IMPLEMENTATION_PLAN.md`) and
are included here so the runbook's shape doesn't change later.

## Starting / stopping the stack

```bash
make run     # docker compose up -d --build --wait
make logs    # follow all service logs
make down    # stop, keep volumes
make clean   # stop and delete volumes (Postgres/MinIO/Redpanda data)
```

Health/readiness:
- Ingestion API: `GET http://localhost:8000/health` (process up),
  `GET http://localhost:8000/ready` (DB + object store initialized),
  `GET http://localhost:8000/metrics` (Prometheus).
- Human review API: same three endpoints on `:8100` (host port -- the
  container listens on 8001 internally; host 8001 was already bound by an
  unrelated container on the dev machine this was built on, see
  docker-compose.yml).
- Postgres/Redis/MinIO/Redpanda: `docker compose ps` — all four have
  compose-level healthchecks; `make run` uses `--wait` so it won't return
  until they're healthy.

## Ingesting documents

- Single file: `POST /documents` (multipart, field name `file`) to the
  ingestion API — see http://localhost:8000/docs.
- Batch directory: `python -m apps.ingestion_api.batch_ingest <dir>
  --tenant-id <id>` — walks the directory, ingests every file whose magic
  bytes are recognized, skips the rest, logs one line per file with the
  resulting `document_id`.

## Diagnosing a document stuck before `PREPARED`

1. `GET /documents/{id}` — check `status`. `RECEIVED` that never advances
   to `PREPARED` means the document-preparation worker either isn't
   running or failed on that document.
2. `docker compose logs document-preparation-worker` — decode/preprocess
   failures are logged with the `document_id` (via
   `logger.exception("failed to prepare document_id=%s", ...)` in
   `workers/document_preparation/consumer.py`); the consumer loop keeps
   running past a single failure (it does not crash the process), but the
   event is not retried automatically yet — that's `workers/retry`
   **(Phase 4)** plus a DLQ **(Phase 5, `processing.dlq` topic already
   reserved in `packages/events/topics.py`)**.
3. Check the outbox: a `document.received` row with `published_at IS NULL`
   in the `outbox` table means the relay hasn't published it yet (check
   the ingestion API logs for `outbox publish failed` — the relay retries
   every second and does not lose the record, but a broker outage will
   stall delivery until it recovers).

## Common failure modes today

| Symptom | Likely cause | Where to look |
|---|---|---|
| `POST /documents` → 415 | magic bytes not TIFF/PDF/PNG/JPEG | `packages/storage/file_types.py` — check the file's actual first bytes, not its extension |
| `POST /documents` → 413 | over `MAX_UPLOAD_SIZE_BYTES` | `.env` |
| `POST /documents` → 422 | malware scan flagged it | `NoOpMalwareScanner` always passes today — a 422 here means a *future* real scanner is wired in and rejected the file |
| document stuck at `RECEIVED` | prep worker down/crashed, or Redpanda unreachable | `docker compose ps`, `docker compose logs document-preparation-worker` |
| `/ready` returns 503 | object store or DB not initialized yet (right after startup) | wait for `--wait` healthchecks; if persistent, check MinIO/Postgres connectivity from the API container |

## Human review workflow

1. A reviewer opens `http://localhost:8100/ui/review-tasks` (or calls
   `GET /review-tasks` with header `X-User-Role: reviewer`) to list open
   tasks — each is scoped to **one failed field**, never a whole claim.
2. The detail page/`GET /review-tasks/{id}` shows the source crop (via a
   short-lived signed MinIO URL), OCR candidates, VLM candidate (if any),
   and the specific validation errors that sent it to review.
3. Approving with a correction (`POST /review-tasks/{id}/correct`, or the
   UI form) persists a `FieldCorrection` (reviewer, timestamp, previous
   value, new value, reason) and emits a `FIELD_CORRECTED` audit event.
   Rejecting persists a `REVIEW_DECIDED` audit event instead. Both require
   role `reviewer` or `admin` (`X-User-Role` header — see
   `packages/security/rbac.py`'s docstring for why this is a hook, not a
   real identity provider, and the one function to replace with one).
4. **(future)** Nothing in the pipeline creates a `ReviewTask` automatically
   yet — that requires `workers/validation` publishing to
   `human.review.requested` and a consumer turning that into a task. Today,
   tasks must be inserted directly (`ReviewTaskRepository.add`) — see
   `tests/unit/test_human_review_api.py` for the shape.

## Retention / deletion

`packages.security.RetentionService.run_retention_sweep(policy, as_of)`
finds every document a tenant received before `as_of - retention_days`,
deletes its object-store original and DB row (cascading to its pages),
and returns one immutable `AuditEvent` per deletion. Tested against fakes
and SQLite; **(future)** not yet wired to a scheduled job (a Kubernetes
CronJob or similar) or exercised against real Postgres — run it manually/
scripted for now:

```python
from datetime import datetime, UTC
from packages.security import RetentionPolicy, RetentionService
from apps.ingestion_api.db.repository import DocumentRepository
# ... construct RetentionService(DocumentRepository(session), object_store)
service.run_retention_sweep(RetentionPolicy(tenant_id="...", retention_days=365), datetime.now(UTC))
```

## Monitoring

- `GET /metrics` on `ingestion-api` (`:8000`) and `human-review-api`
  (`:8100` from the host, `:8001` container-internal — see docker-compose.yml)
  — Prometheus text format, `packages/observability/metrics.py`
  for the full metric list.
- `deploy/monitoring/prometheus.yml` — local scrape config;
  `alert_rules.yml` — 6 alerts (error rate, critical-field validation
  failures, straight-through rate, Kafka lag, an unexpected-VLM-invocation
  tripwire, API availability); `grafana_dashboard.json` — 7 panels. None
  of these three are validated against a live Prometheus/Grafana in this
  environment (YAML/JSON syntax only) — sanity-check before relying on
  them in production.
- `document-preparation-worker` has no HTTP server, so nothing to scrape
  yet (see the commented-out job in `prometheus.yml`).

## Replay **(future — Phase 5 follow-up)**

A `processing.dlq` topic and a replay endpoint/tool are planned but not
implemented; today a failed page in `document_preparation` simply logs and
moves on to the next message (at-least-once redelivery only happens if the
consumer crashes before committing, per `aiokafka`'s manual-commit
semantics in `packages/events/bus.py`).

## Known performance characteristics

`tests/performance/test_throughput.py` (run against all 30 real sample
files) found `document_preparation`'s default pipeline was bottlenecked on
`cv2.fastNlMeansDenoising` (unconditional, ~8.5s/page) and PNG encoding
with `optimize=True` — fixed (median blur default, `optimize=False`,
expensive denoiser moved to the OCR-retry path only): **0.15 → 1.34
pages/sec** end-to-end. Run `pytest tests/performance -m performance -s`
to reproduce against your own hardware; numbers above are from this
project's dev machine, not a portable SLA.
