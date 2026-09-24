# Similar-sample 200 test report

**Source:** [Google Drive Hackathon zip](https://drive.google.com/file/d/1vhLhHwucY2gG6INZS3MB1MpAE1suaIJW/view?usp=sharing)  
**Selection:** stratified 200 across Groups A/B/C/D (135/37/17/11) — `selected_documents.txt`  
**Ledger:** Independent tip (`hackathon_1000_independent_v13c` merge)

## Product gate

| Metric | Value | Target | Status |
|---|---|---|---|
| Claim-page STP | **96.34%** (158/164) | ≥ 97% | FAIL |
| Accepted precision (GOLD) | **1.0** (FA=0) | 1.0 / FA=0 | PASS |
| HITL | 6 | — | |
| REG (no claim ink) | 36 | excluded from STP denom | |
| Gate | **FAIL** | both bars | |

Residual HITL: `{'POLICY_HOLD': 4, 'INK_ABSENT': 2}`

## Notes

- Accuracy bar is green on this 200-doc sample (GOLD + quarantine).
- STP is short of 97% by ~1 claim-page lifts; residuals are POLICY_HOLD / INK_ABSENT (no invent).
- Live re-cascade on current code (`evaluation_results/similar_sample_200_v1`) is running to confirm accept-policy path.
