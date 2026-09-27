# Shared agent field truth

Canonical file: [`hackathon_agent_field_truth.json`](./hackathon_agent_field_truth.json)

| Property | Value |
|---|---|
| Corpus | Hackathon - 1000 Claims.zip |
| Labeled claims | 78 (`M048DJJF` / `M048DJJM` / `M048DJKH`) |
| Label tiers | GOLD + SILVER (product FA gate uses **GOLD only**) |
| Vendor ZIP GT | None — agent consensus / visual ROI labels |

## How scoring uses it

1. Resolver prefers this file, then the runtime mirror at
   `evaluation_data/hackathon_agent_gt/field_truth.json` (gitignored).
2. Sync mirror: `python3 scripts/sync_hackathon_agent_gt.py`
3. Product gate contract: `config/product_stp_accuracy_contract_v1.yaml`
   → `score_gt: docs/gt/hackathon_agent_field_truth.json`

## Honesty rule

**Hackathon-5000** documents (`M046*` / `M047*`) have **zero overlap** with
these labels. Scoring returns `NO_OVERLAP` with `false_accepts=null` — never
report FA=0 for those runs. FA=0 is only certifiable on runs that include the
labeled M048* claims.
