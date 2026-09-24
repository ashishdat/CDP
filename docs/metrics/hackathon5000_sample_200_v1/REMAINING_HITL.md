# Hackathon-5000 sample-200 — remaining HITL review (PRODUCT)

Fresh PRODUCT ledger (seed **20260924**). Insured-twin redecide flipped **0**.
Taxonomy of what is still HITL and which paths must stay HITL for FA=0.

## Unlockable (code already shipped; none left on this draw)

| Pattern | Fix |
|---|---|
| Box-4 `SAME` / DREW peel | `_peel_honorific_glue` + SAME resolver |
| Truncated Self / patient twin | `ClaimDecisionService._resolve_insured_name_patient_twin` |
| Unique shaped ID + CONFLICT_MARGIN | `UNIQUE_SHAPED_ID_CONFLICT_RELIEVED` |

```bash
python3 -u scripts/redecide_hackathon5000_insured_twin.py
```

## Keep HITL on this 200 (precision / ink)

| Claim | Blockers | Why |
|---|---|---|
| `M0472JCM.009` | total_charge | Box28 `563.10` without line corroboration / strong E4 |
| `M0473JG7.005` | insured_id_number | Short padded `0000000` needs multi-engine/vision |
| `M0477JCF.015` | total_charge | Box28/line place-shift (`177` vs `17700`) — policy hold |
| `M0477JJY.037` | total_charge | `MISSING_E4_DETERMINISTIC_VALIDATION` |
| `M0477JKO.002` | patient_dob, total_charge | No DOB ink + charge E4 gap |
| `M047AJCY.027` | patient_name, patient_dob, total_charge | Calibration name `EE SE`, empty DOB, charge `--- $` |
| `M0471JEY.002` (C) | patient_dob | Unstructured HITL (no CMS extract) |
| `M0473JAP.002` (C) | patient_name, total_charge | Unstructured HITL |
| `M0473JEU.001` (C) | patient_name | Unstructured HITL |

Gate residual counts: POLICY_HOLD=6 · INK_ABSENT=2 · RECOVERABLE=1.

## Code map

- `packages/claim_decision/service.py` — `_resolve_insured_name_patient_twin`
- `packages/candidate_reconciliation/reconciler.py` — `_peel_honorific_glue`, `UNIQUE_SHAPED_ID_CONFLICT_RELIEVED`
- `packages/claim_evidence/line_sum_authority.py` — single-line dual gate (do not relax without FA proof)
- `scripts/redecide_hackathon5000_insured_twin.py` — frozen-extract redecide
