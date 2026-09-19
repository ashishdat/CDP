# Redesign evaluation report (implementation owner)

**Commit at report time:** see git tip on `feature/cdp-v3`  
**Golden labels:** not modified  
**Vendor GT on Hackathon ZIP:** none — accuracy marked unavailable; agent GT is not vendor truth

## Implementation summary

Mapped the operator redesign onto the live stack and implemented missing stage
packages A–H with tests and feature-flagged adapters. Closed the M048DJJF.013
POS `11.00` false-STP path via geometry + line-sum guards. GPT-4o remains
non-authoritative for monetary fields without independent local evidence.

## Architecture mapping

See `docs/REDESIGN_AS_IS_TARGET_MAPPING.md`.

## Changed files (this workstream)

- `packages/image_evidence/` — ROI ink dispositions (BLANK_CONFIRMED…)
- `packages/package_intelligence/` — claim package / separator / page class
- `packages/geometry_authority/` — Box 24B vs 24F vs 28 gates
- `packages/candidate_evidence/` — lineage-complete candidate schema
- `packages/field_authority/` — `accept(field)` gate conjunction
- `packages/financial_reconciliation/` — explicit monetary dispositions
- `packages/ocr_portfolio/` — controlled monetary crop variants
- `packages/calibration/` — leakage-safe development dataset + precision thresholds
- `packages/claim_decision/hitl_routes.py` — narrow HITL routes
- `packages/claim_evidence/line_sum_authority.py` — POS-like line-sum reject
- `packages/extraction_recovery/field_cascade.py` — POS-like total semantic gate
- Prior: `config/architecture/redesign_stack_v1.yaml`, OpenOCR/Monkey adapters

## Tests executed

```text
pytest tests/unit/cases/test_redesign_architecture_stages.py \
       tests/unit/cases/test_redesign_stack_v1.py \
       tests/unit/cases/test_line_sum_authority.py \
       tests/unit/cases/test_gpt4o_crop_residual.py \
       tests/unit/cases/test_field_cascade_v7_strategy.py
→ 71+ passed (incl. M048DJJF.013 POS regression)
```

Golden Pack re-run (no label edits):

```text
python3 evaluation/accuracy_100_sample.py \
  --dataset evaluation_data/phase8_7_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V3 \
  --output evaluation_results/accuracy_100_sample_v3_redesign_stages
```

Ops smoke (GPT residuals off for deterministic local path):

```text
scripts/run_hackathon_1000_cascade.py \
  --documents "Group A/M048DJJF.006,Group A/M048DJJF.013" \
  --out-dir evaluation_results/hackathon_redesign_djjf_smoke
```

## Before / after governed metrics

### Ops True STP (Hackathon — no vendor field GT)

| Metric | Before (50-claim v12_3x) | After (targeted DJJF smoke) |
|---|---|---|
| Documents | 50 | 2 (DJJF.006, .013) |
| True STP | **4%** (2/50) | **0/2** (expected; finance unresolved) |
| Claim HITL | 96% | 2/2 |
| Registration HITL | 0% | 0% |
| Field-ink HITL | 96% | 2/2 |
| Critical blocker | total_charge 48/50 | total_charge 2/2 |
| M048DJJF.013 | prior smoke **TRUE_STP @ 11.00** (FA risk) | **HITL** `LINE_SUM_UNCORROBORATED` |
| M048DJJF.006 | HITL / uncorroborated | HITL `EMPTY_FINANCIAL_INK` (no invented 297.00) |
| Field accuracy | UNAVAILABLE_NO_GROUND_TRUTH | same |

### Golden Pack V3 (extraction harness STP **proxy** — not True STP)

| Metric | Before | After redesign stages |
|---|---|---|
| Exact accuracy | 99.8% | 99.8% |
| Critical exact | 99.71% | 99.71% |
| False accepts | **0** | **0** |
| claim_stp_proxy | 98% | 98% |
| claim hard HITL | 2% | 2% |
| P50 latency | ~1377 ms | ~1629 ms |
| Scope | EXTRACTION_HARNESS, identity forced | unchanged |

### Phase 8.10 historical freeze (unchanged reference)

claim_stp 0%, claim_hitl 100%, critical FA 0, overall accuracy 89.05%.

## Release gates

