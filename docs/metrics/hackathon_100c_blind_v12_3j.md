# Blind-100 (`docs[350:450]`) — v12.3j

Prior blind (`hackathon_100_new_cascade_v12`, partial 84): **46% STP**, **37% REG**, 17% field HITL.

## Final metrics (`hackathon_100c_blind_cascade_v12_3j`)

| Metric | v12.3j | Prior blind |
| --- | ---: | ---: |
| TRUE_STP | **76%** (76/100) | 46% |
| Field HITL | **16%** (16/100) | 17% |
| REG | **8%** (8/100) | 37% |
| Mean latency | **17.2s** | — |

Registration OK 92/100. Of completed: STP 82.6%. Mean ≤30s bar met.

## Remaining blockers

| Bucket | n | Notes |
| --- | ---: | --- |
| REG `AZURE_DI_PAGE_CORNERS_DISABLED_LOW_COST` | 8 | Corners off by cost gate after LightGlue miss |
| DOB `AMBIGUOUS_DIGIT_FRAGMENTS` / handwriting | 10 | Hard ink; TrOCR/DI residual still miss |
| ID `CALIBRATION_HITL` | 5–6 | Low-conf / contaminated member ID |
| Empty blockers / `FIELD_CONFLICT:insured_name` | 3 | Box-number OCR `2` vs strong person name |

## Fixes shipped in v12.3j (pre-run)

1. DOB letter-as-separator (`01i081996` → `01/08/1996`)
2. Azure DI DOB crop residual ON after TrOCR miss

## Follow-up (v12.3k)

1. Enable last-resort Azure DI page corners (only after near-miss/LightGlue)
2. Treat digit-only / box-number name OCR as form chrome (not CONFLICT)
