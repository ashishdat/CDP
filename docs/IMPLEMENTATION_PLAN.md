# Implementation Plan

Each phase ends with `pytest` green for the tests introduced in that phase
before moving on (per instructions: "do not claim completion until tests
pass"). Phases map to `docs/DATASET_FINDINGS.md` and
`docs/ARCHITECTURE.md`.

## Phase 1 — Foundations (this delivery)
- Archive inspection (done, see `docs/DATASET_FINDINGS.md`).
- Domain models (`packages/domain`), canonical event envelope + topics
  (`packages/events`), outbox pattern.
- Object storage (`packages/storage/object_store.py`, MinIO/S3), hashing
  (SHA-256 + perceptual hash), magic-byte file-type detection.
- TIFF (incl. multipage Group-4) + PDF decode → per-page original / render /
  thumbnail (`workers/document_preparation`).
- Ingestion API (`apps/ingestion_api`): upload + batch-directory intake,
  dedup, idempotency, `document.received` → `document.prepared` outbox
  events.
- Docker Compose foundation: Postgres, Redis, MinIO, Redpanda.
- Tests: file signature detection, multipage TIFF decode against the real
  dataset, hashing/idempotency, envelope/outbox unit tests.
- **Acceptance gate**: multipage Group-4 TIFF decodes correctly; no document
  bytes touch Kafka; idempotent re-ingestion is a cache hit.

## Phase 2 — Routing & standard-form extraction
- Template registry (`packages/templates`) with versioned CMS-1500/UB
  templates (anchors, alignment points, field/service-line regions).
- Page routing worker (`workers/page_detection`): Bundle A/C anchor
  fast-path, Bundle B enumerate-and-select-CMS-page (attachments preserved,
  never extracted), MobileNetV3 fallback classifier interface.
- OpenCV homography alignment; regional PaddleOCR extraction
  (`workers/standard_form_extraction`) for CMS-1500 and UB field/service-line
  regions.
- Tests: template coordinate math, Bundle B page-selection logic against the
  real Group B TIFFs, routing decision unit tests.
- **Acceptance gate**: Bundle B selects only the CMS-1500 page; standard
  forms use template-region OCR first (no whole-page OCR).

## Phase 3 — Canonical schema, validation, fixed-width output
- `Claim`/`ServiceLine` canonical schema finalized; deterministic validators
  (`packages/validation_rules`): NPI Luhn, date logic, ICD-10/CPT/HCPCS
  adapters, modifiers, numeric/currency normalization, required-field and
  service-line/claim-total reconciliation, per-field confidence thresholds
  (critical vs non-critical).
- `packages/fixed_width` config-driven writer + `config/output_specs/{nsf,ub92}`
  transcribed from the supplied spec docs for the record types present in
  the sample outputs.
- Golden tests: generated output vs supplied `.txt` files, byte-for-byte,
  with a mismatch report (record type, position, expected/actual) when they
  differ.
- **Acceptance gate**: fixed-width output matches the supplied examples for
  Groups A/B/C/D; critical fields fail closed into human review when
  deterministic validation fails.

## Phase 4 — Hybrid router, retry, VLM fallback
- `packages/model_router` full escalation-order implementation + cost/route
  telemetry.
- `workers/retry`: alternate preprocessing + OCR of failed fields only.
- LayoutLMv3 (Bundle D), Table Transformer (UB failed tables only) adapter
  interfaces wired into the router.
- `workers/vlm_fallback`: Qwen2.5-VL-3B-compatible adapter over a
  vLLM-compatible OpenAI endpoint, temperature 0, strict JSON schema,
  crop-only input, `insufficient_evidence` path, `VLM_ENABLED` flag.
- Tests: router decision table, VLM disabled path, VLM adapter schema
  enforcement (mocked endpoint).
- **Acceptance gate**: pipeline runs end-to-end with `VLM_ENABLED=false`;
  VLM is only ever invoked after cheaper stages fail in a forced-failure
  test.

## Phase 5 — HITL, observability, security, deployment (done, with gaps noted)
- `apps/human_review_api` + server-rendered UI: failed-field-only review,
  correction persistence (reviewer, timestamp, before/after, reason),
  immutable audit events. **Gap**: nothing creates a `ReviewTask`
  automatically yet — `workers/validation` → `human.review.requested` →
  a consumer inserting tasks doesn't exist (same underlying gap as
  Phase 4's "router/retry/VLM wired into a running worker").
- Prometheus metrics (every name from the spec) exposed at `/metrics` on
  both APIs; OpenTelemetry span helper; PHI-redacting `structlog` config
  actually wired into every app/worker entrypoint (not just built and
  left unused — verified via a test that captures the real rendered log
  line, not the processor function in isolation).
- RBAC hooks (role/permission model + FastAPI dependency reading
  `X-User-Role` — an explicit hook, not an identity provider), signed
  URLs (Phase 1 capability, now actually used by the review API),
  retention/deletion workflow (tested against fakes + SQLite; not yet
  run against real Postgres or on a schedule), tenant/correlation IDs
  (already end-to-end since Phase 1's domain model).
- Helm charts for the three deployables with a real entrypoint
  (`ingestion-api`, `human-review-api`, `document-preparation-worker`),
  validated with a real downloaded `helm` binary (`lint` + `template`).
  KEDA `ScaledObject`s for all five worker pools from the spec —
  YAML-structure-validated; only one targets a Deployment that exists.
  **Gap**: no live Kubernetes/KEDA to validate against (none available in
  this environment) — `helm install`/actual autoscaling behavior unverified.
- Performance harness (`tests/performance`, run against all 30 real
  sample files): pages/sec, p50/p95/p99 latency for the pipeline stages
  that are real today (decode+preprocess, grid-signature). Found and
  fixed a real 9x bottleneck (unconditional `fastNlMeansDenoising` +
  `optimize=True` PNG encoding). OCR/VLM invocation rates, GPU
  utilization, and straight-through rate are **not measured** (no live
  OCR/VLM model, no end-to-end validate→escalate wiring yet) —
  documented as such rather than faked; cost-per-page is a clearly-labeled
  illustrative projection, not a measurement.
- **Gap, not attempted**: Kafka failure/replay integration test (no
  `processing.dlq`/replay tool exists yet — see docs/RUNBOOK.md
  "Replay").
- **Acceptance gate**: see the top-level README's "Not yet implemented"
  table and "Known simplifications" list for the full, current gap
  inventory — every gap above is cross-referenced there, not just here.
