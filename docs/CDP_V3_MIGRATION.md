# CDP V3 incremental migration

## Status and baseline

Phase 1 foundation, Phase 2 source-only geometry, and Phase 3 OCR routing are
implemented beside the existing application. See [Phase 2 geometry](CDP_V3_GEOMETRY.md)
and [Phase 3 OCR routing](CDP_V3_OCR_ROUTER.md).
No production worker or public API has been switched to them. Phases 4-10 and
production migration remain pending; the extractor has not been replaced.

Phase 2 is published to `ashishdat/CDP` on `feature/cdp-v3`. The following
baseline records the origin of the existing Phase 1 commit.

The destination repository is `ashneevai/cdp`. Its remote had no
`feature/cdp-v3` branch, so this branch is based on `main`, commit
`8c450869ea13b993548b05d61fe58c16293d3e6f`. Only the foundation, its tests,
and this guide are added to that baseline. Production parity still requires
identifying the deployed commit before replacing runtime subsystems.

## Foundation architecture

`packages/extraction_pipeline` owns ordering and execution, not business decisions.

| Module | Responsibility |
| --- | --- |
| interfaces.py | Stage and metric sink ports |
| context.py | Immutable request ID and flag snapshot |
| models.py | Explicit feature flags, disabled by default |
| registry.py | Immutable, ordered registrations with paired legacy/V3 implementations |
| pipeline.py | Sequential invocation, whole-pipeline and individual-module rollback |
| results.py | Internal result with original payload and side-channel metrics |
| exceptions.py | Configuration errors; execution exceptions are not translated |
| metrics.py | Per-stage duration and success, without document content |
| adapter.py | Calls an existing function exactly once with original arguments |

The foundation imports only the standard library and its own modules. Importing
it does not load models, run OCR, query storage, or read an environment file.
The composition root explicitly supplies a flag snapshot. A disabled
`PIPELINE_V3` bypasses every registered stage and calls the whole legacy pipeline.
With that flag enabled, each stage uses its own flag to select its paired
implementation. No automatic retry or fallback follows an execution failure:
doing so could duplicate OCR, evidence writes, and other side effects.

`PipelineResult` is an internal envelope. Public adapters must return `value`
without serializing it or adding metrics to the response. The foundation retains
object identity, exceptions, stage order, and normalizer results. It does not
make mutable worker services thread-safe; request isolation for those services
must be addressed at their composition roots.

## Existing components to reuse

| Subsystem | Existing source owners |
| --- | --- |
| Geometry and registration | workers/page_detection/template_alignment.py, local_crop_alignment.py, crop_safety.py; packages/extraction_geometry and packages/roi_resolution |
| OCR | workers/page_detection/text_extraction.py; packages/ocr/execution.py, contracts.py, rapidocr_provider.py |
| Normalization | packages/field_normalization.py; existing worker re-exports |
| Recovery and ranking | packages/extraction_recovery; packages/candidate_reconciliation; packages/local_evidence_cascade.py |
| Validation | packages/validation_rules; packages/field_verification.py |
| Evidence | packages/ocr/provenance.py; packages/domain/extraction.py; packages/claim_evidence |
| Decision | packages/claim_decision; packages/policy_engine |
| Runtime extraction | workers/standard_form_extraction/extractor.py and processing.py |
| Benchmark | evaluation/ and existing evaluation scripts; never imported into the foundation |

Do not replace these rules with new interpretations. Existing regional OCR
eligibility, crop coalescing, name postprocessing, validation reasons, and
candidate ordering are observable behavior. A nominally improved OCR fallback
order must not silently change that behavior.

## Subsystem sequence and compatibility gates

1. Foundation: review this isolated change; confirm production source and retain
   the existing runtime entry points.
2. Geometry: move existing registration, safe-cell, alignment, component,
   envelope, and ROI operations behind a source-only interface. Preserve public
   imports with compatibility wrappers and compare coordinates and errors.
