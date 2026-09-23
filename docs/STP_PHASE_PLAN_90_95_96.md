# True STP phase plan — 90% → 95% → 96%

**Cohort:** Independent Samples-100 (`offset 50 --limit 100`, field-cascade-v12 + v13 recovery + residual wiring harden `ca4edfd`).  
**Baseline (in-flight ~83 done):** ~**84%** True STP · field HITL only · REG=0 · median ~33s.  
**Bar:** True STP = claim AUTO with zero critical field HITL. Never invent ink. Exact accuracy must not fall when STP rises.

| Gate | True STP | Max HITL / 100 | Lift from ~84% (~16 HITL) |
|------|----------|----------------|---------------------------|
| **P1** | **≥90%** | ≤10 | Clear **~6** HITLs |
| **P2** | **≥95%** | ≤5 | Clear **~11** HITLs |
| **P3** | **≥96%** | ≤4 | Clear **~12** HITLs |

Live HITL Pareto (Independent-100 so far): **charge ~70% · short-padded ID ~25% · name conflict ~5%**. Phases below attack that order.

---

## Non-negotiables (every phase)

1. **Fail-closed on place-shift / digit-drop / scale twins** unless line-Σ, cash-ruling, or financial authority owns the selected total (`pipeline_contract` + evidence tests).
2. **Never `LOCALS_SETTLED` skip** on dual Box28 with `observed_line_charges=[]` or Box28 place-shift of line Σ (wiring stamp required).
3. **No residual-off / OCR-shortcut latency cheats** — prior residual-off collapsed ops STP to ~50%.
4. **Measure on Independent-100 first**, then tip-overlap n100, then ops sample ≥300 before claiming a gate.
5. **Regression pack must stay green:** `test_pipeline_residual_wiring`, `test_cloud_stop_ladder`, `test_evidence_reconciliation`, charge/ID gpt4o suites.

---

## Phase 1 — ≥90% True STP (clear ~6 HITLs)

**Theme:** Finish wiring you already partially shipped; mint strong E4 where ink exists; don’t leave Box28 dual-local stranded with 0 lines.

### P1.A — Charge MISSING_E4 with 0 observed lines (largest bucket)

**Claims (examples):** DJJM.036/037/049, DJKH.023/035 — dual paddle+rapid Box28 shaped, `lines=0`, reasons lack `CLAIM_TOTAL` / strong E4.

| Step | Change | Exit check |
|------|--------|------------|
| 1 | Keep stop-ladder **unsettled** when `observed_line_charges=[]` (done) | Contract `charge_zero_lines_needs_cloud` |
| 2 | Always run **one** Azure DI charge crop (corroborate) before gpt-4o on this class | Field row has `azure_di_residual` or explicit DI abstain reason — never silent skip |
| 3 | If DI agrees with dual-local ±$1 → mint `CHARGE_DI_LOCAL_CONFIRMED` + allow E4 path | Decide-only replay of these 5 claims → TRUE_STP |
| 4 | If DI abstains but Claude/gpt-4o matches dual-local → same E4 partner path | Same replay |
| 5 | If cloud disagrees or abstains → stay HITL (no invent) | No false ACCEPT |

**Expected unlock:** **4–6** of the 0-line MISSING_E4 HITLs.

### P1.B — Single-line uncorroborated / place-shift vs Σ

**Claims (examples):** DJJM.040 (`LINE_SUM_UNCORROBORATED` / 251 vs line ink).

| Step | Change | Exit check |
|------|--------|------------|
| 1 | Stop-ladder already refuses place-shift settle (done) | Contract `charge_place_shift_needs_cloud` |
| 2 | Force **line-cell** gpt-4o/Claude crop for `SINGLE_LINE_GPT4O_LOCAL` when Box28 empty/invalid or place-shift vs sole line | Router `LINE_SUM_UNCORROBORATED` executes, not telemetry-only |
| 3 | Prefer fuller non-implausible twin only when DI/local/cash-ruling corroborates — never Σ rewrite of disagreeing Box28 | `test_truncated_box_does_not_inherit_line_sum_soup_relief` stays green |

**Expected unlock:** **1–2** claims.

### P1.C — Wire v13 router into residual attach (not stamp-only)

Today `recovery_plan` is telemetry. For P1 charge classes, **execute** the planned tool order in `ocr_from_geometry` charge branch.

**Exit:** Every P1 HITL claim either flips STP or emits an explicit ladder stop reason (`DI_ABSTAIN`, `VISION_DISAGREE`, `BUDGET_SKIP`) — no silent LOCALS_SETTLED.

### P1 gate criteria

- Independent-100 True STP **≥90%** (≤10 field HITL), REG=0, infra=0  
- Tip-overlap n20 does not regress below prior (16/20)  
- Residual wiring + evidence suites green  
- Median latency may rise slightly (extra DI on 0-line charge); soft budget 18s / hard 22s still optional-only for unsettled charge

**Stop if:** any new false ACCEPT on place-shift / bleed / truncated Box vs Σ.

---

## Phase 2 — ≥95% True STP (clear ~5 more HITLs)

**Theme:** Identity + hard charge edges that P1 correctly left HITL.

### P2.A — Short-padded member ID (`00000…`)

**Claims:** DJJM.039/041/042/043 — `SHORT_PADDED_MEMBER_ID_NEEDS_CORROBORATION`, gap mislabeled `HANDWRITING_UNREADABLE`.

