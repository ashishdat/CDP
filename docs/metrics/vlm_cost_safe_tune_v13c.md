# Precision-safe VLM cost tune (v13c)

## Goal

Cut Claude/VLM token volume **without** lowering TRUE_STP.

## What changed (default on)

1. **Sole-line Claude deferred** (`CDP_SOLE_LINE_CLAUDE_COST_SAFE=1`)
   - Phase 1 (service-line OCR): dual-local sole line stamps `CHARGE_GPT4O_DEFERRED_SOLE_LINE` instead of calling Claude.
   - Phase 2 (after Box28 DI/local residuals): Claude runs **only if Box28 is still unsettled**.
   - If Box28 DI+local already agrees → `CHARGE_GPT4O_SKIPPED_BOX28_SETTLED` (no tokens).
   - Empty Box28 still gets Claude → preserves `SINGLE_LINE_GPT4O_LOCAL` STP.

2. **Name conflict-agent skip** when `name_locals_settled` (soft-equivalent paddle+rapid).
   - Charge / ID / DOB conflict agent unchanged (STP-critical ink fights).

## Kill switches

```bash
CDP_SOLE_LINE_CLAUDE_COST_SAFE=0   # legacy always-corroborate sole line
```

## Expected spend impact (from Independent-600 sample ~193 claims)

| Driver | Before | After (est.) |
|---|---:|---:|
| `charges` VLM calls | ~1.6/claim | <<1 when Box28 DI settles (~85% of claims) |
| Name conflict-agent | fires on soft twins | skipped when locals soft-agree |
| DI call rate | ~0.85/claim | unchanged (keep DI-first) |

## Tests

`test_field_reader_policy.py`, `test_llm_accuracy_policy.py`, `test_conflict_agent.py` — cost-safe defer/skip + empty-Box28 still Claudes.
