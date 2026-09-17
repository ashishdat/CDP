# Independent-300 v12.3h — latency bar (≤30s/doc mean)

**Run:** `evaluation_results/hackathon_300_cascade_v12_3h`  
**Slice:** offset 50, limit 300, `--workers 1`  
**Config:** residuals off (TrOCR / Azure DI DOB+charge), `CDP_LEARNED_MATCHER=0`,
`CDP_OCR_NAME_CONFIRM_MIN_CONF=0.80`, stp_critical OCR, app+OCR pools  
**Finished:** 2026-09-17T08:19:48Z (`EXIT:0`)

## Latency (user bar: mean ≤30s)

| Metric | v12.2 | **v12.3h** |
| --- | ---: | ---: |
| Mean elapsed | 157.5s | **11.6s** |
| p50 | 128.2s | **9.4s** |
| p90 | 313.1s | **13.9s** |
| Max | 674.3s | 490.1s† |
| Over 30s | 292/300 | **1/300** |
| Mean excl. >60s | 41.1s | **10.0s** |

† Single outlier `Group A__M048HJCX.020` (TRUE_STP, ~490s; REG ~2s, light OCR).
All other claims ≤23s.

**Verdict: ≤30s/doc mean met** (11.6s; 10.0s without the one stall).

## Operational STP / HITL

| Metric | v12.2 | **v12.3h** |
| --- | ---: | ---: |
| TRUE_STP | 203 (67.7%) | **210 (70.0%)** |
| Field HITL | 24 | **21** |
| REG_FAILED | 73 | **69** |
| Registration OK | 227 | **231** |

Latency path did not hurt ops STP on this slice; REG fail-closed slightly improved
vs v12.2 despite LightGlue off (v12.2 already failed many of the same catastrophic
frames after the classical ladder).

## Agent-GT field accuracy

Scored with existing `evaluation_data/hackathon_agent_gt/field_truth.json`
(`scripts.score_hackathon_gt_accuracy`). Artifact:
`docs/metrics/hackathon_300_cascade_v12_3h_gt_accuracy.json`.

| Metric | v12.2 | v12.3h |
| --- | ---: | ---: |
| Claims scored | 218 | 200 |
| Exact field accuracy | **94.4%** | 78.0% |
| Perfect-claim exact | **81.2%** | 38.0% |
| `total_charge` exact | **85.0%** | 45.0% |
| `patient_dob` exact | **97.0%** | 74.2% |
| `patient_name` exact | **96.2%** | 88.2% |
| `insured_name` exact | **95.4%** | 80.0% |
| `insured_id_number` exact | **99.5%** | 98.9% |

Accuracy drop is expected on the latency path: charge/DOB residuals off + looser
name Rapid gate. Use `CDP_TROCR_DOB_RESIDUAL=1 CDP_AZURE_DI_CHARGE_RESIDUAL=1
CDP_LEARNED_MATCHER=1` (and tighter name confirm) for the accuracy path.

## Knobs that got us under 30s

1. `--workers 1` (workers≥2 thrash SIFT/OCR → ~40s mean on this VM)
2. Residuals off (TrOCR/Azure DI)
3. `CDP_LEARNED_MATCHER=0` (no torch in app worker; hard-REG fail-closed ~11–14s)
4. Name Rapid confirm min conf 0.80 (was 0.88)
5. Selective confirm + Paddle-primary + stp_critical + app/OCR pools

See `docs/CASCADE_SPEED.md`, `docs/metrics/hackathon_latency_smoke_v12_3h.md`.
