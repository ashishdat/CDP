# Field accuracy — using agent GT labels

Source labels: `evaluation_data/hackathon_agent_gt/field_truth.json`
(228 claims, **844** field labels; GOLD multi-engine consensus + SILVER
auto-accept/line-sum; no vendor labels on Hackathon ZIP).

## What the labels show (Independent-300 v12.2)

| Signal | Finding |
| --- | --- |
| Exact vs GT | **91.3%** field exact (218 scored claims) before soft-name match |
| False accepts | **70** — mostly `total_charge` AUTO with wrong line-sum |
| Charge misses | **27/27** are v12 `CHARGE_DIGITS_FAST` regressions vs v11 full OCR (e.g. `1571→157`) |
| Name misses | Mostly optional middle initial / form-ruling ghost `I` (`HARRY I P` vs `HARRY P`) |
| DOB HITL | 18 field HITL — almost **no DOB GT** (abstain on unreadable ink); residual = TrOCR → Azure DI crop |
| GOLD DOB | 15/15 exact where labeled |

Accuracy ≠ STP: labels measure value exactness; STP also needs AUTO disposition.

## How we use labels (not circular training)

1. **Score, don’t overwrite** — `score_hackathon_gt_accuracy` loads existing GT; never rewrite 844 labels with seed-only.
2. **Typology → residual** — every miss class maps to a fail-closed rule (below).
3. **Soft exact for representation** — optional CMS MI / ghost `I|1|L|T` is not a person mismatch.
4. **Abstain honesty** — no GT for unreadable DOB; Azure/TrOCR may add GOLD later when ink resolves.
5. **Prefer GOLD** for calibration; SILVER charges from v11 line-sum are the charge oracle that exposed the fast-digit regression.

## Shipped residuals (this pass)

1. **Charge digit-drop recovery** — after `CHARGE_DIGITS_FAST`, verify with paddle/rapid; prefer longer digit-drop twin (`157`←`1571`) or full-OCR on non-twin disagreement.
2. **OCR ghost MI preference** — prefer name without lone `I/1/L/T` MI when engines disagree.
3. **GT scorer soft-match** — optional MI + ghost MI count as exact vs labels.

## Next lifts (ordered by GT leverage)

1. Re-OCR Independent charge-miss subset under verification; expect most of 27 charges to match GT.
2. Expand DOB GOLD from successful TrOCR/Azure DI crop residuals on the 18 HITL claims.
3. Rebuild GT merge across v11+v12+toolstack (`build_hackathon_agent_gt`) so SILVER charges require multi-run agreement.
4. Fail-closed HITL when single-line LINE_TOTALS and box-28 empty with no dual-engine corroboration.
