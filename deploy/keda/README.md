# deploy/keda

`ScaledObject`s keyed on Kafka consumer lag, one per worker pool (CPU
preprocessing, CPU OCR, GPU OCR/layout, VLM, output generation — see
docs/ARCHITECTURE.md and `packages/events/topics.py`).

| File | Pool | Targets a Deployment that exists today? |
|---|---|---|
| `document-preparation-worker-scaledobject.yaml` | CPU preprocessing | **Yes** — `deploy/helm/document-preparation-worker` |
| `standard-form-extraction-worker-scaledobject.yaml` | CPU OCR | No — worker library exists, no consumer entrypoint/chart yet |
| `unstructured-extraction-worker-scaledobject.yaml` | GPU OCR/layout | No — same as above |
| `vlm-fallback-worker-scaledobject.yaml` | VLM | No — same as above; `minReplicaCount: 0` matters most here since `VLM_ENABLED=false` by default |
| `output-generation-worker-scaledobject.yaml` | Output generation | No — same as above |

Structurally valid (`yaml.safe_load` + shape-checked) but not applied
against a real cluster or validated against the actual KEDA CRD schema —
no Kubernetes cluster or KEDA installation is available in this
environment. `bootstrapServers` assumes a `redpanda` Service in the
`idp-claims-platform` namespace; adjust for a real Kafka/MSK/Confluent
endpoint in higher environments.
