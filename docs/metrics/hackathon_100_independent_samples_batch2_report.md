# Metrics

## Independent Samples — 100 batch 2 (v12)

New slice `docs[100:200]` (disjoint from batch 1 `docs[0:100]`).

| Track | Count | Rate |
|---|---:|---:|
| **True STP** | 38 | **38.0%** |
| Field HITL | 30 | 30.0% |
| Registration HITL | 32 | 32.0% |
| **Combined HITL** | 62 | **62.0%** |
| Stage failure | 0 | — |
| **Exact accuracy (agent GT)** | 205/212 | **96.7%** |
| **Perfect-claim exact** | 60/67 | **89.6%** |
| False accepts | 7 | **3.3%** |

## Cost (batch 2 processing)

Measured compute (local OCR — **$0 cloud vision**):

| Item | Value |
|---|---:|
| Cascade wall-clock (100 docs) | 236.5 min (3.94 CPU-hr equiv.) |
| Decision reprocess (HITL subset) | 192s (47 claims) |
| Cloud OCR / API spend | **$0.00** |

Governed cost model A (`$1.00` / reviewed page + `$0.00270` infra/page):

| Track | USD |
|---|---:|
| HITL labor (62 reviewed pages) | **$62.00** |
| Infra (routing+compute+storage) | $0.27 |
| **Total batch** | **$62.27** |
| Per page | $0.6227 |
| Per True-STP claim (amortized) | $1.64 |

Model B (phase-8.7 claim HITL @ `$25/hr`): **$4.37** batch / **$0.0437**/page.
