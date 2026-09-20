# Production launch record

Copy this file into the working close-out package (created by
`scripts/check_production_closeout.py --init`) and fill every field.
Unsigned / blank fields keep the gate at **NEEDS_MORE_DATA**.

## Identity

| Field | Value |
|---|---|
| Release / commit SHA | |
| Runtime profile | `config/runtime_profiles/production_runtime_v1.yaml` |
| Pipeline release | `extraction-v2` |
| Evidence package path | |
| Holdout manifest path | |
| Holdout manifest SHA-256 | |

## Organizational approvals

| Gate | Approver | Date | Evidence reference |
|---|---|---|---|
| IdP / tenant RBAC | | | |
| BAA / PHI external processing | | | |
| Region / retention / key rotation | | | |
| Security assessment | | | |
| Data-governance holdout attestation | | | |
| Staging cluster soak / rollback | | | |
| DB migration + restore drill | | | |

## Holdout results (from sealed run)

| Metric | Value | Gate |
|---|---|---|
| Documents | | ≥1000 |
| Fields | | ≥3000 |
| Overall raw accuracy | | ≥0.95 |
| Critical accuracy | | ≥0.98 |
| Critical false accepts | | =0 |
| Claim STP | | ≥0.92 |
| Claim HITL | | ≤0.08 |
| Claim HITL upper 95% CI | | <0.10 |
| P95 latency (ms) | | ≤30000 |
| Cost / document (USD) | | measured |

## Canary

| Field | Value |
|---|---|
| Canary scope (% / tenants / days) | |
| Shadow samples | |
| Observed critical FA during canary | |
| Rollback decision maker | |
| Incident owner | |
| Dashboards / alerts | |

## Signed promotion decision

- Decision: `PROMOTE_TO_PRODUCTION` / `PROMOTE_TO_SHADOW` / `REJECT` / `NEEDS_MORE_DATA`
- Accountable owner:
- Signature / ticket:
- Date (UTC):

**Note:** Filling this form does not by itself authorize PHI. The machine
validator must also exit 0 on the evidence JSON.
