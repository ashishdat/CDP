# CDP V3 governance repair — evaluation status

This note records what was and was not re-measured after the
`feature/cdp-v3` governance repair. It does **not** certify production
performance.

## Gate status after repair

Mandatory local gates (unit, architecture, ruff, repository structure)
passed on this branch tip. Critical false-accept protection was tightened
for charge AUTO (GPT-4o cannot independently promote).

## What was not re-run as governed release evidence

- The prior `9/10 STP recovery` charge-techstack smoke result remains a
  **smoke test** only; it is not production performance and is not carried
  forward as a V3 release metric.
- Blind-150 `v12.3p` results are **invalid for STP rate** after an OOM
  killed the OCR process pool mid-run (`BrokenProcessPool`); they must not
  be combined with smoke numbers.
- Hold-500 remains blocked until charge exact-match ≥ 6/9 on the frozen
  hard-15 set with FA ≤ 1 under the repaired fail-closed evidence policy.

## Required before READY TO MERGE for extraction-v3 promotion

1. Re-run hard-15 (frozen) with FA=0 and charge exact ≥ 6/9 under V3
   template + fail-closed charge policy.
2. Re-run an independent blind sample with a healthy OCR pool (no OOM).
3. Freeze extraction-v3 only after hashes, FA=0, and accepted precision
   meet the governed threshold on untouched holdout.

Until those complete, `extraction-v3` stays `CANDIDATE` and runtime
default remains `extraction-v2`.
