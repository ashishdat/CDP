#!/usr/bin/env python3
"""Redecide Independent-100 v13b remaining 10 HITLs after L1–L5 unlocks."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "docs/metrics/hackathon_100_independent_v13b.json"
OUT = ROOT / "evaluation_results/hackathon_100_independent_v13b_hitl10_redecide2"


def main() -> int:
    ids = json.loads(METRICS.read_text())["hitl_claim_ids"]
    OUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for k in (
        "CDP_CASCADE_RESPECT_ENV",
        "CDP_TROCR_DOB_RESIDUAL",
        "CDP_GPT4O_CROP_RESIDUAL",
        "CDP_AZURE_DI_CHARGE_RESIDUAL",
        "CDP_LEARNED_MATCHER",
        "CDP_CONFLICT_AGENT",
        "CDP_OCR_SERVICE_LINE_DUAL",
        "CDP_OCR_CHARGE_WINDOWS",
        "CDP_OCR_CRITICAL_EXCLUDE",
    ):
        env.pop(k, None)
    env.update(
        {
            "CDP_DOC_LATENCY_BUDGET": "1",
            "CDP_DOC_BUDGET_SOFT_SEC": "18",
            "CDP_DOC_BUDGET_HARD_SEC": "22",
            "CDP_CLOUD_STOP_LADDER": "1",
            "CDP_ACCURACY_FIRST_LLM": "1",
            "CDP_AZURE_DI_CHARGE_RESIDUAL": "1",
            "CDP_AZURE_DI_CHARGE_ACCEPT": "1",
            "CDP_AZURE_DI_CHARGE_CORROBORATE": "1",
            "CDP_GPT4O_CROP_RESIDUAL": "1",
            "CDP_GPT4O_CROP_ACCEPT": "1",
            "CDP_CONFLICT_AGENT": "1",
        }
    )
    cmd = [
        sys.executable,
        str(ROOT / "scripts/reprocess_failed_cascade_claims.py"),
        "--out-dir",
        str(OUT),
        "--workers",
        "1",
        "--claims",
        *ids,
    ]
    print(f"redecide hitl10 n={len(ids)} out={OUT}", flush=True)
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
