#!/usr/bin/env python3
"""FAST cascade on 200 stratified docs from Hackathon-5000 Drive zip."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/metrics/hackathon5000_sample_200_v1/selected_documents.txt"
OUT = ROOT / "evaluation_results/hackathon5000_sample_200_v1"
ZIP = ROOT / "data/Hackathon - 5000 Claims.zip"
DATASET = ROOT / "dataset_hackathon_5000.yaml"

FAST_ENV = {
    "CDP_CASCADE_RESPECT_ENV": "1",
    "CDP_HACKATHON_ZIP": str(ZIP),
    "CDP_GPT4O_CROP_RESIDUAL": "0",
    "CDP_GPT4O_CROP_ACCEPT": "0",
    "CDP_GPT4O_EMPTY_FINANCE": "0",
    "CDP_CONFLICT_AGENT": "0",
    "CDP_AZURE_DI_CHARGE_RESIDUAL": "0",
    "CDP_AZURE_DI_CHARGE_CORROBORATE": "0",
    "CDP_AZURE_DI_CHARGE_ACCEPT": "0",
    "CDP_TROCR_DOB_RESIDUAL": "0",
    "CDP_LEARNED_MATCHER": "0",
    "CDP_VLM_CROP_TIMEOUT_SECONDS": "8",
    "CDP_DOC_LATENCY_BUDGET": "1",
    "CDP_DOC_BUDGET_SOFT_SEC": "12",
    "CDP_DOC_BUDGET_HARD_SEC": "18",
    "CDP_OCR_LOCK": "0",
    "CDP_OCR_WORKER_POOL": "1",
    "CDP_APP_WORKER_POOL": "1",
    "CDP_UNSTRUCTURED_REG_FALLBACK": "1",
    "CDP_UNSTRUCTURED_REG_AGENT": "0",
}


def main() -> int:
    docs = [ln.strip() for ln in DOCS.read_text().splitlines() if ln.strip()]
    assert len(docs) == 200, len(docs)
    assert ZIP.is_file(), ZIP
    assert DATASET.is_file(), DATASET
    OUT.mkdir(parents=True, exist_ok=True)
    if "--fresh" in sys.argv:
        ledger = OUT / "results.jsonl"
        if ledger.exists():
            ledger.unlink()
        claims = OUT / "claims"
        if claims.exists():
            shutil.rmtree(claims)
        print("cleared prior ledger/claims", flush=True)

    env = dict(os.environ)
    if "--full" not in sys.argv:
        env.update(FAST_ENV)
        print("profile=FAST", flush=True)
    else:
        env["CDP_HACKATHON_ZIP"] = str(ZIP)
        print("profile=FULL", flush=True)

    workers = "1"
    if "--workers" in sys.argv:
        i = sys.argv.index("--workers")
        workers = sys.argv[i + 1]

    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "scripts/run_hackathon_1000_cascade.py"),
        "--zip",
        str(ZIP),
        "--dataset",
        str(DATASET),
        "--out-dir",
        str(OUT),
        "--documents",
        ",".join(docs),
        "--workers",
        workers,
        "--resume",
    ]
    print(f"Running workers={workers} docs={len(docs)} dataset={DATASET.name}", flush=True)
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
