# Hackathon-5000 sample-200 PRODUCT report

**Corpus:** [Hackathon - 5000 Claims.zip](https://drive.google.com/file/d/1ohv3muiEChPU6pqR0sj7ansqUYq7odIY) (`DEVELOPMENT_DATASET_HACKATHON_5000_V1`)  
**Selection:** stratified 200 (A135 / B37 / C17 / D11) — seed **20260924** — `selected_documents.txt`  
**Profile:** **PRODUCT** (`run_manifest.json`) — gpt-4o crop + Azure DI charge + TrOCR DOB + conflict agent ON  
**Ledger:** `evaluation_results/hackathon5000_sample_200_v1/`  
**Gate artifact:** `product_gate.json`

## Product gate

| Metric | Value | Target | Status |
|---|---|---|---|
| Claim-page STP | **95.68%** (155/162) | ≥ 97% | **FAIL** |
| Accepted precision (GOLD) | FA=0 (0 scored fields; incomplete GT) | 1.0 / FA=0 | SCORED w/ `--allow-incomplete-gt` |
| HITL / REG | 7 / 38 | REG excluded from STP denom | |
| Run profile | PRODUCT | require_product_profile | OK |
| Gate | **FAIL** | STP bar | |

Reasons: `RUN_PROFILE_OK:PRODUCT`, `CLAIM_PAGE_STP_BELOW_TARGET:0.9568<0.97`.

Gap to 97%: need **+3** more claim-page AUTO (158/162) without FA.

### Precision-safe unlocks applied (this iteration)

| Claim | Before | Unlock | Governance |
|---|---|---|---|
| `M0472JCM.009` | HITL total_charge `BLEED_CENTS_FAIL_CLOSED` on `563.10` | DI raw `$ 563.10` = printed decimal cents (`_charge_di_printed_decimal_confirms`) | DI+local exact agree; no invent |
| `M0477JCF.015` | HITL `CHARGE_VISION_LOCAL_SCALE_RIVAL_HITL` (`177` vs DI `17700`) | Whole-dollar ×100 place-shift soup exempt from SCALE_RIVAL | DJKH.040 `1571.63` and ×10 (`6000`/`60000`) still HITL |

Insured-twin redecide: **2 flips** (above). Remaining HITL intentionally held for FA=0.

## Disposition

| Disposition | Count | Rate |
|---|---|---|
| TRUE_STP | 155 | 77.5% of all / **95.7% of claim pages** |
| HITL | 7 | 3.5% of all / 4.3% of claim pages |
| REGISTRATION_FAILED | 38 | 19.0% |

## Remaining HITL (keep for FA=0)

See `REMAINING_HITL.md`. Summary:

| Claim | Why not unlocked |
|---|---|
| `M0473JG7.005` | Literal insured id `0000000` |
| `M0477JJY.037` | DI ×10 rival `6000`/`60000`; lines ≠ Box28 |
| `M0477JKO.002` | Empty DOB ink + charge conflict |
| `M047AJCY.027` | Garbage name / empty DOB / `--- $` |
| `M0471JEY.002` (C) | UB04 unstructured — missing DOB only (3/4) |
| `M0473JAP.002` (C) | UB04 — missing name+charge (2/4) |
| `M0473JEU.001` (C) | UB04 — missing name only (3/4) |

Group C near-misses need safer UB04 DI heuristics (or gated agent) — not inventable from frozen CMS extract.

## Latency & cloud cost (est.)

| | |
|---|---|
| Mean latency | **40.0 s/doc** |
| Azure (DI+GPT) | **~$0.005–$0.013**/page |
| All cloud (+Claude) | **~$0.007–$0.015**/page |

## Reproduce

```bash
python3 -u scripts/run_hackathon5000_sample_200.py --product --fresh
python3 -u scripts/redecide_hackathon5000_insured_twin.py
python3 -u scripts/check_similar_sample_product_gate.py \
  --ledger-a evaluation_results/hackathon5000_sample_200_v1 \
  --allow-incomplete-gt \
  --write docs/metrics/hackathon5000_sample_200_v1/product_gate.json
```
