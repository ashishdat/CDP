# Independent-300 STP/HITL roadblocks — v12.3i

Source autopsy: `hackathon_300_cascade_v12_3h` (TRUE_STP **70%**, REG_FAILED **69**, field HITL **21**).

## Deadlocks found

| Rank | Deadlock | Count | Fix |
| ---: | --- | ---: | --- |
| 1 | Near-miss / perspective gated on **latest** evidence only — later catastrophic enhance skipped boost that v12.2 used | ~19 STP→REG | Trail-aware `should_attempt_*_any` |
| 2 | LightGlue off + Azure page corners off → terminal `AZURE_DI_PAGE_CORNERS_DISABLED_LOW_COST` | 62 | Re-enable learned matcher (singleton) |
| 3 | Stale shell `CDP_TROCR_DOB_RESIDUAL=0` suppressed DOB handwriting residual | 16 DOB HITL | Cascade stamps product defaults; TrOCR on |
| 4 | Tesseract name fill stripped as `CANDIDATE_ENGINE_NOT_AUTHORIZED` | 1 | Authorize tesseract for names |
| 5 | Insured-name CMS header OCR with no clean competitor | ~1–few | Inject patient name when all insured vals are label-contaminated |
| 6 | Primary SIFT RANSAC jitter near accept boundary | flaky | Best-of-7 RANSAC |

## Honest residuals (keep HITL)

- DOB where TrOCR returns unshaped / insufficient evidence (`HANDWRITING_UNREADABLE`)
- Catastrophic REG after classical + LightGlue exhaustion (no Azure page corners — cost)

## Smoke (v12.3i)

REG-failed claims from v12.3h recovered on first smoke (**5→0 REG**, **+4 TRUE_STP**), mean **16.3s** (under ≤30s). TrOCR now fires on handwriting DOB gaps; unshaped ink stays HITL.

## Independent-300

Restart as `evaluation_results/hackathon_300_cascade_v12_3i` (workers=1, product defaults).
