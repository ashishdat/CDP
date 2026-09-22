# Next strategy: STP first, latency adaptive (v1)

**Status:** latency OCR shortcuts reverted (`c9e67e6`, `6c6c11e`). Cloud **stop ladder** (`0cf1d5c`) stays.

## What failed

| Lever | Intent | Ops outcome |
|-------|--------|-------------|
| Residual-off + paddle-only lines + 1 charge window + critical-exclude | ≤20s/doc | Median ~17s — **hit** |
| Same profile → fresh OCR + decide | Keep tip STP | **377/744 (50.7%)** True STP — **miss** |
| Charge HITL after recovery | Clear finance | **286** charge_field_hitl still dominate |

Blanket “turn cloud/local quality off” bought wall-clock and destroyed charge ink. Do not re-run that profile as an STP gate.

## Baseline after revert

Keep product cascade stamps (residuals ON, dual paddle+rapid lines, full fast charge windows ≥3, no critical-field exclude) **and** stop ladder:

1. Settled local AUTO → skip DI / Claude for that field.
2. At most one cloud residual family per field when locals are unsettled.
3. Claim gate: do not re-litigate charge once authority session has minted.

Prior tip decide-only on richer OCR: **~88.6%** True STP (281/317). That is the floor to re-earn before chasing ≤20s again.

## Next strategy (ordered)

### A. Adaptive spend, not global kill (primary)

| Stage | Rule |
|-------|------|
| Local dual OCR | Always on for charge lines + patient_name confirm (restored). |
| Extra charge x-windows | Keep primary+mid+right; **early-stop** when currency-shaped + conf ≥ floor (no blanket `CHARGE_WINDOWS=1`). |
| Blank rows | After primary empty on a clearly blank row, skip mid/right for that row only. |
| Cloud residual | Only if field still unsettled **and** stop-ladder allows; one cloud call max. |
| Conflict agent | Only on genuine twin conflict after local+one-cloud, not on soft-equivalent. |

Target: same STP ink path as tip, with cloud calls ≈ unsettled-field count (not ≈ field count).

### B. Per-doc latency budget (secondary)

Track elapsed inside OCR worker:

1. Soft budget **18s** — after that, skip *non-blocking* extras (insured_* confirm if Self-promoted, TrOCR when local DOB already shaped).
2. Hard budget **22s** — skip remaining optional residuals; never skip unsettled charge / patient_dob / insured_id when still empty or conflicting.
3. Never set `CDP_CASCADE_RESPECT_ENV=1` with residual=`0` for STP scoring runs.

### C. Parallelism without lock thrash

- OCR workers=1 for cascade until VLM/DI locks are shard-safe (2-worker + single lock → 378s first-doc pathology).
- Prefetch next page geometry while current page’s cloud residual runs (overlap wait, not double OCR).

### D. Charge HITL attack order (STP recovery)

From latest taxonomy on the weak-OCR cohort (still the backlog shape):

1. **charge_field_hitl (~286)** — restore dual-engine + multi-window, then stop-ladder-gated DI/Claude only on empty/conflict.
2. **charge_conflict_margin (~16)** — honor residual winner; do not keep short local as rival after GPT4O/DI accept.
3. **identity_id / dob (~24)** — already largely local-first; keep stop ladder, no critical-exclude.

### E. Measurement split (unchanged rule)

| File | Use for |
|------|---------|
| `tip_decide_only_v1.json` | Frozen-OCR accuracy / tip STP |
| `ops_fresh_ocr_stp_v1.json` | Fresh cascade ops STP only |

Do not merge. Mark any residual-off / latency-smoke ledger as **non-gate**.

## Explicit non-goals (this cycle)

- Re-introducing `CDP_OCR_SERVICE_LINE_DUAL=0` as default.
- `CDP_OCR_CRITICAL_EXCLUDE` for insured_dob/name.
- Global `*_RESIDUAL=0` for STP eval.
- Raising workers above 1 until lock sharding is proven.

## Validation sequence

1. Smoke 20 docs: product defaults + stop ladder — median wall + True STP vs prior tip cohort overlap.
2. If median ≤25s and STP ≥ tip overlap rate → scale 100 → 317 tip set.
3. Only then tune A/B early-stops to pull median toward ≤20s **without** STP drop >2 pp on the same cohort.
