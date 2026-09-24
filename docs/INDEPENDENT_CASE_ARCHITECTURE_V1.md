# Independent case architecture (v1)

Consolidates Independent-1000 recovery that previously forked ad-hoc across
cascade REG, unstructured DI, and field-ink residuals.

## Toolstack

| Layer | Module / config | Role |
|---|---|---|
| **Case router** | `packages/extraction_recovery/independent_case_router.py` + `config/independent_case_toolstack_v1.yaml` | Page-class → path |
| **Field residuals** | `field_recovery_router` + `field_recovery_toolstack_v13.yaml` | MISSING_INK / OVERLAP / CONFLICT ladders after CMS geometry |
| **Unstructured DI** | `unstructured_reg_fallback.py` | Full-page DI + precision-safe heuristics |
| **Claim decision** | `claim_decision` + `complete_from_extraction` | STP vs HITL on registered CMS |

## Paths

```
page text / registration state
        │
        ▼
 independent_case_router.classify_independent_case
        │
        ├── MAILROOM_REG      → KEEP REG (separator / fax / attachment)
        ├── CMS_GEOMETRY      → sift register → OCR → field_recovery_v13 → claim_decision
        ├── UNSTRUCTURED_DI   → Azure DI page-read → heuristics → promote (4 criticals)
        └── FIELD_INK_RESIDUAL→ complete-inplace / residual ladder (registered CMS HITL)
```

## Why a new router (not field_recovery_router)

`field_recovery_router` plans **field** residual tools. Case routing needs
**pre-registration** page class and disposition policy. Mixing them conflates
orchestration with crop planning.

## Open Independent redo

```bash
python3 -u scripts/rerun_independent_open_hitl.py \
  --ledger-a evaluation_results/hackathon_600_independent_v13c \
  --ledger-b evaluation_results/hackathon_400_remainder_independent_v13c
```

Kill switches unchanged: `CDP_UNSTRUCTURED_REG_FALLBACK`, `CDP_UNSTRUCTURED_REG_AGENT`,
`CDP_CLOUD_STOP_LADDER`.

## Independent-1000 after router (v13c remixed)

| Metric | Count | Rate |
|---|---|---|
| TRUE_STP | 797 | 79.7% |
| HITL | 44 | 4.4% |
| REG (mailroom/fax) | 159 | 15.9% |

HITL breakdown: 31 FIELD_INK · 13 UNSTRUCTURED_DI. Remaining blockers are
precision-held (unread DOB/charge ink, spouse `insured_name` conflict, line-sum
uncorroborated charge). See `docs/metrics/independent_1000_v13c_summary.json`.
