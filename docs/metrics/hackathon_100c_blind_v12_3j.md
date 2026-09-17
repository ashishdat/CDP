# Blind-100 (`docs[350:450]`) — v12.3j

Prior blind (`hackathon_100_new_cascade_v12`, partial 84): **46% STP**, **37% REG**, 17% field HITL.

v12.3i partial (23/100): **91% STP**, **0% REG**, 2 DOB HITL — mid-stream letter confusable (`01i081996`) poisoned compact digit assembly.

## Fixes in v12.3j

1. **DOB letter-as-separator** — when primary confusable→digit compact fails, retry after dropping mid-digit letters (`i`/`l`/`|`/…) as damaged slashes (`01i081996` → `01/08/1996`).
2. **Azure DI DOB crop residual ON** after TrOCR miss (rare; ~1–3s; still page-corners OFF / charge residual OFF).

## Run

`evaluation_results/hackathon_100c_blind_cascade_v12_3j` — offset 350, limit 100, workers=1.
