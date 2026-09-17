# Latency smoke v12.3e — further tuning

## Changes since v12.3 smoke (mean ~41s)

1. **Quiet registration telemetry** (`CDP_REGISTRATION_VERBOSE_TELEMETRY=0`): skip
   multi-MB keypoint/match dumps and full-image SHA256; app.log ~2MB → ~25KB.
2. **Template SIFT cache** + skip redundant pre-preprocess `detect()` on fast path.
3. **Inference-scoped OCR lock** (prep overlaps; Paddle/Rapid still serialized).
4. **Name confirm gate**: ignore weak 1–2 char MI fragments so strong names skip Rapid.
5. **Merged finish** (`finish_from_ocr`): rank→validate→assemble→complete in one process.
6. **OCR worker pool** (`CDP_OCR_WORKER_POOL=1`): spawn ProcessPool keeps engines warm
   across claims (first Paddle field ~0.5s warm vs ~2.9s cold).

## Solo stage profile (M048DJKH.001, residuals off)

| Stage | v12.3 | v12.3e |
| --- | ---: | ---: |
| app | 5.54s | **4.68s** |
| ocr | 9.55s | **8.48s** (no Rapid on patient_name) |
| post-OCR | ~1.39s (4 procs) | **0.67s** (finish) |
| **Total** | **~16.5s** | **~13.8s (−16%)** |

## 5-doc Independent smoke (workers=2, residuals off)

| Doc | v12.3 | v12.3e | Charge |
| --- | ---: | ---: | --- |
| M048DJJM.037 | 41.4s | 56.8s | 121 ✓ |
| M048DJJM.041 | 61.7s | **39.6s** | 2511 ✓ |
| M048DJKH.001 | 35.6s | **35.1s** | 157 ✓ |
| M048DJKH.002 | 35.5s | 38.0s | 1571 ✓ |
| M048DJKH.003 | 30.9s | **27.5s** | 70 ✓ |

| Metric | v12.3 | v12.3e |
| --- | ---: | ---: |
| Mean claim elapsed | 41.0s | **39.4s** |
| p50 | 35.6s | 38.0s |
| Batch wall | 113s | **110s** |
| True STP | 5/5 | **5/5** |

Digit-drop accuracy preserved. Warm-pool claims show first Paddle ~500ms;
one worker still pays ~2.9s cold start on its first claim.
