# Independent-300 v13c — STP dip analysis

**Live ledger (pre-redecide):** first100 **97%**; **101–150: 86%** (EJGE cluster); 151–200 90%; 201+ recovering ~98–100%.

## Driver

Almost all of the dip is the **EJGE** pocket (37/47 = 78.7% on live OCR) plus a few neighbors — **not** a post-resume regression (post-resume ~98% STP).

## Precision-safe flips (decision-only)

| Claim | Prior | After | Notes |
|-------|-------|-------|-------|
| EJGE.005/.016/.017/.018/.032 | HITL charge | **TRUE_STP** | vision-underread E4 / DI soup (prior unlock) |
| EJH6.001 | HITL CONFLICT_MARGIN 150 vs 5700 | **TRUE_STP** | DI+local owns 150; non-twin 5700 cleared |
| DJKN.023 | HITL MISSING_E4 | **stays HITL** | Claude `45000` vs `11` — extreme-ratio underread **blocked** |

## Guard added

`_vision_corroborates_underread_locals`: reject when `chosen / min(underread_local) > 100` so hallucinated place-shift shells cannot AUTO.

## Still HITL (deferred / precision)

- DJKN.022 line-Σ uncorroborated; DJKN.023 Claude 45000
- EJG7.005 DI+Claude 400 vs digit-drop 4007 twin (CONFLICT_MARGIN)
- EJGE.019 line-Σ; .026 ID pad; .041 insured_name `DADC`; .014/.015 REG
- EJI2.020 DOB=`1`; HJCR.004 ID label soup
