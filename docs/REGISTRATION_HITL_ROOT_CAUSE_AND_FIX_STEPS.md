# Registration HITL (Track A) — root cause and fix steps

## What we see in cascade-v9 (n≈25 claims so far)

| Track | Disposition | Count (approx) | Meaning |
|-------|-------------|----------------|---------|
| A | `REGISTRATION_FAILED` | 7 | Never reaches field OCR/STP |
| B | `HITL` (field ink) | residual after DOB/name fixes | Fields incomplete |
| — | `TRUE_STP` | rising after v10 field fixes | Full auto |

Failed claims: `DJJF.001/.005/.007`, `DJJM.001/.005/.006/.008`.

## Root cause (not “registration missing”)

Every failure dies at stage **`Acceptance`** on SIFT+FLANN+RANSAC homography.
Dominant rejection token: **`low_inlier_ratio`** (policy `min_inlier_ratio = 0.12`).

| Claim | Best inliers | good_matches | inlier_ratio | coverage | Other gates |
|-------|-------------|--------------|--------------|----------|-------------|
| DJJF.007 | 14 | 126 | **0.111** | 0.37 | ratio only |
| DJJM.005 | 13 | 114 | **0.114** | 0.34 | ratio only |
| DJJM.006 | 13 | 121 | **0.107** | 0.27 | ratio only |
| DJJF.001 | 10 | 86 | **0.116** | 0.16 | ratio only (best) |
| DJJF.005 | 10 | 103 | 0.097 | 0.20 | + unsafe_perspective |
| DJJM.001 | 10 | 106 | 0.094 | 0.13 | + unsafe_perspective |
| DJJM.008 | 8 | 117 | 0.068 | 0.12 | scale/rotation/corners **broken** (−163° rot) |

Accepted peers sit at ratio ≥ 0.12 (e.g. DJJF.008 = 0.1275, DJJF.012 = 0.1228).
Score alone is **not** the gate — DJJF.007 score 0.405 rejects while DJJF.003 score 0.356 accepts.

Recovery ladder already runs **3 attempts** (primary → CLAHE/strong enhance → contrast-stretch).
Enhancement improves some metrics but **does not push ratio across 0.12** on these near-misses.

## Failure classes

1. **Near-miss ratio (recoverable)** — DJJF.007, DJJM.005, DJJM.006, maybe DJJF.001  
   Many good matches, enough absolute inliers (≥8–14), safe scale/rotation; ratio 0.107–0.116.
2. **Perspective-skewed poor match** — DJJF.005, DJJM.001  
   Ratio + `unsafe_perspective_distortion` (and often bad corners on early attempts).
3. **Catastrophic alignment** — DJJM.008  
   Scale ~0.33, rotation ~−163°, invalid corners — wrong page crop / upside-down / non-form.

## Honesty constraints (do not violate)

- Do **not** globally soften `min_inlier_ratio` just to raise STP.
- Do **not** invent E3 / skip Acceptance.
- Fail-closed Track A HITL remains correct when warp is unsafe.

## Fix steps (ordered by leverage / invasiveness)

### Step 1 — Near-miss secondary matcher (**shipped**)

For attempts that fail **only** `low_inlier_ratio` with:
- `inlier_count >= min_inliers` (8+)
- `coverage_ratio >= min_coverage_ratio`
- no unsafe scale/rotation/perspective/corners
- `inlier_ratio` in `[0.10, 0.12)`

Run a **bounded second geometric pass** (same template, same gates):

1. Raise `sift_features` (3000 → 5000) on enhanced crop  
2. ORB+SIFT **union** matches before RANSAC  
3. Multi-scale pyramid (0.85× / 1.0× / 1.15×) pick best inlier set  
4. Optional ECC refine after coarse H

Accept **only if** the retry passes the **unchanged** full Acceptance policy.

### Step 2 — Landmark content corroboration (**shipped**)

When Step 1 still fails ratio-only near-miss, warp with best H and run
`validate_cms1500_registration_content` on patient name/DOB boxes:

- If landmarks read plausible identity labels/ink → allow accept with reason
  `NEAR_MISS_RATIO_CONTENT_CORROBORATED` (still record geometric near-miss)
- If insurance-row bleed / empty → keep Track A HITL

This is **not** threshold softening; it is an independent content E3 check.

### Step 3 — Perspective / skew path (**shipped** in v11)

For `unsafe_perspective_distortion` + low ratio:

1. Document deskew / border crop before SIFT  
2. Stronger `enhance_for_registration_strong` already used — add **edge-emphasizing** preprocess  
3. Try affine-first (partial) then full homography if affine inliers look form-like

### Step 4 — Catastrophic / wrong-page (DJJM.008) (orientation retry shipped; residual HITL OK)

1. Page orientation classifier (0/90/180/270) before registration  
2. Form-present detector (CMS header “HEALTH INSURANCE CLAIM FORM”)  
3. If no form → honest `REGISTRATION_FAILED` / wrong-document (not field cascade)

### Step 5 — Observability

Emit structured `registration_gap_class` on every Track A HITL:

- `NEAR_MISS_INLIER_RATIO`
- `PERSPECTIVE_UNSAFE`
- `CATASTROPHIC_TRANSFORM`
- `LOW_COVERAGE` / `INSUFFICIENT_INLIERS`

Wire into `hackathon_*_partial.json` `by_bundle` like field blockers.

### Step 6 — Retest protocol

1. Re-run registration-only on the 7 failed claims with Step 1 enabled  
2. Measure: accept rate, landmark content pass, false-accept via spot visual ROI  
3. Only then consider Step 2 conditional accept  
4. Never batch-soften policy without per-claim landmark proof

## Alternate tech stack (if SIFT ceiling)

| Option | Role | Status |
|--------|------|--------|
| Current SIFT+RANSAC + enhance ladder | Production baseline | Shipped |
| **Document-quad crop → re-SIFT** | Phone-framed catastrophic warps | **Shipped** |
| **SuperPoint + LightGlue** | Dense learned matches; same Acceptance gates | **Shipped** (`packages/recovery/learned_matcher.py`) |
| **Azure DI page corners** | Ink-polygon hull → quad (configured Azure DI, not gpt-4o) | **Shipped** (`packages/recovery/azure_di_page_corners.py`) |
| LoFTR | Dense correspondence alternative | Future |
| Human registration HITL | Residual catastrophic / no-form | Fail-closed Track A |

Catastrophic escalation order: **document-quad → SuperPoint/LightGlue → Azure DI corners → Track A HITL**.
Do **not** globally soften Acceptance gates; learned matchers must still clear the same policy.

## Expected impact (this ledger)

- Steps 1–2 target **~4/7** registration failures (ratio-only near-misses)  
- Steps 3–4 needed for the other **~3/7**  
- Unlocks field cascade + STP opportunity on those claims (field blockers then apply)

## Related field-ink work (Track B)

Separate from registration: DOB separator-1, name JI/.1 confusables, claim
`FIELD_CONFLICT` on relieved OCR — see `STP_PIPELINE_ARCHITECTURE_V10.md`.
