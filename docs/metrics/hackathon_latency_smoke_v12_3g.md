# Latency smoke v12.3g — ≤30s/doc bar

## Target

Claim elapsed mean **≤30s** (user bar).

## Config

- Residuals **off** (TrOCR / Azure DI DOB / Azure DI charge) — cascade defaults
- `CDP_LEARNED_MATCHER=0` on smoke (no torch)
- App + OCR worker pools on
- stp_critical OCR (no diagnosis/tax)

## Results (same 5 Independent docs)

| Workers | Mean | p50 | Max | Batch wall | True STP |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 43.3s | 41.1s | 62.1s | 122s | 5/5 |
| **1** | **9.6s** | **10.4s** | 12.8s | **53s** | **5/5** |

`--workers 1` is required on this VM for the ≤30s mean: two parallel claims
contend on SIFT+OCR and inflate wall to ~40s even with residuals off.

Charges vs GT preserved (121, 2511, 157, 1571, 70).
