# Safe 94% STP path — authorized reference (post evidence-integrity)

## Current blockers (locked-50 decide @ 44/50)

| Bucket | Count | Resolution |
|---|---|---|
| `total_charge` arithmetic / place-shift / calibration | 4 | Operator charge review — **never** invent Box 28 from Σ or place-shift corroboration |
| `patient_dob` / `patient_name` identity | 1–2 | **Authorized member reference** (Lane C) — see `docs/reference/AUTHORIZED_MEMBER_INDEX_OPERATOR_FILL.md` |
| Single-line `LINE_TOTALS_UNCORROBORATED` | 2 | Dual-engine / DI / exact gpt-4o local consensus only |

Broader decide remasure on `hackathon_100c_blind_cascade_v12_3k` is **not comparable** until charge crops include the cents ruling (see `docs/metrics/hackathon_100c_decide_line_charge_v1.json`).

## Techstack plan

1. **Keep evidence-integrity invariants** (already on `86087ac`): exact Box28↔24F, no line-sum rewrite of totals.
2. **Lane A — printed OCR**: paddle/rapid/tess + geometry cents; charge FA guards stay.
3. **Lane B — gpt-4o crop**: residual corroboration for lines when Box 28 empty (existing cascade).
4. **Lane C — authorized reference** (this change): exact verified member ID → operator index → name/DOB AUTO with `AUTHORIZED_REFERENCE` audit. Abstain without index.
5. **Never**: Golden/agent labels, DI removal as STP lever, reference-filled `total_charge`.

## Honest measurement bar

Claim ≥47/50 TRUE_STP only with zero critical false accepts **and** an operator-authorized index covering residual identity claims. Without `CDP_AUTHORIZED_MEMBER_INDEX`, STP must not inflate.
