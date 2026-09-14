# Phase 3: OCR Router

The single runtime addition is `packages/ocr_router.py`. Existing OCR adapters,
pipeline architecture, production workers, thresholds, and public APIs are
unchanged. The router is opt-in composition, not a production rollout.

## Behavior

`OCRRouter(accept=...)` requires the caller's existing acceptance policy. It tries
RapidOCR, PaddleOCR, Tesseract, then explicitly eligible TrOCR, stopping at the
first usable observation accepted by that policy. It introduces no confidence
threshold, validation rule, normalization, or cross-engine ranking. Empty text
and TrOCR's insufficient-evidence results cannot end escalation successfully.

`OCRRouteRequest` carries the source image, an in-bounds integer region, and
explicit handwriting eligibility (false by default). TrOCR is intended only for
a tightly cropped handwritten line; callers must not enable it for whole-page
or multiline requests. Regional adapters retain their source-coordinate boxes.
The TrOCR bridge uses the supplied region as its observation box, not inferred
token geometry. No new model implementation is introduced.

Each attempt preserves the original returned lines, including whitespace,
confidence, and order. `OCRRoutingResult` retains all successful observations and
explicit unavailable-engine attempts, plus the selected attempt or exhaustion.
Latency includes lazy construction and recognition. These records are internal;
the router does not serialize or append fields to existing API responses.

Factories are invoked only when reached. A router reuses constructed adapters,
but does not cache OCR results. Calls on one instance are serialized because
existing engines have mutable model state. Policies must not recursively call
the same router. Inject factories for configured model variants; defaults use
the existing adapters' defaults. Required packages and model artifacts must be
provisioned using the existing deployment process.

Missing RapidOCR/Paddle dependencies, a missing Tesseract executable, and TrOCR's
wrapped missing-dependency error are recorded as unavailable. Other exceptions,
including inference, model-download, and policy failures, propagate without
retry. The router does not convert failures into accepted evidence.

## Integration and rollback

`router.stage(legacy)` uses the existing `StageRegistration` and `OCR_ROUTER_V3`
flag. Both `PIPELINE_V3` and `OCR_ROUTER_V3` must be enabled to invoke it.
Disabling either routes through its configured legacy path. No production
worker is automatically rewired. The next stage must consume `OCRRoutingResult`;
Phase 4 field processing and Phase 5 ranking are not included here.

Tests use synthetic observations and injected adapters. They cover invocation
order, lazy loading, early stop, exhaustion, retained observations, unavailable
engines, exception identity, model reuse, timing, TrOCR region conversion, and
all flag combinations. They do not claim real-model accuracy or benchmark gains.

Validation: 102 tests passed across Phase 3, prior-phase regressions, the runtime
evaluation boundary, and existing OCR adapter tests. Ruff and compilation passed.
No benchmark was run.
