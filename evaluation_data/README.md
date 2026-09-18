# Evaluation data

Store versioned labelled ground truth and prediction exports here. Do not
commit claim images or PHI-bearing vendor labels. Split documents into
`calibration`, `validation`, and blind `holdout` sets; never tune thresholds
against the holdout set.

Checked-in agent GT (Hackathon ZIP has no vendor labels):

- `hackathon_agent_gt/field_truth.json` — full agent consensus GT
- `hard15_v12_3o/` — frozen 15-doc hold-500 gate set + 46 field labels

Run:

```bash
python -m evaluation.runner \
  --dataset dataset_raw \
  --ground-truth evaluation_data/ground_truth.json \
  --predictions evaluation_data/predictions.json \
  --output evaluation_results \
  --split holdout
```

The command writes `evaluation.json`, `mismatches.csv`, and
`mismatches.html`. A prediction must explicitly set `accepted` and
`reviewed`; critical false accepts are reported separately. The evaluator
does not infer that OCR confidence is calibrated probability.
