# Production readiness gate

This document separates repository hardening from authorization to process
production healthcare data. Passing the code-quality gate does not by itself
authorize a production launch.

Current platform status: **production-hardened, not production-authorized**.

## Automated code gate

The following checks are mandatory on every pull request:

- architecture dependency validation;
- Python lint and unit/architecture tests;
- evaluation UI tests and production build;
- high/critical JavaScript dependency audit;
- secret and generated-artifact exclusions;
- production runtime fail-closed smoke
  (`scripts/smoke_production_fail_closed.py` +
  `tests/unit/cases/test_production_runtime.py`).

### Production fail-closed pin (shipped)

When `CDP_ENV=production` (or `prod`), APIs and workers refuse unsafe local
defaults before serving traffic:

| Check | Enforcement |
|---|---|
| Runtime profile hashes | `config/runtime_profiles/production_runtime_v1.yaml` |
| Frozen release | `CDP_PIPELINE_RELEASE=extraction-v2` |
| No sqlite / in-memory bus | `packages.production_runtime` |
| No default MinIO credentials | reject `minioadmin` / `minioadmin` |
| External AI | VLM off; Azure DI/OpenAI REVIEW_ONLY; AI gateway needs PHI approval |
| Liveness / readiness | `/health` + `/ready` on ingestion, human-review, output APIs |

Operator entrypoint: `docs/PRODUCTION_OPERATOR_RUNBOOK.md`.

GitHub Actions reproduces the code checks from a clean checkout.

## Release blockers

These items require implementation or an explicitly approved operational
control before processing production PHI:

1. Replace header-based RBAC with the organization's authenticated identity
   provider and enforce tenant claims at every API boundary.
2. ~~Wire validation failures to automatic review-task creation; no critical
   unresolved field may finalize without authorized reference evidence or an
   approved human decision.~~ (Wired via Phase 7)
3. ~~Complete and exercise the live validation, retry, VLM-escalation, and output
   consumer chain. Offline evaluation success is not a substitute for an
   end-to-end production event flow.~~ (Wired via Phase 7)
4. Apply versioned database migrations against a production-like **MySQL 8**
   environment and test backup, restore, retention, and deletion workflows.
   *(MySQL is the preferred platform DB; see `deploy/mysql/` and
   `scripts/apply_mysql_migrations.py`. Postgres remains legacy-only.)*
5. Add deployment definitions for every live worker and validate Helm/KEDA,
   network policy, secret injection, resource limits, and rollback in a staging
   cluster. *(API charts for ingestion, human-review, and output are present;
   staging cluster validation remains.)*
6. Complete security/contract approval for any external OCR or VLM processing,
   including BAA, region, retention, diagnostics, key rotation, and cost limits.
7. Pass the frozen untouched holdout and canary gates defined in the evaluation
   policy. The current-sample benchmark is not an independent production
   generalization estimate.

## Launch evidence

A release record must contain:

- immutable application/config/model checksums;
- migration and rollback identifiers;
- holdout, false-accept, abstention, latency, and cost results;
- security and PHI-processing approvals;
- incident owner, dashboards, alerts, runbook, and rollback decision maker;
- canary scope and signed promotion decision.

Until every blocker is closed or formally accepted by the accountable owner,
the correct status is **production-hardened, not production-authorized**.

## Measured eval tip (development labels — not release authority)

Hackathon decide tip `evaluation_results/hackathon_150_geo_underread_600_decide`
(see `docs/metrics/geo_underread_600_decide_v1.json` and
`docs/metrics/geometry_accuracy_95_gate_v1.json`):

| Gate | Result |
|---|---|
| Field exact accuracy ≥95% | **PASS (98.95%)** via geometry tip + GT ledger |
| True STP ≥94% | PASS (84/89) |
| True STP ≥95% | FAIL operational (need ≥85/89; 5 fail-closed HITL remain) |
| Claim HITL ≤6% | PASS (5.6%) |
| Critical accepted precision ≥99.5% | PASS (100% on scored accepts) |
| Zero critical false accepts | PASS (0) |
| `release_gate_eligible` | **false** — agent-confirmed labels are not independent adjudicated truth |

Operator check: `python3 scripts/check_geometry_accuracy_gate.py` (exit 0 when
exact ≥95%, precision ≥99.5%, FA=0).

These numbers harden confidence in the cascade; they do **not** close holdout
blocker #7 or authorize PHI.

## Staging deploy hygiene (shipped)

- Worker NetworkPolicy egress allows **MySQL 3306** (preferred) and legacy
  Postgres 5432 (`deploy/helm/cdp-worker-pools/templates/platform.yaml`).
- Human-review task worker calls `assert_production_ready` on startup
  (`apps/human_review_api/consumer.py`), matching other Kafka consumers.
- Operator shortcuts: `make prod-smoke`, `make prod-check` (local fail-closed
  + closeout validator). `make run` remains **local Compose only**.

## How to close the remaining blockers

Follow `docs/PRODUCTION_CLOSEOUT_CHECKLIST.md`. Scaffold and validate evidence:

```bash
make prod-closeout-init
make prod-smoke
make prod-check   # exit 0 only when authorized
```

Templates live under `docs/templates/`. The validator fails closed until holdout
metrics, IdP/BAA/staging approvals, canary (0 critical FA), and a signed
promotion are all present — it will not invent them.
