# Metrics

## Independent Samples — 300 (revised v11.2)

| Track | Count | Rate |
|---|---:|---:|
| True STP | 145 | 48.3% |
| Field HITL | 80 | 26.7% |
| Registration HITL | 75 | 25.0% |
| Combined HITL | 155 | 51.7% |
| Stage failure | 0 | — |
| Exact accuracy (agent GT) | 822/824 | 99.8% |
| Perfect-claim exact | 222/224 | 99.1% |
| False accepts | 2 | 0.2% |

Before → after: True STP **118→145**, Field HITL **107→80**, Combined **182→155** (flipped 27).

Tool-fit: Rapid primary / Paddle+Tesseract selective / Docling+Azure+Textract gated / React HITL — see `docs/STP_TOOL_FIT_ARCHITECTURE_V11_2.md`.
