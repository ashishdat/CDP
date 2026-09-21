# Remaining field HITL — fix plan (best existing stack)

Stopped partial, after digit-drop re-decide and the three fail-open seals.

| | n | rate |
| --- | ---: | ---: |
| Completed | 733 | denominator |
| TRUE_STP | 504 | **68.8%** |
| Field-ink HITL | 229 | **31.2%** |
| Infra (not HITL) | 52 | 50 registration + 2 stage |

94% was **47/50** on `docs[350:400]` (`hackathon_50_blind_cascade_v12_3o`), with Azure DI charge reads on. That slice is **38/50** on this corpus. Another decision-only pass cannot close the gap: it recopies frozen `OCRCandidates` and never re-reads the page.

## Stack to use

Do not add a model. This is the stack that produced 47/50 (`docs/metrics/charge_hitl_techstack_v12_3p.md`, `docs/metrics/dob_id_hitl_techstack_v12_3n.md`). The 1000 cascade forces the charge half off (`CDP_AZURE_DI_CHARGE_*=0` in `scripts/run_hackathon_1000_cascade.py`) because Azure DI F0 is 1 analyze/min.

```
local paddle/rapid (+ digit-whitelist tesseract)
  → Azure DI charge crop          # OFF on the 1000 run; ON for the 94% slice
  → Azure gpt-4o line cell + box 28
       digit-drop → fuller local (DIGIT_DROP_FULLER_LOCAL, already coded)
       non-twin conflict → gpt-4o only when it agrees with a local
  → LINE_TOTALS AUTO only when one of:
       every line gpt-4o + local
       plausible box-28 or DI corroborates the line sum
       multi-line exact dual-engine
       MULTI_LINE_DIGIT_DROP_FULLER_LOCAL
  → else field HITL

identity (name / DOB / member id):
  local → TrOCR DOB crop → Azure DI DOB crop
  → gpt-4o crop residual (MISSING_E2, chrome ID, same-length digit tie-break)
  → field HITL
```

Product env for a **bounded re-OCR of HITL claims only** (do not restamp the 504 STP claims):

```
CDP_GPT4O_CROP_RESIDUAL=1
CDP_GPT4O_CROP_ACCEPT=1
CDP_AZURE_DI_CHARGE_RESIDUAL=1
CDP_AZURE_DI_CHARGE_CORROBORATE=1
CDP_AZURE_DI_CHARGE_ACCEPT=1
```

Lane C (authorized member index) stays off unless `CDP_AUTHORIZED_MEMBER_INDEX` is an operator-filled index. Never fill `total_charge` from a reference.

**Not softened:** single-line paddle+rapid alone (13 vs 131 stays `SINGLE_LINE_REQUIRES_DI`). Conflict and confidence floors stay. A line sum is never passed back in as box 28.

## What each HITL cluster gets

Charge is the blocker on 188/229. Charge-only is 159.

| Cluster | n | Action |
| --- | ---: | --- |
| `MULTI_LINE_UNCORROBORATED` | 48 (+5 with margin) | Re-OCR: DI charge crop + gpt-4o line and box 28. AUTO only on an existing gate. |
| `SINGLE_LINE_REQUIRES_DI` | 36 (+4 with margin) | Same re-OCR. This is the hard-15 class. DI or gpt-4o+local is required; paddle+rapid alone is not. |
| `SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28` | 20 (+5 with margin) | Same re-OCR, aimed at box 28. |
| `CALIBRATED_CONFIDENCE_BELOW_THRESHOLD` on charge | 28 | Corroborating DI/gpt-4o read may clear it. Do not lower the floor. |
| `FINANCIAL_CONFLICT_HITL` | 27 | **Stay HITL.** `M048DJJF.004` is box 783 vs lines 261+261=522. Agreeing engines on 522 would be a false STP. |
| `POS_LIKE_LINE_SUM_REJECTED` | 4 | Stay HITL. |
| `BOX28_OR_DI_CONFLICT` | 3 | Stay HITL unless a new read removes the conflict. Do not drop the disagreeing total. |
| `patient_name` `MISSING_E2` | ~28 | gpt-4o name crop. Format (`NAME_STRONG_PERSON`) is not enough — current values are garbage. |
| `patient_dob` calendar-valid but `MISSING_E2` | 6 | gpt-4o / DI DOB crop (punct normalize + cell-split already shipped). |
| `patient_dob` invalid / empty crop | rest of 23 | gpt-4o cell-split. Sealed shells stay HITL (`10041004`, `0196-01-04`). |
| `insured_id` format-valid, below threshold | 11 | gpt-4o tie-break only when it matches a local. Do not lower 0.92. |
| Label / short ids | leftovers | Stay HITL (`7267`, `INSURED'S I.D. NUMBER`). |
| Empty critical blockers | 8 | `insured_name` still `blocks_stp`. Do not flip these to STP. Lane C only with an authorized index. |

Infra (52) is a registration/stage problem, not this plan. It stays out of the HITL rate.

## Order of work

1. Re-OCR **only** charge-gate HITL whose reason is `SINGLE_LINE_REQUIRES_DI`, `SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28`, or `MULTI_LINE_UNCORROBORATED`, with DI charge + gpt-4o charge on. Then rank → validate → assemble → complete. About 118 claims. F0 at 1 analyze/min bounds this; it is not a second 1000-claim cascade.
2. gpt-4o crop residual on the remaining identity HITL (`MISSING_E2` name, unshaped DOB, weak or conflicting member id).
3. Leave financial conflicts, POS-like sums, box-28 conflicts, sealed invalid dates, label ids, and empty-critical `insured_name` as HITL.
4. Regression locks before any rate is quoted: `M048DJJF.004` stays HITL; `HJDF.022` (1851+1551=3402) stays STP; the three sealed claims stay HITL; single-line 13 vs 131 stays closed.

## Ceiling

Blind-50 can move from 38/50 toward 47/50 only if the nine leftover `HJE5` claims get a real charge or identity re-read. The corpus will not become 94% of 733 by loosening gates. If every addressable charge gate and identity crop corroborated — they will not — STP would still stop short of the financial-conflict and policy HITL that must remain. Quote `true_stp / completed` and `field_ink_hitl / completed` only, after the re-OCR, on the same 733 completed claims.
