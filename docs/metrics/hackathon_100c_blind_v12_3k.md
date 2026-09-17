# Blind-100 (`docs[350:450]`) — v12.3k

## Final metrics

| Metric | v12.3k | v12.3j | Prior blind (partial 84) |
| --- | ---: | ---: | ---: |
| TRUE_STP | **79%** (79/100) | 76% | 46% |
| Field HITL | **13%** (13/100) | 16% | 17% |
| REG | **8%** (8/100) | 8% | 37% |
| Mean latency | **17.3s** | 17.2s | — |

Registration OK 92/100. Of completed: STP **85.9%** (79/92). Mean ≤30s bar met.

## What moved vs v12.3j

HITL→STP (3): `HJHO.010`, `HJHO.013`, `HJHO.029` — name box-chrome conflict relief (`2` vs strong person).

REG set unchanged (8). Last-resort Azure DI page corners **ran** (12 page calls, 9 OK) but did not convert these catastrophic pages; terminal reasons are now real align/geometry failures (or 2× `AZURE_DI_ERROR:RuntimeError`), not the cost-gate skip.

## Remaining buckets

| Bucket | n | Notes |
| --- | ---: | --- |
| REG (catastrophic geometry) | 8 | Same hard pages as v12.3j; corners/LightGlue exhausted |
| DOB ambiguous / handwriting | ~11 | Dominant field HITL |
| ID `CALIBRATION_HITL` | ~6 | Mix of short `20755` and garbage OCR held for conf |

## Fixes in this tag

1. Last-resort Azure DI page corners ON after near-miss/LightGlue
2. Digit-only / box-number name OCR treated as form chrome (not CONFLICT)

## Artifacts

`evaluation_results/hackathon_100c_blind_cascade_v12_3k/` — `summary.json`, `results.jsonl`, `azure_di_meter.jsonl`.
