# CDP Accuracy Strategy — 90%+ Exact Field Accuracy

Status: active implementation plan  
Baseline (frozen Phase 8.10 governed metrics): **89.05%** overall / **91.67%** critical  
Target: **≥90%** overall Exact (critical ≥95% remains a follow-on gate)  
Commit context: `feature/cdp-v3` @ recovery planner `b835ffd`

## Gap math

| Metric | Baseline | Target | Absolute gap |
|---|---:|---:|---|
| Overall Exact | 89.05% (374/420) | 90.00% (378/420) | **+4 fields** |
| Critical Exact | 91.67% | 95.00% | larger; not this unit |

Crossing 90% overall requires recovering **at least 4** of the 46 incorrect fixed fields without adding false accepts.

## Failure Pareto (fixed fields)

| Layer | Count | Share |
|---|---:|---:|
| OCR empty | 19 | 41% |
| OCR character error | 16 | 35% |
| Localization | 7 | 15% |
| Under-crop | 2 | 4% |
| Ranking / normalization | 2 | 4% |

OCR empty + character = **35/46 (76%)**. Authorized bottleneck (Phase 8.10 failure decomposition): **regional RapidOCR crop preparation**.

## Root cause in code

`workers/page_detection/text_extraction.py::RapidOCRTextExtractor.extract_region` only does a blind ≤3× upscale. It does **not** apply `PreprocessingRegistry` field profiles. Provenance is labeled `REGIONAL_DEFAULT`.

`config/ocr_preprocessing_phase8_10.yaml` already defines field-aware profiles (digit-preserving without Otsu, currency, date, alphanumeric). `packages/ocr/rapidocr_provider.py` can apply them, but the **live regional extractor path does not**.

Prior NAME_STROKE_V2-only experiment **regressed** (Phase 8.10B) because it stacked aggressive prep on top of the blind 3× upscale. This plan applies field profiles **once**, and disables the blind upscale when the profile already upscales.

## Strategy ladder (ordered)

### S1 — Wire Phase 8.10 field-profile prep into regional RapidOCR (this change)
- Load `ocr_preprocessing_phase8_10.yaml` in `RapidOCRTextExtractor`
- Honor `set_context(field=..., field_type=...)`
- Apply **specialized** profiles only (DIGIT / DATE / CURRENCY) before recognition
- Unmatched fields (names, free text) keep **REGIONAL_DEFAULT** (legacy blind ≤3×) — Golden V2 crop probes show NAME_STROKE / GENERAL_TEXT destroy readable names
- Skip blind 3× upscale when a specialized profile already includes `upscale_2x`
- Record real profile in provenance
- Expected: recover OCR-empty (esp. currency) and digit/date character errors without regressing names

### S2 — Bounded cause-driven OCR recovery (uses new recovery planner)
- On empty/rejected regional OCR with explicit OCR signal: `diagnose(..., ocr_attempted=True)` → `plan_recovery(ALTERNATIVE_OCR)`
- At most **one** alternate profile attempt (e.g. `GENERAL_TEXT` fallback)
- Never blind retry; never guess templates

### S3 — Localization residuals (next release if still <90%)
- Address 7 wrong-localization + 2 under-crop errors only after S1/S2 measured

### S4 — Critical-field gate (≥95%)
- Separate evidence/HITL path (Phase 8.10B E6-style); do not loosen accept precision

## Safety gates (must hold)

- Accepted precision remains 100% / critical false accepts remain 0
- No new OCR engine, no cloud OCR, no second unbounded OCR cascade
- Recovery max_attempts = 1 when executable
- Measure on frozen Phase 8.10 / Golden Pack V2 — do not invent a new benchmark

## Out of scope for this unit

- Geometry algorithm rewrite
- Validator / business-rule relaxation
- Engineering Benchmark CMS12 corpus restore (separate BLOCKED track)
- Blind retries

## Success criteria

1. Unit tests prove field-profile resolution + single alternate OCR recovery path  
2. Regional provenance emits concrete profile ids  
3. On the frozen accuracy replay (when artifacts available): overall Exact **≥90%** with no safety regression  
4. If replay artifacts absent locally: code change is complete and measurement is gated as `PENDING_REPLAY`

## Measurement status

| Track | Status | Notes |
|---|---|---|
| Phase 8.10 frozen replay (420 fields, 89.05% baseline) | `PENDING_REPLAY` | `evaluation_data/phase8_8_generalization` and `evaluation_results/phase8_10` artifacts absent here |
| Unit proofs (S1/S2 wiring) | PASS | regional profile OCR, OCR recovery, recovery planner, glyph-merge |
| Golden V2 CMS001 crop probe (proxy, not governed gate) | 8/11 soft-Exact after normalize | Names keep REGIONAL_DEFAULT; NPI/DOB/CPT/currency recover; service_date/relationship/diagnosis remain residual |
| Safety | HOLD | No accept-threshold changes; recovery max_attempts=1; REGIONAL_DEFAULT empty does not alternate into digit prep |
