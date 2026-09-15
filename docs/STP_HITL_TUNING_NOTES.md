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
