# deploy/helm

One values-driven Helm chart per deployable that has a running entrypoint:

- `ingestion-api/` — FastAPI app (Deployment + Service + ConfigMap)
- `human-review-api/` — FastAPI app + server-rendered UI (Deployment + Service + ConfigMap)
- `output-api/` — FastAPI app for NSF/UB92/canonical artifact retrieval (Deployment + Service + ConfigMap)
- `document-preparation-worker/` — Kafka consumer, no Service (Deployment + ConfigMap; see `deploy/keda`)
- `cdp-worker-pools/` — pooled worker Deployments + KEDA ScaledObjects for the remaining consumers

Each chart pulls secrets (DB URL, object-store credentials, Kafka
bootstrap servers) from a pre-existing `Secret` named in `values.yaml`'s
`secretName` — never templated from `values.yaml` itself (see
docs/ARCHITECTURE.md "SECURITY").

Production charts pin fail-closed defaults:

```
CDP_ENV=production
CDP_PIPELINE_RELEASE=extraction-v2
CDP_RUNTIME_PROFILE=config/runtime_profiles/production_runtime_v1.yaml
```

API readiness probes use `/ready` (DB + object store initialized); liveness
uses `/health`. See `docs/PRODUCTION_OPERATOR_RUNBOOK.md`.

Validated with a real `helm` binary:

```
helm lint deploy/helm/<chart>
helm template <release-name> deploy/helm/<chart>
```

Not validated: `helm install` against a live cluster, or KEDA ScaledObjects
against an installed KEDA CRD schema (see `deploy/keda` README).

Until holdout / IdP / BAA gates close, deploy status remains
**production-hardened, not production-authorized**.
