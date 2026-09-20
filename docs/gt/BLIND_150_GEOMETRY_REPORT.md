# Blind 150 geometry v4 — partial score

Run: `evaluation_results/hackathon_150_blind_geometry_v4`  
GT score: `evaluation_results/hackathon_150_blind_geometry_v4_gt/`  
Template: `cms1500` / `field-cascade-v12` (`CDP_PIPELINE_RELEASE=extraction-v3`)  
Log: `/tmp/cdp_150_blind.log`

## Run status

**Killed mid-run** (`EXIT:143` / `SIGTERM` / `KILLED_150`) after progress **40/150**.
Ledger has **41** rows. Metrics below are for those completed rows only — not a full blind-150 result.

## Operational totals (41 rows)

| Metric | Count |
|---|---|
| Terminal rows | 41/150 requested |
| Registration OK | 41/41 |
| Completed | 39/41 |
| True STP | **15/41** |
| HITL | **24/41** |
| Stage failure | **2/41** |

### Critical blockers (HITL)

| Field | Count |
|---|---|
| `total_charge` | 23 |
| `patient_name` | 4 |
| `patient_dob` | 1 |

### Field AUTO of completed (39)

| Field | AUTO |
|---|---|
| `patient_dob` | 38/39 |
| `total_charge` | 16/39 |
| `patient_name` | 35/39 |
| `insured_id_number` | 39/39 |
| `insured_name` | 39/39 |

### Residual HITL (24)

`total_charge`: DJJM.036, .037, .040, .042, .044, .045, .046, .048, .049, .050; DJKH.005, .006, .008, .009, .011, .013, .014, .015, .016, .018, .023, .024, .025

`patient_name`: DJJM.036, .046, .047, .048

`patient_dob`: DJJM.050

## GT accuracy (partial, 32 scored claims)

Scored with `scripts/score_hackathon_gt_accuracy.py` against
`evaluation_data/hackathon_agent_gt/field_truth.json`.

| Metric | Value |
|---|---|
| Claims scored | 32 |
| Field exact accuracy | **0.746** (100/134) |
| Perfect-claim exact rate | **0.0625** (2/32) |
| False accepts (all fields) | **20** (rate 0.149) |
| True STP among scored | 14 |

### Field exact rates

| Field | Exact |
|---|---|
| `insured_id_number` | 31/31 (1.00) |
| `insured_name` | 29/29 (1.00) |
| `patient_name` | 28/30 (0.933) |
| `patient_dob` | 7/12 (0.583) |
| `total_charge` | 5/32 (0.156) |

## Critical false accepts (AUTO ≠ GT)

Thresholds were **not** changed for this score. Charge FAs on TRUE_STP:

| Claim | Predicted | GT | Notes |
|---|---|---|---|
| DJJM.039 | 251.00 | 262.00 | SILVER |
| DJJM.041 | 251.10 | 2511.00 | place-shift vs SILVER |
| DJJM.043 | 370.00 | 481.00 | SILVER |
| DJKH.001 | 157.07 | 157.00 | near-miss cents |
| DJKH.002 | 157.00 | 1571.00 | place-shift vs SILVER |
| DJKH.003 | 701.00 | 70.00 | 10× / digit twin |
| DJKH.004 | 222.22 | 233.00 | SILVER |
| DJKH.007 | 228.32 | 239.00 | SILVER |
| DJKH.010 | 228.32 | 228.00 | near-miss cents |
| DJKH.012 | 701.00 | 70.00 | 10× / digit twin |
| DJKH.017 | 222.22 | 222.00 | near-miss cents |
| DJKH.019 | 157.10 | 157.00 | near-miss cents |
| DJKH.022 | 25.43 | 25.00 | near-miss cents |

Also on TRUE_STP: DOB FAs DJKH.001 (`1998-10-31` vs `1998-05-03`) and DJKH.010 (`2010-11-11` vs `1995-05-01`).

No `4972.00` / `212400.00` / `400406.00` false totals appear in this partial score.

## What this does not authorize

- Do not treat 15/41 as a full blind-150 result.
- Do not lower confidence thresholds from these SILVER disagreements.
- Re-run the remaining 110 claims (resume from ledger) before comparing to a prior full 150.
