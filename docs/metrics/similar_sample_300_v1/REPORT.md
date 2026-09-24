# Similar-sample 300 holdout test report

**Source:** [Google Drive Hackathon zip](https://drive.google.com/file/d/1vhLhHwucY2gG6INZS3MB1MpAE1suaIJW/view?usp=sharing)  
**Selection:** stratified **300** holdout excluding `similar_sample_200_v1` (A/B/C/D = 202/56/26/16)  
**Method:** tip-seed FAST (`--seed-tip` equivalent)

## Product gate

| Metric | Value | Target | Status |
|---|---|---|---|
| Claim-page STP | **98.40%** (246/250) | ≥ 97% | PASS |
| Accepted precision (GOLD) | **1.0** (FA=0) | 1.0 / FA=0 | PASS |
| HITL / REG | 4 / 50 | REG excluded from STP denom | |
| Gate | **PASS** | both bars | |

Residual HITL: `{'POLICY_HOLD': 3, 'INK_ABSENT': 1}`  
REG classes: `{'FAX_PATCH': 22, 'DOCUMENT_SEPARATOR': 22, 'UNIQUE_ID_COVER': 6}`