| Gate | Result |
|---|---|
| True STP ≥94% | **FAIL** — ops sample still ~4% (finance EMPTY / uncorroborated dominates) |
| Claim HITL ≤6% | **FAIL** — ~96% on 50-claim blind |
| Critical accepted precision ≥99.5% | **PASS on Golden proxy**; ops unscored (no vendor GT) |
| False-accepted critical = 0 | **PASS on Golden**; DJJF.013 POS FA path closed in smoke |
| Registration HITL ≤1% | **PASS** (0% on measured samples) |
| All governed rows scored | Golden yes; Hackathon accuracy UNAVAILABLE |
| No Golden-label mutation | **PASS** |
| No test regression | **PASS** (unit suite green) |

**Redesign is NOT complete** — release gates for True STP / claim HITL are not met.

## Largest HITL buckets (evidence-based next experiments)

1. **EMPTY_FINANCIAL_INK (~94% of 50-claim blockers)** — blank box-28 + no recoverable line charges. Next: ROI ink taxonomy → BLANK_CONFIRMED (optional) vs INK_PRESENT_UNREADABLE; expanded charge-column geometry; monetary crop variants on 24F only; never invent.
2. **LINE_SUM_UNCORROBORATED** — observed lines without dual-engine / box-28 corroboration. Next: parallel independent variants on authorised 24F crops; calibrate acceptance risk; keep GPT residual-only.
3. **Name / policy gaps (smaller)** — continue gpt-4o name arbitrator with local consensus.

## Total-charge ink tune (follow-on)

**Commit:** tip of `feature/cdp-v3` after ruling-split / prefer-ink / line-identity fixes.

### Root cause (pixels)

On CMS-1500 24F, typed amounts sit right-aligned against the dollars|cents dashed
vertical ruling. The primary template x-window often clips to a leading digit
(`6` / `2`), while a right-shifted window that also covers units reads digit soup
(`64010`, `26010`). Box-28 is frequently ruling-only blank (`BLANK_CONFIRMED`).

Agent visual GT for M048DJJF.002 previously listed `910.00` (`640+260+10`); warped
24F crops show **`640+260+260=1160.00`**. M048DJJF.006 is a single `270.00` line
(POS `11` is 24B, not a second charge).

### Fixes

- Dollars-only OCR left of the vertical dashed ruling + `prefer_charge_ink_amount`
- Fast mode keeps primary+mid+right charge windows
- Duplicate line amounts (`260+260`) no longer collapse in financial reconcile
- GPT empty-finance sweep skips `BLANK_CONFIRMED` cells
- Monetary shaping: ruling-tail `5`, units bleed `…10`

### Smoke (same docs, after ink tune)

```text
scripts/run_hackathon_1000_cascade.py \
  --documents "Group A/M048DJJF.002,Group A/M048DJJF.003,Group A/M048DJJF.006" \
  --out-dir evaluation_results/hackathon_ink_tune_djjf_smoke
```

| Document | Before (EMPTY / wrong) | After |
|---|---|---|
| M048DJJF.002 | EMPTY_FINANCIAL_INK / GPT soup | **TRUE_STP `1160.00`** (640+260+260) |
| M048DJJF.003 | EMPTY_FINANCIAL_INK | **TRUE_STP `260.00`** |
| M048DJJF.006 | EMPTY / POS confusion | **TRUE_STP `270.00`** |

### Same-10 before/after (first 10 of 50-claim blind)

| Metric | Before (`v12_3x`) | After ink tune |
|---|---|---|
| True STP | **0/10 (0%)** | **7/10 (70%)** then FA retest closed DJJF.005 `2701→270` |
| total_charge AUTO | 0/10 | 8/10 on first pass; DJJF.005 units-bleed FA fixed |
| Dominant residual | EMPTY_FINANCIAL_INK ×10 | LINE_SUM_UNCORROBORATED / evidence policy on 2–3 docs |

Units-bleed follow-up: `shape_monetary("2701.00")→270.00` and GPT merge keeps local clean stem
(`CHARGE_GPT4O_CORROBORATED_LOCAL_KEPT`). Retest DJJF.005/006 → both **TRUE_STP @ 270.00**.

Unit: `test_total_charge_recovery_regressions.py` + redesign stages + line_sum → **48+ passed**.

### 50-claim ink-tune run is not an after metric

`evaluation_results/hackathon_50_ink_tune_after` finished 2026-09-19 10:52 UTC, **before** the split-read commit (`723f457`, 10:53). It is not the post-fix 50-claim baseline.

