# Locked-50 precision-safe result (Box 28 authority)

Run: `evaluation_results/hackathon_50_box28_v3`  
Template: `cms1500@03` (`CDP_PIPELINE_RELEASE=extraction-v3`)  
Date: 2026-09-19

## Score

| Metric | Result |
|---|---|
| Terminal | 50/50 |
| Registration | 50/50 |
| Stage failures | 0 |
| True STP | **18/50** |
| HITL | **32/50** |
| Critical blockers | `total_charge` 31, `patient_name` 5, `patient_dob` 1 |

This is not a 99.5% precision claim. Thresholds were not fitted. The previous 38/50 STP used line-sum AUTO without a readable Box 28 and carried 30 critical false accepts. This run requires independent Box 28 / DI corroboration before a charge AUTO. Coverage dropped because that gate is fail-closed, not because registration failed.

## Nine printed residuals

| Claim | Disposition | Blockers | Notes |
|---|---|---|---|
| DJJF.015 | TRUE_STP | — | Box 28 `200.00` matches line sum |
| DJJM.002 | HITL | name, total | Box 28 `210` conflicts with line `270` |
| DJJM.005 | HITL | total | Box 28 `270` conflicts with line sum `111` |
| DJJM.009 | HITL | total | Box 28 unshaped; line sum `49` not `4972` |
| DJJM.019 | HITL | dob, total | Box 28 junk (`97600` / `27`); lines `135+135` |
| DJJM.023 | HITL | name, total | Box 28 `242` conflicts with line `212` |
| DJJM.024 | HITL | total | Box 28 `100` / `810` conflicts with line `81` |
| DJJM.026 | HITL | total | Box 28 `5212` conflicts with line `212` |
| DJJM.027 | HITL | total | Box 28 `600` conflicts with incomplete line sum `80+300` |

Only **DJJF.015** of the nine printed residuals became True STP. The other eight stay HITL because the live digits-first crop still reads caption bleed or the service-line sum does not match the Box 28 read. That is the correct fail-closed outcome. It is not yet the 38→47 recovery.

## Three hard residuals

| Claim | Disposition | Blockers |
|---|---|---|
| DJJM.025 | HITL | `patient_name` only (charge reconciled) |
| DJJM.034 | HITL | `patient_name`, `total_charge` |
| DJJM.035 | HITL | `patient_name`, `total_charge` |

`.025` charge is corroborated; the remaining blocker is the overprinted name. `.034` and `.035` stay handwritten residuals. No authorized member index was configured (`CDP_AUTHORIZED_MEMBER_INDEX` unset), so the structured join abstained. These three are not to be resolved by another OCR guess.

## What this does not authorize

- Do not lower the Box 28 gate to recover the old 38/50.
- Do not fit confidence thresholds on this run.
- Do not treat 18/50 as production precision.
- Do not use the 300-claim diagnostic to tune the same model.

## Next extraction work (not threshold work)

Digits-first Box 28 crops are still mixing the caption (`28. TOTAL CHARGE`) into the amount (`210` vs `270`, `5212` vs `212`). The value-only band needs to win before digits-first, and line rows that drop a populated service line (`.027` `80+300` vs Box 28 `600`) must not veto a geometrically verified Box 28. Until those reads agree, the honest HITL count stays well above 3.
