# Blind-150 stop — charge STP gap analysis (`docs[530:680]`)

Stopped at **50/150** (TRUE_STP **3/50 = 6%**). Identity fields were fine; charge blocked almost everything.

## Pareto (n=50)

| Signal | Count |
| --- | ---: |
| `total_charge` blocker | 46 |
| `SINGLE_LINE_REQUIRES_DI` | 32 |
| `BOX28_OR_DI_CONFLICT` | 7 |
| Calibration / other | ~8 |
| patient_dob / patient_name | 1 each |

Field auto: DOB/ID/name ≥96%; **total_charge 8%**.

## Root causes

1. **Single-line DI gate** — hard-15 fail-closed required box-28/DI for single-line AUTO. Azure DI F0 **403/RuntimeError** left lines without corroboration even when paddle+gpt-4o agreed on the amount.
2. **Junk box-28** — digits-first accepted form-ruling soup (`208408.00`, `420840.00`) which forced `BOX28_OR_DI_CONFLICT` against sensible line-sums.
3. **Empty-value → raw fallback** — consensus used `value or raw_value`, so paddle `value=""` + `raw=9AA` became `9` and blocked gpt-4o+local agreement.

## Fixes shipped

1. Single-line AUTO when **gpt-4o + ≥1 local** agree on the selected line charge (`SINGLE_LINE_GPT4O_LOCAL`); paddle+rapid alone still insufficient.
2. Ignore **implausible corroborators** (>5× or <1/5 line-sum, or >$99,999) instead of CONFLICT.
3. Reject `CURRENCY_IMPLAUSIBLE_TOTAL` in cascade semantic accept; defer implausible box-28.
4. Consensus reads shaped **`value` only** (never raw soup).

## Replay estimate on saved OCR (same 50)

| | Before | After (gate replay) |
| --- | ---: | ---: |
| TRUE_STP | 3 (6%) | **~29 (58%)** |

Remaining HITL: single-line without gpt-4o local agree, multi-line uncorroborated, near-miss box-28 conflicts (e.g. 222 vs 200).

## E2E retest (8 prior charge-HITL claims)

`evaluation_results/hackathon_150_gapfix_retest/` — **5/8 TRUE_STP** (was 0/8).

Flipped: IJN2.002/004/005/019, IJMP.009. Still HITL: multi-line uncorroborated / residual single-line without gpt-4o+local agree.
