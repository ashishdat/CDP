#!/usr/bin/env python3
"""Hackathon-5000 full corpus (5000) — PRODUCT STP / accuracy / HITL latency.

Binds dataset_hackathon_5000.yaml to the Drive zip. Document list is the
disjoint union of sample_2000_v1 + remainder_3000_v1.

Usage:
  python3 -u scripts/run_hackathon5000_all.py --product --workers 4
  python3 -u scripts/run_hackathon5000_all.py --product --fresh --workers 4
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.corpus_binding import CorpusBindingError, bind_corpus, write_corpus_binding
from packages.run_profiles import apply_profile_env, write_run_manifest

DOCS = ROOT / "docs/metrics/hackathon5000_all_v1/selected_documents.txt"
OUT = ROOT / "evaluation_results/hackathon5000_all_v1"
ZIP = ROOT / "data/Hackathon - 5000 Claims.zip"
DATASET = ROOT / "dataset_hackathon_5000.yaml"


def main() -> int:
    docs = [ln.strip() for ln in DOCS.read_text().splitlines() if ln.strip()]
    assert len(docs) == 5000, len(docs)
    assert ZIP.is_file(), ZIP
    assert DATASET.is_file(), DATASET
    OUT.mkdir(parents=True, exist_ok=True)

    argv = set(sys.argv[1:])
    product = "--full" in argv or "--product" in argv
    profile_name = "PRODUCT" if product else "FAST"

    try:
        binding = bind_corpus(
            dataset_yaml=DATASET,
            zip_path=ZIP,
            documents=docs,
            require_documents=True,
        )
    except CorpusBindingError as exc:
        print(f"ERROR: corpus binding failed: {exc}", flush=True)
        return 2
    write_corpus_binding(OUT, binding)

    if "--fresh" in argv:
        ledger = OUT / "results.jsonl"
        if ledger.exists():
            ledger.unlink()
        claims = OUT / "claims"
        if claims.exists():
            shutil.rmtree(claims)
        print("cleared prior ledger/claims", flush=True)

    env, profile = apply_profile_env(profile_name, dict(os.environ))
    env["CDP_HACKATHON_ZIP"] = str(ZIP)
    env["CDP_AZURE_DI_METER_PATH"] = str(OUT / "azure_di_meter.jsonl")
    env["CDP_VLM_TOKEN_METER_PATH"] = str(OUT / "vlm_token_meter.jsonl")
    env.setdefault("CDP_UNSTRUCTURED_FIRST", "1")
    env.setdefault("CDP_APP_POOL_TIMEOUT_SECONDS", "20")
    env.setdefault("CDP_UNSTRUCTURED_DI_TIMEOUT_SECONDS", "90")
    env.setdefault("CDP_OCR_POOL_TIMEOUT_SECONDS", "300")
    write_run_manifest(
        OUT,
        profile=profile.name,
        dataset_id=binding.dataset_id,
        extra={
            "runner": "run_hackathon5000_all",
            "docs": len(docs),
            "selection": "sample_2000_v1 + remainder_3000_v1",
            "unstructured_first": env.get("CDP_UNSTRUCTURED_FIRST"),
            "metrics": ["stp", "accuracy_vs_shared_gt", "hitl_latency"],
        },
    )
    if profile.name != "PRODUCT":
        print(
            "profile=FAST — NOT product-gate eligible "
            "(re-run with --product for STP scoring)",
            flush=True,
        )
    else:
        print("profile=PRODUCT — residuals on; product-gate eligible", flush=True)

    # 15 GiB hosts: 2 claim workers + 1 OCR pool (~3.5–4 GiB) stays under OOM.
    # Raise to 3/2 only when free RAM ≥ ~9 GiB (see sample_2000 runner notes).
    workers = "2"
    if "--workers" in sys.argv:
        i = sys.argv.index("--workers")
        workers = sys.argv[i + 1]
    env.setdefault("CDP_OCR_POOL_WORKERS", "1")

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
    print(
        f"Running workers={workers} ocr_pool={env.get('CDP_OCR_POOL_WORKERS')} "
        f"docs={len(docs)} dataset={DATASET.name} profile={profile.name} "
        f"unstructured_first={env.get('CDP_UNSTRUCTURED_FIRST')}",
        flush=True,
    )
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