| Step | Change | Exit check |
|------|--------|------------|
| 1 | Lone padded shell always needs vision (done); dual-engine padded may settle (done) | Contracts in `pipeline_contract` |
| 2 | After vision: accept only if Claude/gpt-4o **matches** a local padded canon (no invent) | ID attach policy already “match local”; add decide replay |
| 3 | Fix gap taxonomy: padded ID → `SHORT_PADDED_NEEDS_CORROBORATION`, not handwriting | Router + gap tests |
| 4 | Optional Lane C: **authorized member index** for residual padded IDs that vision cannot corroborate (`docs/gt/STP94_AUTHORIZED_REFERENCE_PLAN.md`) — operator-filled only | STP may count only with index present; without index stay HITL |

**Expected unlock:** **2–4** claims (vision path); **+0–2** only with authorized index.

### P2.B — Bleed cents / conflict margin charge

**Claims:** DJKH.030 (`BLEED_CENTS_FAIL_CLOSED` on 251.43), DJKH.048 (`CONFLICT_MARGIN` on 701).

| Step | Change | Exit check |
|------|--------|------------|
| 1 | Cash ruling-split **without requiring `$`** (`25|43` class) before bleed fail-closed | Existing cash-ruling tests + these two decide-only |
| 2 | Digit-substring scrap clear under `CHARGE_DI_LOCAL_CONFIRMED`; **keep** place-shift/digit-drop HITL (done) | `test_di_local_confirmed_does_not_clear_place_shift_rival` |
| 3 | Conflict agent only on listed rivals (BOX28\|LINES\|engine values) — never invent | Conflict-agent process tests |

**Expected unlock:** **1–2** claims.

### P2.C — Name engine conflict

**Claims:** DJJM.036 (`NAME_ENGINE_CONFLICT` + charge).

| Step | Change | Exit check |
|------|--------|------------|
| 1 | Soft-eq settle for latency only when cascade accepted; else force vision tie-break (current) | Name stop-ladder tests |
| 2 | gpt-4o may replace name when it matches one local shaped name; garbage third name → HITL | Name residual tests |
| 3 | Measure after P1 charge unlock — this claim is often dual-blocker | Single-blocker name HITL ≤1 on Independent-100 |

**Expected unlock:** **0–1** (often free once charge clears).

### P2 gate criteria

- Independent-100 True STP **≥95%** (≤5 HITL)  
- Tip-overlap n100 True STP **≥93%** (allows tip hardness)  
- Zero critical false accepts vs agent GT on flipped cohort  
- Pipeline contracts expanded with P2 claim IDs as fixtures where possible

**Stop if:** authorized-index path is used without operator file, or ID vision invents digits.

---

## Phase 3 — ≥96% True STP (≤4 HITL / 100)

**Theme:** Residual irreducible + ops generalization. Do **not** loosen evidence policy.

### P3.A — Irreducible HITL budget (keep ≤4)

Reserve HITL for:

- Genuine dual-shaped amount twins with no cash ruling / line Σ / DI partner  
- Unreadable / chrome ID after vision  
- True multi-field identity conflict without authorized reference  

Document each remaining HITL with claim id, gap class, and “why AUTO is unsafe.”

### P3.B — Ops generalization (same rate, bigger N)

| Step | Cohort | Pass bar |
|------|--------|----------|
| 1 | Tip-overlap n100 | ≥95% True STP |
| 2 | Fresh OCR ops sample ≥300 (no residual-off) | ≥94% True STP, REG&lt;1%, median ≤40s |
| 3 | Blind holdout (locked set) | ≥96% True STP **or** explain each miss |

### P3.C — Only if still short of 96%

Ordered, precision-safe levers (pick one at a time, measure, keep or revert):

1. **Authorized member index** for residual ID/name/DOB (Lane C) — never for `total_charge`  
2. **Geometry cents / ruling** expansion for bleed cohort only  
3. **Sixth-row / line-window** re-OCR when Box28 blank and lines under-read  
4. **Never:** lower CONFLICT_MARGIN, accept place-shift as E4, or residual-off

### P3 gate criteria

- Independent-100 **≥96%** and tip-overlap n100 **≥95%**  
- Ops ≥300 at **≥94%** with no bleed-cents AUTO without cash ruling  
- Written kill-list of the ≤4 remaining HITLs

---

## Work sequence (engineering)

```
P1.A DI/E4 for 0-line dual Box28
  → P1.B execute line-cell vision for uncorroborated / place-shift
  → P1.C router execution (charge only)
  → Independent-100 redecide HITL-only + full n100 confirm  → GATE 90
P2.A padded ID vision + taxonomy
  → P2.B bleed/cash ruling + conflict agent
  → P2.C name (if still blocked)
  → GATE 95
P3 irreducible budget + ops ≥300 + optional Lane C
  → GATE 96
```

**Redecide protocol:** For each phase, run decide-only (or cascade `--resume` HITL subset) on the prior HITL claim list before a full 100. Cheaper, isolates lift.

---

## Tracking

| Artifact | Role |
|----------|------|
| `evaluation_results/hackathon_100_independent_v13/` | Live Independent-100 |
| `docs/metrics/hackathon_100_independent_v13.json` | Gate scorecard (write on completion) |
| `packages/extraction_recovery/pipeline_contract.py` | Fail-closed wiring contracts |
| `docs/FIELD_RECOVERY_TOOLSTACK_V13.md` | Tool ladder reference |
| `docs/gt/STP94_AUTHORIZED_REFERENCE_PLAN.md` | Lane C for P2/P3 identity |

Update the scorecard after each gate with: True STP, field HITL, REG, median/mean latency, flipped claim ids, false-accept count vs GT.
