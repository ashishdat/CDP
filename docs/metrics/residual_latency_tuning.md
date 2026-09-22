# TrOCR / Azure DI residual latency tuning

Measured on Independent-300 v12.3f (~72 claims in):

| Residual | Fires | Claim elapsed when fired | Notes |
| --- | ---: | ---: | --- |
| TrOCR DOB | 3 | **~285–303s** (vs ~142s clean) | All `TROCR_INSUFFICIENT_EVIDENCE`; one claim already had local `08/01/2016` |
| Azure DI DOB crop | 3 | after TrOCR miss | 1 shaped review-only, 2 unshaped — little STP gain |
| Azure DI charge crop | 8 | meter only | Empty/conflict gate already in place |

Root causes:

1. **TrOCR rebuilt the adapter every call** → `from_pretrained` reload (~30–150s CPU) per residual.
2. **Planner matched every `patient_dob` gap** (`or field in {patient_dob}`), so non-handwriting rejects still escalated.
3. **Local date-shaped ink still triggered residual** when cascade had not accepted (conflict/policy).

## Knobs

| Env | Default | Effect |
| --- | --- | --- |
| `CDP_TROCR_DOB_RESIDUAL` | `1` | Local TrOCR after handwriting DOB miss |
| `CDP_AZURE_DI_DOB_RESIDUAL` | `1` | Azure DI DOB crop after TrOCR miss/off |
| `CDP_DOB_RESIDUAL_SKIP_IF_LOCAL_SHAPED` | `1` | Skip TrOCR/DI when local candidate is already date-shaped |
| `CDP_AZURE_DI_CHARGE_RESIDUAL` | `1` | Charge-cell DI on empty/conflict only |
| `CDP_AZURE_DI_CHARGE_ACCEPT` | `1` | Accept currency-shaped charge DI |
| `CDP_AZURE_DI_PAGE_CORNERS` | `0` | Full-page corners (keep off) |

Latency-first recipe (smoke-style **only** — never for STP gates):

```bash
CDP_TROCR_DOB_RESIDUAL=0
CDP_AZURE_DI_DOB_RESIDUAL=0
CDP_AZURE_DI_CHARGE_RESIDUAL=0
```

**2026-09-22:** residual-off + paddle-only lines + single charge window hit ~17s median
but collapsed ops True STP to **50.7%** on 744. Those OCR shortcuts were **reverted**.
Next path: adaptive early-stop + stop ladder (see `stp_latency_next_strategy_v1.md`).

Accuracy path (default cascade): keep residuals on; singleton TrOCR + skip-if-local-shaped
cuts wasted cold loads. Prefer Azure DI crop-only over TrOCR on CPU-bound VMs:

```bash
CDP_TROCR_DOB_RESIDUAL=0
CDP_AZURE_DI_DOB_RESIDUAL=1   # ~1–3s network vs TrOCR load
```
