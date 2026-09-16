# Metrics

## Independent Samples — 300 (revised v11.6)

| Track | Count | Rate |
|---|---:|---:|
| **True STP** | 167 | **55.7%** |
| Field HITL | 58 | 19.3% |
| Registration HITL | 75 | 25.0% |
| **Combined HITL** | 133 | **44.3%** |
| Stage failure | 0 | — |
| **Exact accuracy (agent GT)** | 822/824 | **99.8%** |
| **Perfect-claim exact** | 222/224 | **99.1%** |
| False accepts | 2 | **0.2%** |

Before → after: True STP **118→167**, Field HITL **107→58**, Combined **182→133** (flipped 49; **+2 vs v11.5**).

v11.6 batch-of-15 field audit: **15/15 PASS** (7 targeted fixes + 8 honest HITL controls). Rules covered by independent use-case tests in `tests/unit/cases/test_residual_field_batch_v11_6.py`.

New True STP from this batch: `EJG7.032` (spaced member ID compact), `EJGE.001` (punctuated ID + tesseract-only conflict filter). Additional ID/name auto-accepts landed on multi-blocker claims still held by empty finance / handwriting DOB.
