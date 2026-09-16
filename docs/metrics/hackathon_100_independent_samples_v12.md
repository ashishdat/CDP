# Metrics

## Independent Samples — 100 (v12 Field Value Authority)

First 100 docs of the Independent Samples-300 hackathon cohort, with v12 decision overlay.

| Track | Count | Rate |
|---|---:|---:|
| **True STP** | 74 | **74.0%** |
| Field HITL | 10 | 10.0% |
| Registration HITL | 16 | 16.0% |
| **Combined HITL** | 26 | **26.0%** |

Baseline slice → v12: True STP **58→74**, Field HITL **26→10**, Combined **42→26**.

## Full Independent Samples — 300 (v12)

| Track | Count | Rate |
|---|---:|---:|
| **True STP** | 170 | **56.7%** |
| Field HITL | 55 | 18.3% |
| Registration HITL | 75 | 25.0% |
| **Combined HITL** | 130 | **43.3%** |

Flipped 52 from baseline 118 (**+3 vs v11.6**): `EJG7.030`, `EJI2.034`, `HJCX.006`.

## Golden Pack V3 — Independent 100 (EXTRACTION_HARNESS)

| Metric | Value |
|---|---:|
| Exact accuracy | **99.8%** |
| Claim STP proxy | **98%** |
| Claim hard HITL | 2% |
| False accepts | **0** |

Architecture: `docs/STP_PIPELINE_ARCHITECTURE_V12.md` · tests: `tests/unit/cases/test_field_value_authority_v12.py`.
