# True STP phase plan — 90% → 95% → 96%

**Cohort:** Independent Samples-100 (`offset 50 --limit 100`, field-cascade-v12 + v13 recovery + residual wiring harden + **accuracy-first LLM**).  
**Baseline (in-flight ~83 done):** ~**84%** True STP · field HITL only · REG=0 · median ~33s.  
**Bar:** True STP = claim AUTO with zero critical field HITL. Never invent ink. Exact accuracy must not fall when STP rises.

| Gate | True STP | Max HITL / 100 | Lift from ~84% (~16 HITL) |
|------|----------|----------------|---------------------------|
| **P1** | **≥90%** | ≤10 | Clear **~6** HITLs |
| **P2** | **≥95%** | ≤5 | Clear **~11** HITLs |
| **P3** | **≥96%** | ≤4 | Clear **~12** HITLs |

Live HITL Pareto (Independent-100 so far): **charge ~70% · short-padded ID ~25% · name conflict ~5%**. Phases below attack that order.

---

## Accuracy-first LLM policy (pipeline revisit)

**Principle:** Latency stop-ladder / doc budget may skip cloud only when locals are **safely** settled. For every accuracy-critical residual, bring **DI and/or Claude/gpt-4o** — never leave dual-local ink as MISSING_E4 because cloud was skipped.

| Class | Always call | Strong E4 / unlock | Must not |
|-------|-------------|-------------------|----------|
| Charge, 0 lines, dual-local | **Azure DI** (default ON); LLM if DI abstains | `CHARGE_DI_LOCAL_CONFIRMED` or `CHARGE_VISION_LOCAL_CONFIRMED` | Invent amount; skip via budget |
| Charge place-shift vs Σ / lines | DI **and** vision arbitrator | Conflict agent listed rivals | Treat place-shift as settle |
| Short-padded ID | Vision match-local | Second family / authorized index | Accept lone padded shell |
| Name conflict | Vision tie-break (+ DI name confirm) | Soft-eq only when cascade settled | Invent third name |
| DOB unsettled | TrOCR → DI → vision | Calendar-shaped only | Stack after one shaped cloud |

**Code:** `packages/extraction_recovery/llm_accuracy_policy.py`  
**Flags:** `CDP_ACCURACY_FIRST_LLM=1` (default), `CDP_AZURE_DI_CHARGE_RESIDUAL=1` (default), `CDP_GPT4O_CROP_RESIDUAL=1`, `CDP_CONFLICT_AGENT=1`.  
**Budget:** `force_cloud_despite_budget` overrides soft/hard skip for the classes above.

---

## Non-negotiables (every phase)

1. **Fail-closed on place-shift / digit-drop / scale twins** unless line-Σ, cash-ruling, or financial authority owns the selected total.
2. **Never `LOCALS_SETTLED` skip** on dual Box28 with `observed_line_charges=[]` or Box28 place-shift of line Σ.
3. **No residual-off / OCR-shortcut latency cheats** — residual-off collapsed ops STP to ~50%.
4. **LLM/DI on every accuracy-critical residual** — see table above.
5. **Measure on Independent-100 first**, then tip-overlap n100, then ops ≥300 before claiming a gate.
6. **Regression pack green:** `test_pipeline_residual_wiring`, `test_llm_accuracy_policy`, `test_cloud_stop_ladder`, `test_evidence_reconciliation`, charge/ID gpt4o suites.

---

## Phase 1 — ≥90% True STP (clear ~6 HITLs)

**Theme:** Mint strong E4 with DI **or** vision+local; don’t leave Box28 dual-local stranded with 0 lines.

### P1.A — Charge MISSING_E4 with 0 observed lines

**Claims:** DJJM.036/037/049, DJKH.023/035 — dual paddle+rapid Box28, `lines=0`, MISSING_E4.

| Step | Change | Exit check |
|------|--------|------------|
| 1 | Stop-ladder unsettled when lines=`[]` (done) | `charge_zero_lines_needs_cloud` |
| 2 | DI charge residual **default ON** (done) | `azure_di_charge_residual_enabled()` |
| 3 | DI agrees dual-local → `CHARGE_DI_LOCAL_CONFIRMED` | Decide-only → TRUE_STP |
| 4 | DI abstains + Claude/gpt-4o matches → `CHARGE_VISION_LOCAL_CONFIRMED` (done) | `test_vision_local_mints_strong_e4_without_di` |
| 5 | Cloud disagrees → HITL | No false ACCEPT |

**Expected unlock:** **4–6** HITLs.

### P1.B — Place-shift / single-line uncorroborated

**Claims:** DJJM.040.

| Step | Change | Exit check |
|------|--------|------------|
| 1 | Refuse place-shift settle (done) | `charge_place_shift_needs_cloud` |
| 2 | Force vision even if DI agrees (done) | `test_place_shift_vs_lines_always_needs_vision` |
| 3 | Line-cell crop + conflict agent next | Router executes |
| 4 | Never Σ-rewrite disagreeing Box28 | Truncated-box test green |

**Expected unlock:** **1–2** HITLs.

### P1.C — Router execution

Accuracy policy already forces DI+LLM. Next: execute line-cell crops + conflict agent for OVERLAP (not telemetry-only).

### P1 gate

Independent-100 ≥90% · tip n20 holds · suites green · budget must not skip accuracy cloud.

---

## Phase 2 — ≥95% True STP (clear ~5 more)

**LLM on every padded ID and name conflict.**

### P2.A — Short-padded member ID

Vision match-local (done gates); fix gap taxonomy; optional authorized member index (Lane C). Unlock **2–4**.

### P2.B — Bleed / conflict margin

Cash ruling without `$`; conflict agent listed rivals only. Unlock **1–2**.

### P2.C — Name conflict

Vision tie-break; often free after charge clears. Unlock **0–1**.

### P2 gate

Independent-100 ≥95% · tip n100 ≥93% · zero critical false accepts.

---

## Phase 3 — ≥96% True STP (≤4 HITL)

Irreducible HITL budget documented · tip n100 ≥95% · ops ≥300 ≥94% · Lane C / geometry cents only if still short · **never** loosen CONFLICT_MARGIN or residual-off.

---

## Work sequence

```
Accuracy-first LLM (DI default ON + vision+local E4)   [done]
  → Force DI/LLM on 0-line + place-shift                [done]
  → P1.C line-cell + conflict agent execution
  → HITL redecide + Independent-100 confirm → GATE 90
P2 padded ID + bleed + name → GATE 95
P3 ops ≥300 + optional Lane C → GATE 96
```

**Redecide:** HITL-only subset before full n100 each phase.

---

## Tracking

| Artifact | Role |
|----------|------|
| `evaluation_results/hackathon_100_independent_v13/` | Live Independent-100 |
| `docs/metrics/hackathon_100_independent_v13.json` | Gate scorecard |
| `packages/extraction_recovery/llm_accuracy_policy.py` | When to force DI/LLM |
| `packages/extraction_recovery/pipeline_contract.py` | Wiring contracts |
| `docs/FIELD_RECOVERY_TOOLSTACK_V13.md` | Tool ladder |
| `docs/gt/STP94_AUTHORIZED_REFERENCE_PLAN.md` | Lane C identity |
