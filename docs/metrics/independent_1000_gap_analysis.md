# Independent-1000 gap analysis (registration / STP / HITL)

## Why so many gaps appeared

The corpus is **1000 pages**, but not 1000 CMS-1500 claim forms. Gaps came from three layers:

### 1. Run / ledger process gaps (now closed)
| Gap | Cause | Resolution |
|---|---|---|
| ~175 never-run docs | Split Independent-600 + remainder-400; Group D + some Group A never launched | Step 3 cascade on remaining 39 Group D; Step 2c on missing Group A |
| Lost fast-REG rows | First DI-only REG redo wrote HITL/REG, then ledger compacted without those claim folders | Re-ran full 159 REG plan through fast path |
| Fake HITL inflation | Mailroom/fax pages shaped `DOCUMENT SEPARATOR` / `BAD, THEREFORE B` as patient names → HITL | Precision-safe name filters; those pages now stay **REG** (empty fields) |

### 2. Page-type gaps (not CMS-1500 registration bugs)
Of **159 REGISTRATION_FAILED** after fallback:

| Signature | Count | Correct disposition |
|---|---|---|
| Mailroom document separator / DOCSEP / Patch II | ~91 | REG (no claim ink) |
| FAX IMAGE boilerplate only | ~67 | REG (no recoverable fields) |
| Other separator-class | ~1 | REG |

These pages **cannot register** to a CMS-1500 template. Treating them as HITL was the precision bug; REG is correct.

### 3. Form-family gaps (registration works for CMS-1500 only)
| Family | What happens | Handling |
|---|---|---|
| CMS-1500 with geometry | Template register → OCR cascade → STP/HITL | Main path (~743 STP) |
| CMS-1500 hard REG / freeform | Unstructured DI heuristics | ~19 STP + remaining HITL |
| UB-04 / CMS-1450 | No CMS-1500 template match | Unstructured DI; charge often space/dash OCR (`231-00`) |
| Field-ink HITL on registered CMS | Geometry OK; one critical field weak (mostly `total_charge`) | Separate precision-safe OCR residual path (Step 4) |

## Current taxonomy (full 1000 coverage)

After Steps 1–3 (pre-Step2c lift):

- **TRUE_STP** ~762 (CMS geometry + unstructured lifts)
- **HITL** ~79 (field-ink ~47 + unstructured ~32)
- **REG** ~159 (mailroom/fax only — irreducible)

Unstructured HITL blockers (precision-safe, not invent fields):
- Missing `total_charge` (majority of UB-04)
- Missing `patient_dob` / `insured_id_number` on noisy freeform

## What we fixed in heuristics
1. Reject mailroom / fax / form-label names (`IFYES, RETURN`, `FED TAX`, `STATEMENT COVERS`, city-state).
2. UB-04: prefer `LAST, FIRST` near patient labels over facility headers.
3. Member ID: keep leading `\d{8,12}` on address-soup lines (was dropped by blvd/ave skip).
4. Charge: accept `780 00` / `231-00` **only** on TOTAL / `$` cue lines (+ following line).
5. Kill-switch unchanged: `CDP_UNSTRUCTURED_REG_FALLBACK`, `CDP_UNSTRUCTURED_REG_AGENT=0`.

## Remaining intentional non-STP
- **159 REG**: separators / fax covers — keep REG.
- **Field-ink HITL (~47)**: registered CMS with weak charge/DOB/ID — needs geometry-bound OCR residual, not unstructured guessing.
- **UB-04 HITL**: person/DOB/ID often OK; TOTALS OCR sometimes absent or ambiguous — stay HITL unless cue-line currency shapes cleanly.
