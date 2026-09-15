# STP / HITL tuning notes (post-ROI independent samples)

## Changes
1. **CMS-1500 OCR span cleanup** wired into ops OCR + validate (`select_field_span`):
   - Strip box headers / label bleed for names and member IDs
   - Assemble DOB from MM/DD/YY digit tokens; reject invalid assemblies
   - Treat NPI-contaminated total-charge crops as empty (HITL), not `$1.00`
2. **Evidence policy**: `require_strong_e4: false` for `patient_name`, `insured_name`, `insured_id_number`, `patient_dob`; honor explicit opt-out for C2/C3 in `EvidencePolicy._qualified_available`
3. **Claim E6**: read `rel_code`; infer SELF when patient/insured names match; attach to identity fields
4. **C3 reconciler**: format-valid `insured_id_number` satisfies independent-evidence gate after hard validation

## Reprocess metrics (10 previously completed live claims)

| Metric | Value |
|--------|-------|
| True STP (`review_required=false`) | **0 / 10** |
| Dominant remaining blockers | `{'total_charge': 10, 'patient_dob': 9, 'patient_name': 2, 'insured_id_number': 3}` |
| Auto-accepted critical fields | `{'insured_id_number': '7/10', 'patient_name': '8/10', 'patient_dob': '1/10', 'total_charge': '0/10'}` |

## HITL queue (honest remaining gates)
- **`total_charge`**: empty / NPI bleed after span — needs ROI retarget or line-charge E6, not policy waiver
- **`patient_dob`**: empty or un-assemblable OCR tokens on many forms
- **`insured_id_number` / `patient_name`**: residual OCR damage when span cannot recover a clean value

Frozen 100-claim baseline remains NOT QUALIFIED until a full live 100 re-run.

## Charge ROI / line-total E6 + DOB crop reliability (next hard gates)

1. **OCR crop insets** (`packages/extraction_recovery/roi_insets.py`) shrink `patient_dob` and `total_charge` inside the recorded safe cell so header/NPI bleed is excluded without re-registration. Template ROIs retargeted to the same windows.
2. **Service-line charge OCR** in `scripts/ocr_from_geometry.py` writes `service_lines` onto OCR candidates; assemble + complete pass them into `ClaimEvidenceBuilder` so `CLAIM_TOTAL_CONFIRMED` (E6) can auto-accept `total_charge` when the crop total matches Σ line charges.
3. **Authoritative financial E6** enabled on `EvidenceReconciler` so a confirmed claim-total can clear the C3 confidence gate without inventing amounts.
4. **DOB token assembly** keeps edge-glyph stripping; currency span rejects NPI-adjacent `$1.00` artifacts.

Still not an identity-policy waiver. Empty/contaminated crops remain HITL.

## Reprocess after charge ROI / DOB crop gates (independent sample B)

| Metric | Value |
|--------|-------|
| Completed claims reprocessed | 6 / 6 |
| True STP (`review_required=false`) | **0 / 6** |
| `patient_dob` auto-accepted | **1 / 6** |
| `total_charge` auto-accepted | **0 / 6** |

Tight charge crops clear NPI bleed; empty box-28 digit bands and pointer-bleed line charges stay HITL (no invented amounts).

## Strategy redesign: field-cascade OCR (v1)

Replaced RapidOCR-first + bolted crop retries with a governed cascade:

1. Typed crop ladder (DOB digit band, NPI-cleared charge, name/id value bands, charge x-windows)
2. Route engines from `config/ocr_field_routes.yaml` (Paddle → Rapid → Tesseract)
3. Span selection (observed characters only)
4. Semantic accept (`DATE_SHAPED` / `CURRENCY_SHAPED` / …) before stopping

Honesty unchanged: empty/contaminated box-28 stays HITL; E6 only when crop total matches Σ line charges.
See `docs/STP_FIELD_CASCADE_STRATEGY.md`.

### Sample B after cascade redesign

| Metric | Prior (crop bolts) | Cascade v1 |
|--------|--------------------|------------|
| True STP | 0 / 6 | **0 / 6** |
| `patient_dob` auto | 1–2 / 6 | **2 / 6** (digit-band accept on IJN2.008) |
| `total_charge` auto | 0 / 6 | **0 / 6** (empty/NPI box-28 stays HITL by design) |
| `patient_name` auto | ~6 / 6 | **6 / 6** |
| `insured_id_number` auto | ~5 / 6 | **5 / 6** |
| Dominant blockers | DOB + total | `total_charge` 6/6, `patient_dob` 4/6 |

