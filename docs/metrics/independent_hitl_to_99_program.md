# Independent HITL → 97–99% STP program (governance-preserving)

**Baseline (claim pages only):** 797 / 841 = **94.77%** STP · **44** HITL  
**Non-claim REG (159):** out of scope — irreducible separators/fax (do not invent).

| Target | STP needed | Lifts from HITL | Headroom in 44 |
|---|---|---|---|
| **97%** | 816 | **+19** | feasible |
| **98%** | 825 | **+28** | stretch |
| **99%** | 833 | **+36** | only if ink exists |

99% is **not** a policy-relaxation goal. If ink is unread or spouse Box-4 conflicts, HITL stays.

---

## Governance invariants (never break)

1. **Fail closed** — prefer HITL over a wrong AUTO.
2. **No invent** — no synthetic patient/DOB/ID/charge from labels or mailroom.
3. **No threshold fitting** on Independent-1000 to chase STP (no confidence cut tuned on this corpus).
4. **Kill switches** remain: `CDP_UNSTRUCTURED_REG_*`, `CDP_CLOUD_STOP_LADDER`, `CDP_AZURE_DI_CHARGE_*`, `CDP_GPT4O_CROP_*`, `CDP_CONFLICT_AGENT`.
5. **Field residual toolstack v13** decides MISSING_INK / OVERLAP / CONFLICT — case router does not bypass it.
6. **Accepted-field precision gate** — any phase that lifts STP must report false-accept on agent-GT / silver labels when available; stop the phase if FA rises.
7. **Spouse/Other Box-4 ≠ patient** — never twin-promote (N1 in `docs/gt/GAP_CLOSE_STRATEGY.md`).
8. **REG stays REG** — separators/fax never become HITL/STP via name soup.

Release language: claim-page STP is the attack metric; all-page STP includes irreducible REG and must not be “fixed” by absorbing separators.

---

## Remaining HITL taxonomy (44)

| Cohort | n | Track | Root cause (observed) | Governed unlock |
|---|---|---|---|---|
| **H1 Charge observed, policy hold** | 15 | FIELD_INK | Value present (`41`–`45000`) but `LINE_TOTALS_UNCORROBORATED` / `CALIBRATED_*` / `SCALE_RIVAL` / `C3` / `MISSING_E4` | Dual corroboration (Box28↔lineΣ **or** DI crop **or** vision) — never lower E4 alone |
| **H2 DOB empty / fragment** | 6 | FIELD_INK | `NO_NONEMPTY_CANDIDATE` or `"1"`/`"1 1"` | TrOCR → Azure DI DOB crop → vision crop; abstain if no calendar |
| **H3 Insured-name conflict** | 3 | FIELD_INK | Spouse/Other + junk Box4 (`PATD`, label soup) | Vision crop Box4 **or** keep HITL; **no** patient twin |
| **H4 ID ± charge/DOB** | 6 | FIELD_INK | Multi-field weak | Per-field residual ladder only |
| **H5 Unstr DOB miss** | 5+ | UNSTRUCTURED_DI | Freeform DOB not shaped | Page DI re-read + label-near DOB; agent when creds healthy |
| **H6 Unstr name/charge** | ~8 | UNSTRUCTURED_DI | Name non-comma / charge absent / `RESET FORM` junk | Strict name shape; charge cue lines; junk → stay HITL |

---

## Step-by-step program

### Phase 0 — Freeze baseline & gates (done when numbers locked)
- [x] Ledger merge Independent-1000
- [x] REG annotated `IRREDUCIBLE_NO_CLAIM_INK`
- [ ] Snapshot `docs/metrics/independent_1000_v13c_summary.json` as **baseline_t0**
- [ ] Enable FA scoring vs `evaluation_data/hackathon_agent_gt/field_truth.json` on every lift batch

**Exit:** baseline hash + FA harness wired.

### Phase 1 — H1 charge corroboration (target **+8 to +12** STP → ~96.0–96.5%)
**Goal:** lift charge-only FIELD_INK where a **second independent engine** confirms the same amount.

