# Hackathon-5000 sample-200 PRODUCT report

**Corpus:** [Hackathon - 5000 Claims.zip](https://drive.google.com/file/d/1ohv3muiEChPU6pqR0sj7ansqUYq7odIY) (`DEVELOPMENT_DATASET_HACKATHON_5000_V1`)  
**Selection:** stratified 200 (A135 / B37 / C17 / D11) — seed **20260924** — `selected_documents.txt`  
**Profile:** **PRODUCT** (`run_manifest.json`) — gpt-4o crop + Azure DI charge + TrOCR DOB + conflict agent ON  
**Ledger:** `evaluation_results/hackathon5000_sample_200_v1/`  
**Gate artifact:** `product_gate.json`

## Product gate

| Metric | Value | Target | Status |
|---|---|---|---|
| Claim-page STP | **94.44%** (153/162) | ≥ 97% | **FAIL** |
| Accepted precision (GOLD) | FA=0 (0 scored fields; incomplete GT) | 1.0 / FA=0 | SCORED w/ `--allow-incomplete-gt` |
| HITL / REG | 9 / 38 | REG excluded from STP denom | |
| Run profile | PRODUCT | require_product_profile | OK |
| Gate | **FAIL** | STP bar | |

Reasons: `RUN_PROFILE_OK:PRODUCT`, `CLAIM_PAGE_STP_BELOW_TARGET:0.9444<0.97`.

Gap to 97%: need **+5** claim-page AUTO lifts (158/162) without FA. Residual taxonomy on HITL: POLICY_HOLD=6, INK_ABSENT=2, RECOVERABLE=1.

Insured-twin redecide (`scripts/redecide_hackathon5000_insured_twin.py`): **0 flips** — remaining HITL is charge/DOB/ID/name policy, not SAME/twin.

## Disposition

| Disposition | Count | Rate |
|---|---|---|
| TRUE_STP | 153 | 76.5% of all / **94.4% of claim pages** |
| HITL | 9 | 4.5% of all / 5.6% of claim pages |
| REGISTRATION_FAILED | 38 | 19.0% |

REG reasons: `NO_TEMPLATE_ABOVE_THRESHOLD` 37 · geometry unsafe 1 (Group B/C/D unstructured / non-CMS pages).

## Latency & cloud cost (est.)

| | |
|---|---|
| Mean latency | **40.0 s/doc** |
| Azure DI | ~0.89 calls/page → **~$0.0013–$0.0089**/page |
| Azure GPT-4o | ~1.8 calls/page → **~$0.0037**/page |
| Azure (DI+GPT) | **~$0.005–$0.013**/page |
| + Claude conflict | **~$0.007–$0.015**/page all-cloud |

Pricing assumptions: DI $0.0015–$0.01/call; GPT-4o $2.5/$10 per 1M tok (~659/45 proxy); Claude $3/$15 (~312/97 from Independent-600 meter). No live `vlm_token_meter` on this run.

## Remaining HITL (keep for FA=0)

See `REMAINING_HITL.md`. Live blockers: charge (Box28↔line / MISSING_E4), empty DOB ink, short-padded ID, calibration name/`--- $`, plus 3 Group C unstructured HITL without extract.

## Reproduce

```bash
python3 -u scripts/run_hackathon5000_sample_200.py --product --fresh
python3 -u scripts/redecide_hackathon5000_insured_twin.py
python3 -u scripts/check_similar_sample_product_gate.py \
  --ledger-a evaluation_results/hackathon5000_sample_200_v1 \
  --allow-incomplete-gt \
  --write docs/metrics/hackathon5000_sample_200_v1/product_gate.json
```
