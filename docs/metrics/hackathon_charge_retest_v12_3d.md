# Charge retest v12.3d — dual-engine + DI crop

Cohort: 27 GT charge-miss docs + 3 controls (30 total).  
Fix: always dual-engine (paddle+rapid) on service-line charges; prefer longer digit-drop twin; Azure DI only for short-amount corroboration (not blank rows).

## Results

| Metric | Baseline v12.2 (same 27) | Retest v12.3d |
| --- | ---: | ---: |
| True STP | 26/27 | **26/27** (29/30 w/ controls) |
| Reg HITL | 0 | **0** |
| Field HITL | 1 | **1** |
| Charge exact on 27 misses | 0/27 | **14/27 (52%)** |
| Controls charge exact | — | 2/2 labeled |
| Azure DI charge crops | — | 54 (vs 138 in v12.3) |

### Digit-drop subset (classic truncations)

Earlier v12.3c smoke: **7/8** exact (`1571`, `1291`, `701`, `2511`, `251`, `50`, control `157`; miss `2001` where both engines read `200`).

### Projected Independent-300 (if applied)

- Charge exact: 85.0% → **~92.8%** (+14)
- Field exact: ~94.4% → **~96.1%**
- STP/HITL unchanged on this cohort (wrong charges were already AUTO)

## Remaining 13 misses

Mostly non-digit-drop: wrong line count / multi-line sum / both engines agree on wrong amount (`200` vs `2001`). Honest residual or box-28 corroboration next.
