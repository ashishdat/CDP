# Tool-fit architecture — field-cascade-v11.2

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
| **Azure AI cascade** | Crop-level VLM residual | `HANDWRITING_UNREADABLE`, orientation | Review-only until route promotion |
| **AWS Textract DetectDocumentText** | Cloud-OCR fallback | Local OCR exhausted **and** field blocks STP | Off common path; crop-scoped |
| **React field-level HITL** | Human review UI | Residual honest HITL queue | Field-scoped tasks only |

## Common path (cheap → expensive)

```
OpenCV SIFT/FLANN/RANSAC register (+ recovery)
  → geometry / ROI inset
  → RapidOCR primary (ONNX)
  → PaddleOCR selective confirmation (names/orgs) OR Tesseract selective (dates/digits/IDs)
  → span_select → semantic_accept → reconcile (v11.2 name order / glued MI / ID lift)
  → Pydantic validators + E6 cross-field
  → claim decision (True STP = COMPLETED ∧ ¬review)
       ↘ residual empty finance / tables → Docling (gated)
       ↘ residual handwriting / orientation → Azure AI (review-only)
       ↘ local OCR exhausted + blocks STP → Textract DetectDocumentText (gated)
       ↘ else → React field HITL
```

## v11.2 Track-B fixes (local, no cloud)

| Residual | Fix |
|----------|-----|
| Last/First token order (`CHANG SHERRILEE` vs `SHERRILEE L CHANG`) | Token-bag equivalence + Western display prefer |
| Glued MI (`DESIRAE CL` vs `L`, `CP` vs `P`) | Glued-middle-initial relief |
| Digit-as-letter in names (`L0` → `LO`) | Name tokenizer keeps 0→O / 1→I |
| Dual-engine ID below C3 floor | Confidence lift when paddle+rapid exact-agree + hard validation |
| Engine authority | Governed routes: **Rapid primary**, Paddle confirmation |

## Honest residuals (do not invent ink)

- Catastrophic multipage registration → Track A HITL (OpenCV exhausted)
- True empty box-28 with no recoverable lines → HITL or Docling/Textract only if policy allows
- Unreadable handwriting DOB → Azure review-only or React HITL
