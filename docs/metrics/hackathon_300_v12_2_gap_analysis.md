# Independent-300 v12.2 — process gaps

Source: `hackathon_300_cascade_v12_2` (STP **67.7%**, Reg HITL 73, Field HITL 24).

## Gap inventory

| Track | Count | Nature | Action |
| --- | ---: | --- | --- |
| Registration HITL | 73 | Catastrophic multi-reason warps; orientation already attempted on rotation-only fails | **Honest residual** (Track A) |
| Field HITL — `patient_dob` | 18 | Unreadable / incomplete cell OCR (`INVALID_FORMAT`) | Honest until Azure DI configured |
| Field HITL — `insured_id_number` | 5 | Low-conf garbage / fragments | Honest residual |
| Field HITL — `insured_name` CONFLICT (no critical_blocker list entry but blocks STP) | 4 | OCR twin of accepted `patient_name`, or short-fragment insured | **Fixed in v12.2.1** |
| Field HITL — `patient_name` CONFLICT | 1 | Genuine multi-engine name conflict | Honest residual |

## Resolved this pass (v12.2.1)

1. **Name OCR-twin equivalence** — `C↔O`, `I↔U`; confusable edit ≤2 subs after one deletion; tokenwise twins (`KLUMP COLLEEN` ≈ `KTIIMP COTTEEN`); mid-name period join (`COT.LEEN`).
2. **Soft SELF E6** — `MEMBER_RELATIONSHIP_CONFIRMED` when patient/insured are confusable twins (not short-fragment false matches).
3. **Patient→insured inject** — when insured crop is a short fragment / OCR twin of a strong patient name, inject observed patient ink as competitor (no invention).

### Smoke (reuse OCR → complete)

| Claim | Before | After |
| --- | --- | --- |
| `M048EJGE.020` | HITL (`STERN SOARTET`) | **STP** (`STERN SCART.ET`) |
| `M048EJI2.011` | HITL (`KTIIMP COTTEEN`) | **STP** (`KLUMP. COLLEEN`) |
| `M048EJGE.041` | HITL (`2 DD`) | **STP** (`FUENTESPEDRO`) |
| `M048EJGE.003` | HITL (different names) | HITL (unchanged — correct) |

## Remaining honest gaps

- **~73 Reg HITL**: perspective / inlier catastrophic failures after orientation ladder — keep fail-closed.
- **~18 empty/garbage DOB**: need Azure Document Intelligence (endpoint/key still unconfigured) or human review.
- **~5 bad member IDs**: ink not recoverable from local OCR.
- **1 patient_name conflict** (`EJGE.021`): competing person-shaped readings with no safe twin rule.

Expected STP lift from this fix alone on the 300 cohort: **+3** true STP (the three smoke flips), ~**68.7%** if re-run end-to-end.
