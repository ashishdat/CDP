# Tool-fit architecture — field-cascade-v11.2 (+ Azure gpt-4o cascade)

Maps the production tooling stack onto residual STP/HITL bottlenecks
(Independent Samples-300 post-fix).

## Tool → stage → bottleneck

| Tool | Stage | Bottleneck it attacks | Gate |
|------|-------|----------------------|------|
| **OpenCV + SIFT/FLANN/RANSAC** | Track A registration + recovery ladder | Registration HITL (~25%): perspective / rotation / inliers | Fail-closed on catastrophic warp |
| **RapidOCR / ONNX** | Primary regional OCR | Speed + printed CMS names/IDs/charges | Always first on governed routes |
| **PaddleOCR** | Selective secondary confirmation | Name conflict / E2 independence when Rapid alone is weak | Only on VALIDATION_FAILED or confirmation_mode |
| **Tesseract (+ digits)** | Selective secondary fill | DOB cells, charge digits, alphanumeric IDs | Digit whitelist; never name primary |
| **Docling** | Difficult tables / empty finance | `EMPTY_FINANCIAL_INK` service-line structure | Off common path; only after regional OCR attempted |
| **Pydantic healthcare validation** | Hard validation + E3/E4/E6 | Prevents false STP; formats ID/DOB/charge | Never waived |
| **Azure OpenAI gpt-4o** | Crop-level AI cascade | `HANDWRITING_UNREADABLE`, orientation | Review-only until route promotion (`AZURE_OPENAI_REVIEW_ONLY`) |
| **AWS Textract DetectDocumentText** | Cloud-OCR fallback | Local OCR exhausted **and** field blocks STP | Off common path; crop-scoped |
| **React field-level HITL** | Human review UI (`apps/evaluation_ui`) | Residual honest HITL queue | Field-scoped tasks only |

## Common path (cheap → expensive)

```
OpenCV SIFT/FLANN/RANSAC register (+ recovery)
  → geometry / ROI inset
  → RapidOCR primary (ONNX)
  → PaddleOCR selective confirmation (names/orgs) OR Tesseract selective (dates/digits/IDs)
  → span_select → semantic_accept → reconcile (v11.2 name order / glued MI / ID lift)
  → Pydantic validators + E6 cross-field
       ↘ empty/invalid/contradictory box-28 + observed lines → LINE_TOTALS_RECONCILED (local)
  → claim decision (True STP = COMPLETED ∧ ¬review)
       ↘ residual empty finance / tables → Docling (gated)
       ↘ residual handwriting / orientation → Azure gpt-4o (review-only)
       ↘ local OCR exhausted + blocks STP → Textract DetectDocumentText (gated)
       ↘ else → React field HITL
```

Planner: `packages/tool_escalation.py` (`plan_field_escalation`).

## v11.2 Track-B fixes (local, no cloud)

| Residual | Fix |
|----------|-----|
| Last/First token order (`CHANG SHERRILEE` vs `SHERRILEE L CHANG`) | Token-bag equivalence + Western display prefer |
| Glued MI (`DESIRAE CL` vs `L`, `CP` vs `P`) | Glued-middle-initial relief |
| Digit-as-letter in names (`L0` → `LO`) | Name tokenizer keeps 0→O / 1→I |
| Dual-engine ID below C3 floor | Confidence lift when paddle+rapid exact-agree + hard validation |
| Engine authority | Governed routes: **Rapid primary**, Paddle confirmation |
| Empty/tiny/contradictory box-28 with line charges | `line_sum_authority` → LINE_TOTALS_RECONCILED inject |

## Azure credentials

Set via environment / `.env` (gitignored) — never commit:

- `AZURE_AI_EVALUATION_ENABLED=true`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_AI_EVALUATION_DEPLOYMENT=gpt-4o`
- `AZURE_OPENAI_REVIEW_ONLY=true`

## Honest residuals (do not invent ink)

- Catastrophic multipage registration → Track A HITL (OpenCV exhausted)
- True empty box-28 with no recoverable lines → HITL or Docling/Textract only if policy allows
- Unreadable handwriting DOB → Azure review-only suggestion or React HITL
