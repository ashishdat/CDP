# CDP V3 technology decision

Status: user-selected target architecture. This records the implementation direction; it does not assert that all routes are wired, validated or deployed.

Baseline inspected: ffb33c9677bd7afc97a2382b3c52c659140adb47. This decision supersedes earlier proposed technology alternatives and Paddle-first recommendations for the continuing CDP V3 work.

| Capability | Selected technology | Intended role |
| --- | --- | --- |
| Preprocessing and registration | OpenCV with SIFT, FLANN and RANSAC | Orientation, deskew, border/contrast processing, feature matching and robust transform estimation. Retain compatibility, residual, reflection, scale/perspective and critical-ROI gates. |
| Primary OCR | RapidOCR on ONNX Runtime | First recognition pass on localized fields. Retain raw observations and crop/model provenance. |
| Selective secondary OCR | PaddleOCR and Tesseract | Paddle for printed text/name recovery or corroboration; Tesseract with field constraints for appropriate digit/date/code crops. Invoke when required evidence is missing, validation fails, or observations conflict. Preserve field-specific exclusions until independently evaluated. |
| Difficult tables | Docling | Selective table/layout recovery when deterministic geometry and regional extraction leave rows unresolved. Retain row/cell evidence; score against existing governed labels. |
| Healthcare validation | Python and Pydantic | Schema and field validation, NPI checks, calendar validity, identifier preservation, governed code/payer rules and Decimal financial reconciliation. Plausibility alone is not corroboration. |
| AI cascade | Azure | Controlled field/crop candidate generation after local recovery fails. Deployment/model versions remain explicitly configured; no new model is selected by this document. AI output cannot invent missing values or override unresolved critical evidence conflicts. |
| Cloud OCR fallback | AWS Textract DetectDocumentText | Additional OCR observations for unresolved fields after local OCR recovery, under the existing cloud-processing controls. This role is text detection; difficult-table structure remains Docling's role. |
| Field-level human review | React | Show source crop, competing candidates, provenance and reason codes; capture corrections with authenticated reviewer/tenant and immutable audit evidence. |

## Processing and recovery

Ingest -> quality/orientation -> form classification -> governed template selection -> SIFT/FLANN/RANSAC registration -> field localization -> RapidOCR -> Python/Pydantic validation and evidence decision.

Unresolved fields take bounded, field-specific recovery: crop/preprocessing retry and selective PaddleOCR/Tesseract; difficult tables use Docling. Textract is an OCR fallback; Azure is the AI candidate cascade after open-source recovery is exhausted. Their conditional ordering and budgets require an explicit route policy and independent benchmarks before activation. Any unresolved critical conflict or missing required evidence goes to React HITL. Do not run every engine on every field.

Every attempt retains engine/model version, crop reference, observed value, latency, cost where measured, validation outcomes and conflicts. A second engine returning usable text is not confirmation unless independent observations agree. Preserve leading zeros and compare amounts with Decimal. Apply the existing restrictions on external PHI processing, tenant isolation and auditability.

## Existing implementation and required reconciliation

Paths below refer to the inspected ffb33c9 source:

- `workers/page_detection/template_alignment.py` and `app.py` already use SIFT/FLANN/RANSAC with recovery. Build Phase 2 around this implementation; no alternate learned matcher is selected.
- `packages/ocr/rapidocr_provider.py` provides RapidOCR/ONNX. `config/secondary_ocr_policy_v1.yaml` already describes Rapid-first selective secondary routes.
- `config/ocr_field_routes.yaml` contains Paddle-first field routes and historical benchmark/approval records. Migrate them to the chosen Rapid-first architecture only through a new versioned policy with fresh independent validation. Do not reuse Paddle-first approval statistics for a changed route.
- `workers/field_candidates/docling_provider.py`, `packages/docling_policy.py` and `config/docling_candidate_pilot.yaml` provide Docling integration points. Existing pilot status is not production qualification.
- `config/evaluation/azure_vlm_production.yaml` and the Azure factory/holdout tests are integration points for the selected AI cascade. `config/ai_models.yaml` currently names Gemini tiers; those aliases are not the selected target architecture and need reconciliation during the AI-routing implementation.
- `packages/ai_gateway/providers.py` contains a transport-injected Textract adapter. A provider adapter alone does not establish that an authenticated AWS SDK transport is wired or validated.
- `apps/evaluation_ui/package.json` already uses React. Field-level correction permissions and audit immutability still require end-to-end verification.

## Phase ordering and gates

Phase 2 remains template selection and registration. The missing UB-04 canonical package and governed mock-layout bindings are unresolved. This technology choice does not supply those external assets or authorize bypassing selection/registration.

Resume the existing file-level Phase 2 plan with this selected registration stack once the required assets are supplied. Keep OCR routing changes, AI promotion and confidence calibration behind the user's Phase 2 gates. Do not train or tune using Golden V3, create templates from evaluated images, relax gates, or present harness identity as operational selection.

Provisional engineering P95 targets remain 5 seconds for selection plus registration and 30 seconds end-to-end. They are not approved business SLAs. No runtime routing changes, cloud requests, production enablement, push, merge or PR were performed to record this decision.
