# STP field-cascade architecture v6

## Why redesign

Cascade v1–v5 recovered Sample B STP by bolting crop retries, span repairs, and
completion injections onto a strategy document that the orchestrator did not
load. Version ids drifted (`v3` YAML / `v4` class default / `v5` runtime). The
v6 redesign makes **one declared architecture** the source of truth.

## Design principles (from Sample B)

1. **Crop/OCR first, never policy softening** — recover observed ink; do not
   invent DOBs/amounts or waive identity gates to chase STP.
2. **Always span-select before accept** — even when OCR returns non-empty text.
3. **Typed crop ladders are first-class** — digit-band, year-wide, NPI-cleared,
   declared in YAML and ordered by the orchestrator.
4. **Post-miss stages are declared** — DOB cell OCR runs only when configured
   under `post_miss`, after the crop ladder misses.
5. **Completion E6 is observed-ink derivation** — empty box-28 + observed line
   charges → `LINE_TOTALS_RECONCILED`; never a synthetic total.
6. **Honest HITL taxonomy** — residual gaps get a gap class
   (`HANDWRITING_UNREADABLE`, `AMBIGUOUS_DIGIT_FRAGMENTS`,
   `EMPTY_FINANCIAL_INK`, `NPI_CONTAMINATED_CHARGE`) instead of silent fail.

## Pipeline

```
GeometryResult (rectified)
  → ROI inset
  → crop ladder × route engines
  → span select → semantic accept
  → post_miss (e.g. dob_cells)
  → service-line OCR
  → rank → validate → assemble
  → complete (LINE_TOTALS_RECONCILED when eligible)
  → FinalClaim (true STP ⇔ completed ∧ review_required=false)
```

## Source of truth

| Artifact | Role |
|----------|------|
| `config/field_cascade_strategy.yaml` | Strategy id, stages, crop ladders, post_miss, honesty, gap classes |
| `config/ocr_field_routes.yaml` | Governed engine order per field |
| `packages/extraction_recovery/strategy.py` | Loader |
| `packages/extraction_recovery/field_cascade.py` | Crop×engine orchestrator (`field-cascade-v6`) |
| `packages/extraction_recovery/gap_taxonomy.py` | Residual HITL classification |
| `scripts/ocr_from_geometry.py` | Ops OCR entry |
| `scripts/reprocess_ops_cascade.py` | Cohort reprocess + STP/HITL metrics |

## Measurement

- **Tuning cohort**: Sample B (`fix_sample_b`) — used to discover v5 levers.
- **Independent ops cohort**: Sample A (`fix_sample`) — STP / HITL / blockers.
- **Independent accuracy cohort**: Golden Pack V3
  (`evaluation_data/phase8_7_golden_pack/...`) — exact accuracy + hard HITL +
  STP proxy (extraction harness; identity forced verified).

Do not treat Sample B re-scores as independent generalization evidence.
