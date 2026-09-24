# Similar-sample 1000 full-corpus test report

**Source:** [Google Drive Hackathon zip](https://drive.google.com/file/d/1vhLhHwucY2gG6INZS3MB1MpAE1suaIJW/view?usp=sharing)  
**Selection:** **all 1000** pages (Groups {'Group A': 675, 'Group B': 186, 'Group C': 86, 'Group D': 53})  
**Method:** tip-seed from Independent cascade ledgers

## Product gate

| Metric | Value | Target | Status |
|---|---|---|---|
| Claim-page STP | **96.20%** (809/841) | ≥ 97% | FAIL |
| Accepted precision (GOLD) | **1.0** (FA=0) | 1.0 / FA=0 | PASS |
| HITL / REG | 32 / 159 | REG excluded from STP denom | |
| Gate | **FAIL** | both bars | |

Residual HITL: `{'POLICY_HOLD': 21, 'INK_ABSENT': 11}`  
REG classes: `{'DOCUMENT_SEPARATOR': 54, 'FAX_PATCH': 67, 'UNIQUE_ID_COVER': 38}`

## Context vs slices

| Sample | Claim-page STP | FA | Gate |
|---|---|---|---|
| 200 (first stratified) | see similar_sample_200_v1 | 0 | PASS |
| 300 (holdout) | 98.40% | 0 | PASS |
| **1000 (full)** | **96.20%** | **0** | **FAIL** |