Artifacts: `evaluation_results/operational_e2e_100_v1_std_sample_b_cascade_v1/`.

## Phase 2 tuning: line-sum E6 + cascade preprocess (v2)

Cascade v1 recovered names/IDs well but left **empty box-28** as a hard wall
and often emitted **zero service lines** (header-row probe aborted the table).

### Strategy / architecture changes

1. **`LINE_TOTALS_RECONCILED`** — when box-28 OCR is empty and ≥1 observed
   currency-shaped line charges exist, sum those charges (observed ink only)
   and treat the sum as financial E6 for `total_charge`. Distinct from
   `CLAIM_TOTAL_CONFIRMED` (crop total ∩ Σ lines).
2. **Completion injection** — empty `total_charge` candidates are filled from
   that E6 onto an **authorized OCR engine shell** so route allowlisting does
   not drop the derived amount; provenance records line-sum derivation.
3. **Service-line liveness** — skip leading header/blank rows; charge-column
   currency can prove a row is live when date/CPT probes fail.
4. **Cascade preprocess** — Phase 8.10 `CURRENCY_DECIMAL_V2` on charge
   crops only (full-page bbox OCR kept for DOB/name/ID after crop-OCR
   shifted DOB digits on sample B).
5. **C3 gate** — `LINE_TOTALS_RECONCILED` counts as financial authority for the
   independent-evidence requirement (no invented amounts; no identity waiver).

See `docs/STP_FIELD_CASCADE_STRATEGY.md` (Phase 2).

### Sample B after Phase 2

| Metric | Cascade v1 | Cascade v2 (Phase 2) |
|--------|------------|----------------------|
| True STP | 0 / 6 | **0 / 6** |
| `patient_dob` auto | 2 / 6 | **2 / 6** |
| `total_charge` auto | 0 / 6 | **5 / 6** (line-sum E6) |
| `patient_name` auto | 6 / 6 | **6 / 6** |
| `insured_id_number` auto | 5 / 6 | **5 / 6** |
| Dominant blockers | total 6 + DOB 4 | **DOB 4**, total **1**, id 1 |

`total_charge` is no longer the wall: five claims auto-accept via
`LINE_TOTALS_RECONCILED` from observed service-line charges. Residual HITL is
mostly DOB plus non-critical blockers (e.g. empty `insured_name`) that still
force claim review even when critical blockers are clear.

Artifacts: `evaluation_results/operational_e2e_100_v1_std_sample_b_cascade_v2/`.

## Phase 3: evidence completeness (route + span) — reframed

### Diagnosis (after Phase 2)

1. **`insured_name` false STP wall** — OCR already returned NAME_SHAPED values
   (e.g. `DUNCANTEEANY`, `TRIPLETT .AARON E`) but decision emitted
   `CANDIDATE_ROUTE_AUTHORITY_MISSING` because `insured_name` had no
   `ocr_field_routes.yaml` entry (`blocks_stp: true`, C1).
2. **DOB residual** — fragmented streams with CJK confusables aborted when a
   1-digit year token short-circuited before compact digit-stream assembly.
3. **Name header bleed** — span matched parenthetical `NaTe, Midale` before the
   real ink line under the CMS header.

### Tech stack

**Do not rewrite the stack.** RapidOCR/Paddle routes remain; optional Paddle
install later. DocVQA / Donut / Textract deferred — architecture completeness
first.

### Architecture changes

1. Add **`insured_name` PRODUCTION_APPROVED route** (parity with `patient_name`).
2. **Name span** strips CMS headers before Last, First search; prefers last match;
   expands boilerplate junk (`MIDALE`, `NATE`, …); keeps commas.
3. **DOB assembly** maps `了→7`, falls through 1-digit year to compact stream,
   repairs `MMDD9911 → MMDD1991` when year > 2100 and starts with `9`.
4. Cascade strategy **`field-cascade-v3`**.

See `docs/STP_FIELD_CASCADE_STRATEGY.md` (Phase 3).

### Sample B after Phase 3

| Metric | Phase 2 | Phase 3 |
|--------|---------|---------|
| True STP | 0 / 6 | **2 / 6** |
| `insured_name` auto | 0 / 6 | **6 / 6** |
| `patient_dob` auto | 2 / 6 | **3 / 6** |
| `total_charge` auto | 5 / 6 | **5 / 6** |
| Dominant blockers | DOB 4, total 1, id 1 | **DOB 3**, id 1, total 1 |

