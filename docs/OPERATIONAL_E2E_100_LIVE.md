# Operational E2E — 100 real Hackathon claims (live)

## Verdict

**NOT QUALIFIED** for production on the live 100-claim application path.

| Metric | Live (this run) | Frozen baseline |
|--------|-----------------|-----------------|
| Operational completion (FinalClaim) | **43%** (43/100) | 39% (39/100) |
| True STP (completed + no review) | **0%** | 0% |
| E2E correct completion | Unavailable (no independent GT) | Unavailable |

## What ran

- Archive: `data/Hackathon - 1000 Claims.zip` (SHA-256 verified against `DEVELOPMENT_DATASET_V1`)
- Cohort: 100 paired claims from `AnchorNormalizationDeltaReport.json`
- Path: `app.py` → geometry → OCR → rank → validate → assemble → FinalClaim
- Recovery: diagnose + plan on every incomplete claim (no executable registration/scan recovery yet; OCR alternate-prep only)

## Blocking reasons

1. True STP remains 0% — every completed claim still has `review_required=true`
2. Completion is still far below a production bar (43%)
3. 57/100 stop at selection/registration (`POOR_SCAN` / template issues)
4. E2E correctness cannot be scored without field-level ground truth for these claims

## Artifacts

- Compact report: [`docs/OPERATIONAL_E2E_100_LIVE_REPORT.json`](OPERATIONAL_E2E_100_LIVE_REPORT.json)
- Full machine output (gitignored): `evaluation_results/operational_e2e_100_v1/`
- Re-run: `python3 scripts/run_operational_e2e_100.py --live --live-limit 100`
