# Metrics

## Independent Samples — 300

| Track | Count | Rate |
|---|---:|---:|
| True STP | 118 | 39.3% |
| Field HITL | 107 | 35.7% |
| Registration HITL | 75 | 25.0% |
| Combined HITL | 182 | 60.7% |
| Stage failure | 0 | — |
| Exact accuracy (agent GT) | 822/824 | 99.8% |
| Perfect-claim exact | 222/224 | 99.1% |
| False accepts | 2 | 0.2% |

Cohort: `hackathon docs[50:350] independent of diagnostic first-50` · strategy `field-cascade-v11` · n=300.

Accuracy is vs agent GT on labeled fields only (unlabeled hard ink abstains; HITL claims included when labeled).
