# Production close-out checklist

How to move from **production-hardened** to **production-authorized PHI**.
Hackathon STP and synthetic packs do **not** close these gates.

Operator package:

| Artifact | Path |
|---|---|
| This checklist | `docs/PRODUCTION_CLOSEOUT_CHECKLIST.md` |
| Launch record (human) | `docs/templates/PRODUCTION_LAUNCH_RECORD.md` |
| Evidence skeleton (machine) | `docs/templates/production_promotion_evidence.template.json` |
| Holdout attestation form | `docs/templates/holdout_attestation.template.json` |
| Validator | `python3 scripts/check_production_closeout.py` |

```bash
# Scaffold a working evidence package (gitignored under evaluation_results/)
python3 scripts/check_production_closeout.py --init

# Validate current package (fails closed until complete)
python3 scripts/check_production_closeout.py
```

---

## Phase A — Organizational gates (parallel)

### A1. Identity provider (blocker #1)

- [ ] Choose IdP (OIDC/SAML) and register CDP API clients
- [ ] Map IdP roles → `packages.security.rbac.Role`
- [ ] Replace `X-User-Role` hook in `packages/security/fastapi_rbac.py` with JWT/claim lookup
- [ ] Enforce tenant claim on every API boundary
- [ ] Staging test: unauthenticated → 401; cross-tenant → 403
- [ ] Record: IdP issuer, client IDs, test evidence path in launch record

### A2. External AI / PHI contracts (blocker #6)

- [ ] BAA (or equivalent) signed for each external OCR/VLM vendor
- [ ] Region approved; retention / diagnostics / key rotation documented
- [ ] Cost limits set
- [ ] Only then set env flags:
  - `AZURE_DOCUMENT_INTELLIGENCE_AUTHORIZED`
  - `AZURE_DOCUMENT_INTELLIGENCE_REGION_APPROVED`
  - `AZURE_DOCUMENT_INTELLIGENCE_PHI_CONTRACT_APPROVED`
  - `AI_PHI_EXTERNAL_PROCESSING_APPROVED` (if AI gateway used)
- [ ] Keep `*_REVIEW_ONLY=true` until route promotion after holdout

### A3. Named owners

- [ ] Incident owner
- [ ] Rollback decision maker
- [ ] Security / compliance approvers
- [ ] Data-governance approver (holdout attestation)

---

## Phase B — Infrastructure drills (parallel with A)

### B1. Database (blocker #4)

- [ ] Apply `deploy/postgres/migrations` against prod-like Postgres
- [ ] Backup → restore drill; record RTO and migration IDs
- [ ] Retention / deletion workflow exercised
- [ ] Attach evidence paths in launch record

### B2. Staging cluster (blocker #5)

- [ ] Deploy Helm: `ingestion-api`, `human-review-api`, `output-api`, workers/KEDA
- [ ] Secrets from secret manager (not `minioadmin`)
- [ ] `CDP_ENV=production` + `CDP_PIPELINE_RELEASE=extraction-v2` + production runtime profile
- [ ] Prove `/ready` on all three APIs
- [ ] Network policy, resource limits, rollback demo
- [ ] Optional: 1k/10k soak + failure injection

---

## Phase C — Frozen holdout (blocker #7) — critical path

Policy: `config/production_holdout_policy.yaml`  
Freeze builder: `evaluation/untouched_holdout.py`  
Readiness gate: `config/production_readiness_gate.yaml` (≥1000 docs / ≥3000 fields for promote)

### C1. Acquire independent corpus

- [ ] New source — **not** `dataset_raw/`, hackathon packs, or prior eval data
- [ ] Meet composition minima (CMS-1500 + UB-04, quality buckets, blocking fields)
- [ ] Independent ground truth labels (sealed from engineering during labeling)

### C2. Attest + freeze

- [ ] Fill `docs/templates/holdout_attestation.template.json` (all `never_*` true)
- [ ] Overlap-audit vs development hashes/sources
- [ ] Freeze with `UntouchedHoldoutBuilder.freeze(...)` → immutable manifest
- [ ] Store manifest path + `manifest_sha256` in evidence package
- [ ] Do **not** tune OCR/ROI/policy after unsealing

### C3. Run sealed evaluation

- [ ] Pin `extraction-v2` + `production_runtime_v1`
- [ ] Run extraction **before** joining labels (or seal predictions)
- [ ] Score vs truth; fill readiness evidence fields (STP, HITL, FA=0, latency, cost)
- [ ] `python3 scripts/check_production_closeout.py` → must reach `PROMOTE_TO_PRODUCTION` gates for metrics portion

### C4. Shadow + canary

- [ ] Promote eligible routes to SHADOW; collect runtime shadow samples
- [ ] Canary limited live traffic; monitor false-accept + HITL
- [ ] Signed promotion decision in launch record

---

## Phase D — Sign and authorize

- [ ] Complete `docs/templates/PRODUCTION_LAUNCH_RECORD.md`
- [ ] Complete machine evidence JSON (all org + metric fields)
- [ ] `python3 scripts/check_production_closeout.py` exits **0** with decision `PROMOTE_TO_PRODUCTION`
- [ ] Accountable owner signs launch record
- [ ] Only then label the environment **production-authorized**

Until Phase D completes, status remains **production-hardened, not production-authorized**.
