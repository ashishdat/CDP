# deploy/helm

One values-driven Helm chart per deployable that actually has a running
entrypoint today:

- `ingestion-api/` — FastAPI app (Deployment + Service + ConfigMap)
- `human-review-api/` — FastAPI app + server-rendered UI (Deployment + Service + ConfigMap)
- `document-preparation-worker/` — Kafka consumer, no Service (Deployment + ConfigMap; see `deploy/keda`)

Each chart pulls secrets (DB URL, object-store credentials, Kafka
bootstrap servers) from a pre-existing `Secret` named in `values.yaml`'s
`secretName` — never templated from `values.yaml` itself (see
docs/ARCHITECTURE.md "SECURITY").

Validated with a real `helm` binary (v3.15.4, downloaded for this
session — no live cluster available):

```
helm lint deploy/helm/<chart>
helm template <release-name> deploy/helm/<chart>
```

All three charts pass both. Not validated: `helm install` against a real
cluster (none available), or the KEDA `ScaledObject`s in `deploy/keda`
against the actual KEDA CRD schema (KEDA isn't installed anywhere
reachable from this environment either — see that directory's README for
which ScaledObjects target a Deployment defined here vs. one that doesn't
exist yet).

Remaining workers (`page_detection`, `standard_form_extraction`,
`unstructured_extraction`, `validation`, `retry`, `vlm_fallback`,
`output_generation`) have complete, tested library code but no
`consumer.py` wiring them to a Kafka topic as a standalone process yet —
see docs/IMPLEMENTATION_PLAN.md. Charts for them would follow the exact
same pattern as `document-preparation-worker/` once that wiring exists.
