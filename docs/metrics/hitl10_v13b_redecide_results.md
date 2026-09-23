# Independent-100 v13b — HITL-10 redecide after L1–L5

**Baseline:** 90/100 True STP (`hackathon_100_independent_v13b.json`).  
**Run:** `evaluation_results/hackathon_100_independent_v13b_hitl10_redecide/`  
**Code:** L1–L5 unlocks + precision tighten (DI-raw embed soup, underread scrap only, no BOX28 wipe→geometry invent).

## Results (first redecide, pre-tighten)

| Claim | Plan | Outcome | Selected | Notes |
|-------|------|---------|----------|-------|
| DJJM.040 | L1 yes | **STP** | `2.51` | Cents-column LINES honored |
| DJKH.023 | L2 yes | **STP** | `70.00` | Vision+local; DI raw `70 100` soup |
| DJKH.030 | L3 yes | **STP** | `25.43` | Cash ruling `$ 25:43` (not prior `251.43` read) |
| DJKH.040 | L4 maybe | **STP** | `516.00` | **Suspect** — geometry-underread overrode agent `1571.63` |
| DJKH.048 | KEEP | **STP** | `701.00` | Agent **resolved** this run (plan assumed abstain); DI `70 100 $` |
| DJKN.022 | L4 maybe | **STP** | `25.00` | Agent BOX28 path |
| DJKN.023 | KEEP | **HITL** | `45000.00` | Correct fail-closed |
| EJG7.005 | L4 yes | **STP** | `400.00` | DI+partner BOX28 |
| EJG7.007 | L5 yes | **HITL** | charge `140` | DOB calendar E2 ok; charge margin vs DI `14` underread |
| EJG7.009 | L2 yes | **STP** | `200.00` | DI+local; paddle `20` scrap |

**Raw flip count:** 8/10 → projected **98%** if all count.  
**Precision-safe flips (plan conservative + clean stretch):** DJJM.040, DJKH.023, DJKH.030, EJG7.005, EJG7.009 (=5) → **~95%**.  
**Keep-HITL:** DJKN.023 stayed HITL. DJKH.048 flipped only because agent resolved (not abstain).  
**Follow-up:** DJKH.040 `516` geometry invent patched (keep agent BOX28 when authorize fails); EJG7.007 underread scrap clearance added for redecide-2.

## Projected Independent-100

| Lens | Cleared | True STP |
|------|---------|----------|
| Precision-safe (≥5 clean) | +5 | **~95%** |
| If stretch EJG7.005 + DJKN.022 hold | +7 | **~97%** |
| Irreducible | DJKN.023 (+ DJKH.040 until redecide-2) | remain HITL |
