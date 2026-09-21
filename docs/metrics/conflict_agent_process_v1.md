# AI conflict agent — process

When two OCR engines or models disagree on the same ink, do not send the field
to human review by default. Run a Claude crop agent that must pick one of the
existing rivals.

## Triggers

1. **Same-field rival values** — two or more shaped, non-equivalent candidates
   on `patient_name`, `patient_dob`, `insured_id_number`, or `total_charge`
   (for example paddle `50.00` vs Document Intelligence `660.00`).
2. **Financial arithmetic gap** — Box 28 total ≠ sum of service-line charges
   (for example Box 28 `783.00` vs lines `261+261=522`).

## Steps

1. Collect the rival values only (no invented third amount).
2. Crop the field (Box 28 for financial gaps).
3. Ask Claude: look at the ink; reply with exactly one rival, or `BOX28` /
   `LINES` for a financial gap, or `ABSTAIN`.
4. Match the reply to a listed rival. Anything else is abstain.
5. On resolve:
   - Same-field: adopt that value, prepend a Claude confirming candidate,
     tag `CONFLICT_AGENT_RESOLVED`, accept the cascade.
   - Financial `BOX28`: adopt the printed total, mint
     `CLAIM_TOTAL_CONFIRMED` + `FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED` with
     reason `CONFLICT_AGENT_FINANCIAL_RESOLVED` (clears `FINANCIAL_CONFLICT_HITL`).
   - Financial `LINES`: adopt the line sum the same way.
6. On abstain or error: leave the field in review (fail-closed).

## Flags

- `CDP_CONFLICT_AGENT=1` (cascade default on)
- Uses the existing Claude crop stack (`CDP_CROP_VLM_PROVIDER=claude`)

## What this is not

- Not sole monetary authority from Claude when only one weak local exists.
- Not a license to invent a third amount.
- Digit-drop hard-15 (`13` vs `131` with no confirming local) stays closed
  unless the agent explicitly picks one listed rival from the crop.
