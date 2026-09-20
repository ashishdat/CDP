# Safe 94% STP path — authorized reference (post evidence-integrity)

## Current blockers (locked-50)

| Bucket | Count | Resolution |
|---|---|---|
| `total_charge` / `LINE_SUM_UNCORROBORATED` | ~11 | Local dual-engine / gpt-4o line corroboration only — **never** invent Box 28 from Σ |
| `total_charge` / `CALIBRATION_HITL` | ~5 | Fail-closed until calibrated; no threshold fit |
| `total_charge` / `EVIDENCE_POLICY_GAP` | ~5 | Need E4/E6 evidence path |
| `patient_dob` / `patient_name` | 1–2 | **Authorized member reference** (this package) |
| Empty-blocker field-ink HITL | ~3 | Same identity path when ID is AUTO |

## Techstack plan

1. **Keep evidence-integrity invariants** (already on `86087ac`): exact Box28↔24F, no line-sum rewrite of totals.
2. **Lane A — printed OCR**: paddle/rapid/tess + geometry cents; charge FA guards stay.
3. **Lane B — gpt-4o crop**: residual corroboration for lines when Box 28 empty (existing cascade).
4. **Lane C — authorized reference** (this change): exact verified member ID → operator index → name/DOB AUTO with `AUTHORIZED_REFERENCE` audit. Abstain without index.
5. **Never**: Golden/agent labels, DI removal as STP lever, reference-filled `total_charge`.

## Honest measurement bar

Claim ≥47/50 TRUE_STP only with zero critical false accepts **and** an operator-authorized index covering residual identity claims. Without `CDP_AUTHORIZED_MEMBER_INDEX`, STP must not inflate.
