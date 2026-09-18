# Blind-50 (`docs[350:400]`) — v12.3o

Product path: gpt-4o crop residuals (DOB/ID), charge DI corroboration, DOB punct repair, ID digit-conflict tie-break.

Slice: `Group A/M048HJDF.022` … `Group A/M048HJE5.021` · offset 350 · limit 50 · workers=2  
Artifact: `evaluation_results/hackathon_50_blind_cascade_v12_3o/`

## Summary table

| Metric | Value |
| --- | ---: |
| **TRUE_STP** | **94%** (47/50) |
| Field HITL | 6% (3/50) |
| REG HITL | 0% (0/50) |
| Registration OK | 98% (49/50) |
| Completed | 100% (50/50) |
| **Accuracy (field GT)** | **Unavailable** (no labels on Hackathon ZIP) |
| Operational proxy (TRUE_STP) | 94% |
| Field auto — patient_dob | 98% (49/50) |
| Field auto — total_charge | 98% (49/50) |
| Field auto — insured_name | 98% (49/50) |
| Field auto — patient_name | 96% (48/50) |
| Field auto — insured_id_number | 96% (48/50) |
| **Latency mean** | **45.9s** |
| Latency median | 45.4s |
| Latency min | 12.8s |
| Latency max | 83.4s |
| ≤30s bar | Not met (mean 45.9s; charge DI corroborate ON) |
| gpt-4o crop calls | 4 (ID×3, DOB×1) |
| Azure DI calls | 64 (charge 59, DOB 2, corners 2, unstr. page 1) |
| **gpt-4o cost / page** | **\$0.00017** |
| Cloud cost / page (low DI) | \$0.0021 |
| Cloud cost / page (high DI) | \$0.0130 |
| HITL labor amortized / page | \$0.0180 (\$0.30 × 3 HITL ÷ 50) |
| **Fully loaded / page (low DI)** | **\$0.020** |
| **Fully loaded / page (high DI)** | **\$0.031** |
| gpt-4o batch cost | \$0.008 |
| Cloud batch (low / high DI) | \$0.104 / \$0.648 |
| HITL labor batch | \$0.90 |
| Fully loaded batch (low / high) | \$1.00 / \$1.55 |
| HJDF bundle STP | 100% (29/29) |
| HJE5 bundle STP | 85.7% (18/21) |
| HITL docs | HJE5.006 (ID), HJE5.018 (name), HJE5.021 (DOB) |

### Cost assumptions

gpt-4o Azure Global Standard \$2.50/1M in + \$10/1M out; ~659 in / ~45 out per crop ≈ \$0.0021/call. DI \$0.0015–\$0.01/call (SKU band). HITL labor \$0.30/reviewed page.
