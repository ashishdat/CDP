# DOB / member-ID HITL tech stack — v12.3n

Hard-150 FIELD_INK residual (28 docs): blockers **patient_dob×22**, **insured_id_number×14**.

## Failure modes (current stack exhausted)

| Mode | n (approx) | What local+TrOCR+DI did |
| --- | ---: | --- |
| UNSHAPED_DOB | 17 | DI returned `7:30.77`, `04/`, Hebrew glyphs, `MM` labels; TrOCR insufficient |
| ID chrome / garbage | ~8 | Cascade `ID_SHAPED` on label bleed (`1a.INSURED'S…`) or alpha soup (`Mrieniian`) |
| ID calibration | ~6 | Format-valid short IDs (`20755`, `OSC768X5`) but conf &lt; 0.92 |

Geometry agent is still the wrong tool. Need **crop-scoped field reading**.

## Bakeoff (gpt-4o crop-only)

Script: `scripts/bakeoff_dob_id_hitl_vlm.py`  
Artifacts: `evaluation_results/dob_id_hitl_vlm_bakeoff_v12_3m/`

| Field | Shaped / usable | Abstain | Mean latency |
| --- | ---: | ---: | ---: |
| patient_dob | **16/17 (94%)** | 1 | ~2.0s |
| insured_id_number | **14/14*** | 0 | ~2.0s |

\*One ID (`IJMP.006`) returned label-bleed soup (`…N0BER`) — reject via chrome filter, keep HITL.

Visual spot-check: `HJE5.016` DOB `7/30/77` → `07/30/1977` ✓; `HJHO.003` `04/11/98` ✓; `HJE5.019` ID `949774145` ✓ (paddle had `Mrieniian`).

## Recommended stack (shipped)

```
local Rapid/Paddle/Tesseract (+ DOB digit-band / ID value-band)
  → TrOCR DOB crop (local)
  → Azure DI DOB crop (accept if date-shaped)
  → Azure gpt-4o crop-only  ← NEW for DOB miss + weak/chrome ID
  → React field HITL
```

| Lever | Env | Role |
| --- | --- | --- |
| gpt-4o crop residual | `CDP_GPT4O_CROP_RESIDUAL=1` | After DI miss (DOB) or weak/chrome ID |
| accept shaped | `CDP_GPT4O_CROP_ACCEPT=1` | Promote date-/ID-shaped non-abstain |
| reject ID chrome | built-in | Drop `NUMBER`/`PROGRAM`/`N0BER` ghosts |

**Not recommended as primary:** Florence-2 alone (no bakeoff win vs gpt-4o here); full-page VLM; softening ID conf threshold without corroboration (raises false STP).

## Code

- `packages/extraction_recovery/gpt4o_crop_residual.py`
- Wired in `scripts/ocr_from_geometry.py` residual pass
- Product stamps in `scripts/run_hackathon_1000_cascade.py`
- Adapter reuse: `workers/vlm_fallback` (crop-only, temp 0, strict JSON)
