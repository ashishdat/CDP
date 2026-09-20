# Authorized member index — operator fill (locked-50)

Locked-50 decide is **44/50 STP** without an authorized index. Index fill is the
only safe path for residual **identity** HITL. It must never invent names/DOBs
from OCR or Golden labels.

## How to activate

1. Fill P0 rows in `docs/reference/authorized_member_index.locked50.json`
   from enrollment / payment systems (exact `member_id` join only).
2. Set `authorized=true`, `identity_verified=true`, `effective_from=<ISO date>`,
   and `source` to the attestation system (not OCR).
3. Export:

```bash
export CDP_AUTHORIZED_MEMBER_INDEX=/absolute/path/to/authorized_member_index.locked50.json
python3 scripts/decide_locked50_line_charge.py
```

Without the env var the join abstains and STP must not inflate.

## P0 rows (identity still blocks STP)

| member_id   | claim            | fill fields                         | notes |
|-------------|------------------|-------------------------------------|-------|
| `5079520266` | M048DJJM.019    | **patient_dob** (required)          | Self+distinct Box4; name already AUTO |
| `97734518`   | M048DJJM.035    | **patient_name** (+ dob optional)   | Handwritten garble; charge stays HITL |

## Not unlocked by index

| claim        | reason |
|--------------|--------|
| M048DJJF.004 | Box28 783 vs Σ 522 arithmetic mismatch |
| M048DJJM.008 | Single-line place-shift (49.77↔4972) |
| M048DJJM.010 | Single-line place-shift (49.72↔4972) |
| M048DJJM.034 | total_charge calibration (identity already AUTO) |

## Expected ceiling after P0 fill

At most **+1–2 STP** from identity (M.019; M.035 only if charge also clears —
it will not from index alone). Honest ≥47/50 still needs charge corroboration
or operator charge review on the four financial HITL above.

See also: `docs/gt/STP94_AUTHORIZED_REFERENCE_PLAN.md`.
