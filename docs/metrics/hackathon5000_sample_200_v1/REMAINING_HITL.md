# Hackathon-5000 sample-200 — remaining HITL review (PRODUCT)

Fresh PRODUCT ledger (seed **20260924**) after precision-safe charge unlocks.
Insured-twin + charge redecide flipped **2** (`JCM.009`, `JCF.015`). **7** remain.

## Unlocked this iteration (FA-safe)

| Claim | Was | Fix |
|---|---|---|
| `M0472JCM.009` | `BLEED_CENTS_FAIL_CLOSED` on DI+local `563.10` | `_charge_di_printed_decimal_confirms` — DI raw `$ 563.10` is printed cents |
| `M0477JCF.015` | `CHARGE_VISION_LOCAL_SCALE_RIVAL_HITL` (`177` vs `17700`) | Whole-dollar ×100 place-shift soup exempt; ×10 and non-`.00` (DJKH.040) still HITL |

```bash
python3 -u scripts/redecide_hackathon5000_insured_twin.py
```

## Keep HITL (accuracy governance)

| Claim | Blockers | Why |
|---|---|---|
| `M0473JG7.005` | insured_id_number | Literal `0000000` — never AUTO |
| `M0477JJY.037` | total_charge | DI ×10 (`6000`/`60000`); line Σ ≠ Box28 |
| `M0477JKO.002` | patient_dob, total_charge | No DOB ink; charge `25094` vs DI `250.94` vs line `250` |
| `M047AJCY.027` | patient_name, patient_dob, total_charge | `EE SE` / empty DOB / `--- $` |
| `M0471JEY.002` (C) | patient_dob | UB04 unstructured 3/4 — DOB not shaped |
| `M0473JAP.002` (C) | patient_name, total_charge | UB04 unstructured 2/4 |
| `M0473JEU.001` (C) | patient_name | UB04 unstructured 3/4 — name not shaped |

Do **not**: accept all-zero IDs, invent DOB/name, relax `SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28`, or AUTO ×10 DI magnitude contests without line Σ.

## Code map

- `packages/candidate_reconciliation/reconciler.py` — `_charge_di_printed_decimal_confirms`, `_charge_inflated_rivals_are_whole_dollar_place_shift_soup`
- `packages/claim_decision/service.py` — `_resolve_insured_name_patient_twin`
- `packages/claim_evidence/line_sum_authority.py` — single-line dual gate
- `scripts/redecide_hackathon5000_insured_twin.py` — frozen-extract redecide
