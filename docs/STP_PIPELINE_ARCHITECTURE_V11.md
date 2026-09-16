# STP Pipeline Architecture — field-cascade-v11

## Learning from hackathon_50_cascade_v11

| Track | Rate (n=50) | Dominant cause |
|-------|-------------|----------------|
| True STP | 52% | — |
| Field-ink HITL | 34% of all / ~40% of completed | `insured_name` CONFLICT_MARGIN (7), `patient_dob` INVALID/E4 (5+), `insured_id` confidence (7), `patient_name` CONFLICT (3) |
| Registration HITL | 14% | residual DJJM multipage perspective/rotation |
| Combined non-STP | ~48% | Track A + Track B |

### Field root causes (Track B)

1. **Label-contaminated name OCR** — rapid keeps `4. 1NSURED'S NAME … FURST NAME SLOGER CHLOE` while paddle has clean ink; high-confidence header wins ranking → `CONFLICT_MARGIN_TOO_SMALL`.
2. **`semantic_accept` treated headers as `NAME_SHAPED`** — `Middie Initial` / `INSURED'S` residue passed the token gate.
3. **Glued CMS headers** — `PATIENT'SNAMELASTNAME`, `1NSURED'S` (I→1) escaped the box-header regex.
4. **Token-prefix names** — `ORR JAMES` vs `ORR JAMES ANTHONY` treated as conflict.
5. **Single-letter OCR substitution** — `CAITEIN` ↔ `CAITLIN` (E↔L) treated as conflict.
6. **ID header-only crops** — `1a.INSURED'SI.D.NUMBER…` outranked shaped member IDs on raw confidence.
7. **Honest residual DOB** — year conflicts (`1967` vs `1961`) and handwriting-only cells stay HITL.

### Registration (Track A)

Near-miss / mild-perspective / orientation ladder (v11 registration recovery) recovered most ratio-only fails. Residual DJJM multipage catastrophic warps remain fail-closed.

## hackathon_300_cascade_v11 FINAL

Independent cohort `docs[50:350]` under `field-cascade-v11` (+ v11.1 live for late claims).

| Metric | Value |
|--------|------:|
| n | 300 |
| TRUE_STP | 118 (39.3%) |
| Field HITL | 107 (35.7%) |
| Registration failed | 75 (25.0%) |
| Combined HITL | 182 (60.7%) |
| TRUE_STP of completed | 52.4% (118/225) |
| Agent-GT exact accuracy | 99.76% (822/824 labeled fields; 2 FA on patient_dob SILVER) |

Accuracy ≠ STP: labeled HITL claims still score; unlabeled hard ink abstains.

## Independent Samples — 300 post-decision v11.4

Decision-only reprocess of the 107 field-HITL claims after reconciler reliefs
(`hackathon_300_field_hitl_decision_reprocess_v11_4`).

| Metric | v11.3 | v11.4 |
|--------|------:|------:|
| True STP | 153 (51.0%) | **161 (53.7%)** |
| Field HITL | 72 | **64** |
| Registration HITL | 75 | 75 |
| Combined HITL | 147 | **139 (46.3%)** |
| Flipped from baseline 118 | +35 | **+43** |
| Agent-GT exact / FA | 822/824 · 2 FA | same (0 new FA on flips) |

v11.4 reliefs: broader name confusables (E↔F/V↔Y/T↔Y/G↔C/L↔T), MRS honorific
peel, SAME/Z junk, glued-vs-spaced names, ID multi-engine corroboration when E2
is empty, FORMAT_VALID ID floor 0.92, member-ID L/I insertion (APU↔APLU), future
DOB reject, and name helpers gated off DOB/ID conflict paths (corrected 3 prior
false STPs that name-MI had wrongly accepted).

## Golden Pack V3 (authoritative truth)

Dataset: `CDP_GOLDEN_ENGINEERING_PACK_V3` (`evaluation_data/phase8_7_golden_pack/...`).
Evaluator: `evaluation/accuracy_100_sample.py` → `evaluation_results/accuracy_100_sample_v3_independent_cascade_v11/`.

| Metric | Value |
|--------|------:|
| n | 100 (50 CMS + 50 UB) |
| Claim STP proxy | **98%** |
| Claim hard HITL | **2%** |
| Exact field accuracy | **99.8%** |
| Critical exact accuracy | 99.71% |
| False accepts | **0** |

