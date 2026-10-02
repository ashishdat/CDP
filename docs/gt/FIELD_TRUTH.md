# Shared agent field truth

Canonical file: [`hackathon_agent_field_truth.json`](./hackathon_agent_field_truth.json)

Hackathon-5000-only file: [`hackathon5000_agent_field_truth.json`](./hackathon5000_agent_field_truth.json)

| Property | Value |
|---|---|
| Hackathon-1000 labels | 78 claims (`M048DJJF` / `M048DJJM` / `M048DJKH`) — GOLD+SILVER |
| Hackathon-5000 labels | 200 stratified completed claims (`M046*` / `M047*`) — SILVER RapidOCR |
| Merged canonical | 278 claims |
| Vendor ZIP GT | None — agent consensus / observed OCR labels |

## How scoring uses it

1. Resolver (`packages/evaluation/agent_gt_paths.py`):
   - `CDP_FIELD_TRUTH` env override
   - corpus=`hackathon5000` → `hackathon5000_agent_field_truth.json` then canonical
   - default → canonical `docs/gt/hackathon_agent_field_truth.json`
   - runtime mirror `evaluation_data/hackathon_agent_gt/field_truth.json`
2. Sync mirror: `python3 scripts/sync_hackathon_agent_gt.py`
3. Rebuild 5000 sample:
   `python3 -u scripts/build_hackathon5000_agent_gt.py --sample 200 --seed 20261002 --merge-canonical`
4. Product gate contract: `config/product_stp_accuracy_contract_v1.yaml`
   → `score_gt: docs/gt/hackathon_agent_field_truth.json` (merged)

## Methodology

**Hackathon-1000 (M048*)** — multi-engine cascade OCR consensus + visual ROI seeds.
GOLD = ≥2 engines agree; SILVER = single shaped engine / hard validation.

**Hackathon-5000 (M046*/M047*)** — RapidOCR full-page text + unstructured field
heuristics (`semantic_accept`). Labels are SILVER (single-engine observed ink).
Dual Paddle+Rapid GOLD consensus is available via `--dual` when RAM allows
(≥8 GiB free); default is Rapid-only to avoid OOM on 15 GiB hosts.

## Honesty rules

- Never invent DOB/amounts/IDs when OCR is empty or engines conflict on dual mode.
- Product FA green bar still prefers **GOLD** criticals. Hackathon-5000 Rapid-only
  labels are SILVER — report accepted-field precision on the SILVER set, and do
  not claim GOLD FA=0 from them alone.
- Before the 5000 labels existed, scoring returned `NO_OVERLAP` (not FA=0).
