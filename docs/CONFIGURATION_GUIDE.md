# Model / Template Configuration Guide

## What's configurable today (Phase 1)

Everything today is environment-variable driven — one settings class,
`packages/settings.py::Settings`, loaded from `.env` (see
`.env.example` for the full list and defaults). Key ones:

| Variable | Effect |
|---|---|
| `PIPELINE_VERSION`, `SCHEMA_VERSION` | Part of the document idempotency key (`sha256 + pipeline_version + schema_version`); bump `PIPELINE_VERSION` whenever decode/preprocessing logic changes in a way that should force reprocessing of previously-ingested documents |
| `MAX_UPLOAD_SIZE_BYTES` | Ingestion API upload size limit |
| `VLM_ENABLED` | Must stay `false` until Phase 4's adapter is real; the pipeline is designed to run fully without it |
| `USE_IN_MEMORY_BUS` | `true` for local dev without Redpanda (single process only — the in-memory bus doesn't cross process boundaries) |

## What will be configurable (by phase)

### Templates (Phase 2) — `config/templates/`

One file per `template_id`/`version`, matching the `Template` shape from
`docs/ARCHITECTURE.md`:

```yaml
template_id: cms1500
version: "1.0"
form_type: CMS1500
reference_dimensions: {width_px: 1700, height_px: 2200}
anchor_definitions: [...]      # phrases/marks used to confirm form identity
alignment_points: [...]        # for OpenCV homography against the reference
field_regions: {...}           # named field -> region on the reference image
service_line_regions: {...}
required_fields: [...]
validation_profile: cms1500_default
```

Adding a new payer's CMS-1500 variant, or a new UB revision, is a new YAML
file plus reference image — not a code change.

### Validation (Phase 3) — `config/validation/`

Per-field criticality and confidence thresholds:

```yaml
field_name: provider_npi
criticality: CRITICAL
min_confidence: 0.92
rule: npi_luhn_checksum
```

Critical fields below `min_confidence`, or failing their `rule`, route to
human review (`workers/validation` + `packages/validation_rules`); this is
deliberately per-field, never a single document-level confidence gate.

### Fixed-width output (Phase 3) — `config/output_specs/{nsf,ub92}/`

One YAML file per record type, transcribed field-by-field from the
supplied `NSF Matrix Version 2 15 - June 2013.doc` /
`UB92 File Specs - February 2012.doc` (see `docs/DATASET_FINDINGS.md` for
which record types the sample dataset actually exercises):

```yaml
record_type: BA0
fields:
  - field_name: record_id
    start_position: 1
    length: 3
    alignment: left
    padding_character: " "
    data_type: string
    required: true
    default: "BA0"
  - field_name: provider_id
    start_position: 4
    length: 20
    alignment: left
    padding_character: " "
    data_type: string
    required: true
    source_field: claim.provider_npi
```

`packages/fixed_width` interprets this directly — no per-record-type code.

### Model router cost table (Phase 4) — env-driven initially

`packages/model_router` will accept an estimated-cost table (VLM $/call,
GPU-hour amortized cost for LayoutLMv3/Table Transformer, etc.) so
`estimated_cost_usd_total` is a real number, not a placeholder; format TBD
when Phase 4 lands, documented here when it does.

## Guiding principle

If a behavior would otherwise require a code change to support a new
payer, form revision, or validation rule, it belongs in `config/`, not in
`packages/` or `workers/` — those should only change when the *mechanism*
changes, not the *data*.
