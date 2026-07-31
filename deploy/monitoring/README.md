# deploy/monitoring

- `prometheus.yml` — scrape config for local/dev (docker-compose hostnames).
  In Kubernetes, prefer the `prometheus.io/scrape` pod annotations already
  set in each Helm chart's `values.yaml` instead of this static file.
- `alert_rules.yml` — 6 alerts covering error rate, critical-field
  validation failures, straight-through rate, Kafka consumer lag, an
  unexpected-VLM-invocation tripwire (useful specifically because
  `VLM_ENABLED=false` by default — this firing at all in an environment
  where it should be off is itself the signal), and API availability.
- `grafana_dashboard.json` — 7 panels: intake rate, straight-through rate,
  OCR latency percentiles, validation failures by rule, the retry/VLM/
  human-review escalation funnel, estimated cost by extraction method, and
  Kafka consumer lag.

Both `.yml` files are YAML-syntax-validated
(`python -c "import yaml; yaml.safe_load(open(...))"`); the dashboard JSON
is JSON-syntax-validated. **Not validated**: PromQL expression correctness
(`promtool` isn't available in this environment) or actually loading the
dashboard into a running Grafana — both should be sanity-checked against a
live Prometheus/Grafana before relying on this in production.

`ingestion-api` and `human-review-api` expose `/metrics` today
(`packages.observability.REGISTRY` via `prometheus_client.generate_latest`).
`document-preparation-worker` has no HTTP server to scrape yet — see the
commented-out job in `prometheus.yml`.
