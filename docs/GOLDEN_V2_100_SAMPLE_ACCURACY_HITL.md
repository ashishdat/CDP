# Golden Pack V3 — HITL/STP Optimization (100 + 300 sample)

Date: 2026-09-14  
Branch: `feature/cdp-v3`  
Harness: `evaluation/accuracy_100_sample.py`

## Scope note on “300 of 1000”

The external Hackathon **1000-claims** corpus is registered but not present in this environment (`dataset.yaml` points at a local Windows zip).  
For a 300-doc measurement we built a photometric expansion of Golden V3:

```bash
PYTHONPATH=. python3 evaluation/build_golden_v3_300_augmented.py --force
```

Pack: `CDP_GOLDEN_ENGINEERING_PACK_V3_300` = 100 V3 docs × `{base, bright, soft}` (truth/bboxes unchanged; no geometric warp).

## Gaps found and resolved

| Gap | Fix | Policy safe? |
|---|---|---|
| OCR date dots (`0.4/03/20.02`) | `normalize_date` strips in-digit dots | Yes |
| Glued names / hyphens / facility OCR junk | `_clean_secondary_name` peels org suffixes, splits FIRSTLAST before MD, drops FAC* debris | Yes |
| NPI MISSING on label-contaminated crop | ROI recovers unique Luhn-valid NPI candidate bbox | Yes (Luhn still required) |
| ICD MISSING when ownership unproven | ROI prefers ICD-shaped candidate (not labels like SERVICE DATE) | Yes |
| Truncated / dotted member ids | PREFIX-8 recovery; compact dots only inside id body | Yes |
| Member id glued to labels (`…INSUREDNAME`) | Bound body to 8 alnum; never overwrite normalized id | Yes |

Residual (not invented away): single-character name OCR (`PRIYA`→`PRJYA`) on hard variants.

## Results

### V3 base 100 (post-fixes)

| Metric | Value |
|---|---:|
| Claim STP proxy | **99%** (99/100) |
| Residual hard HITL claims | 1 (`UB041` patient_name) |
| False accepts | 0 |

### V3_300 photometric sample (150 CMS + 150 UB)

| Metric | Value |
|---|---:|
| Exact field accuracy | **99.93%** (2998/3000) |
| Field hard HITL | **0.067%** (2/3000) |
| **Claim STP proxy** | **99.33%** (298/300) |
| Perfect-claim Exact | 99.33% |
| False accepts | **0** |

### By family (300)

| Family | Exact | Field hard HITL | Claim STP |
|---|---:|---:|---:|
| CMS1500 (150) | 100% | 0% | **100%** |
| UB04 (150) | 99.85% | 0.15% | **98.67%** |

Top residual Exact misses: `patient_name` × 2 (same OCR glyph error across variants).

## Interpretation

1. Targeting **HITL/STP** without loosening Luhn or evidence thresholds is working: claim STP moved from ~11% (V2 invalid NPIs) → ~91% (V3 valid NPIs) → **~99%** after residual HITL fixes.
2. The 300-run stress test (photometric clones) did not reopen CMS regressions once member-id glue was fixed.
3. Next incremental HITL gains are OCR-engine / multi-engine agreement on rare glyph swaps — not policy relaxation.

Artifacts: `evaluation_results/accuracy_300_sample_v3/`.

## Measurement integrity (V3)

Do **not** promote Golden Pack harness KPIs as production-qualified operational metrics.

| Scope | What it measures | Current result |
|---|---|---|
| `OPERATIONAL_E2E` | FinalClaim / submitted claims on the application path | **39%** (39/100 FinalClaim, 61 incomplete) |
| `EXTRACTION_HARNESS` | Exact field accuracy + claim STP **proxy** with harness-supplied form identity on **100 independent** V3 docs | **99.9%** field accuracy, **99%** Golden Pack Claim STP Proxy, **1** hard-HITL |
| `EXTRACTION_HARNESS_PHOTOMETRIC_STRESS` | OCR-stress clones of the same 100 docs (base/bright/soft → 300 observations) | Useful stress only — **not** 300 independent claims |

Rules:
1. Rename harness STP to **Golden Pack Claim STP Proxy** everywhere in UI/reports.
2. Show independent sample size as **100 source docs**; never label photometric observations as Total Ingested.
3. Keep operational completion on a separate ribbon from extraction harness KPIs.
4. The accuracy harness forces `FormIdentityStatus.VERIFIED` and selects the matching template — extraction accuracy is conditional on a correct identity/template path.
5. The end-to-end KPI that matters for production qualification is: correct FinalClaim / submitted claims.

