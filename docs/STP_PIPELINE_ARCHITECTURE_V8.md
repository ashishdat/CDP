# STP pipeline architecture v8

## Why stop the v7 1000-run and redesign

Stopped Hackathon-1000 mid-run after **n=521** under field-cascade-v7:

| Metric (n=521) | Value | Meaning |
|---|---|---|
| Registration OK | 320/521 (61.4%) | ~39% never reach field cascade |
| Completed | 320 | Geometry → OCR → complete finished |
| True STP | 201/320 completed (62.8%); 201/521 all (38.6%) | Residual Track-B HITL still large |
| Critical blockers | patient_dob **105**, insured_id 37, name 16, charge 3 | DOB dominates field HITL |
| Registration buckets | catastrophic 74, inlier+perspective 76, perspective 22, low-inlier 21 | Ladder under-recovered multi-gate |

Frozen artifacts: `evaluation_results/hackathon_1000_cascade_v7/` (+ `partial_summary.json`).

## Gap taxonomy (honest)

| Observed class | Real failure | v8 fix |
|---|---|---|
| `patient_dob` + `CANDIDATE_ENGINE_NOT_AUTHORIZED` | `dob_cells` engine not in route families → assembled date stripped | Attribute cell assembly to producing route engine |
| `HANDWRITING_UNREADABLE` with header digit ink | Compact `D→0` poison + missing trailing-1 peel / MMDDYYY century | Header-safe compact; trailing-1 MM/DD; 7-digit century-first |
| `AMBIGUOUS_DIGIT_FRAGMENTS` on calendar-valid ISO dates | Calibrated confidence ~0.88–0.91 under C2 0.92 | `DATE_CORROBORATED_THRESHOLD_RELIEF` (floor 0.80) when `DATE_VALID` |
| Registration multi-gate | One CLAHE enhance insufficient | Second contrast-stretch preprocess; same template/gates |

## Architecture principles (unchanged)

1. Artifact contracts over incidental files.
2. Evidence before disposition — never invent DOB/amounts; never waive E3/C2/C3 identity gates.
3. Two HITL tracks — (A) registration/geometry, (B) field-ink after evidence-complete decision.
4. Honest taxonomy — plumbing/calibration ≠ handwriting.

## Registration ladder (v8)

```
primary
  → cause-specific enhance (IMAGE_ENHANCEMENT | ALTERNATIVE_REGISTRATION)
  → optional CONTRAST_STRETCH_SECOND_PREPROCESS (if still failing on poor-scan / geometric tokens)
```

Same accepted template. Same inlier / perspective / scale gates. No invented landmarks.

## Field cascade (v8)

`config/field_cascade_strategy.yaml` → **field-cascade-v8**

DOB path additions:

- Trailing edge-1 peel on 3-digit MM/DD (`051 291 196` → `05/29/1996`)
- Header-safe compact (strip `MM`/`DD`/`YY` before `D→0` confusable)
- MMDDYYY century repair before mid-stream `1` insert (`0929196` → `09/29/1996`)
- Single-char confusable tokens (`L` → `1`)
- `dob_cells` candidates use producing OCR engine (route-authorized)

Decision path:

- `DATE_VALID` + `HARD_VALIDATION_PASSED` → calibrated floor 0.80 (corroboration, not invention)

## Metrics rules

Report separately:

- `registration_ok_rate`
- `true_stp_rate` (completed ∧ ¬review)
- `field_ink_hitl_rate` (Track B)
- `registration_hitl_rate` (Track A)

Retest corpus: `evaluation_results/hackathon_1000_cascade_v8/` (`--no-resume`).
