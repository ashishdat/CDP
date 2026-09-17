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
| `CDP_OCR_LOCK` | `1` | Enable cross-process OCR flock |
| `CDP_OCR_LOCK_SCOPE` | `inference` | Flock Paddle/Rapid only (prep overlaps). `process` = entire OCR subprocess |
| `CDP_OCR_LOCK_ENGINES` | `paddleocr,rapidocr` | Engines that take the inference flock (Tesseract digits stay unlocked) |
| `CDP_OCR_WORKER_POOL` | `1` | Long-lived OCR processes amortize Paddle/Rapid cold start across claims |
| `CDP_APP_WORKER_POOL` | `1` | Long-lived app/registration processes amortize imports + template SIFT |
| `CDP_REGISTRATION_VERBOSE_TELEMETRY` | `0` | Skip multi-MB keypoint/match dumps + full-image SHA256 |
| `CDP_AZURE_DI_DOB_RESIDUAL` | `0` | DOB Azure DI crop (off for ≤30s/doc latency bar) |
| `CDP_TROCR_DOB_RESIDUAL` | `0` | Local TrOCR DOB residual (off for ≤30s/doc latency bar) |
| `CDP_AZURE_DI_CHARGE_RESIDUAL` | `0` | Charge Azure DI crop (off for ≤30s/doc latency bar) |
| `CDP_DOB_RESIDUAL_SKIP_IF_LOCAL_SHAPED` | `1` | Skip TrOCR/DI when local OCR already date-shaped |
| `CDP_LEARNED_MATCHER` | `1` | SuperPoint+LightGlue for catastrophic REG (local) |
| `CDP_AZURE_DI_PAGE_CORNERS` | `0` | Full-page Azure DI corners (billable; off by default) |

**Latency bar (this VM):** claim mean **≤30s**. Achieved at **`--workers 1`** with residuals
off + app/OCR pools (~10s mean smoke). `--workers 2+` thrash SIFT/OCR and push mean ~40s+.
For accuracy residuals: `CDP_TROCR_DOB_RESIDUAL=1 CDP_AZURE_DI_DOB_RESIDUAL=1 CDP_AZURE_DI_CHARGE_RESIDUAL=1`.

Override examples:

```bash
CDP_OCR_PRIMARY_OVERRIDE=rapidocr   # production Rapid-primary authority
CDP_OCR_SELECTIVE_CONFIRM=0         # legacy dual-engine always
CDP_OCR_LOCK=0                      # allow parallel OCR (slower under contention)
CDP_OCR_LOCK_SCOPE=process          # legacy: flock entire ocr_from_geometry subprocess
CDP_OCR_FIELD_SCOPE=all             # full-form OCR
CDP_REGISTRATION_VERBOSE_TELEMETRY=1  # debug keypoint/match dumps
CDP_REGISTRATION_ORIENTATION_VLM=1  # gated VLM orientation hint before fail-closed
```

Solo OCR benchmark (one claim, stp_critical): **~11.4s → ~7.2s** after selective + Paddle-primary.

Cascade claim wall (Independent-300, 3 workers, this VM):

| Run | p50 elapsed | Notes |
| --- | ---: | --- |
| v12.2 | ~128s | selective + paddle-primary (prod-ish bar) |
| v12.3 early | ~243s | always dual-engine on charges (regressed) |
| v12.3 smoke | ~36s mean ~41s | conditional charge confirm + one charge window |
| v12.3d target | **≤ smoke** | inference lock + quiet REG telemetry + merged finish |

Charge confirm policy: force rapid only when primary currency has **≤3 dollar digits**
(digit-drop risk). Longer amounts stay single-engine under selective confirm.

Name confirm: use mean confidence of tokens length ≥3 so a weak MI fragment does not
force Rapid.

Inference-scoped lock lets registration+warp overlap across workers while still serializing heavy OCR.
Post-OCR rank/validate/assemble/complete run in one `finish_from_ocr` subprocess.
`CDP_OCR_WORKER_POOL=1` (default) keeps OCR engines warm across claims in a spawn process pool.
