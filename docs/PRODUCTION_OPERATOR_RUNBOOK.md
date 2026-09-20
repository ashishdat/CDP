# Production operator runbook

Status: **production-hardened configuration**, not **production-authorized PHI**.
Hackathon STP (locked-50 decide 44/50, blind-50 cascade 94%) is an evaluation
proxy — it does not close holdout / IdP / BAA gates in
`docs/PRODUCTION_READINESS.md`.

## What “ready” means in this repo

| Layer | Ready when |
|---|---|
| Code / config pin | `production_runtime_v1` hashes verify; fail-closed settings enforce; CI green |
| Compose / Helm | Images build; `/health` + `/ready` respond; APIs + workers call `assert_production_ready`; Helm charts for ingestion / human-review / output |
| Authorized PHI | Holdout, IdP/RBAC, migrations drill, BAA/region, signed promotion |

## Quick start (staging / hardened local)

```bash
cp .env.example .env
# Inject secrets via your secret manager — never commit .env

export CDP_ENV=production
export CDP_PIPELINE_RELEASE=extraction-v2
export CDP_RUNTIME_PROFILE=config/runtime_profiles/production_runtime_v1.yaml

# Required for CDP_ENV=production (fail-closed):
# DATABASE_URL=postgresql+psycopg://...
# OBJECT_STORE_ACCESS_KEY / OBJECT_STORE_SECRET_KEY  (not minioadmin)
# USE_IN_MEMORY_BUS=false
# AZURE_*_REVIEW_ONLY=true until route promotion
# AI_GATEWAY_ENABLED=false unless PHI approved

docker compose up -d
python3 scripts/smoke_production_fail_closed.py
```

Health endpoints:

| Service | Liveness | Readiness |
|---|---|---|
| Ingestion API `:8000` | `/health` | `/ready` |
| Human review API `:8001` | `/health` | `/ready` |
| Output API `:8002` | `/health` | `/ready` |

## Release pin

Production must use the **FROZEN** release:

```bash
export CDP_PIPELINE_RELEASE=extraction-v2
# or CDP_RELEASE_MANIFEST=config/releases/extraction-v2.yaml
```

`extraction-v3` is **CANDIDATE** — do not pin in production until holdout promotion.

Runtime decision evidence hashes:

```bash
python3 -c "from packages.production_runtime import load_production_runtime_profile; print(load_production_runtime_profile()[0].profile_id)"
```

## External AI (fail-closed)

Defaults keep Azure OpenAI / Document Intelligence **off or REVIEW_ONLY**.
Enabling DI requires all of:

- `AZURE_DOCUMENT_INTELLIGENCE_AUTHORIZED=true`
- `AZURE_DOCUMENT_INTELLIGENCE_REGION_APPROVED=true`
- `AZURE_DOCUMENT_INTELLIGENCE_PHI_CONTRACT_APPROVED=true`
- `AZURE_DOCUMENT_INTELLIGENCE_REVIEW_ONLY=true` until route promotion

AI gateway requires `AI_PHI_EXTERNAL_PROCESSING_APPROVED=true` plus budget/region.

## Identity Lane C (optional STP unlock)

For residual identity HITL only:

```bash
export CDP_AUTHORIZED_MEMBER_INDEX=/secure/path/authorized_member_index.json
```

See `docs/reference/AUTHORIZED_MEMBER_INDEX_OPERATOR_FILL.md`. Never fill from OCR labels.

## Qualification / promotion

```bash
python3 scripts/qualify_vnext.py          # exits non-zero unless PROMOTABLE
python3 scripts/smoke_production_fail_closed.py
pytest tests/unit/cases/test_production_runtime.py \
       tests/unit/cases/test_production_readiness_gate.py -q
```

Until holdout + security gates pass, the correct launch label remains
**production-hardened, not production-authorized**.
