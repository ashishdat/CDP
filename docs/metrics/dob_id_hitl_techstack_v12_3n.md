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
- **Evidence auth:** `packages/evidence_decision/service.py` allows `azure_gpt4o_crop` (`CLOUD_AI_FAMILY`) on `patient_dob` + `insured_id_number`

## Auth smoke (6 prior FIELD_INK HITL docs)

`evaluation_results/hackathon_dob_id_gpt4o_auth_smoke_v12_3n/` → **3/6 TRUE_STP**

| Doc | Prior | After auth | Notes |
| --- | --- | --- | --- |
| `HJE5.019` | HITL (ID stripped) | **TRUE_STP** | gpt-4o ID `949774145` AUTO_ACCEPTED |
| `HJHO.010` | HITL (ID) | **TRUE_STP** | gpt-4o ID `938332027` |
| `HJHO.003` | HITL (DOB) | **TRUE_STP** | local DATE/ID shaped (no gpt-4o) |
| `HJHO.005` | HITL (ID) | HITL | ID+DOB cleared; residual **total_charge** |
| `HJE5.016` | HITL (DOB) | HITL | gpt-4o **abstain** on DOB; ID conflict margin |
| `HJHO.011` | HITL (DOB) | HITL | gpt-4o **abstain** on DOB |

Authorization is working for member ID. Remaining DOB HITL is model abstain / unshaped DI — not engine stripping.

## v12.3o follow-ups (implemented)

| Target | Fix | Mechanism |
| --- | --- | --- |
| `HJE5.016` DOB | DI punct confusables | `_normalize_dob_punct_separators`: `7:30.77` / `7:30,77` → `07/30/1977` via span + YY expand |
| `HJHO.011` DOB | gpt-4o abstain | Full-box miss → MM/DD/YY cell-split strip retry + DI prior hints in prompt |
| `HJHO.005` charge | line-sum ≠ box-28 | `CDP_AZURE_DI_CHARGE_RESIDUAL=1` + `CDP_AZURE_DI_CHARGE_CORROBORATE=1` after local accept |

Env stamps (product cascade): charge residual/corroborate **ON**.

### Smoke retest (3 prior HITL docs)

`evaluation_results/hackathon_hitl_fix_smoke_v12_3o/` → **2/3 TRUE_STP** (mean ~23s)

| Doc | Prior (auth smoke) | After v12.3o | Notes |
| --- | --- | --- | --- |
| `HJHO.005` | HITL (total_charge) | **TRUE_STP** | Charge AUTO via `LINE_TOTALS_RECONCILED` (315.00); DI corroborate ran |
| `HJHO.011` | HITL (DOB abstain) | **TRUE_STP** | gpt-4o DOB `12/08/1983` AUTO |
| `HJE5.016` | HITL (DOB) | HITL (ID) | DOB fixed (`07/30/1977` via DI punct); residual ID conflict `33847173` vs `338977` (`CONFLICT_MARGIN_TOO_SMALL`) |
