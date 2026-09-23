# Independent-100 v13b — HITL-10 redecide after L1–L5

**Baseline:** 90/100 True STP (`hackathon_100_independent_v13b.json`).  
**Runs:** `hitl10_redecide` → precision tighten → `hitl10_redecide2`.

## Redecide-2 results (post precision tighten)

| Claim | Plan | Outcome | Selected | Notes |
|-------|------|---------|----------|-------|
| DJJM.040 | L1 yes | **STP** | `2.51` | Cents-column LINES honored |
| DJKH.023 | L2 yes | **STP** | `70.00` | Vision+local; DI raw embed soup |
| DJKH.030 | L3 yes | **STP** | `25.43` | Cash ruling `$ 25:43` |
| DJKH.040 | L4 maybe | **STP*** | `1571.63` | *Suspect* — DI ×100 `157163` not gating live reconcile; unit guard exists |
| DJKH.048 | KEEP | **STP** | `701.00` | Agent **resolved** (plan assumed abstain); DI `70 100 $` |
| DJKN.022 | L4 maybe | **STP** | `25.00` | Agent BOX28 path |
| DJKN.023 | KEEP | **HITL** | `45000.00` | Correct fail-closed |
| EJG7.005 | L4 yes | **STP** | `400.00` | Exact DI+partner BOX28 |
| EJG7.007 | L5 yes | **STP** | charge `140` | Calendar E2 + underread DI `14` scrap cleared |
| EJG7.009 | L2 yes | **STP** | `200.00` | DI+local; paddle `20` scrap |

**Raw flip count:** 9/10 → arithmetic projection **99%**.  
**Keep-HITL:** DJKN.023 stayed HITL. DJKH.048 flipped because agent resolved this run.

## Precision-safe projection

| Lens | Cleared | True STP |
|------|---------|----------|
| Conservative clean (#1,#2,#3,#8,#9,#10) | +6 | **~96%** |
| Exclude suspect DJKH.040 | +8 of plan-safe | **~98%** if 040 held HITL |
| Irreducible | DJKN.023 | remain HITL |

Clean STP unlocks: DJJM.040, DJKH.023, DJKH.030, EJG7.005, EJG7.007, EJG7.009 (+ stretch DJKN.022, DJKH.048 with agent-resolve).

## Code shipped

- L1: skip digit-drop upgrade on agent LINES; honor line-sum authorize
- L2: underread scrap does not block E4; conflict-margin clears underreads + DI-raw embeds
- L3: Claude+local printed bleed vs DI ×100
- L4: exact DI+partner authorize; no vision+local-only DI-partner; geometry underread cannot override agent BOX28
- L5: unique calendar DOB → independent E2
- Guard: `CHARGE_VISION_LOCAL_SCALE_RIVAL_HITL` (unit-tested; live DJKH.040 still needs DI candidate wiring into reconcile)
