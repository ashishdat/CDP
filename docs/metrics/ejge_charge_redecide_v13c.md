# EJGE charge unlock — decision-only redecide (v13c)

**Commit:** `adca03f` — vision+underread E4 + DI/vision non-twin soup clear.

## Target fails (Independent-300 v13c)

| Claim | Prior | After | Mechanism |
|-------|-------|-------|-----------|
| EJGE.005 | HITL `CONFLICT_MARGIN` (19 vs 9300.19/93) | **TRUE_STP** | DI+local owns 19; non-twin geometry/rapid cleared |
| EJGE.016 | HITL `MISSING_E4` (Claude 300 vs paddle 29) | **TRUE_STP** | `VISION_CORROBORATES_CONFLICT_PICK` + underread E4 |
| EJGE.017 | HITL `MISSING_E4` (Claude 300 vs paddle 28) | **TRUE_STP** | same |
| EJGE.018 | HITL `MISSING_E4` (Claude 1800 vs paddle 29) | **TRUE_STP** | same |
| EJGE.032 | HITL `MISSING_E4` (Claude 250 vs rapid 12) | **TRUE_STP** | same |

**Result:** 5/5 flipped (`evaluation_results/hackathon_300_ejge_charge_redecide_v13c/`).

## Precision guards (unit-tested)

- Inflated local rival (`300` vs `3000`) still `CONFLICT_AGENT_SOLE_AUTHORITY`.
- Digit-drop twin under DI-local (`200` vs `2001`) still CONFLICT (DJKN.005).

## Deferred EJGE (not this unlock)

- `.014` / `.015` — `REGISTRATION_FAILED`
- `.019` — line-Σ uncorroborated (`600`)
- `.026` — `insured_id_number` pad conflict
- `.041` — `insured_name` CONFLICT (`DADC`)
