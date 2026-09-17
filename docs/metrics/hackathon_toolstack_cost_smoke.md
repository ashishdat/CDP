# Independent toolstack cost smoke (5 docs)

Run: `evaluation_results/hackathon_toolstack_final_smoke`  
Cost policy: local first (document-quad → SuperPoint/LightGlue → TrOCR); **full-page Azure DI corners OFF**; Azure DI **DOB crop only** after TrOCR miss.

## Results vs v12.2

| Document | v12.2 | Now | Notes |
| --- | --- | --- | --- |
| `Group A/M048DJJM.047` | REGISTRATION_FAILED | **TRUE_STP** | SuperPoint+LightGlue (`$0`) |
| `Group A/M048EJG7.009` | REGISTRATION_FAILED | **TRUE_STP** | SuperPoint+LightGlue (`$0`) |
| `Group A/M048DJJM.036` | HITL (patient_dob) | **TRUE_STP** | Azure DI crop → `2016-08-01` |
| `Group A/M048EJG7.005` | HITL (patient_dob) | HITL | Honest residual (DI unshaped) |
| `Group A/M048DJJM.037` | TRUE_STP | TRUE_STP | Control |

**True STP: 4/5** · **Reg HITL: 0/5** · **Field HITL: 1/5**

## Azure DI cost

- Full-page page-corner calls: **0**
- DOB crop calls: **2** (only the two handwriting DOB misses)
- LightGlue recoveries: **2** (both prior Reg failures)

## Cost knobs

| Env | Default | Role |
| --- | --- | --- |
| `CDP_LEARNED_MATCHER` | `1` | Local LightGlue (avoids Azure $) |
| `CDP_AZURE_DI_PAGE_CORNERS` | `0` | Billable full-page; keep off |
| `CDP_TROCR_DOB_RESIDUAL` | `1` | Local TrOCR before DI |
| `CDP_AZURE_DI_DOB_RESIDUAL` | `1` | Crop DI after TrOCR miss |
| `CDP_AZURE_DI_DOB_ACCEPT` | `1` | Accept date-shaped DI crops |

Generated: 2026-09-17T02:16:15.465807+00:00
