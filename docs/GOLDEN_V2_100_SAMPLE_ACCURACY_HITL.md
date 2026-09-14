# Golden Pack V2 — 100-sample Exact + HITL Results

Date: 2026-09-14  
Branch: `feature/cdp-v3`  
Harness: `evaluation/accuracy_100_sample.py`  
Dataset: `CDP_GOLDEN_ENGINEERING_PACK_V2` (50 CMS1500 + 50 UB04 = 100 docs / 1000 fields)

## Gaps resolved before the 100-run

| Gap (from 50-sample) | Fix |
|---|---|
| Date Exact false-misses (`12/09/1965` vs `1965-12-09`) — 74 fields | `normalize_date` accepts ISO `YYYY-MM-DD` |
| ICD `I10` → `110` — 8 fields | `normalize_icd` repairs leading I/O OCR swaps; extractor maps `ICD_CODE` → `icd` |
| HITL reported as 100% because extractor leaves `PENDING` | Report **hard HITL** separately from raw disposition |

## Headline metrics

| Metric | Value |
|---|---:|
| **Exact field accuracy** | **98.60%** (986/1000) |
| Critical Exact | 98.43% |
| Perfect-claim Exact | 87.00% |
| False accepts | 0 |
| **Field hard HITL** | **13.10%** (131/1000) |
| Claim hard HITL | 93.00% |
| Claim STP proxy (zero hard-HITL fields) | 7.00% |
| Field raw disposition HITL (`PENDING` counted) | 100% |
| Correct-but-reviewed (Exact ∧ PENDING/INVALID) | 98.60% |

### By family

| Family | Exact | Field hard HITL | Claim STP proxy | Perfect Exact |
|---|---:|---:|---:|---:|
| CMS1500 (50) | 98.55% | 10.55% | 6% | 86% |
| UB04 (50) | 98.67% | 16.22% | 8% | 88% |

## Hard HITL composition (131 fields)

- **INVALID (117)**: mostly synthetic `provider_npi` failing Luhn (89) + some `provider_name` (26)
- **Exact misses (14)**: name glyph insertions (`ANITAE`, `ROBERTF`), truncated member IDs, one empty principal diagnosis

## Interpretation

1. **Accuracy target (≥90%) is met on this pack** at 98.6% Exact after the date/ICD gap fixes.
2. **Operational HITL remains high at claim level** because most claims still carry at least one INVALID NPI (golden NPIs are not Luhn-valid) or a residual Exact miss.
3. **Raw `PENDING` ≠ final policy HITL**. Extraction leaves fields `PENDING` until `EvidenceDecisionService` runs; correct-but-reviewed is the dominant economics gap (same pattern as Phase 8.10 analysis).

Artifacts (local, gitignored): `evaluation_results/accuracy_100_sample/`.
