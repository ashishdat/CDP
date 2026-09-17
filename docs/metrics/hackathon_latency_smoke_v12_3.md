# Latency smoke v12.3 — back under cascade bar

## Problem

Always dual-engine confirm on charges regressed Independent-300 claim wall from
**v12.2 p50 ~128s** to **v12.3 early p50 ~243s** (mean ~244s) — far above the
cascade speed bar / prod-ish benchmark on this VM.

## Fix

1. **Conditional rapid confirm** on charges: only when primary currency has ≤3
   dollar digits (digit-drop risk). Longer amounts stay selective single-engine.
2. **One charge x-window** under STP fast (was 2).
3. Azure DI charge crops remain gated to empty/conflict only (not every short $).

## Measured (5 Independent docs, workers=2, residuals off)

| Doc | v12.2 elapsed | smoke elapsed | Charge vs GT |
| --- | ---: | ---: | --- |
| M048DJJM.037 | 176.5s | **41.4s** | 121 ✓ |
| M048DJJM.041 | 251.9s | **61.7s** | 2511 ✓ (rapid confirm) |
| M048DJKH.001 | 248.9s | **35.6s** | 157 ✓ |
| M048DJKH.002 | 265.5s | **35.5s** | 1571 ✓ (rapid confirm) |
| M048DJKH.003 | 146.0s | **30.9s** | 70 ✓ |

| Metric | v12.2 same docs | Smoke |
| --- | ---: | ---: |
| Mean | 217.8s | **41.0s** (−81%) |
| p50 | 248.9s | **35.6s** |
| Batch wall | — | **113s** / 5 docs |

Digit-drop accuracy preserved: paddle `157`/`251` + rapid confirm → `1571`/`2511`.
