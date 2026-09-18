# Hard-15 retest (v12.3o open-item close)

Freeze: `evaluation_data/hard15_v12_3o/`  
Cascade: `evaluation_results/hard15_v12_3o_cascade/`  
GT score: `evaluation_results/hard15_v12_3o_gt_score/summary.json`

## Gate vs result

| Must hold | Target | Result | Status |
| --- | ---: | ---: | --- |
| `false_accepts` | ≤ 1 | **0** | Closed — SAME≡patient twin scoring + PIRSR→patient GT |
| Charge exact | ≥ 6/9 | **2/9** | Open — see charge note |
| TRUE_STP | ≥ 60% | **~0%** | Open — follows charge; fail-closed HITL correct |
| REG HITL | 0 | **1** | Azure DI page-corners **403 F0 quota** (env) |

Label agreement **38/46 (82.6%)**. Identity AUTO held: DOB **7/7**, ID **11/11**, patient_name **9/9**, insured_name **9/10** exact.

## What closed this pass

1. **gpt-4o currency crop** on empty/unshaped box-28 after DI.
2. **gpt-4o service-line charge residual** for single-engine / empty-after-DI / digit-drop twin cells; unbiased prompt (no prior OCR anchor).
3. **gpt-4o excluded** from LINE_TOTALS dual-engine AUTO (paddle+gpt4o false STP blocked).
4. **Preserve** shaped Azure box-28 over contradictory single-line OCR wipe.
5. **insured_name FA**: score `SAME` as patient twin; repair `PIRSR` GT to `MITSUI DANA A`.

## Charge note (why exact stays 2/9)

On the 7 misses, paddle+rapid and gpt-4o usually **agree with each other** against the SILVER `auto_accepted+line_sum` labels (e.g. 222 vs GT 233, 200 vs GT 22). Box-28 crops abstain when empty. Residual cannot invent a third amount when all readers see the same ink.

Exact AUTO remains **EJGE.021 (400)** + value-correct HITL **EJG7.036 (165)**.

**Hold 500** until charge exact ≥6/9 after visual re-label of those SILVER charges (or a stronger independent charge reader). FA gate is already met.

## Remaining open (ordered)

1. **Charge SILVER GT vs multi-engine consensus** — visual re-read of the 7 disagreeing totals.
2. **STP recovery** — follows corroborated charge values.
3. **Azure DI F0 quota** — REG corners + some charge DI crops; paid tier or skip corners on 403.
