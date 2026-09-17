# Independent Samples — 300 (v12.2 learning retest)

Run: `evaluation_results/hackathon_300_cascade_v12_2` (offset 50, limit 300, workers 3)  
Learning fixes: `4f2c7f2`

## Headline metrics

| Metric | Count | Rate |
| --- | ---: | ---: |
| **True STP** | 203 | **67.7%** |
| Registration HITL | 73 | 24.3% |
| Field HITL | 24 | 8.0% |
| Combined HITL | 97 | 32.3% |

**Target met:** beat v12 decision-reprocess STP 56.7% → **67.7%** (YES).

## vs baselines

| Cohort | True STP | Reg HITL | Field HITL |
| --- | ---: | ---: | ---: |
| v11 cascade | 118 (39.3%) | 75 | 107 |
| v12 decision-reprocess | 170 (56.7%) | 75 | 55 |
| v12.1 partial (stopped @ 213) | 145 (68.1%) | 50 | 18 |
| **v12.2 (this run)** | **203 (67.7%)** | 73 | 24 |

- vs v11: **+87 flips to STP**, 2 regressions (Δ STP +85)
- vs v12 decision-reprocess: **+33 STP** (+11.0 pp)
- vs v12.1 partial overlap (213 docs): STP 145 → 145 (+0)

## Learnings applied

1. DOB YY pivot aligned with reconciler (`≥30 → 19xx`) + future→19xx repair
2. Weak person-name selective confirm when primary confidence `< 0.88`
3. OCR periods no longer invent `Last, First` separators

### Learning-claim outcomes

| Document | v11 STP | v12.2 STP | Notes |
| --- | --- | --- | --- |
| `Group A/M048EJG7.002` | True | **True** | dob=1930-09-01; name=BELDIN BONNIE |
| `Group A/M048EJGE.012` | False | **True** | dob=1934-01-01; name=DE LUDE. TAYLOR |
| `Group A/M048EJGE.020` | False | **False** | dob=1930-12-21; name=STERN SCART.ET |
| `Group A/M048EJGE.022` | True | **True** | dob=2016-01-06; name=TOHNSON RATSTRY |

## Regressions vs v11 (2)

- `Group A/M048EJG7.009` — REGISTRATION_FAILED reason=`low_inlier_ratio,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners` blockers=None
- `Group A/M048HJBI.006` — REGISTRATION_FAILED reason=`insufficient_inliers,low_inlier_ratio,low_coverage,unsafe_scale_change,unsafe_rotation,unsafe_perspective_distortion,invalid_transformed_corners` blockers=None

## Field HITL blockers

{
  "patient_dob": 18,
  "insured_id_number": 5,
  "patient_name": 1
}

## Honest residuals

Registration HITL remains dominated by catastrophic perspective / multi-reason warp failures (Track A). Empty/garbage DOB crops without calendar shape stay Field HITL (Azure DI still unconfigured).

Generated: 2026-09-17T00:28:38.642085+00:00
