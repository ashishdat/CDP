# Blind-100 (`docs[350:450]`) — v12.3i retest

Prior blind run (`hackathon_100_new_cascade_v12`): **48% STP**, **37% REG**, 15% field HITL.

## Smoke (8 hard claims from prior REG/HITL)

| Claim | Prior | v12.3i | Elapsed |
| --- | --- | --- | ---: |
| HJDF.024 | REG | **TRUE_STP** | 20.7s |
| HJDF.027 | REG | **TRUE_STP** | 19.5s |
| HJDF.041 | HITL (DOB) | **TRUE_STP** | 7.5s |
| HJE5.003 | REG | **TRUE_STP** | 18.9s |
| HJE5.027 | REG | REG (`insufficient_good_matches`) | 18.4s |
| HJHO.001 | REG | **TRUE_STP** | 18.8s |
| HJHO.014 | REG | REG (catastrophic / corners disabled) | 9.8s |
| HJHO.034 | REG | **TRUE_STP** | 13.7s |

**6/8 → TRUE_STP**, mean **15.9s**. Remaining 2 are honest catastrophic REG.

## Full retest

`evaluation_results/hackathon_100c_blind_cascade_v12_3i` — offset 350, limit 100, workers=1, v12.3i product defaults (trail-aware near-miss, TrOCR DOB, LightGlue singleton).
