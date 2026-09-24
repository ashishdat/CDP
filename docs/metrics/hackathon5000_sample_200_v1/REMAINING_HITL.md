# Hackathon-5000 sample-200 — remaining HITL review (PRODUCT)

Live ledger after insured_name SAME/twin unlocks. Taxonomy of what is still HITL
and which code paths unlock vs must stay HITL for FA=0.

## Unlockable (code shipped)

| Pattern | Example | Fix |
|---|---|---|
| Box-4 `SAME` demoted after AUTO patient | JEB.025 `MAUS. DREW, D` | `_peel_honorific_glue` no longer strips `DR` from `DREW`; SAME resolver does not require `strong_person` when patient already AUTO |
| Truncated Self token / soft twin | JAJ.001 `FELICIA` | `ClaimDecisionService._resolve_insured_name_patient_twin` |
| Unique shaped ID + CONFLICT_MARGIN | JEB.004 `944808` | `UNIQUE_SHAPED_ID_CONFLICT_RELIEVED` in reconciler |

```bash
python3 -u scripts/redecide_hackathon5000_insured_twin.py
```

## Keep HITL (precision / ink)

| Pattern | Example | Why |
|---|---|---|
| Different strong Box-4 person | JAL.002 `LOE, SEEN` ≠ `TAYLOR, JENNILEE D` | Spouse/other — never twin |
| Empty / garbage DOB | JEB.014 empty; JEB.018 `1H`; JEB.024 `05H 91723 1` | No calendar ink |
| Invalid charge ink | JEB.008 `--- $` | Empty financial |
| Charge calibration, no DI/vision | JEB.010 `60.00`; JEB.013 `28500.00`; JEB.019 `145.00` | `MISSING_E4` / place-shift risk |
| Single-line dual needs Box28 | JEB.017 / JEB.023 | Intentional FA guard in `line_sum_authority` (`SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28`) |
| Short padded member ID | JEB.016 `00212280` | Needs multi-engine/vision corroboration |

## Code map

- `packages/claim_decision/service.py` — `_resolve_insured_name_patient_twin`
- `packages/candidate_reconciliation/reconciler.py` — `_peel_honorific_glue`, `UNIQUE_SHAPED_ID_CONFLICT_RELIEVED`
- `packages/claim_evidence/line_sum_authority.py` — single-line dual gate (do not relax without FA proof)
- `scripts/redecide_hackathon5000_insured_twin.py` — frozen-extract redecide
