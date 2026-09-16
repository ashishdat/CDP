# STP Pipeline Architecture — v12 Field Value Authority

## Learning → redesign

Track-B residual HITL on Independent Samples-300 showed the same failure mode
across name / ID / DOB: **OCR twins and fragments treated as identity conflicts**,
while empty finance and handwriting stay honest HITL (need re-OCR, not policy).

v11.1–v11.6 bolted `prefer_*` helpers into `EvidenceReconciler`. v12 extracts a
**Field Value Authority** so equivalence and display selection are:

- one API (`are_equivalent`, `prefer_authority`)
- independently unit-tested
- reusable by reconciler, harnesses, and future VLM routers

```
register → geometry → cascade OCR → span/semantic
  → FieldValueAuthority (equiv + prefer)
  → EvidenceReconciler (thresholds, E2/E4/E6, accept/review)
  → ClaimDecision
```

## Authority rules (generalizable)

| Family | Rule | Example |
|--------|------|---------|
| member_id | Compact FORMAT_VALID (strip spaces/punct) | `4E80 VH6 HJ14` → `4E80VH6HJ14` |
| member_id | Length fragment | `981366` vs `98126619000` |
| member_id | Fill-only (tesseract) disagreement ignored | rapid ID vs tesseract soup |
| member_id | Confusable / prefix bleed | J↔U, OSC… vs C… |
| name | Short fragment vs strong person | `Ace` vs `Maraafet Kalomatis` |
| name | Vowel skeleton | `LUR` vs `LAURA` |
| name | Truncated secondary | `BET IT` vs `BET DOMTNIC` |
| name | Shared core token | `DUDAN` vs `DOCTNIKCS DOUDAN` |
| name | Strong-person calibration floor 0.70 | FORMAT_VALID multi-token |
| dob | January / separator / year confusable | existing v11.5 |
| charge | Line-sum only from observed lines; never invent | empty finance stays HITL |

## Honest HITL (do not auto-accept)

- Genuine digit ID conflicts (`909293380` vs `909295500`)
- Unrelated names (`VITI`/`ILIA`, `PERRI`/`PEMI`)
- Distinct calendar DOBs / future DOBs
- Empty box-28 with zero service-line ink

## Packages

- `packages/field_value_authority/` — authority API
- `packages/candidate_reconciliation/reconciler.py` — decision gate + ranking
- `packages/deterministic_evidence/` — compact member-ID FORMAT_VALID

## Evaluation

- Independent Samples-100: first 100 of hackathon Independent-300 with decision overlay
- Golden Pack V3 100: EXTRACTION_HARNESS accuracy (identity supplied)
