#!/usr/bin/env python3
"""Wait for HITL-16 redecide to finish, then run Independent-100 fresh."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HITL_DIR = ROOT / "evaluation_results/hackathon_100_independent_v13_hitl_redecide"
OUT = ROOT / "evaluation_results/hackathon_100_independent_v13b"
METRICS_HITL = ROOT / "docs/metrics/hackathon_100_independent_v13_hitl_redecide.json"
METRICS_N100 = ROOT / "docs/metrics/hackathon_100_independent_v13b.json"


def _env() -> dict[str, str]:
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
    return env


def wait_hitl(timeout_sec: int = 3600) -> list[dict]:
    summary = HITL_DIR / "summary.json"
    ledger = HITL_DIR / "results.jsonl"
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        if summary.exists() and ledger.exists():
            rows = [
                json.loads(l)
                for l in ledger.read_text().splitlines()
                if l.strip()
            ]
            if len(rows) >= 16:
                return rows
        time.sleep(15)
        n = 0
        if ledger.exists():
            n = sum(1 for l in ledger.read_text().splitlines() if l.strip())
        print(f"wait_hitl progress={n}/16", flush=True)
    raise SystemExit("HITL redecide timeout")


def write_hitl_metrics(rows: list[dict]) -> dict:
    import statistics
    from datetime import datetime, timezone

    stp = [r for r in rows if r.get("true_stp")]
    hitl = [r for r in rows if not r.get("true_stp")]
    elaps = [
        float(r["elapsed_sec"])
        for r in rows
        if isinstance(r.get("elapsed_sec"), (int, float))
    ]
    metrics = {
        "cohort": "hackathon_100_independent_v13_hitl_redecide",
        "n": len(rows),
        "true_stp": len(stp),
        "true_stp_rate": round(len(stp) / max(len(rows), 1), 4),
        "still_hitl": len(hitl),
        "flipped_to_stp": len(stp),
        "projected_n100_if_merge": 84 - len(hitl) + 0,  # 84 prior STP; hitl were all non-STP
        "note": "Prior Independent-100 had 84 STP + 16 HITL; flipped replace HITL.",
        "still_hitl_ids": [r.get("document") for r in hitl],
        "flipped_ids": [r.get("document") for r in stp],
        "median_elapsed_sec": round(statistics.median(elaps), 2) if elaps else None,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    # projected: 84 - (16 - flipped) = 84 - still_hitl = 68 + flipped... 
    # Actually: final = (100-16) + flipped = 84 + flipped
    metrics["projected_n100_stp"] = 84 + len(stp)
    metrics["projected_n100_rate"] = round((84 + len(stp)) / 100, 4)
    METRICS_HITL.parent.mkdir(parents=True, exist_ok=True)
    METRICS_HITL.write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2), flush=True)
    return metrics


def run_n100() -> int:
    if OUT.exists():
        import shutil

        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    cmd = [
        sys.executable,
        str(ROOT / "scripts/run_hackathon_1000_cascade.py"),
        "--out-dir",
        str(OUT),
        "--offset",
        "50",
        "--limit",
        "100",
        "--workers",
        "1",
        "--no-resume",
    ]
    print(f"starting Independent-100 → {OUT}", flush=True)
    return subprocess.call(cmd, cwd=str(ROOT), env=_env())


def main() -> int:
    print("waiting for HITL-16 redecide…", flush=True)
    rows = wait_hitl()
    write_hitl_metrics(rows)
    return run_n100()


if __name__ == "__main__":
    raise SystemExit(main())