Scope: EXTRACTION_HARNESS (identity/template supplied). This is the engineering golden truth for accuracy + STP proxy / hard HITL — not Hackathon agent GT and not ops E2E True STP.


## Learning from hackathon_300_cascade_v11 (historical partial notes)

| Track | Rate | Dominant cause |
|-------|------|----------------|
| True STP | ~38% | — |
| Field-ink HITL | ~36% | name CONFLICT (~65), empty finance (~25), calibration (~21), plumbing (~21), DOB fragments |
| Registration HITL | ~26% | insufficient inliers / perspective / rotation (fail-closed) |
| Combined non-STP | ~62% | Track A + Track B |

### Architecture gaps (and fixes)

| Gap | Why HITL | Fix (v11.1) |
|-----|----------|-------------|
| **Name confusable multi-sub** | paddle `DAVIIA KEVTN` vs rapid `DAVILA KEVIN` → CONFLICT | Allow ≤2 confusable substitutions (I↔L, T↔I, …) as equivalent |
| **Optional middle initial** | `THOMAS DWAYNE` vs `THOMAS S DWAYNE` → CONFLICT | Treat single-letter MI insert as equivalent; prefer longer |
| **Digit-engine authority** | `tesseract_digits` stripped as `CANDIDATE_ENGINE_NOT_AUTHORIZED` on charge/ID | Authorize Tesseract family for DOB/charge/ID; attribute digit fills to paddle |
| **Empty box-28 + missed lines** | Fast digit service-line OCR returned 0 lines → EMPTY_FINANCIAL_INK | Fallback: one paddle/rapid pass on primary charge column |
| **Honest residual** | True handwriting / empty ink / catastrophic registration | Keep HITL; VLM orientation later (deferred) |

Plumbing gaps are **not** ink failures — taxonomy already says `EVIDENCE_PLUMBING_GAP`.

## v11 architecture

```
register → register_recovery → geometry → roi_inset
  → dob_cells_first (MM/DD/YY inset)
  → crop_ladder (name/id value-band FIRST; DOB digit-band; charge NPI-cleared)
  → route_engines (paddle + rapid confirmation; tesseract fill)
  → span_select (CMS header + OCR-garble strip)
  → semantic_accept (reject label-contaminated name/id)
  → engine_agreement → post_miss → assemble → E3/E6 → decide
```

### Name / ID changes

| Stage | Change |
|-------|--------|
| Crop ladder | `name_value_band` / `id_value_band` before `primary` |
| Span | Match `1NSURED` / `FATIENT` / `FURST`; glued `…NAMELASTNAME`; reject `NAME, SLOGER` false pairs |
| Semantic accept | `NAME_LABEL_CONTAMINATED` / `ID_LABEL_CONTAMINATED` never stop the cascade |
| Reconciler | Prefer clean over dirty; token-prefix expansion; E↔L substitution equivalence; shaped ID over header |
| Reconciler v11.1 | ≤2 confusable letter subs; optional middle-initial equivalence |
| Reconciler v11.2 | Last/First token-order bag; glued MI (CL↔L); name digit 0→O; dual-engine ID confidence lift |

### OCR stack (v11.2 tool-fit)

| Engine | Role |
|--------|------|
| RapidOCR / ONNX | **Primary** printed CMS (governed routes) |
| PaddleOCR | Selective secondary confirmation (names/orgs) |
| Tesseract (+ digits) | Selective secondary for dates/digits/IDs |
| Docling | Difficult tables / empty-finance residual (gated) |
| Azure AI cascade | Handwriting / orientation residual (review-only) |
| AWS Textract DetectDocumentText | Cloud-OCR fallback when local exhausted + blocks STP |
| React HITL | Field-level residual queue |

See `docs/STP_TOOL_FIT_ARCHITECTURE_V11_2.md`.

Gates unchanged: no invented ink, no E3 waiver, True STP = `COMPLETED` ∧ ¬`review_required`.

## Metrics duty

Report separately:

- True STP / field-ink HITL / registration HITL / combined HITL
- OCR cascade health (`engines_probe`, per-claim OBSERVED)
- Accuracy = agent consensus GT on labeled fields (not vendor GT); HITL claims included when completed
