# Blind-30 (`docs[350:380]`) — v12.3l

Slice of the blind cohort (first 30 of docs[350:450]), current product path including Azure DI 429 retry (~55s).

## Final metrics

| Metric | Blind-30 v12.3l | Blind-100 v12.3k |
| --- | ---: | ---: |
| TRUE_STP | **100%** (30/30) | 79% |
| Field HITL | **0%** | 13% |
| REG | **0%** | 8% |
| Mean latency | **13.8s** | 17.3s |

Registration OK 30/30. Mean ≤30s bar met (max 31.7s on one doc).

## Note

This slice is the easier head of the blind window. Hard REG/DOB/ID HITLs in the full blind-100 clustered later (`HJE5.*` / `HJHO.*` after ~doc 380). Use full docs[350:450] for the harder bar.

## Artifact

`evaluation_results/hackathon_30_blind_cascade_v12_3l/`