`insured_name` is no longer a false STP wall. Two claims reach true STP (IJN2.008,
JJJM.014). Residual HITL is real ink/calibration gaps, not missing route authority.

Artifacts: `evaluation_results/operational_e2e_100_v1_std_sample_b_cascade_v3/`.
Metrics: `docs/metrics/sample_b_cascade_v3_metrics.json`.

## Phase 4: residual gap closure

### Identified gaps (post Phase 3)

1. **Cascade span skip** — DOB digit-band values like `12 26l 108` were never assembled because cascade only spanned empty OCR.
2. **Member-id near-miss** — IJN2.005 had full deterministic + E6 relationship evidence at calibrated ~0.97 vs C3 0.98 gate.
3. **Hard HITL remainders (at Phase 4)** — IJN2.022 ambiguous DOB ink; HJHK.005 empty DOB + no usable line-charge sum.

### Fixes shipped

- Always span-select before semantic accept
- DOB trailing-letter / 3-digit-year recovery + calendar validation
- Identity-corroborated C3 threshold relief (0.95) with `IDENTITY_CORROBORATED_THRESHOLD_RELIEF`

### Sample B after Phase 4

| Metric | Phase 3 | Phase 4 |
|--------|---------|---------|
| True STP | 2 / 6 | **4 / 6** |
| `patient_dob` auto | 3 / 6 | **4 / 6** |
| `insured_id_number` auto | 5 / 6 | **6 / 6** |
| Dominant blockers | DOB 3, id 1, total 1 | **DOB 2**, total **1** |

Artifacts: `evaluation_results/operational_e2e_100_v1_std_sample_b_cascade_v4/`.
Metrics: `docs/metrics/sample_b_cascade_v4_metrics.json`.

### Next honest levers (not policy waivers) → Phase 5

- Retarget DOB ROI / digit-band span for fragmented cells (**done in v5** — IJN2.022 STP)
- Currency-confusable line charges + line-sum injection (**done in v5** — HJHK total auto)
- Remaining: HJHK.005 DOB handwriting still header-only — scan/ROI quality, handwriting model, or human entry
- Do **not** invent DOBs or totals when ink is absent/ambiguous



## Cascade v5 — residual IJN2 / HJHK recovery (crop/OCR, not policy)

| Lever | Change |
|-------|--------|
| Currency confusable | `I/00` / `L00` → `100.00` (observed glyph repair only) |
| Service-line noise | Allow `/` `|` in raw charge ink so repaired amounts are not wiped |
| DOB ROI / crops | Reduce right inset; keep year column; add `dob_year_wide` |
| DOB span | 3-digit year `983`→`1983`; split day `03 1 983 1 9`→`03/19/1983` |
| DOB cells | Optional MM/DD/YY cell OCR after cascade miss |

Sample B target: true STP **5/6** (HJHK DOB handwriting remains HITL when ink is unreadable).


## Cascade v5 sample B results

| Metric | Cascade v4 | Cascade v5 |
|--------|------------|------------|
| True STP | 4/6 | **5/6** |
| `patient_dob` auto | 4/6 | **5/6** |
| `total_charge` auto | 5/6 | **6/6** |

Recovered without policy softening:
- **IJN2.022** DOB via digit-band span (`03/19/1983`) after century-clip / split-day repair
- **HJHK.005** line charge `I/00`→`100.00` → `LINE_TOTALS_RECONCILED` for box-28

Residual HITL: **HJHK.005** handwritten DOB (header-only OCR) — human entry / better scan.

## Cascade v6 independent Sample A

Architecture redesign (`field-cascade-v6`) evaluated on held-out Sample A (no
overlap with Sample B tuning). True STP **2/4** (was 0/5 pre-cascade). Charge
auto **4/4**. Remaining HITL is DOB-only with classified gaps
(`AMBIGUOUS_DIGIT_FRAGMENTS`, `HANDWRITING_UNREADABLE`) — not policy waivers.

See `docs/STP_FIELD_CASCADE_ARCHITECTURE_V6.md` and
`docs/metrics/cascade_v6_independent_eval.json`.

## Cascade v6 HITL leftover closure (Sample A)

- **DJJM.022** → DOB `07/11/1990` (U→0 + year glue)
- **DJJM.042** → DOB `06/14/1974` (split-day + cross-variant fusion)
- Sample A true STP **4/4** (geometry set); no remaining critical HITL

