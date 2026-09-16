# Metrics

## Independent Samples — 300 (revised v11.3)

| Track | Count | Rate |
|---|---:|---:|
| True STP | 153 | 51.0% |
| Field HITL | 72 | 24.0% |
| Registration HITL | 75 | 25.0% |
| Combined HITL | 147 | 49.0% |
| Stage failure | 0 | — |
| Exact accuracy (agent GT) | 822/824 | 99.8% |
| Perfect-claim exact | 222/224 | 99.1% |
| False accepts | 2 | 0.2% |

Before → after: True STP **118→153**, Field HITL **107→72**, Combined **182→147** (flipped 35; +8 vs v11.2 via line-sum authority).

Tool-fit: Rapid primary / Paddle+Tesseract selective / Docling+Azure gpt-4o+Textract gated / React HITL — see `docs/STP_TOOL_FIT_ARCHITECTURE_V11_2.md`.
Azure: gpt-4o @ truesdlc-test (review-only; credentials in gitignored `.env`).
