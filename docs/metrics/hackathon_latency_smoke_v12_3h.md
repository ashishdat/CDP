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

## Smoke

Same 5 Independent docs, `--workers 1`, residuals off, learned matcher off
(cascade defaults).
