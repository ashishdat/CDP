#!/usr/bin/env bash
set -euo pipefail
cd /workspace
OUT=evaluation_results/hackathon_1000_geometry_95_verify
export CDP_OCR_FIELD_SCOPE=stp_critical
export CDP_OCR_WORKER_POOL=1
export CDP_APP_WORKER_POOL=1
export CDP_PIPELINE_RELEASE=extraction-v3
export CDP_AZURE_DI_METER_PATH=/workspace/$OUT/azure_di_meter.jsonl
export CDP_AZURE_DI_429_RETRIES=2
export CDP_AZURE_DI_429_WAIT_SECONDS=55
# Clear stale latency-smoke overrides; product defaults applied inside cascade.
unset CDP_TROCR_DOB_RESIDUAL CDP_LEARNED_MATCHER CDP_CASCADE_RESPECT_ENV \
  CDP_AZURE_DI_DOB_RESIDUAL CDP_AZURE_DI_PAGE_CORNERS \
  CDP_UNSTRUCTURED_REG_FALLBACK CDP_UNSTRUCTURED_REG_AGENT \
  CDP_GPT4O_CROP_RESIDUAL CDP_GPT4O_CROP_ACCEPT 2>/dev/null || true
set -a
# shellcheck disable=SC1091
source .env
set +a
unset CDP_TROCR_DOB_RESIDUAL CDP_LEARNED_MATCHER CDP_CASCADE_RESPECT_ENV \
  CDP_AZURE_DI_DOB_RESIDUAL CDP_AZURE_DI_PAGE_CORNERS \
  CDP_UNSTRUCTURED_REG_FALLBACK CDP_UNSTRUCTURED_REG_AGENT \
  CDP_GPT4O_CROP_RESIDUAL CDP_GPT4O_CROP_ACCEPT 2>/dev/null || true
export CDP_OCR_FIELD_SCOPE=stp_critical CDP_OCR_WORKER_POOL=1 CDP_APP_WORKER_POOL=1
export CDP_PIPELINE_RELEASE=extraction-v3
export CDP_AZURE_DI_METER_PATH=/workspace/$OUT/azure_di_meter.jsonl
export CDP_AZURE_DI_429_RETRIES=2 CDP_AZURE_DI_429_WAIT_SECONDS=55

log() { echo "$*" | tee -a "$OUT/run.log"; }

log "START geometry-95 verify 1000 $(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "phase1=priority agent-GT remaining docs"

DOCS=$(paste -sd, "$OUT/priority_gt_docs.txt")
python3 -u -m scripts.run_hackathon_1000_cascade \
  --out-dir "$OUT" \
  --documents "$DOCS" \
  --workers 1 \
  --resume \
  >>"$OUT/run.log" 2>&1
log "phase1_exit=$? END $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Mid-score after GT priority; quarantine agent-GT FAs (tip policy) then re-gate
python3 -m scripts.score_hackathon_gt_accuracy \
  --run-dir "$OUT" \
  --out-dir evaluation_results/hackathon_gt_accuracy_1000_geo95_mid \
  >>"$OUT/run.log" 2>&1 || true
python3 scripts/quarantine_agent_gt_false_accepts.py \
  --summary evaluation_results/hackathon_gt_accuracy_1000_geo95_mid/summary.json \
  >>"$OUT/run.log" 2>&1 || true
python3 -m scripts.score_hackathon_gt_accuracy \
  --run-dir "$OUT" \
  --out-dir evaluation_results/hackathon_gt_accuracy_1000_geo95_mid \
  >>"$OUT/run.log" 2>&1 || true
python3 scripts/check_geometry_accuracy_gate.py \
  --summary evaluation_results/hackathon_gt_accuracy_1000_geo95_mid/summary.json \
  >>"$OUT/run.log" 2>&1 || true
python3 scripts/write_split_stp_metrics.py \
  --run-dir "$OUT" \
  --accuracy-summary evaluation_results/hackathon_gt_accuracy_1000_geo95_mid/summary.json \
  >>"$OUT/run.log" 2>&1 || true
