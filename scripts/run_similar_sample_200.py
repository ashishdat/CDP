#!/usr/bin/env python3
"""Run product-gate test on 200 stratified docs from Hackathon Drive zip.

Profiles (permanent — see docs/PRODUCT_RUN_PROFILE_AND_CORPUS_BINDING_V1.md):
  FAST (default)  — latency only; NOT product-gate eligible
  --product/--full — PRODUCT residuals; gate eligible
  --seed-tip       — TIP_SEED; gate only with --allow-tip-seed

Usage:
  python3 -u scripts/run_similar_sample_200.py           # fast resume
  python3 -u scripts/run_similar_sample_200.py --seed-tip
  python3 -u scripts/run_similar_sample_200.py --product
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.corpus_binding import CorpusBindingError, bind_corpus, write_corpus_binding
from packages.run_profiles import apply_profile_env, write_run_manifest

DOCS = ROOT / "docs/metrics/similar_sample_200_v1/selected_documents.txt"
OUT = ROOT / "evaluation_results/similar_sample_200_v1"
ZIP = ROOT / "data/Hackathon - 1000 Claims.zip"
DATASET = ROOT / "dataset.yaml"
TIP_ROOTS = (
    ROOT / "evaluation_results/hackathon_600_independent_v13c",
    ROOT / "evaluation_results/hackathon_400_remainder_independent_v13c",
)


def _load_docs() -> list[str]:
    docs = [ln.strip() for ln in DOCS.read_text().splitlines() if ln.strip()]
    assert len(docs) == 200, len(docs)
    return docs


def _seed_from_tip(docs: list[str]) -> int:
    """Copy tip ledger rows + claim dirs so the 200-gate finishes in seconds."""
    OUT.mkdir(parents=True, exist_ok=True)
    by_doc: dict[str, dict] = {}
    by_cid: dict[str, dict] = {}
    for tip in TIP_ROOTS:
        ledger = tip / "results.jsonl"
        if not ledger.is_file():
            continue
        for line in ledger.open(encoding="utf-8"):
            row = json.loads(line)
            doc = str(row.get("document") or "")
            cid = str(row.get("claim_id") or "")
            if doc:
                by_doc[doc] = row
            if cid:
                by_cid[cid] = row

    claims_out = OUT / "claims"
    claims_out.mkdir(parents=True, exist_ok=True)
    ledger_path = OUT / "results.jsonl"
    written = 0
    missing: list[str] = []
    with ledger_path.open("w", encoding="utf-8") as handle:
        for doc in docs:
            cid = doc.replace("/", "__")
            row = by_doc.get(doc) or by_cid.get(cid)
            if row is None:
                missing.append(doc)
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
            src = None
            for tip in TIP_ROOTS:
                cand = tip / "claims" / cid
                if cand.is_dir():
                    src = cand
                    break
            dst = claims_out / cid
            if src is not None and not dst.exists():
                try:
                    os.symlink(src.resolve(), dst)
                except OSError:
                    shutil.copytree(src, dst, dirs_exist_ok=True)
    meta = {
        "seeded": written,
        "missing": missing,
        "source": [str(p) for p in TIP_ROOTS],
    }
    (OUT / "seed_tip_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    write_run_manifest(
        OUT,
        profile="TIP_SEED",
        dataset_id="DEVELOPMENT_DATASET_V1",
        extra={"seed_tip_meta": meta},
    )
    print(json.dumps(meta, indent=2), flush=True)
    print(
        "profile=TIP_SEED — product gate requires --allow-tip-seed "
        "(not valid for a new Drive corpus without tip)",
        flush=True,
    )
    return 0 if not missing else 1


def main() -> int:
    docs = _load_docs()
    OUT.mkdir(parents=True, exist_ok=True)
    argv = set(sys.argv[1:])

    if "--seed-tip" in argv:
        return _seed_from_tip(docs)

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

    workers = "1"
    if "--workers" in sys.argv:
        i = sys.argv.index("--workers")
        if i + 1 < len(sys.argv):
            workers = sys.argv[i + 1]

    product = "--full" in argv or "--product" in argv
    profile_name = "PRODUCT" if product else "FAST"
    env, profile = apply_profile_env(profile_name, dict(os.environ))
    env["CDP_HACKATHON_ZIP"] = str(ZIP)
    write_run_manifest(
        OUT,
        profile=profile.name,
        dataset_id=binding.dataset_id,
        extra={"runner": "run_similar_sample_200", "docs": len(docs)},
    )
    if profile.name == "FAST":
        print(
            "profile=FAST — NOT product-gate eligible (use --product for STP gate)",
            flush=True,
        )
    else:
        print("profile=PRODUCT — residuals on; product-gate eligible", flush=True)

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
        f"Running workers={workers} docs={len(docs)} out={OUT} profile={profile.name}",
        flush=True,
    )
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
