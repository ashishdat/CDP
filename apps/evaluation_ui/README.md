# Accuracy and comparison dashboard

Generate a field-level evaluation report first:

```bash
python -m evaluation.runner \
  --dataset dataset_raw \
  --ground-truth evaluation_data/ground_truth.json \
  --predictions evaluation_data/predictions.json \
  --output evaluation_results \
  --split holdout
```

Run the React UI:

```bash
cd apps/evaluation_ui
npm install
npm run dev
```

Either upload `evaluation_results/evaluation.json` in the browser or copy it
to `apps/evaluation_ui/public/reports/evaluation.json` for automatic loading. Report
JSON may contain PHI; do not deploy it publicly and apply the same access
controls and retention policy as claim evidence.

The checked-in report under `public/reports` is synthetic demonstration data
for UI smoke testing. It is not a measured platform accuracy result.
