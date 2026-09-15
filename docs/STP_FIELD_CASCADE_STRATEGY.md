# STP field-cascade OCR strategy

## Why redesign

The previous ops OCR path stopped at the first non-empty RapidOCR result and
bolted field-specific crop retries onto `recognize_regions`. That fought the
governed field routes (Paddle primary → Rapid confirmation) and left DOB /
charge recovery as ad-hoc special cases.

## New pipeline contract

```
geometry (saved)
  → field-cascade OCR          # crop × route engines × span × semantic accept
  → rank
  → validate
  → assemble (forwards service_lines)
  → complete (evidence + claim STP; E6 = crop total ∩ Σ lines)
```

### Cascade steps (per field)

1. **Crop ladder** — typed variants from the safe cell (digit-band DOB,
   NPI-cleared charge, name/id value band, charge-column x-windows).
2. **Route engines** — order from `config/ocr_field_routes.yaml`
   (primary → confirmation → tesseract fallback).
3. **Span selection** — segment observed characters only; never invent.
4. **Semantic accept** — stop only when the value is field-shaped
   (`DATE_SHAPED`, `CURRENCY_SHAPED`, `NAME_SHAPED`, `ID_SHAPED`).

### Honesty / STP rules

| Situation | Outcome |
|-----------|---------|
| DOB digit band yields `MM/DD/YYYY` | Auto-eligible for evidence path |
| Box 28 empty / NPI bleed / leading-minus glyph | Empty → HITL (no invented total) |
| Service-line charges recovered | Used for E6 **only if** crop total matches Σ |
| Name/ID label bleed cleaned by span | Auto-eligible when format validates |

True STP still requires every critical field resolved without review. Cascade
raises recovery rate; it does not waive empty financial crops.

## Code

- `packages/extraction_recovery/field_cascade.py` — strategy + orchestrator
- `packages/ocr_router.py` — optional per-call `engine_order`
- `scripts/ocr_from_geometry.py` — ops OCR stage uses `FieldCascade`
- `config/field_cascade_strategy.yaml` — declared ladder / accept codes
