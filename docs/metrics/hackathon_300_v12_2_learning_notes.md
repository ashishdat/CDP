# Independent-300 v12.2 learning notes

Source: partial `hackathon_300_cascade_v12_1` (~213/300 when stopped) + residual autopsy.

## What v12.1 showed

| Slice | STP | Reg HITL | Field HITL |
| --- | --- | --- | --- |
| v12.1 @213 | 68.1% | 23.5% | 8.5% |
| v12 decision-reprocess baseline (300) | 56.7% | 25.0% | 18.3% |
| vs v11 same docs (@~166) | +47 flips to STP, 3 regressions | | |

## Actionable learnings (shipped in v12.2)

1. **DOB YY century pivot mismatch** — span assembly used `YY<=36 → 20xx`, minting future dates (`2030`/`2034`) that fail closed as `FUTURE_DOB_REJECTED`. Reconciler / evidence / GT scorer already used `YY>=30 → 19xx`. Aligned span assembly + refuse/repair future DOBs to 19xx.
2. **Selective confirm skipped weak primary names** — paddle ~0.75 shaped `"DATST EY"` short-circuited rapidocr (`"TOHNSON RATSTRY"`), causing a patient_name regression. Person-name confirmation now always runs when primary confidence `< 0.88`.
3. **Period is not Last, First** — `DAtSt.EY` was parsed as `DATST, EY` via `[.,]` separator. Comma-only + reject first tokens shorter than 3.

## Honest residuals (not targeted this pass)

- Catastrophic perspective / multi-reason registration failures remain Track A HITL.
- Empty / garbage DOB crops without calendar shape stay HITL (Azure DI still unconfigured).

## Smoke (geometry reuse)

- `M048EJG7.002`: FUTURE `2030-09-01` → STP with `1930-09-01`
- `M048EJGE.012`: FUTURE `2034-01-01` → STP with `1934-01-01`
