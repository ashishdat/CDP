# As-is → target architecture mapping (redesign owner)

Governed by `config/architecture/redesign_stack_v1.yaml`. Baseline metrics below
are **measured** from existing artifacts / re-runs — not invented.

| Target capability | Existing component | Current behavior | Gap | Required change | Files |
|---|---|---|---|---|---|
| Package Intelligence | `workers/page_detection/router.py`, Bundle A–D; attachment marking | Routes CMS/UB/attachment; no SourceHOV separator barcode; weak missing/dup/continuation | No claim-package identity before extraction | Add `packages/package_intelligence` builder: page class, separator, completeness | `packages/package_intelligence/*`, `workers/page_detection/router.py` |
| Image Evidence Analyzer | `packages/image_quality/assessment.py` | Page-level blur/contrast/DPI; OCR empty → generic EMPTY | No ROI ink taxonomy; optional blanks → HITL | ROI analyzer + dispositions BLANK_CONFIRMED…OCR_EMPTY_UNCLASSIFIED | `packages/image_evidence/*` |
| Registration + Semantic Geometry | `workers/page_detection/template_alignment.py`, `packages/recovery/`, templates | SIFT/FLANN/RANSAC + LightGlue recovery; ROIs from templates | Weak Box 24B vs 24F vs 28 semantic gate; POS `11` → charge FA risk | Explicit CMS region authority; reject charge outside 24F | `packages/geometry_authority/*`, `config/table_templates/cms1500_service_lines.yaml` |
| OCR Portfolio | field-cascade-v12, paddle/rapid/tess, openocr/trocr/vl stubs, gpt-4o residual | Economical cascade; GPT not sole monetary authority | Parallel variants sparse; OpenOCR/Monkey CANDIDATE | Controlled monetary crop variants + portfolio interface | `packages/ocr_portfolio/*`, `workers/openocr_svtr`, `workers/complex_tables` |
| Candidate Evidence Store | Candidates on field rows / MinIO artifacts | Partial lineage; no unified schema | Missing geometry-valid, ink features, reconciliation refs | Persist `CandidateEvidenceRecord` | `packages/candidate_evidence/*` |
| Field Value Authority | `semantic_accept`, `evidence_decision`, reconciler | Shape + policy accept; E2 incomplete on selective confirm | No single `accept(field)` combining all gates | Central `FieldValueAuthority.accept` | `packages/field_authority/*` |
| Financial Reconciliation | `line_sum_authority.py`, `claim_evidence/builder.py` | LINE_TOTALS_RECONCILED / UNCORROBORATED; gpt+local paths | Incomplete disposition set; POS bleed into charges | Explicit dispositions + column verification | `packages/claim_evidence/line_sum_authority.py`, `packages/financial_reconciliation/*` |
| Claim Decision | `packages/claim_decision/service.py` | STP vs claim/field review | Coarse HITL; not REGISTRATION/FIELD_INK/PACKAGE/FINANCIAL tracks | Narrow route reason codes | `packages/claim_decision/*`, `packages/review_reasons.py` |
| Calibration | `packages/confidence`, `acceptance_risk.py` | Platt/isotonic partial; heuristic acceptance risk | No leakage-safe training set / field thresholds for 99.5% | Dev-only calibration dataset + threshold selector | `packages/calibration/*` |
| Evaluation | `run_hackathon_1000_cascade.py`, Golden Pack, agent GT | Ops True STP on ZIP (no vendor GT); Golden STP **proxy** | Hackathon accuracy UNAVAILABLE without GT | Score agent GT where present; never mutate Golden | `scripts/*`, `evaluation/*` |
| HITL UI | `apps/evaluation_ui/src/hitl.tsx` | Evidence-centric field review | Package/financial routes not first-class | Surface new reason codes | `apps/evaluation_ui/src/hitl.tsx` |

## Measured baselines (do not treat Golden proxy as True STP)

| Source | Scope | True STP / proxy | Claim HITL | Critical FA | Notes |
|---|---|---|---|---|---|
| `evaluation_results/hackathon_50_blind_cascade_v12_3x/summary.json` | 50 claims ops | **True STP 4%** (2/50) | 96% | n/a (no GT) | total_charge blocks 48/50; EMPTY_FINANCIAL_INK 47 |
| `evaluation_results/accuracy_100_sample_v3_independent_cascade_v12/metrics.json` | Golden Pack V3 | claim_stp_**proxy** 98% | hard HITL 2% | **0** | EXTRACTION_HARNESS; identity forced |
| `evaluation/baselines/phase8_10_governed.json` | Phase 8.10 freeze | claim_stp 0% | 100% | 0 | Historical engineering baseline |

## Release gates status at start of this workstream

- True STP ≥94% — **FAIL** on ops Hackathon sample (4%)
- Claim HITL ≤6% — **FAIL** (96%)
- Critical accepted precision ≥99.5% — Golden proxy path OK; ops unscored without vendor GT
- False-accepted critical = 0 — Golden FA 0; ops POS/`11.00` risk on DJJF.013 smoke
- Registration HITL ≤1% — **PASS** on 50-claim sample (0%)
- No Golden mutation — preserved
