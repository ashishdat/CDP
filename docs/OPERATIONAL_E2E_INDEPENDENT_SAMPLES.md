# Operational E2E — independent live samples (post-ROI fix)

Frozen 100-claim baseline remains **NOT QUALIFIED** (39% completion in frozen ops report / ~43% prior live, **0% true STP**).
These live samples measure the application path after CMS-1500 ROI correction, registration content recovery, and E3/STP wiring.

Document overlap between cohorts: **none**.

## Cohort A — first 5 paired claims

| Metric | Value |
|--------|-------|
| Attempted | 5 |
| FinalClaim completed | **4 / 5 (80%)** |
| True STP | **0 / 5 (0%)** |

Incomplete (1): registration geometry failure after enhancement retry (`insufficient_inliers` / unsafe transform).

## Cohort B — seeded independent sample

| Metric | Value |
|--------|-------|
| Selection | `--live-seed 20260915 --live-limit 10` |
| Attempted | 10 |
| FinalClaim completed | **6 / 10 (60%)** |
| True STP | **0 / 10 (0%)** |

Incomplete (4): registration/template failures (`insufficient_inliers` / `unsafe_perspective` / `template_lineage_mismatch`).

## Comparison

| Cohort | Completion | True STP vs frozen 39% / 0% |
|--------|------------|-----------------------------|
| A (n=5) | 80% | ↑ completion, STP unchanged at 0% |
| B (n=10) | 60% | ↑ completion, STP unchanged at 0% |

## Shared STP blockers (completed claims)

Every completed claim has `review_required=true` / `FIELD_REVIEW_REQUIRED`. Dominant critical blockers:

1. `patient_dob` — empty / `NORMALIZATION_FAILED` (often also listed in `missing_fields`)
2. `total_charge` — empty, low calibrated confidence, or `SUSPICIOUS`
3. `patient_name` — sometimes `SUSPICIOUS` from form-label bleed in OCR text
4. `diagnosis_codes` — OCR includes printed form labels → invalid ICD tokens
5. Secondary: `federal_tax_id`, `patient_sex`, `amount_paid`, `rel_code`

## Verdict

ROI correction improved identity OCR vs insurance-row bleed, and sample completion beats the frozen **39%** baseline, but **true STP remains 0%**. Next gates: strip form-label text from OCR values, fix DOB/charge empty-crop recovery, then re-qualify on the full 100.

Machine-readable: `docs/OPERATIONAL_E2E_INDEPENDENT_SAMPLES.json`.
