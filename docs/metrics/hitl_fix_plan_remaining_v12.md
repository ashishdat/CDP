# Field readers — what actually runs

Azure Document Intelligence is not on the path. Each critical field has one local OCR stack and, where a miss remains, one model.

| Field | OCR | Model | Model may replace the local value |
| --- | --- | --- | --- |
| patient_dob, insured_dob | MM/DD/YY cells: digit-whitelist tesseract, then paddle/rapid. Handwriting: TrOCR | Claude crop only after both miss, date-shaped only | No |
| patient_name, insured_name | rapid + paddle, value band | Claude crop arbitrates conflict and garbage | Yes |
| insured_id_number | paddle + rapid, value band | Claude only when it matches one local ID | No |
| total_charge, service-line charges | paddle + rapid. Tesseract digits only when it matches a local amount | Claude confirms that amount, including a single line where paddle and rapid already agree | No |

A single charge line straight-throughs only when Claude matches the local amount within $1 (`SINGLE_LINE_GPT4O_LOCAL`), or box 28 matches the line sum. Claude `131` against local `13` stays in review. A box 28 that disagrees with the lines stays in review. Multi-line paddle+rapid agreement does not call Claude.

Code: `packages/extraction_recovery/field_reader_policy.py`. Charge confirm: `scripts/ocr_from_geometry.py` (`_confirm_sole_charge_line_with_claude`).
