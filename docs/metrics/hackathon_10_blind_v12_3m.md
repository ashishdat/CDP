# Blind-10 (`docs[350:360]`) — v12.3m

Quick blind smoke on the current product path (Azure DI 429 retry + unstructured REG fallback stamps).

## Final metrics

| Metric | Blind-10 v12.3m | Blind-30 v12.3l `[350:380]` | Hard-30 v12.3m `[420:450]` |
| --- | ---: | ---: | ---: |
| TRUE_STP | **100%** (10/10) | 100% | 80% |
| Field HITL | **0%** | 0% | 20% |
| REG | **0%** | 0% | 0% |
| Mean latency | **21.1s** | 13.8s | 24.3s |

Registration OK 10/10. Docs: `M048HJDF.022`–`.031`. No unstructured REG path triggered (all geometry accepted). Mean ≤30s bar met (max 31.9s).

## Artifact

`evaluation_results/hackathon_10_blind_cascade_v12_3m/`
