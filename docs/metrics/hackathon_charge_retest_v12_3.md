# Charge retest v12.3 — first pass (tess-primary + DI)

Run: `evaluation_results/hackathon_charge_retest_v12_3`  
Cohort: 27 GT charge-miss docs + 3 controls (30 total).

## Operational

| Metric | Value |
| --- | ---: |
| True STP | **29/30 (96.7%)** |
| Reg HITL | 0 |
| Field HITL | 1 |
| Baseline STP on same 27 misses | 26/27 |

## Charge accuracy vs agent GT

| | Baseline v12.2 | Retest v12.3 |
| --- | ---: | ---: |
| Charge exact on 27 misses | 0/27 | **1/27** |
| Controls exact | — | 2/2 labeled |

**Verdict:** STP held; charge exact did **not** lift. Root causes from artifacts:

1. When paddle/rapid **agreed** with truncated tess (`157`), DI was skipped.
2. Blank fast-mode rows called DI heavily (**138 charge_crop** calls) — cost blow-up.
3. Non-twin DI sometimes overrode local (`12.00` vs GT `121.00`).

## Follow-up (v12.3b)

- Paddle/rapid **primary** for service-line charges under STP fast; tess digits only if empty.
- DI only to recover **longer digit-drop twins** on short amounts (≤3 dollar digits), never blank rows / non-twin override.