3. OCR routing: adapt existing engine implementations and eligibility policies.
   Compare invocation order/count as well as text, confidence, and failures.
4. Field processors: move field-specific extraction and recovery without
   modifying normalization. Preserve existing signatures and unknown-field behavior.
5. Ranking: extract the current selection policy into explicit ordered rules.
   Preserve ties, winner/loser order, rejection reasons, and empty inputs.
6. Validation: reuse existing validators and retain separate observation,
   normalization, validation, and selection records internally. Continue emitting
   the existing response schema.
7. Evidence: retain observations and provenance through the existing persistence
   path. Verify crop references, bounding boxes, IDs, and existing audit behavior.
8. Benchmark: keep answer sources exclusively in reviewer/evaluation code.
9. Field metrics: add OCR, geometry, and recovery timings and decision reasons to
   the observability channel. Do not introduce client response fields implicitly.
10. Rollout: verify each flag independently and together; replace the remaining
    extractor implementation only after parity and reviewer benchmark approval.

Each subsystem belongs in a separate compiling, tested PR. Keep legacy code
available during migration. Delete a legacy module only after its consumers,
compatibility imports, and parity gates have been reviewed.

## Verification and reviewer benchmark handoff

Run the foundation checks from the repository root:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_extraction_pipeline.py tests/integration/test_extraction_pipeline_adapter.py tests/architecture/test_extraction_pipeline_boundary.py -q
.venv/Scripts/python.exe -m pytest tests/architecture/test_evaluation_leakage.py tests/integration/test_canonical_route_extractor_contract.py tests/unit/cases/test_field_processors.py -q
.venv/Scripts/python.exe -m ruff check packages/extraction_pipeline tests/unit/test_extraction_pipeline.py tests/integration/test_extraction_pipeline_adapter.py tests/architecture/test_extraction_pipeline_boundary.py
.venv/Scripts/python.exe -m compileall -q packages/extraction_pipeline
```

Implementation does not run benchmarks. The reviewer should use the existing
evaluation tooling after the production baseline, dataset, configurations, and
engine versions have been identified. Execute V2 and V3 on equivalent isolated
inputs so evaluation cannot duplicate runtime side effects. Preserve production
outputs as the comparison contract; the new pipeline must never read truth.

The existing models generate UUIDs and timestamps. Parity fixtures must control
those producers consistently; silently dropping mismatched evidence fields does
not establish output compatibility. Compare failures and OCR invocation traces
in addition to serialized outputs. Existing normalization coverage and the new
adapter tests are not end-to-end document parity evidence.

## Performance report

No benchmark was executed. No throughput, latency improvement, or production
parity claim is made. The foundation adds one timing pair and one sink call per
executed stage. The reviewer should report p50/p95/p99 duration, throughput,
peak memory, OCR calls, output mismatches, and the exact environment for both
implementations. A failing metric sink does not change successful payloads or
replace engine errors; operators must monitor sink availability separately.

Validation environment: Windows, uv-managed CPython 3.14.7, project-local virtual
environment. This is not a substitute for CI on the production Python version
and locked dependencies. Completed checks: 35 new tests and 20 existing tests;
lint and foundation compilation pass.

## Deployment and rollback

This foundation-only change requires no database migration, model download, or
API deployment change. The four flag names are `PIPELINE_V3`, `GEOMETRY_V3`,
`OCR_ROUTER_V3`, and `VALIDATOR_V3`. Parsing is available through
`FeatureFlags.from_mapping`; environment variables alone do not yet alter any
worker because production composition has not been wired.

After integration, take an immutable flag snapshot per request. Roll back all
new orchestration by disabling `PIPELINE_V3`; roll back one module by disabling
its flag while retaining orchestration. Keep the legacy callable and stage
implementations deployed for that rollback. Do not enable production replacements
before their compatibility tests and reviewer-run benchmarks pass.
