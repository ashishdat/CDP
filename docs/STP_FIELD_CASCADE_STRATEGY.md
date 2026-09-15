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
| **Field preprocess in cascade** | Apply Phase 8.10 `CURRENCY_DECIMAL_V2` to charge crops only; DOB/name/ID keep full-page bbox OCR. |
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

## Sample B Phase 2 result

| Metric | Cascade v1 | Phase 2 |
|--------|------------|---------|
| True STP | 0/6 | 0/6 |
| `total_charge` auto | 0/6 | **5/6** |
| `patient_dob` auto | 2/6 | 2/6 |
| `total_charge` blockers | 6 | **1** |

Metrics: `docs/metrics/sample_b_cascade_v2_metrics.json`.

## Phase 3 — evidence completeness (v3) — current

Phase 2 cleared the financial wall (`total_charge` 5/6) but **true STP stayed 0/6**.
Root cause was not OCR engine capacity: `insured_name` had OBSERVED, NAME_SHAPED
candidates that decision stripped as `CANDIDATE_ROUTE_AUTHORITY_MISSING` because
the field was absent from `config/ocr_field_routes.yaml`. Residual DOB misses
were fragmented digit streams (`04 1 了 .9 9 1 1`) aborted before compact assembly.

### Strategy / architecture (reframed)

| Change | Why |
|--------|-----|
| **`insured_name` route authority** | Parity with `patient_name` so OBSERVED OCR can enter evidence / STP |
| **Name span: strip headers first** | Prefer ink below CMS parenthetical; reject `NATE, MIDALE` boilerplate |
| **DOB compact recovery** | CJK confusables (`了→7`); do not abort on 1-digit year mid-stream; repair leading-`1` loss on `19xx` years from observed digits only |
| **Cascade id `field-cascade-v3`** | Marks evidence-completeness phase (not a new OCR stack) |

### Tech-stack decision

**Keep Python + RapidOCR (Paddle primary in routes, Rapid runtime).** Bottleneck was
evidence-architecture completeness (missing routes, span assembly, claim blockers),
not Python vs cloud DocVQA. Defer Donut/LayoutLM/Textract until residual ink cannot
be recovered by crop/span/route completeness.

### Honesty / STP rules (unchanged)

- No invented amounts or DOBs
- No waiving identity gates
- `insured_name` still blocks STP when unresolved; route authority lets real ink count

## Sample B Phase 3 result

| Metric | Phase 2 | Phase 3 |
|--------|---------|---------|
| True STP | 0/6 | **2/6** |
| `insured_name` auto | 0/6 | **6/6** |
| `patient_dob` auto | 2/6 | **3/6** |
| `total_charge` auto | 5/6 | 5/6 |

Unlocked STP on IJN2.008 and JJJM.014 once `insured_name` gained route authority.
DOB gain: IJN2.005 (`04 1 了 .9 9 1 1` → `04/17/1991`). Remaining HITL: DOB ink loss (3),
member-id calibration (1), empty total+lines (1).

Metrics: `docs/metrics/sample_b_cascade_v3_metrics.json`.

## Sample B Phase 3 target

Unlock STP on claims that already clear critical fields once `insured_name` is
route-authorized; raise DOB auto without inventing dates.

Artifacts: `evaluation_results/operational_e2e_100_v1_std_sample_b_cascade_v3/`.