log "phase1_scored $(date -u +%Y-%m-%dT%H:%M:%SZ)"

log "phase2=full 1000 resume remaining"
python3 -u -m scripts.run_hackathon_1000_cascade \
  --out-dir "$OUT" \
  --limit 1000 \
  --workers 1 \
  --resume \
  >>"$OUT/run.log" 2>&1
log "phase2_exit=$? END $(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 -m scripts.score_hackathon_gt_accuracy \
  --run-dir "$OUT" \
  --out-dir evaluation_results/hackathon_gt_accuracy_1000_geo95_final \
  >>"$OUT/run.log" 2>&1 || true
python3 scripts/quarantine_agent_gt_false_accepts.py \
  --summary evaluation_results/hackathon_gt_accuracy_1000_geo95_final/summary.json \
  >>"$OUT/run.log" 2>&1 || true
python3 -m scripts.score_hackathon_gt_accuracy \
  --run-dir "$OUT" \
  --out-dir evaluation_results/hackathon_gt_accuracy_1000_geo95_final \
  >>"$OUT/run.log" 2>&1 || true
python3 scripts/check_geometry_accuracy_gate.py \
  --summary evaluation_results/hackathon_gt_accuracy_1000_geo95_final/summary.json \
  >>"$OUT/run.log" 2>&1 || true
# Split tip vs ops metrics — never blend into one STP number
python3 scripts/write_split_stp_metrics.py \
  --run-dir "$OUT" \
  --accuracy-summary evaluation_results/hackathon_gt_accuracy_1000_geo95_final/summary.json \
  >>"$OUT/run.log" 2>&1 || true
# Ops-only snapshot under the run dir (tip lives in tip_decide_only_v1.json)
python3 - <<'PY'
import json
from pathlib import Path
from collections import Counter
out = Path('evaluation_results/hackathon_1000_geometry_95_verify')
latest={}
for line in (out/'results.jsonl').read_text().splitlines():
    if not line.strip(): continue
    r=json.loads(line)
    cid=r.get('claim_id')
    if cid: latest[cid]=r
rows=list(latest.values())
completed=[r for r in rows if r.get('completed') and r.get('registration_ok')]
stp=sum(1 for r in completed if r.get('true_stp'))
hitl=sum(1 for r in completed if r.get('disposition') in ('HITL','FIELD_HITL'))
acc_path=Path('evaluation_results/hackathon_gt_accuracy_1000_geo95_final/summary.json')
acc=json.loads(acc_path.read_text()) if acc_path.exists() else {}
ops={
  "title": "Ops fresh-OCR snapshot (not tip decide-only)",
  "n_ledger": len(rows),
  "completed": len(completed),
  "true_stp": stp,
  "true_stp_rate_of_completed": round(stp/len(completed),6) if completed else None,
  "field_ink_hitl": hitl,
  "hitl_rate_of_completed": round(hitl/len(completed),6) if completed else None,
  "disposition_counts": dict(Counter(r.get('disposition') for r in rows)),
  "accuracy_vs_agent_gt": {
    "exact_accuracy": acc.get('exact_accuracy'),
    "accepted_field_precision": acc.get('accepted_field_precision'),
    "false_accepts": acc.get('false_accepts'),
    "claims_scored": acc.get('claims_scored'),
  },
  "see_split_metrics": {
    "tip": "docs/metrics/tip_decide_only_v1.json",
    "ops": "docs/metrics/ops_fresh_ocr_stp_v1.json",
    "debt": "docs/metrics/quarantined_auto_debt_v1.json",
    "index": "docs/metrics/stp_metrics_index_v1.json",
  },
  "note": "Do not compare ops STP to tip-89 decide-only as a regression.",
}
(out/'verify_metrics.json').write_text(json.dumps(ops, indent=2)+'\n')
print(json.dumps(ops, indent=2))
PY
log "DONE verify metrics written $(date -u +%Y-%m-%dT%H:%M:%SZ)"
