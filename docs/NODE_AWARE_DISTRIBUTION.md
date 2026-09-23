# Node-aware work distribution

## Goal

Given **N nodes**, automatically split claim load so each node processes ~`pending/N`
claims with no manual `offset/limit` sharding.

## How it works

1. **Topology** — `CDP_NODE_COUNT` + `CDP_NODE_INDEX` (or `--nodes` / `--node-index`).
   StatefulSet ordinals and `HOSTNAME` endings like `pod-2` are auto-detected.
2. **Sharding** — `sha256(claim_id) % N` (stable). Scaling N reassigns only the
   affected fraction of keys; same N → same assignment forever.
3. **Local workers** — `--auto-workers` / `CDP_AUTO_WORKERS=1` sizes per-node
   concurrency from CPUs, pending, and fleet size (more nodes → less local fan-out).

## Cascade usage

```bash
# 3-node fleet — run once per node with its index
export CDP_NODE_COUNT=3 CDP_AUTO_WORKERS=1
python3 -m scripts.run_hackathon_1000_cascade \
  --out-dir evaluation_results/fleet_demo \
  --offset 50 --limit 600 \
  --nodes 3 --node-index 0 --auto-workers --resume

# Preview plan without running OCR
python3 -m scripts.plan_node_distribution --count 600 --nodes 4 --auto-workers
```

Plan artifact: `<out-dir>/work_distribution_plan.json` (also shown in the Ops UI **Scale** tab).

## Production note

Live traffic already scales via Kafka consumer groups + KEDA lag
(`deploy/helm/cdp-worker-pools`). This package covers **offline cascade / batch**
horizontal scale. Example StatefulSet: `deploy/helm/cdp-cascade-fleet/statefulset-example.yaml`.
