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

## Learning from hackathon_300_cascade_v11 (~260 partial)

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

### OCR stack (unchanged engines, retuned use)

| Engine | Role |
|--------|------|
| PaddleOCR | Primary printed CMS |
| RapidOCR | Independent confirmation |
| Tesseract (+ digits) | Fill after dual-engine miss; DOB cell whitelist; charge digits (authorized) |
| Optional later | TrOCR / handwriting route only for residual `HANDWRITING_UNREADABLE`; VLM for Track-A orientation |

Gates unchanged: no invented ink, no E3 waiver, True STP = `COMPLETED` ∧ ¬`review_required`.

## Metrics duty

Report separately:

- True STP / field-ink HITL / registration HITL / combined HITL
- OCR cascade health (`engines_probe`, per-claim OBSERVED)
- Accuracy = agent consensus GT on labeled fields (not vendor GT); HITL claims included when completed
