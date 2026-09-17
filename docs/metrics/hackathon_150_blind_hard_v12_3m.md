# Hard blind-150 (`docs[380:530]`) — v12.3m

Difficult window starting at the HJE5/HJHO cluster (where blind-100 hardness begins) through follow-on IJ* bundles. Product path: Azure DI 429 retry + unstructured REG fallback.

## Final metrics

| Metric | Hard-150 v12.3m | Hard-30 v12.3m `[420:450]` | Blind-100 v12.3k `[350:450]` |
| --- | ---: | ---: | ---: |
| TRUE_STP | **78%** (117/150) | 80% (24/30) | 79% |
| HITL | **22%** (33/150) | 20% (6/30) | 13% |
| REG (terminal) | **0%** (0/150) | 0% | 8% |
| Mean latency | **17.9s** | 24.3s | 17.3s |

Registration geometry failed on 9 docs; unstructured DI recovered all off Track A (**4 STP / 5 HITL**). Overlap with prior hard-30: 24/30 STP (same as v12.3m hard-30).

## HITL breakdown

| Track | n | Typical blockers |
| --- | ---: | --- |
| FIELD_INK | 28 | `patient_dob` (22), `insured_id_number` (14) |
| UNSTRUCTURED_DI | 5 | missing DOB after DI page extract |

Gap classes: CALIBRATION_HITL 16, HANDWRITING_UNREADABLE 10, AMBIGUOUS_DIGIT_FRAGMENTS 9.

## By bundle

| Bundle | n | STP | HITL |
| --- | ---: | ---: | ---: |
| M048HJHO | 50 | 80% | 20% |
| M048HJI6 | 30 | 97% | 3% |
| M048HJE5 | 26 | 77% | 23% |
| M048IJJH | 17 | 76% | 24% |
| M048IJDP | 11 | 45% | 55% |
| M048IJMP | 7 | 57% | 43% |
| M048IJJT | 5 | 40% | 60% |
| M048IJD1 | 4 | 100% | 0% |

Hardest residual: IJDP / IJJT (DOB + ID ink). Unstructured agent unused (`agent_used=false` — Azure OpenAI 401); heuristics carried the 4 STP recoveries.

## Artifact

`evaluation_results/hackathon_150_blind_hard_cascade_v12_3m/`
