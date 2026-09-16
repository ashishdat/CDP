# 50-sample evaluation — accuracy / HITL / STP issues

## A. Golden Pack V2 (25 CMS + 25 UB) — extraction accuracy

Path: `evaluation_results/accuracy_50_sample_v10/`  
Harness: `evaluation/accuracy_50_sample.py` (standard-form RapidOCR; **not** full cascade decision).

| Metric | Value | Meaning |
|--------|------:|---------|
| Exact field accuracy | **99.8%** (499/500) | OCR+span vs golden truth |
| Critical exact | **99.7%** | |
| Perfect claim exact | **98%** (49/50) | |
| False accepts | **0** | |
| Raw claim HITL | 100% | PENDING≠AUTO — **not production HITL** |
| Hard claim HITL | **94%** | INVALID / exact-miss only |
| Claim STP proxy | **6%** | Claims with zero hard HITL |

### Issues identified (Golden Pack)

1. **`provider_npi` Luhn INVALID (47/50 claims)** — dominant hard HITL  
   - Synthetic V2 NPIs fail Luhn checksum → `validation_status=INVALID`  
   - Extraction often reads the digits correctly; policy correctly rejects  
   - **Fix:** evaluate on Luhn-valid pack (V3) *or* keep fail-closed and exclude NPI from STP proxy when measuring extraction quality  

2. **`patient_dob` exact miss (1)** — CMS019  
   - Predicted `2020-04-03` vs expected `04/03/2002`  
   - Century / year assembly error (02→2020 vs 2002)  
   - **Fix:** tighten DOB century repair / cells-first year cell; add regression case  

3. **Harness STP gap** — extractor leaves fields `PENDING`  
   - EvidenceDecision / claim STP stack not wired in this Golden Pack path  
   - Raw HITL/STP from this harness are **misleading** for production STP  

## B. Operational cascade (50 hackathon claims) — true STP/HITL

Path: `evaluation_results/hackathon_50_cascade_v10/` (**RUNNING**)  
Measures Track A registration HITL + Track B field-ink HITL + true STP (`COMPLETED` ∧ ¬review).

Known issue classes from prior v9 ledger (will confirm on this 50):

| Class | Symptom | Fix direction |
|-------|---------|----------------|
| Registration `low_inlier_ratio` | Track A HITL ~30%+ | Secondary matcher / landmark corroboration (see registration doc) |
| DOB separator-1 / E4 | Was Track B wall | v10 cells-first + separator peel + unique calendar (shipped) |
| Name JI / .1 confusables | patient/insured name CONFLICT | v10 name peel (shipped) |
| Claim FIELD_CONFLICT on relieved OCR | Empty blockers but HITL | Fixed — accepted fields ignore residual conflicts |

Hackathon ZIP has **no vendor GT** → accuracy = agent visual GT only when scored.

## How to read the two tests together

- **Accuracy** → Golden Pack exact (A)  
- **Production HITL/STP** → Cascade 50 (B), not Golden Pack raw HITL  
- **Actionable Golden Pack blockers** → NPI Luhn (data) + CMS019 DOB year
