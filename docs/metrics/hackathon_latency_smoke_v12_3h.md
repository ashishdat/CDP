# Latency smoke v12.3h — ≤30s/doc bar (learned matcher off)

## Target

Claim elapsed mean **≤30s** (user bar).

## Config delta vs v12.3g

| Knob | v12.3g Independent-300 | v12.3h |
| --- | --- | --- |
| `CDP_LEARNED_MATCHER` | `1` (torch on hard REG) | **`0`** (cascade default) |
| `CDP_OCR_NAME_CONFIRM_MIN_CONF` | hardcoded 0.88 | **`0.80`** |
| Residuals (TrOCR / Azure DI) | off | off |
| Workers | 1 | 1 |

## Why

Independent-300 v12.3g early mean ~15s was under bar, but hard-REG claims
(M048DJJM.046–.050) hit **23–33s**: 6–7 SIFT attempts + SuperPoint/LightGlue
(~6–8s REG) then elevated Rapid confirm counts. LightGlue also polluted the
long-lived app worker.

## Smoke (5 docs, workers=1)

| Doc | v12.3g | v12.3h | Disposition |
| --- | ---: | ---: | --- |
| M048DJJM.046 | 33.1s | **14.3s** | REGISTRATION_FAILED (was HITL via LightGlue) |
| M048DJJM.047 | 26.8s | **11.4s** | REGISTRATION_FAILED (was TRUE_STP via LightGlue) |
| M048DJJM.048 | 29.5s | **11.2s** | REGISTRATION_FAILED (was HITL) |
| M048DJKH.001 | ~9s | **11.3s** | TRUE_STP |
| M048DJKH.002 | ~7s | **6.6s** | TRUE_STP |

**Mean 11.0s / p50 11.3s / max 14.3s** — under ≤30s bar.

Tradeoff: catastrophic REG no longer recovered by LightGlue → more
`REGISTRATION_FAILED` HITL, much lower wall on those claims.
