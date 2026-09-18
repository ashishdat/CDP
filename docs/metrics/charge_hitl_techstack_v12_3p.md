# Charge HITL tech stack — v12.3p

Blind-150 `docs[530:680]` stop (50 docs): identity ≥96% AUTO; **total_charge 8%** → STP 6%.  
After v12.3o line-sum gate: ~58% estimated. Remaining hole needs a dedicated charge stack.

## Failure modes (post v12.3o)

| Mode | n (of ~20 residual) | Example |
| --- | ---: | --- |
| Digit-drop twin gpt-4o↔local | ~8 | `622` vs `6225`, `643` vs `6430`, `13` vs `130` |
| Multi-line without dual-engine | ~3 | Both lines gpt-4o+local but paddle missing on line 2 |
| Weak box-28 veto | ~2 | Digits-first `222` vs line `200` with full gpt-4o+local |
| Local form-noise vs gpt-4o | ~4 | `2.00` / `900` shells vs gpt-4o `200` |
| Empty / no lines | ~1 | No charge ink |

## Stack (ordered)

```
local paddle/rapid (+ digit-whitelist tesseract)
  → Azure DI charge crop (empty / non-twin conflict)
  → Azure gpt-4o charge crop (line cell + box-28)
       • digit-drop twin → prefer longer gpt-4o read
       • non-twin conflict → gpt-4o override
  → LINE_TOTALS AUTO when:
       1. every charge line has gpt-4o + local consensus, or
       2. plausible box-28 / DI corroborates line-sum, or
       3. multi-line exact dual-engine (paddle+rapid)
  → React field HITL
```

| Lever | Mechanism |
| --- | --- |
| gpt-4o before box-28 conflict | Strong line consensus wins over weak digits-first box-28 |
| Multi-line gpt-4o+local | `MULTI_LINE_GPT4O_LOCAL` — no paddle+rapid required on every line |
| Digit-drop twin consensus | `amounts_corroborate` in consensus; OCR prefers longer gpt-4o |
| Noise local filter | Ignore locals tiny / >3× off vs gpt-4o; allow gpt-4o-only after noise |
| Junk box-28 | `CURRENCY_IMPLAUSIBLE_TOTAL` + corroborator filter (`208408`-class) |
| Evidence auth | `azure_gpt4o_crop` allowed on charge fields |

**Not softened:** single-line paddle+rapid alone (hard-15 FA class). Global conflict/conf floors unchanged.

## Code

- `packages/claim_evidence/line_sum_authority.py` — consensus + gate order
- `scripts/ocr_from_geometry.py` — `CHARGE_GPT4O_DIGIT_DROP`
- `packages/evidence_decision/service.py` — charge gpt-4o family allow
- `packages/extraction_recovery/field_cascade.py` — implausible total reject

## Env (product)

```
CDP_GPT4O_CROP_RESIDUAL=1
CDP_GPT4O_CROP_ACCEPT=1
CDP_AZURE_DI_CHARGE_RESIDUAL=1
```

## Results

| Cohort | Before | After v12.3p |
| --- | ---: | ---: |
| Blind-150 stop (50) gate replay | 6% STP | **~94%** estimated |
| Hard charge retest (10 prior HITL) | 0/10 | **9/10 TRUE_STP** |

Residual HITL: `CONFLICT_MARGIN_TOO_SMALL` on multi-line corroboration (reconciler margin), not the line-sum gate.
