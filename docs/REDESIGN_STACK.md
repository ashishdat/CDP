# Redesigned extraction stack (v1)

Capability → technology → role mapping for CDP healthcare claims extraction.
Source of truth: `config/architecture/redesign_stack_v1.yaml`. Operational
binding: `config/field_cascade_strategy.yaml` (field-cascade-v12) and
`config/releases/extraction-v3.yaml`.

| Capability | Technology | Role | Status |
| --- | --- | --- | --- |
| Image preparation | OpenCV, Pillow/libtiff | Preserve TIFF; deskew/denoise; render variants | PRODUCTION |
| Registration | SIFT/FLANN/RANSAC; LightGlue recovery | Align fixed forms; field geometry (E3) | PRODUCTION |
| Fixed-form printed | OpenOCR / SVTRv2 | Dates, IDs, monetary crops | CANDIDATE (`CDP_OPENOCR_SVTR`) |
| General local OCR | PP-OCR, RapidOCR, Tesseract | Low-cost extract + E2 confirmation | PRODUCTION |
| Handwriting | TrOCR | Handwritten DOB residual | PRODUCTION_RESIDUAL |
| Complex tables | PaddleOCR-VL, MonkeyOCR | Tables/columns/labels (REVIEW_ONLY) | CANDIDATE |
| Cloud document OCR | Azure DI Read, Textract | Residual crop recovery | PRODUCTION_RESIDUAL (DI charge default off) |
| LLM/VLM | GPT-4o | Residual semantics / review assist — **not monetary authority** | PRODUCTION_RESIDUAL |
| Validation | Pydantic + rule engine | Format, arithmetic, location, cross-page | PRODUCTION |
| Calibration | Platt/Isotonic + optional LightGBM | Acceptance-risk estimate | PARTIAL |
| Workflow | FastAPI, Kafka, Redis, PostgreSQL | Orchestration, retry, audit, HITL | PRODUCTION |
| HITL UI | React | Evidence-centric review of unresolved fields | PARTIAL |

## Charge residual ladder (fail-closed)

1. local paddle + rapid on primary/mid/right windows, plus dollars left of the
   CMS vertical dashed ruling (`CHARGE_DOLLARS_RULING*`)
2. tesseract digits fill (full + dollars-ruling)
3. GPT-4o empty-finance / line corroboration (local agreement required for AUTO)
4. Azure DI charge (optional, default off)
5. Field-scoped HITL

OpenOCR/SVTRv2 and MonkeyOCR/PaddleOCR-VL are **off** — same-family / wrong
window; they do not close EMPTY_FINANCIAL_INK. Empty / unreadable financial ink
never becomes STP by invention.

## Env flags

```bash
# CANDIDATE printed-crop OCR — FAILED for charge gap; keep off
CDP_OPENOCR_SVTR=0

# Complex tables REVIEW_ONLY — keep off for charge STP path
CDP_PADDLEOCR_VL_TABLE=0
CDP_MONKEYOCR=0

# GPT-4o crop residual (default on in cascade eval)
CDP_GPT4O_CROP_RESIDUAL=1
CDP_GPT4O_CROP_ACCEPT=1
CDP_GPT4O_EMPTY_FINANCE=1

# Azure DI charge residual (default off)
CDP_AZURE_DI_CHARGE_RESIDUAL=0

# Optional acceptance-risk LightGBM artifact
CDP_ACCEPTANCE_RISK_LGBM=0
# CDP_ACCEPTANCE_RISK_LGBM_PATH=/path/to/model.txt
```

## Code entry points

- Stack loader: `packages/architecture/redesign_stack.py`
- Charge ladder: `packages/architecture/charge_ladder.py`
- Acceptance risk: `packages/architecture/acceptance_risk.py`
- OpenOCR adapter: `workers/openocr_svtr/`
- Complex tables: `workers/complex_tables/` (wraps VL + MonkeyOCR stub)
- GPT monetary guard: `packages/extraction_recovery/gpt4o_crop_residual.py`
- HITL UI: `apps/evaluation_ui/src/hitl.tsx`
