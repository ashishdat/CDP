# Hackathon-5000 all-v1 PRODUCT

Generated: 2026-10-02T02:07:20.190804+00:00

| Metric | Value |
|---|---|
| Docs | 5000 / 5000 (COMPLETE) |
| TRUE_STP / completed | 3437 / 3534 (**97.26%**) |
| HITL | 97 ({'UNSTRUCTURED_DI': 97}) |
| REG | 1466 |
| agent_used | 0 (0.0%) |
| vs 95% STP | **PASS** |
| FA vs shared GT | **SCORED** (false_accepts=0) |
| Latency all p50/p95 | 3.675s / 4.371s (n=5000) |
| Latency HITL p50/p95 | 3.399s / 4.165s (n=97) |

Shared field truth: `docs/gt/hackathon5000_agent_field_truth.json` (200 stratified
M046*/M047* claims, SILVER RapidOCR observed ink) merged into
`docs/gt/hackathon_agent_field_truth.json` (278 total with M048*).

FA above is vs SILVER RapidOCR labels (same engine family as unstructured-first).
`release_gate_eligible=false` — not independent adjudicated GOLD. Rebuild:
`python3 -u scripts/build_hackathon5000_agent_gt.py --sample 200 --seed 20261002 --merge-canonical`
