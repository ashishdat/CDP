# Operational E2E — independent live samples (post STP/HITL tuning)

Frozen 100-claim baseline remains **NOT QUALIFIED** (~39% completion, **0% true STP**).

After CMS-1500 ROI correction + this STP/HITL tuning pass, independent completed claims were **reprocessed** through validate → assemble → complete (same OCR crops; span cleanup + policy/reconciler changes applied).

Document overlap between cohorts A and B: **none**.

## Cohort completion (unchanged selection)

| Cohort | Selection | FinalClaim completed | True STP |
|--------|-----------|----------------------|----------|
| A | first 5 paired | **4 / 5 (80%)** | **0 / 5 (0%)** |
| B | seed `20260915`, n=10 | **6 / 10 (60%)** | **0 / 10 (0%)** |

## Critical-field auto-accept after retune (10 previously completed claims)

| Field | AUTO_ACCEPTED | Notes |
|-------|---------------|-------|
| `patient_name` | **8 / 10** | Box-header / label bleed stripped |
| `insured_id_number` | **7 / 10** | Trailing ID span + C3 format-valid path |
| `patient_dob` | **1 / 10** | Token assembly when MM/DD/YY digits present |
| `total_charge` | **0 / 10** | Empty / NPI bleed → HITL (no invented amounts) |

Best case (`Group A/M048DJJM.012`): only **`total_charge`** remains as a critical blocker; name, ID, and DOB auto-accepted.

## Remaining HITL gates

1. **`total_charge`** — NPI-label bleed or empty crop; span correctly empties contaminated OCR rather than accepting `$1.00`
2. **`patient_dob`** — empty or un-assemblable digit noise on most forms
3. Residual name/ID OCR damage when no clean `LAST, FIRST` / ID token exists

## Tuning shipped in this pass

- Wire `select_field_span` into ops OCR + validate
- CMS-1500 header/label span cleanup; DOB token assembly; NPI-bleed → empty currency
- `require_strong_e4: false` for identity/DOB fields; honor explicit opt-out for C2/C3
- Claim E6: `rel_code` + inferred SELF when patient/insured names match
- C3 reconciler: format-valid `insured_id_number` clears independent-engine hard fail

Machine-readable: `docs/OPERATIONAL_E2E_INDEPENDENT_SAMPLES.json`, `docs/STP_HITL_TUNING_NOTES.md`.
