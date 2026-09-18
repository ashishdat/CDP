# Blind-50 (`docs[350:400]`) — v12.3o

Product path with gpt-4o crop residuals (DOB/ID), charge DI corroboration, DOB punct repair, and ID digit-conflict tie-break.

Slice: `Group A/M048HJDF.022` … `Group A/M048HJE5.021` (offset 350, limit 50, workers=2).

## Final metrics

| Metric | Blind-50 v12.3o | Blind-10 v12.3m `[350:360]` | Blind-30 v12.3l `[350:380]` | Hard-30 v12.3m `[420:450]` |
| --- | ---: | ---: | ---: | ---: |
| TRUE_STP | **94%** (47/50) | 100% | 100% | 80% |
| Field HITL | **6%** (3/50) | 0% | 0% | 20% |
| REG HITL | **0%** | 0% | 0% | 0% |
| Registration OK | 98% (49/50) | 100% | — | — |
| Mean latency | **45.9s** | 21.1s | 13.8s | 24.3s |
| Median latency | 45.4s | — | — | — |
| Max latency | 83.4s | 31.9s | — | — |

HJDF bundle (29): **100% STP**. HJE5 bundle (21): **85.7% STP** (18/21).

### Field auto-accept (of completed)

| Field | Auto |
| --- | ---: |
| patient_dob | 49/50 (98%) |
| total_charge | 49/50 (98%) |
| insured_name | 49/50 (98%) |
| patient_name | 48/50 (96%) |
| insured_id_number | 48/50 (96%) |

### HITL residuals

| Doc | Blocker |
| --- | --- |
| `M048HJE5.006` | `insured_id_number` |
| `M048HJE5.018` | `patient_name` |
| `M048HJE5.021` | `patient_dob` |

## Cost (batch + per page)

Assumptions:

- **gpt-4o** Azure Global Standard: \$2.50 / 1M input, \$10 / 1M output
- Token proxy from crop bakeoff: ~659 in + ~45 out ≈ **\$0.0021 / crop call**
- Blind-50 gpt-4o crop attempts: **4** (ID×3, DOB×1)
- **Azure DI** meter (run window): 64 calls (charge 59, DOB 2, page_corners 2, unstructured page 1)
- DI unit cost band: **\$0.0015–\$0.01 / call** (SKU-dependent Read pricing)
- HITL labor: **\$0.30 / reviewed page** (prior economics target)

### Batch totals (50 pages)

| Component | Calls | Cost (low DI) | Cost (high DI) |
| --- | ---: | ---: | ---: |
| gpt-4o crop | 4 | **\$0.008** | **\$0.008** |
| Azure DI | 64 | \$0.096 | \$0.640 |
| **Cloud subtotal** | | **\$0.104** | **\$0.648** |
| HITL labor (3 pages) | 3 | \$0.90 | \$0.90 |
| **Fully loaded** | | **\$1.00** | **\$1.55** |

### Per-page cost

| Metric | Low DI | High DI |
| --- | ---: | ---: |
| gpt-4o only | **\$0.00017** | **\$0.00017** |
| Cloud (gpt-4o + DI) | **\$0.0021** | **\$0.0130** |
| HITL labor amortized | \$0.0180 | \$0.0180 |
| **Fully loaded / page** | **\$0.020** | **\$0.031** |

LLM is negligible vs DI and especially vs residual HITL labor. Cloud-only cost stays well under the \$0.30/page HITL economics bar; fully loaded is driven by the 3 HITL pages.

## Artifact

`evaluation_results/hackathon_50_blind_cascade_v12_3o/` — `summary.json`, `results.jsonl`, `run.log`.
