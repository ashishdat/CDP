# Specification-driven reference system

The platform keeps four different kinds of reference data separate:

1. Formal NSF/UB92 specifications define output record structure.
2. Layout templates define anchors, alignment and crop locations.
3. Authoritative runtime providers verify member, provider, address and
   medical-code candidates when an approved source is configured.
4. Evaluation labels are generated offline from keyed output files and may
   never be imported by runtime packages.

`scripts/parse_legacy_claim_specs.py` converts `.doc` files through
LibreOffice with a unique temporary user profile. When LibreOffice is absent,
the supplied pre-extracted text siblings are used. Compiled schemas are stored
under `config/output_specs/{nsf,ub92}/compiled/`; ambiguity reports are written
to `evaluation_results/specification_review/`.

Run:

```powershell
python scripts/parse_legacy_claim_specs.py
python scripts/inventory_claim_documents.py
python scripts/build_labels_from_fixed_width.py
python -m evaluation.offline_pipeline `
  --predictions evaluation_data/predictions_fixed_family.json `
  --output evaluation_results/offline_benchmark
```

The label builder associates whole documents with output claims, hashes
document identifiers, and creates versioned calibration/validation/holdout
splits. Holdout documents must not be used to tune templates, thresholds,
parsers or models.

Runtime code can load the compiled structural specifications through
`SpecificationRegistry`, layout references through `LayoutTemplateRegistry`,
and approved reference sources through the protocols in
`packages.authoritative_references`. It cannot access keyed output data or
evaluation labels; `tests/architecture/test_evaluation_leakage.py` enforces
that boundary.

Rescaling is only a preprocessing fallback. It is not successful geometric
alignment. Every layout template therefore requires a minimum feature-inlier
ratio and maximum reprojection-error threshold.

## Field-level page routing gate

`FieldLevelPageRouter` evaluates every available page independently for every
required field. Selection combines calibrated OCR confidence, document-family
confidence, anchor/page relevance, crop quality and hard validation. A winner
must pass both an absolute score and a runner-up margin. Unresolved critical
fields receive `HUMAN_REVIEW_REQUIRED`.

Generate the evaluation-only 40-case regression manifest and routing metrics:

```powershell
python -m evaluation.routing_metrics
```

The metrics distinguish actual selection from oracle selection. Oracle
selection uses retained `page_candidates` provenance only; it never supplies
answers to runtime inference.

Handwriting fine-tuning remains disabled until the append-only approved-label
dataset satisfies `config/handwriting_dataset_policy.yaml`. Name-only fuzzy
reference matches cannot accept critical fields.

## Candidate provenance backfill

Candidate generation and evaluation are separate commands. The first command
does not accept a ground-truth argument:

```powershell
python -m evaluation.backfill_page_candidates `
  --manifest evaluation_data/document_manifest.json `
  --all-pages `
  --overwrite-incomplete `
  --output evaluation_results/page_candidates

python -m evaluation.page_candidate_metrics `
  --candidates evaluation_results/page_candidates `
  --truth evaluation_data/ground_truth.json `
  --manifest evaluation_data/document_manifest.json `
  --output evaluation_results/page_candidate_metrics
```

Every provider emits `EVIDENCE`, `NO_EVIDENCE`, or `PROVIDER_ERROR` for every
attempt. Routing is blocked until the field completeness record is terminal.
Cache identity includes the page-image hash, adapter version and field/model
identity. Candidate crops, terminal outcomes, completeness and routing
decisions are persisted independently, allowing interrupted runs to resume.