Steps:
1. Export H1 id list (`miss=['total_charge']`, FIELD_INK).
2. For each: run **Azure DI charge crop** + existing line-Σ / Box28 authority (`resolve_safe_charge_total`).
3. Accept AUTO only if authority returns confirmed amount **and** reason not in fail-closed set (`DIGIT_SOUP`, `SCALE_RIVAL` without DI agree, bleed cents).
4. Kill-switch: `CDP_AZURE_DI_CHARGE_ACCEPT=0` reverts lifts.
5. Measure: ΔSTP, FA on scored accepts, residual H1 count.

**Do not:** AUTO on `CHARGE_VISION_LOCAL_SCALE_RIVAL_HITL` without DI agree; AUTO `45000` place-shift soup.

**Exit gate:** FA ≤ baseline; STP claim-page ≥ **96%** or H1 exhausted with documented abstains.

### Phase 2 — H2 DOB residual ladder (target **+2 to +4** → toward **97%**)
1. Confirm TrOCR + `CDP_AZURE_DI_DOB_RESIDUAL` (or vision crop) on H2 only.
2. Accept only calendar-valid DOB with engine agreement or DI confirm.
3. Fragments `"1"` / `"1 1"` stay HITL.

**Exit gate:** claim-page STP ≥ **97%** **or** remaining H2 are `HANDWRITING_UNREADABLE` (honest HITL).

### Phase 3 — H5/H6 unstructured precision lifts (target **+3 to +6**)
1. Name: accept `LAST FIRST` / `LAST, FIRST` only via `_looks_like_person_name`; reject `RESET FORM`.
2. DOB: birthdate-proximate lines only (already); optional text agent when Azure OpenAI **not** 401.
3. Charge: TOTALS cue + tiny allow only with cue (already).
4. Re-run `scripts/rerun_independent_open_hitl.py` on UNSTRUCTURED_DI residual only.

**Exit gate:** no new REG→HITL name-soup; FA flat.

### Phase 4 — H3/H4 residual vision (target **+2 to +5**, stretch **98%**)
1. Box4 vision crop for insured_name when relationship ≠ Self.
2. ID residual (vision/DI) for short-pad / conflict.
3. Conflict agent only with healthy credentials + stop ladder.

**Exit gate:** spouse conflict with unread Box4 remains HITL (governance).

### Phase 5 — Honest ceiling & ops packaging (99% only if ink exists)
1. Classify residual HITL as `INK_ABSENT` vs `POLICY_HOLD` vs `REL_CONFLICT`.
2. Publish two rates forever:
   - **Claim-page STP** (attack metric)
   - **All-page STP** (includes REG)
3. 99% requires ≥36/44 lifts — only declare if residual ≤8 and all are `INK_ABSENT`/`REL_CONFLICT`.

---

## Phase runner (ops)

```bash
# Phase 1 — charge cohort
python3 -u scripts/run_independent_hitl_phase.py --phase H1_CHARGE \
  --ledger-a evaluation_results/hackathon_600_independent_v13c \
  --ledger-b evaluation_results/hackathon_400_remainder_independent_v13c

# After each phase
python3 -u scripts/score_independent_hitl_gates.py --phase H1_CHARGE
```

Config: `config/independent_hitl_program_v1.yaml`.

---

## Projected path (precision-safe, not a promise)

| After phase | Claim-page STP (est.) | Notes |
|---|---|---|
| Baseline | 94.8% | 797/841 |
| Phase 1 | 96.0–96.5% | charge corroboration |
| Phase 2 | **97.0–97.5%** | DOB residuals that have ink |
| Phase 3 | 97.5–98.0% | unstructured DOB/name |
| Phase 4–5 | 98–99% | only with real Box4/ID ink; else stop |

If Azure OpenAI stays 401, Phases 3–4 lean on DI + local OCR only — 99% may be unreachable without inventing; **stop at honest ceiling**.

---

## Explicit non-goals

- Absorbing 159 REG into STP/HITL.
- Twin-promoting patient→insured on Spouse/Other.
- Fitting calibrated confidence on Independent to clear H1.
- Declaring 99% from all-1000 denominator (REG floor ≈ 15.9%).
