# STP pipeline architecture v9

## Why revisit v8

Stopped Hackathon-1000 cascade-v8 partial (**n=309**) showed real gains over v7
but left three architecture gaps:

| Gap | Evidence (v8 n=309) | Learning |
|---|---|---|
| Confirmation OCR observed but **ignored at pick time** | Cascade took the first engine's text; primary header bleed blocked STP even when Rapid had a date | Dual-engine must **select**, not only run |
| `insured_id` **CALIBRATION_HITL** (11) | Format-valid IDs ~0.96–0.97 under C3 0.98 with paddle∩rapid agree unused for floor | Multi-engine agreement is corroboration |
| Metrics incomplete for ops steering | Accuracy unmarked; STP/HITL not rolled up **by bundle** | Report UNAVAILABLE accuracy + by_group/by_bundle |

Frozen: `evaluation_results/hackathon_1000_cascade_v8/` (+ engines run superseded by v9).

## Past learning → architecture law

1. **Crop/OCR first, never invent** — empty/ambiguous ink stays HITL; no DOB/amount fabrication; never waive E3/C2/C3 identity gates to chase STP.
2. **Two HITL tracks** — (A) registration/geometry failure; (B) field-ink after evidence-complete decision. Report separately.
3. **Typed crop ladder × governed routes** — `field_cascade_strategy.yaml` + `ocr_field_routes.yaml` are source of truth.
4. **Always span-select before accept** — even when OCR is non-empty (v4).
5. **Dual-engine confirmation** — OCRRouter requires **2 usable OBSERVED** engines before short-circuit when ≥2 engines are listed; primary remains the selected attempt once confirmation has run.
6. **Agreement-aware pick (v9)** — among candidates prefer span-normalized multi-engine agreement; else first field-shaped value in route order.
7. **Honest taxonomy** — plumbing / calibration ≠ handwriting.
8. **Accuracy honesty** — Hackathon 1000 has no field GT → `accuracy.status = UNAVAILABLE_NO_GROUND_TRUTH`; use Golden Pack for exact accuracy when needed.
9. **Completion E6** — `LINE_TOTALS_RECONCILED` only from observed service-line charges.

## Pipeline

```
register (+ recovery ladder / contrast-stretch)
  → geometry + ROI inset
  → crop ladder
  → OCRRouter(primary → confirmation → fill)   # require 2 usable
  → pick_engine_candidates (agreement > shaped > nonempty)
  → semantic accept → post_miss (dob_cells)
  → service-line OCR
  → rank → validate → assemble → complete (E3/E6)
  → decide (true STP ⇔ completed ∧ ¬review)
  → gap taxonomy + metrics (overall / by_group / by_bundle)
```

## Source of truth

| Artifact | Role |
|----------|------|
| `config/field_cascade_strategy.yaml` | **field-cascade-v9** stages, ladders, honesty, metrics duties |
| `config/ocr_field_routes.yaml` | Primary / confirmation engines per field |
| `packages/ocr_router.py` | Dual usable confirmation short-circuit |
| `packages/extraction_recovery/field_cascade.py` | Crop×engine + `pick_engine_candidates` |
| `packages/candidate_reconciliation/reconciler.py` | DATE / identity / multi-engine ID corroboration floors |
| `scripts/run_hackathon_1000_cascade.py` | Ops STP/HITL/accuracy/OCR-cascade rollups |

## Decision corroboration (not policy waivers)

| Signal | Floor | Reason code |
|--------|-------|-------------|
| DOB `DATE_VALID` + hard validation | 0.80 | `DATE_CORROBORATED_THRESHOLD_RELIEF` |
| Member ID + relationship E6 + hard validation | 0.95 | `IDENTITY_CORROBORATED_THRESHOLD_RELIEF` |
| Member ID + multi-engine agreement + hard validation | 0.95 | `MULTI_ENGINE_ID_CORROBORATED_THRESHOLD_RELIEF` |

## Metrics contract

Every summary (overall, `by_group`, `by_bundle`) reports:

- `registration_ok_rate` (Track A inverse)
- `completion_rate`
- `true_stp_rate_of_all` / `true_stp_rate_of_completed`
- `hitl_rate_of_all` / `field_ink_hitl_rate_of_completed` / `registration_hitl_rate`
- `accuracy.status` = `UNAVAILABLE_NO_GROUND_TRUTH` on Hackathon corpus
- `ocr_cascade`: engines attempted/observed/unavailable + `cascade_healthy` (paddle∩rapid)

Retest: `evaluation_results/hackathon_1000_cascade_v9/` (`--no-resume`).
