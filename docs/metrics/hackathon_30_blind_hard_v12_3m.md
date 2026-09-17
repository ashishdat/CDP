# Hard blind-30 (`docs[420:450]`) — v12.3m (unstructured REG fallback)

| Metric | Hard-30 v12.3m | Hard-30 v12.3l | Easy blind-30 `[350:380]` |
| --- | ---: | ---: | ---: |
| TRUE_STP | **80%** (24/30) | 70% (21/30) | 100% |
| Field / unstructured HITL | **20%** (6/30) | 13% (4/30) | 0% |
| REG (terminal Track A) | **0%** (0/30) | 17% (5/30) | 0% |
| Mean latency | **24.3s** | 21.8s | 13.8s |

Geometry still failed on the same 5 docs (`HJHO.015/.017/.018/.020/.021`); unstructured DI+heuristic REG fallback recovered all five off Track A.

| Prior REG doc | v12.3m | Unstructured fields | Residual blocker |
| --- | --- | --- | --- |
| `.015` | TRUE_STP | DOB, ID, names, charge | — |
| `.017` | TRUE_STP | DOB, ID, names, charge | — |
| `.021` | TRUE_STP | DOB, ID, names, charge | — |
| `.018` | HITL (`UNSTRUCTURED_DI`) | ID, names, charge (no DOB) | `patient_dob` |
| `.020` | HITL (`UNSTRUCTURED_DI`) | ID, names, charge (no DOB) | `patient_dob` |

Registered-page HITL unchanged: `.019` (DOB), `.022/.024` (ID+DOB), `.025` (ID). Agent path unused (`agent_used=false` — Azure OpenAI 401 in this env); heuristics alone carried freeform STP.

Artifacts: `evaluation_results/hackathon_30_blind_hard_cascade_v12_3m/`.
See `hard_blind_ocr_stack_v12_3m.md` for stack rationale.
