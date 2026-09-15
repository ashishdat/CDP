# STP field-cascade OCR strategy

## Phase 1 — cascade redesign (v1)

The ops OCR path previously stopped at the first non-empty RapidOCR result and
bolted field-specific crop retries onto region recognition. That fought the
governed field routes (Paddle primary → Rapid confirmation) and left DOB /
charge recovery as ad-hoc special cases.

```
geometry (saved)
  → field-cascade OCR          # crop × route engines × span × semantic accept
  → rank → validate → assemble (forwards service_lines)
  → complete (evidence + claim STP)
```

### Cascade steps (per field)

1. **Crop ladder** — typed variants from the safe cell (digit-band DOB,
   NPI-cleared charge, name/id value band, charge-column x-windows).
2. **Route engines** — order from `config/ocr_field_routes.yaml`.
3. **Span selection** — segment observed characters only; never invent.
4. **Semantic accept** — stop only when the value is field-shaped.

## Phase 2 — tuning (v2) — current

Cascade v1 left sample B at **0% true STP**. Dominant walls: empty box-28
`total_charge` and residual DOB misses. Service-line OCR often aborted on the
printed header row before any charge ink was read.

### Architecture changes

| Change | Why |
|--------|-----|
| **Line-sum financial path** | When box-28 OCR is empty but ≥1 currency-shaped **observed** line charges exist, emit `LINE_TOTALS_RECONCILED` (Σ lines) and inject that amount as the `total_charge` candidate. Provenance: `DERIVED_FROM_OBSERVED_LINE_CHARGES`. Not the same as crop∩Σ `CLAIM_TOTAL_CONFIRMED`. |
| **Service-line probe** | Skip leading header/blank rows; stop only after a live charge block ends. Charge-column currency can prove liveness when date/CPT probes fail. |
| **Field preprocess in cascade** | Wire Phase 8.10 profiles (`DATE_DELIMITER_V2`, `CURRENCY_DECIMAL_V2`) onto cascade crops before route engines run. |
| **C3 financial authority** | `LINE_TOTALS_RECONCILED` satisfies the C3 independent-evidence gate when `allow_authoritative_financial_e6` is on (already true in the operational decision profile). |

### Honesty / STP rules (unchanged intent)

| Situation | Outcome |
|-----------|---------|
| DOB digit band yields `MM/DD/YYYY` | Auto-eligible for evidence path |
| Box 28 empty **and** no observed line charges | Empty → HITL (no invented total) |
| Box 28 empty **and** observed line charges sum | `LINE_TOTALS_RECONCILED` → auto-eligible for `total_charge` |
| Box 28 crop matches Σ line charges | `CLAIM_TOTAL_CONFIRMED` |
| Name/ID label bleed cleaned by span | Auto-eligible when format validates |

True STP still requires every **blocking** field resolved without review.
Cascade + Phase 2 raise recovery; they do not waive identity gates or invent ink.

## Code

- `packages/extraction_recovery/field_cascade.py` — strategy + orchestrator (`field-cascade-v2`)
- `packages/claim_evidence/builder.py` — `LINE_TOTALS_RECONCILED` when box-28 empty
- `packages/candidate_reconciliation/reconciler.py` — financial E6 authority includes line totals
- `scripts/ocr_from_geometry.py` — cascade OCR + preprocess + service-line probe
- `scripts/complete_from_extraction.py` — inject derived total onto authorized OCR shell
- `config/field_cascade_strategy.yaml` — declared ladder / Phase 2 notes
- `config/ocr_preprocessing_phase8_10.yaml` — DOB/currency/charges profiles
Currency preprocess is limited to charge fields — full-page bbox OCR is kept for DOB/name/ID (crop-then-OCR shifted DOB digits on sample B).
