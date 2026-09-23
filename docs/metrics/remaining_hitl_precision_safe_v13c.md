# Remaining n300 HITL analysis — precision-safe unlock plan

Live Independent-300: **284/300 (94.7%)**, median **37.3s** (vs n100 v13c 97%/37.0s).

## Unlock matrix (without breaking STP)

| Claim | Root cause | Unlock? | Mechanism / guard |
|-------|------------|---------|-------------------|
| EJGE.005/.016/.017/.018/.032 | MISSING_E4 / CONFLICT_MARGIN | **Yes** | Vision+underread E4; DI non-twin soup clear. Guard: ratio ≤100×; underread scrap required |
| EJH6.001 | DI 150 vs paddle 5700 CONFLICT | **Yes** | DI-owned non-twin soup clear |
| EJGE.026 | Claude `USW000179858` vs paddle `000179858` | **Yes** | Digit-core pad fragment relief (carrier vs zero-pad) |
| EJG7.005 | DI+Claude 400 upgraded to rapid 4007 | **Yes** | Skip digit-drop fuller when DI+partner exact; authorize BOX28 DI partner |
| DJKN.022 | Agent BOX28 25 vs dual-line 450 | **No** | Must stay HITL. Guard: underread path requires scrap (not exact local agree) — blocked false STP on 25 |
| DJKN.023 | Claude 45000 vs rapid 11 | **No** | Extreme ratio >100× blocked |
| EJGE.019 | Line Σ uncorroborated / agent abstain | **Defer** | Messy multi-line OCR; needs line dual-engine path |
| EJGE.041 | insured_name `DADC` vs `2` | **Defer** | Label/fragment soup; no strong person rival |
| EJGE.014/.015 | REGISTRATION_FAILED | **Defer** | Geometry/reg, not field ink |
| EJI2.020 | DOB=`1` only | **Defer** | Need DOB cloud force when digit scrap |
| HJCR.004 | ID is form label only | **Defer** | No digit ink — correctly HITL |

## Precision guards added this pass

1. Vision-underread requires ≥1 underread scrap (blocks DJKN.022 false 25 STP).
2. Vision-underread rejects `chosen/min(local) > 100` (blocks DJKN.023 45000).
3. DI+partner exact → do not digit-drop-upgrade agent pick (blocks 400→4007).
4. ID digit-core pad fragment: carrier vision vs zero-padded digit-only local.

## Projected STP after precision-safe redecide

**292/300 (97.3%)** — eight flips; six remain intentional HITL/REG.
