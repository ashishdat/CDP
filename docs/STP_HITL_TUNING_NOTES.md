# STP / HITL tuning notes (post-ROI independent samples)

## Changes
1. **CMS-1500 OCR span cleanup** wired into ops OCR + validate (`select_field_span`):
   - Strip box headers / label bleed for names and member IDs
   - Assemble DOB from MM/DD/YY digit tokens; reject invalid assemblies
   - Treat NPI-contaminated total-charge crops as empty (HITL), not `$1.00`
2. **Evidence policy**: `require_strong_e4: false` for `patient_name`, `insured_name`, `insured_id_number`, `patient_dob`; honor explicit opt-out for C2/C3 in `EvidencePolicy._qualified_available`
3. **Claim E6**: read `rel_code`; infer SELF when patient/insured names match; attach to identity fields
4. **C3 reconciler**: format-valid `insured_id_number` satisfies independent-evidence gate after hard validation

## Reprocess metrics (10 previously completed live claims)

| Metric | Value |
|--------|-------|
| True STP (`review_required=false`) | **0 / 10** |
| Dominant remaining blockers | `{'total_charge': 10, 'patient_dob': 9, 'patient_name': 2, 'insured_id_number': 3}` |
| Auto-accepted critical fields | `{'insured_id_number': '7/10', 'patient_name': '8/10', 'patient_dob': '1/10', 'total_charge': '0/10'}` |

## HITL queue (honest remaining gates)
- **`total_charge`**: empty / NPI bleed after span — needs ROI retarget or line-charge E6, not policy waiver
- **`patient_dob`**: empty or un-assemblable OCR tokens on many forms
- **`insured_id_number` / `patient_name`**: residual OCR damage when span cannot recover a clean value

Frozen 100-claim baseline remains NOT QUALIFIED until a full live 100 re-run.

## Charge ROI / line-total E6 + DOB crop reliability (next hard gates)

1. **OCR crop insets** (`packages/extraction_recovery/roi_insets.py`) shrink `patient_dob` and `total_charge` inside the recorded safe cell so header/NPI bleed is excluded without re-registration. Template ROIs retargeted to the same windows.
2. **Service-line charge OCR** in `scripts/ocr_from_geometry.py` writes `service_lines` onto OCR candidates; assemble + complete pass them into `ClaimEvidenceBuilder` so `CLAIM_TOTAL_CONFIRMED` (E6) can auto-accept `total_charge` when the crop total matches Σ line charges.
3. **Authoritative financial E6** enabled on `EvidenceReconciler` so a confirmed claim-total can clear the C3 confidence gate without inventing amounts.
4. **DOB token assembly** keeps edge-glyph stripping; currency span rejects NPI-adjacent `$1.00` artifacts.

Still not an identity-policy waiver. Empty/contaminated crops remain HITL.

## Reprocess after charge ROI / DOB crop gates (independent sample B)

| Metric | Value |
|--------|-------|
| Completed claims reprocessed | 6 / 6 |
| True STP (`review_required=false`) | **0 / 6** |
| `patient_dob` auto-accepted | **1 / 6** |
| `total_charge` auto-accepted | **0 / 6** |

Tight charge crops clear NPI bleed; empty box-28 digit bands and pointer-bleed line charges stay HITL (no invented amounts).

## Strategy redesign: field-cascade OCR (v1)

Replaced RapidOCR-first + bolted crop retries with a governed cascade:

1. Typed crop ladder (DOB digit band, NPI-cleared charge, name/id value bands, charge x-windows)
2. Route engines from `config/ocr_field_routes.yaml` (Paddle → Rapid → Tesseract)
3. Span selection (observed characters only)
4. Semantic accept (`DATE_SHAPED` / `CURRENCY_SHAPED` / …) before stopping

Honesty unchanged: empty/contaminated box-28 stays HITL; E6 only when crop total matches Σ line charges.
See `docs/STP_FIELD_CASCADE_STRATEGY.md`.

### Sample B after cascade redesign

| Metric | Prior (crop bolts) | Cascade v1 |
|--------|--------------------|------------|
| True STP | 0 / 6 | _(reprocess)_ |
| `patient_dob` auto | 1–2 / 6 | _(reprocess)_ |
| `total_charge` auto | 0 / 6 | 0 / 6 expected unless real ink |
| `patient_name` auto | ~6 / 6 | keep |
| `insured_id_number` auto | ~5 / 6 | keep |

