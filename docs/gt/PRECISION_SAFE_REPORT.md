# Locked-50 precision-safe result (geometry cents)

Run: `evaluation_results/hackathon_50_geometry_v4`  
Template: `cms1500@03` (`CDP_PIPELINE_RELEASE=extraction-v3`)  
Workers: 1, pools off, `--offset 0 --limit 50 --no-resume`  
Compared with `evaluation_results/hackathon_50_box28_v3` (18/50 STP). Thresholds were not changed.

## Score

| Metric | Box 28 baseline | This run |
|---|---|---|
| Terminal | 50/50 | **50/50** |
| Registration | 50/50 | 50/50 |
| Stage failures | 0 | 0 |
| True STP | 18/50 | **32/50** |
| Claim HITL | 32/50 | **18/50** |
| Critical blockers | `total_charge` 31, `patient_name` 5, `patient_dob` 1 | `total_charge` 15, `patient_name` 4, `patient_dob` 1 |

This is not a 99.5% precision claim and not a 47/50 release. No confidence threshold was fitted.

## Critical false accepts

Two accepted totals disagree with the printed Box 28 and with the service-line sum. Both were already True STP on the Box 28 baseline, so they are not new accepts from this change. They are still wrong:

| Claim | Accepted | Printed Box 28 | Line sum |
|---|---|---|---|
| DJJM.014 | 212400.00 | 212.00 | 212.00 |
| DJJM.028 | 400406.00 | 400.00 | 200.00 + 200.00 |

Every other True STP total equals the sum of the accepted Box 24F rows.

An intermediate geometry run (`hackathon_50_geometry_v3`) auto-accepted DJJM.010 as 4972.00. The cents ruling on that page splits the same four digits as 49.72. That accept was removed. DJJM.010 is HITL again (`GPT4O_LOCAL_NEEDS_BOX28`). The line window still reads 4972.00, so the claim is not promoted.

No 2701 units bleed was accepted. No three-digit amount was split into dollars and cents.

## Nine printed targets

None of these nine is still blocked on `total_charge`, so no new diagnostic bundle was added. Earlier crops remain under `evaluation_results/box28_diagnostics` (not committed).

| Claim | Disposition | total_charge | Notes |
|---|---|---|---|
| DJJF.015 | TRUE_STP | 200.00 | Matches the one service line |
| DJJM.002 | TRUE_STP | 270.00 | Patient name `SAN NICOLAS.WILLIAM` (Box 2 agrees with Box 4) |
| DJJM.005 | TRUE_STP | 270.00 | `MORALES, KENITHA`, Self |
| DJJM.009 | TRUE_STP | 49.72 | Cents column, not 4972.00 |
| DJJM.019 | HITL | 270.00 | Charge agrees (135+135). Blocker is `patient_dob`. Names differ; relationship is not used to force them equal |
| DJJM.023 | HITL | 212.00 | Charge agrees. Blocker is `patient_name` (Box 2 and Box 4 disagree) |
| DJJM.024 | TRUE_STP | 81.00 | Inside Box 28. Relationship is Child, so Box 2 and Box 4 are not forced equal |
| DJJM.026 | TRUE_STP | 212.00 | Matches the one service line |
| DJJM.027 | TRUE_STP | 600.00 | 300.00 + 300.00 |

## Residual HITL (18)

`total_charge`: DJJF.001, DJJF.002, DJJF.003, DJJF.004, DJJM.001, DJJM.008, DJJM.010, DJJM.011, DJJM.012, DJJM.018, DJJM.022, DJJM.029, DJJM.030, DJJM.034, DJJM.035

`patient_name`: DJJM.023, DJJM.025, DJJM.034, DJJM.035

`patient_dob`: DJJM.019

DJJM.011 was True STP on the Box 28 baseline and is HITL here. That is a fail-closed loss, not a new accept. DJJM.025, DJJM.034, and DJJM.035 stay handwritten / overprinted. No authorized member index was set.

## What each correction contributed

Box 28 crop. The caption-excluded value band is what the production crop uses. It is why 270.00, 200.00, 212.00, 81.00, and 600.00 stopped reading the box title or Box 29. Recovered from the baseline: DJJF.007, DJJF.011, DJJF.012, DJJM.002, DJJM.003, DJJM.004, DJJM.005, DJJM.015, DJJM.020, DJJM.021, DJJM.024, DJJM.026, DJJM.027.

Implied decimal. Character x-coordinates against the cents ruling, not a visible dot alone. DJJM.009 is 49.72. DJJM.013 is 34.25 (a ruling tick had been read as `1` inside `34125`). DJJM.010 uses the same rule and is held for review because Box 24F on the winning window is still 4972.00. A two-place shift (`49.72` vs `4972.00`) is not treated as agreement. Raw text `4 972` is not a Box 28 total.

Box 24F reconciliation. Accepted totals on this run match the line sum except the two pre-existing concatenations above. Pointer windows whose center is outside the charge column are rejected. A clipped window cannot outrank a cents-column read.

Box 2 / Box 4 names. Under Self, the stored OCR value keeps an already-printed longer surname when Box 4 agrees. DJJM.002 is `SAN NICOLAS.WILLIAM`, not `NICOLAS, WILLIAM`. Non-Self claims are not forced equal (DJJM.024 Child). Disagreement stays HITL (DJJM.023).

Box 3 / Box 11a DOB. No new DOB accept in this pass. DJJM.019 remains the only DOB blocker.

## What this does not authorize

- Do not lower a confidence threshold to turn the 18 HITL claims into STP.
- Do not treat 32/50 as production precision while DJJM.014 and DJJM.028 are accepted.
- Do not add another OCR engine for the remaining charge HITL. The open gap is still cents-column geometry on the service-line window, which is why DJJM.010's line can still read 4972.00.
