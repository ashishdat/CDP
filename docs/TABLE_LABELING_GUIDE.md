# Table cell labeling guide

Table labels are evaluation data and must never be loaded by inference workers.
The append-only store is `evaluation_data/table_labels/approved_cell_labels.jsonl`;
the reviewer queue is `cell_label_manifest.jsonl`.

1. Open the original page, grid overlay, and individual cell crop.
2. Transcribe only visible evidence. Preserve a genuinely blank cell as `""`.
3. Record writing type and the page-image SHA-256.
4. Submit a new event; never edit or delete an earlier JSONL event.
5. Critical code/NPI cells require a different second reviewer.
6. Resolve duplicate or contradictory approved events before evaluation.

Only `APPROVED` events with a matching source-image hash enter official metrics.
Unlabeled cells remain `AWAITING_HUMAN_LABEL` and do not enter the denominator.
Evaluation truth is displayed only by the evaluation report.

## Local review screen

Run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn evaluation.table_labeling_app:app --host 127.0.0.1 --port 8190
```

Open `http://127.0.0.1:8190/`. The queue presents UB-04, laboratory invoices,
and statements before CMS-1500. Available dispositions are `APPROVED`,
`CORRECTED`, `BLANK_CONFIRMED`, `UNREADABLE`, `WRONG_CELL_BOUNDARY`,
`WRONG_ROW_OR_COLUMN`, and `NOT_APPLICABLE`.

Corrections and critical semantic columns require an independent second
reviewer. Run `python -m evaluation.table_label_checkpoint` after 50 approved
labels; it writes `evaluation_results/table_shadow_v2/checkpoint_50.json`.
