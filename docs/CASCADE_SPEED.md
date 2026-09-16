# Cascade speed knobs (ops STP eval)

Hackathon claims were ~150–170s wall-clock each under 3 workers because:

1. **RapidOCR** warm ~0.5s/crop (vs Paddle ~0.01s) and both engines always ran
2. **Parallel OCR subprocesses** thrashed CPU (OCR stage ballooned ~13s work → ~87s wall)

## Defaults now (via `run_hackathon_1000_cascade._stage_env`)

| Env | Default | Effect |
|-----|---------|--------|
| `CDP_OCR_FIELD_SCOPE` | `stp_critical` | OCR only STP-critical fields |
| `CDP_OCR_SELECTIVE_CONFIRM` | `1` | Stop after field-shaped primary; confirm only on miss |
| `CDP_OCR_PRIMARY_OVERRIDE` | `paddleocr` | Prefer fast Paddle first on STP eval (Rapid confirms if needed) |
| `CDP_OCR_LOCK` | `1` | Serialize OCR across workers (registration still parallel) |

Override examples:

```bash
CDP_OCR_PRIMARY_OVERRIDE=rapidocr   # production Rapid-primary authority
CDP_OCR_SELECTIVE_CONFIRM=0         # legacy dual-engine always
CDP_OCR_LOCK=0                      # allow parallel OCR (slower under contention)
CDP_OCR_FIELD_SCOPE=all             # full-form OCR
```

Solo OCR benchmark (one claim, stp_critical): **~11.4s → ~7.2s** after selective + Paddle-primary.