| | Baseline `hackathon_50_blind_cascade_v12_3x` | This run |
|---|---|---|
| Completed | 50/50 | **13/50** |
| True STP | **2/50 (4%)** | 9/50, but **not comparable** |
| HITL | 48 | 4 (completed only) |
| Stage failure | 0 | **37** OCR `BrokenProcessPool` (all 35 DJJM + DJJF.014/015) |
| total_charge blockers | 48 | 4, all `LINE_SUM_UNCORROBORATED` |
| Dominant gap | EMPTY_FINANCIAL_INK ×47 | pool crash, not ink |

On the 13 claims that finished, known pre-fix errors are still in the file: DJJF.002 HITL **`621.00`** (later smoke **`1160.00`**), DJJF.009 TRUE_STP **`2701.00`** (later smoke **`270.00`**), DJJF.006 HITL **`2701.00`**. Do not read 9/50 (18%) as True STP. The identical 50-claim rerun on current code is still required. Release gates are not met.

## Vision corroboration of the four residual blockers

GPT-4o crop residual is a corroborator, never sole monetary or date authority.
Golden labels were not mutated.

| Issue | Mechanism | Measured |
|---|---|---|
| Split-read cents (`640 .101` → `101`) | Prefer a local/vision stem within $1 over the fragment | M048DJJF.002 **TRUE_STP `1160.00`** (640+260+260), not `621` |
| Line-sum veto by POS `11` | POS-like locals are non-votes; GPT cannot promote alone | M048DJJF.009 **TRUE_STP `270.00`**, one line (not `540`) |
| Name E2 (`WOOD`/`WO0D`, `KIVERA`/`RIVERA`) | `0→O` normalization, plus vision tie-break when locals are confusable but not normalize-exact | M048DJJF.008 **TRUE_STP `WOOD AVA`**. M048DJJM.019 name **AUTO `RIVERA LARAA`** (`GPT4O_NAME_INK_CONFLICT_RELIEVED`) when paddle read `KIVERALARAA` |
| DOB without local digits | Shaped vision date promotes only if a local read shares ≥4 digits | M048DJJM.019 DOB **ESCALATE** `MISSING_E2` (`GPT_DOB_NEEDS_LOCAL_DIGITS`). Vision `11/02/1980` is not STP. A lone local `1` cannot confirm `07/02/1980` |

Smoke: `evaluation_results/hackathon_ai_confirm_smoke` (002/008/009 charges and WOOD) and `evaluation_results/hackathon_ai_confirm_dob_name_gate` (019). Claim 019 stays HITL on DOB only; total charge `270.00` and the name are AUTO. Unreadable single-token names still stay HITL. Release gates are not met; the identical 50-claim after-eval is still outstanding.

## Document-family financial correction

OpenOCR-on-CMS-ROI was the wrong strategy for mixed corpora. Extraction now:

1. Classifies each page (`CMS1500` / `UB04` / `REIMBURSEMENT_SUPERBILL` /
   `RUNNING_ACCOUNT_STATEMENT` / `EOB` / `SEPARATOR` / `ATTACHMENT` / `UNKNOWN`)
2. Forbids CMS Box 28 / 24F unless the family is `CMS1500`
3. Parses superbills as fee×qty lines with printed-total corroboration
4. Parses ledgers with opening/service/payment/ending-balance roles
5. Dedupes cumulative statement transactions by business fingerprint
6. Defines `total_charges` as unique service-charge sum — never ending balance
   or Amount Paid

Disputed DOB labels (DJJF.003, DJJF.037) are recorded in
`docs/gt/ground_truth_discrepancy_ledger.json` and quarantined from OCR accuracy.
No Golden mutation.

The locked Group A 50-claim sample is CMS-1500 on direct OCR probe; family
routing still runs so non-CMS pages cannot enter CMS geometry.


## Exact evidence on 94% STP target

The 50-claim blind run shows **2/50 True STP (4%)** with **48/50 total_charge HITL**, almost all `EMPTY_FINANCIAL_INK`. Closing registration is already solved (0% registration HITL). Reaching ≥94% True STP requires recovering ≈45+ of those charge blockers **without** false accepts — which needs recoverable ink in Box 24F/28 or independent corroboration, not threshold lowering. Current measured evidence **rejects** the claim that 94% True STP is already achieved.
