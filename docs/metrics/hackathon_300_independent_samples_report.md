# Metrics

## Independent Samples — 300 (revised v11.5)

| Track | Count | Rate |
|---|---:|---:|
| **True STP** | 165 | **55.0%** |
| Field HITL | 60 | 20.0% |
| Registration HITL | 75 | 25.0% |
| **Combined HITL** | 135 | **45.0%** |
| Stage failure | 0 | — |
| **Exact accuracy (agent GT)** | 822/824 | **99.8%** |
| **Perfect-claim exact** | 222/224 | **99.1%** |
| False accepts | 2 | **0.2%** |

Before → after: True STP **118→165**, Field HITL **107→60**, Combined **182→135** (flipped 47; **+4 vs v11.4**).

v11.5 batch-of-15 field audit: **15/15 PASS** (7 targeted fixes + 8 honest HITL controls). Rules covered by independent use-case tests in `tests/unit/cases/test_residual_field_batch_v11_5.py`.
