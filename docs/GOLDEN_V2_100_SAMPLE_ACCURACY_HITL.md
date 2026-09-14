# Golden Pack — 100-sample Exact + HITL / STP Results

Date: 2026-09-14  
Branch: `feature/cdp-v3`  
Harness: `evaluation/accuracy_100_sample.py`

## Strategy for STP vs HITL

Exact on V2 was already high (~99.5% after name recovery). **Claim STP was blocked by Luhn-invalid synthetic `provider_npi`** (~80 single-blocker claims). Production policy must keep Luhn; the unlock is an engineering pack with **checksum-valid NPIs redrawn on images** (Golden V3), not auto-accepting INVALID NPIs.

| Lever | Effect | Policy safe? |
|---|---|---|
| Name secondary cleanup (glyph debris / glued org suffixes) | Cuts provider_name INVALID hard HITL | Yes |
| Golden V3 Luhn-valid NPI redraw | Removes synthetic NPI INVALID ceiling | Yes (eval data only) |
| Loosen Luhn / evidence thresholds | Would inflate STP theater | **No** |

Build V3: `PYTHONPATH=. python3 evaluation/build_golden_v3_valid_npi.py --force`

---

## V2 baseline (post name recovery, pre V3)

Dataset: `CDP_GOLDEN_ENGINEERING_PACK_V2` (50 CMS + 50 UB)

| Metric | Value |
|---|---:|
| Exact field accuracy | 99.5% |
| Field hard HITL | 9.9% |
| Claim STP proxy | **11%** |
| Perfect-claim Exact | 95% |
| False accepts | 0 |

Hard HITL dominated by Exact-but-Luhn-invalid `provider_npi` (89). Informational: if those were not hard HITL → ~91% claim STP (matches V3 after valid NPIs).

---

## V3 target (Luhn-valid NPIs + name cleanup)

Dataset: `CDP_GOLDEN_ENGINEERING_PACK_V3`  
Artifacts: `evaluation_results/accuracy_100_sample_v3/` (gitignored)

| Metric | V2 | **V3** |
|---|---:|---:|
| Exact field accuracy | 99.5% | **99.3%** |
| Field hard HITL | 9.9% | **1.0%** |
| Claim hard HITL | 89% | **9%** |
| **Claim STP proxy** | 11% | **91%** |
| Perfect-claim Exact | 95% | 93% |
| False accepts | 0 | **0** |

### By family (V3)

| Family | Exact | Field hard HITL | Claim STP proxy |
|---|---:|---:|---:|
| CMS1500 (50) | 100% | 0.36% | **96%** |
| UB04 (50) | 98.4% | 1.8% | **86%** |

### Residual hard HITL (~10 fields / 9 claims)

- `provider_npi` MISSING (2): dynamic ROI unresolved on hard skew/shift (`WRONG_CROP_*`)
- `member_id` truncations / wrong span (2)
- `provider_name` OCR garbage prefix (1)
- `patient_name` / `patient_dob` residual INVALID (shape) (2)
- `principal_diagnosis` MISSING (1)

Raw disposition remains 100% PENDING on this extraction-only path (`EvidenceDecisionService` not applied). Hard HITL is the actionable STP proxy.

## Interpretation

1. **STP target is reachable without loosening NPI policy** once evaluation NPIs are business-valid.
2. V3 claim STP **91%** ≈ the earlier informational “ignore Exact-but-Luhn-invalid NPI” ceiling on V2.
3. Remaining HITL is real OCR/ROI residue (mostly UB04), not checksum theater.
4. Next HITL reductions: ROI recovery for unresolved NPI crops; member_id span; optional EvidenceDecisionService for true AUTO_ACCEPTED disposition (economics of correct-but-reviewed).
