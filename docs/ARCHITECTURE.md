# Architecture Decisions

## 1. Monorepo layout, single installable distribution

`apps/`, `workers/`, `packages/` are all part of one Python distribution
(`pyproject.toml` at repo root, `packages.find` over the three trees). Each
deployable (an app or a worker) gets its own thin `Dockerfile` that installs
the whole distribution but runs a different entrypoint/extras group — this
avoids duplicating shared domain/event/storage code across N Dockerfiles
while still letting each service scale independently in Kubernetes/KEDA.
Heavy ML extras (`paddleocr`, `torch`, `transformers`) are an optional
extras group (`pip install .[ml]`) so `apps/*` and CPU-only workers don't
pull GPU deps, and Phase 1 can be developed/tested on a plain laptop.

## 2. Domain layer is Pydantic v2, persistence is separate

`packages/domain` contains only Pydantic v2 models — the wire/canonical
representation used in events, APIs, and JSON output. SQLAlchemy 2.0
declarative ORM models live next to each service's persistence code
(`apps/*/db/models.py`), with explicit mapper functions to/from the domain
models. This keeps the canonical schema free of ORM concerns (relationships,
lazy loading) and makes it trivial to version the canonical JSON
independently of the DB schema.

## 3. Kafka-compatible abstraction, not a Kafka SDK leak

`packages/events/bus.py` defines an `EventBus` protocol (`publish`,
`subscribe`) with two implementations:
- `InMemoryEventBus` — synchronous, used in unit/integration tests and local
  dev without Docker.
- `AIOKafkaEventBus` — `aiokafka` (pure-Python client, no `librdkafka` build
  dependency, which matters for Windows dev boxes) against Redpanda locally
  and Kafka/MSK/Confluent in higher environments (same wire protocol).

No worker imports `aiokafka` directly; they depend on `EventBus`. Local
compose uses **Redpanda** (single binary, Kafka-API compatible) instead of
Kafka+Zookeeper — satisfies "Kafka-compatible abstraction" with a much
lighter `docker-compose.yml`.

Every event is `packages/events/envelope.py::EventEnvelope`, and payloads
carry **object-storage URIs only** — never bytes. This is enforced by a
Pydantic validator on payload models used in Kafka topics (reject any field
typed `bytes`).

## 4. Outbox pattern

Each app/worker that must publish an event as a side effect of a DB write
inserts an `OutboxRecord` row in the *same transaction*. A separate
`OutboxRelay` (a small poller, run as its own process/thread per service)
reads unpublished rows in order, publishes to the `EventBus`, and marks them
published — guaranteeing at-least-once delivery tied to DB commit, not to
in-process Kafka availability. Consumers are idempotent (dedupe on
`event_id`) to absorb the at-least-once redelivery.

## 5. Object storage

`packages/storage/object_store.py` wraps `boto3` S3 client against MinIO
locally / any S3-compatible endpoint in prod. Keys are content-addressed
under `documents/{sha256}/...` so exact-duplicate uploads are naturally
deduplicated at the storage layer too. Signed GET URLs (short TTL, default
15 min) are generated on demand for the review UI — the object store never
returns a permanent public URL.

## 6. File-type detection without `python-magic`

`python-magic` requires `libmagic`, which isn't reliably available on
Windows dev machines. `packages/storage/file_types.py` implements a small,
dependency-free magic-byte sniffer (first N bytes only) covering TIFF
(`II*\0` / `MM\0*`), PDF (`%PDF`), PNG, JPEG — sufficient for this pipeline's
supported inputs and portable everywhere. Verified against the real dataset
in `docs/DATASET_FINDINGS.md`.

## 7. TIFF/PDF decode

Pillow (bundled libtiff, Group-4/T.6 support confirmed against the real
dataset) for TIFF, including multipage (`n_frames` / IFD chain walk).
PyMuPDF (`fitz`) for PDF. Both produce a common `DecodedPage` (PIL Image +
metadata); everything downstream (deskew, classification, OCR) is
format-agnostic once decoded.

## 8. Idempotency

Key = `sha256(document_bytes) + pipeline_version + schema_version`, enforced
as a DB unique constraint on `documents`. Re-ingesting the same bytes under
the same pipeline/schema version short-circuits to the existing
`Document`/`Claim` (cache hit, route #1 in the hybrid router) rather than
reprocessing.

## 9. Hybrid model router

`packages/model_router` is a pure decision function:
`(field_criticality, ocr_confidence, alignment_score, validation_failures,
ocr_disagreement, doc_type, estimated_cost_table) -> ModelDecision`. It is
deliberately side-effect-free and unit-testable without any model
dependency — workers call it, then dispatch to whichever stage it selected.
Escalation order (cache → template rules → OpenCV alignment → regional
PaddleOCR → deterministic validation → alternate preprocessing/OCR on failed
fields only → LayoutLMv3/Table Transformer/TrOCR → VLM on failed crops only
→ human review) is encoded as an ordered list of `RouteStage` with
short-circuit on first acceptable confidence, not a single classifier.

## 10. Config-driven fixed-width writer, not hand-coded per record type

`packages/fixed_width` interprets `config/output_specs/{nsf,ub92}/*.yaml`
(one file per record type, fields = `start_position/length/alignment/
padding_character/data_type/format/required/default/source_field`, as
transcribed from the supplied spec docs) — adding a new record type or
correcting a field position is a config change, not a code change. A
`FixedWidthValidator` checks record length, position, padding, and
header/trailer/record-count/financial-total invariants before bytes are
considered final output; golden tests diff generated bytes against the
supplied reference `.txt` files record-by-record.

## 11. VLM as last resort, off by default

`packages/model_router` + `workers/vlm_fallback` only ever receive **failed
field crops**, never a full page, and only after every cheaper stage in §9
has been tried. `VLM_ENABLED=false` is the default in `.env.example`; the
adapter also enforces temperature 0, a strict output JSON schema, rejection
of any field not in that schema, and `insufficient_evidence` instead of a
guess — validated with the same deterministic validators as OCR output
before it can touch a `Claim`.

## 12. Optional model runtimes and controlled disposition

To keep each phase honestly testable on a normal dev machine:
- PaddleOCR, Tesseract, and TrOCR have lazy, versioned adapters behind the
  common field OCR contract. PP-OCRv5 remains isolated from the stable
  PaddleOCR 2.x worker image. LayoutLMv3 and Table Transformer remain
  optional model adapters.
- `workers.cascade.field_pipeline.FieldCascade` performs cost-aware
  field-level routing. `CandidateReconciler` applies hard validation,
  calibrated-probability hooks, independent-engine agreement, authoritative
  reference evidence, and alignment quality. Critical fields without enough
  evidence receive `HUMAN_REVIEW_REQUIRED`; they cannot silently finalize.
- Kubernetes/Helm/KEDA (Phase 5) is authored against the same images built
  in Phases 1-4; it is not runnable inside this sandboxed dev environment
  (no cluster) — validated with `helm template`/`helm lint` only.
