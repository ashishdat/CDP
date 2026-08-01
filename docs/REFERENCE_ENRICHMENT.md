# Governed reference enrichment

The enrichment pipeline closes review-routed fields only with independently
authorized evidence. OCR, Azure, evaluation truth and the current candidate are
never reference sources.

## Default operation

All providers in `config/reference_enrichment.yaml` are disabled. A default run
makes no external calls, preserves all pending decisions and emits
`AWAITING_AUTHORIZED_REFERENCE_SOURCE`.

```powershell
python -m evaluation.run_reference_enrichment `
  --workbook reference_decisions_governed_v3_corrected.xlsx `
  --output evaluation_results/reference_enrichment
```

## Provider promotion

An adapter may be enabled only after authorization, secrets, region, retention,
dataset version and lineage have been approved. Tier-A member matching requires
member ID plus DOB and a compatible name. The approved fallback requires DOB,
strong name and ZIP. Provider matching requires a checksum-valid exact NPI.
Name-only matching is prohibited.

Synthetic fixtures are always `TEST_ONLY`, never evaluation eligible. Downstream
lineage containing `extraction-v2`, `azure-fallback`, `unreviewed-ocr` or
`cdp-prediction` is rejected, including indirect lineage.

## Historical backfill

`evaluation.run_reference_historical_backfill` seals the prediction hash and
inference timestamp before any finalized truth can be retrieved. The current
implementation intentionally stops at `SEALED_AWAITING_AUTHORIZED_HISTORICAL_SOURCE`.
