#!/usr/bin/env python3
"""Run product-gate test on 1000 full-corpus docs from Hackathon Drive zip.

Speed profile (default): workers=1, cloud/VLM/TrOCR/learned-matcher off,
local OCR + unstructured DI heuristics only — targets ~tip latency (~30s/doc)
instead of the multi-worker lock + residual path that ballooned to ~5min/doc.

Usage:
  python3 -u scripts/run_similar_sample_200.py           # fast resume
  python3 -u scripts/run_similar_sample_200.py --seed-tip  # copy tip results (seconds)
  python3 -u scripts/run_similar_sample_200.py --full      # product residuals on
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/metrics/similar_sample_1000_v1/selected_documents.txt"
OUT = ROOT / "evaluation_results/similar_sample_1000_v1"
ZIP = ROOT / "data/Hackathon - 1000 Claims.zip"
TIP_ROOTS = (
    ROOT / "evaluation_results/hackathon_600_independent_v13c",
    ROOT / "evaluation_results/hackathon_400_remainder_independent_v13c",
)

# Fast sample profile — kill network/torch residuals that dominate wall clock.
FAST_ENV = {
    "CDP_CASCADE_RESPECT_ENV": "1",  # honor these over cascade product stamp
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
    "CDP_OCR_LOCK": "0",  # single worker — no cross-claim flock needed
    "CDP_OCR_WORKER_POOL": "1",
    "CDP_APP_WORKER_POOL": "1",
    "CDP_UNSTRUCTURED_REG_FALLBACK": "1",
    "CDP_UNSTRUCTURED_REG_AGENT": "0",
}


def _load_docs() -> list[str]:
    docs = [ln.strip() for ln in DOCS.read_text().splitlines() if ln.strip()]
    assert len(docs) == 1000, len(docs)
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
    # Replace ledger with seeded tip rows for the 200 (deterministic).
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
    print(json.dumps(meta, indent=2), flush=True)
    return 0 if not missing else 1


def main() -> int:
    docs = _load_docs()
    OUT.mkdir(parents=True, exist_ok=True)
    argv = set(sys.argv[1:])

    if "--seed-tip" in argv:
        return _seed_from_tip(docs)

    workers = "1"
    if "--workers" in sys.argv:
        i = sys.argv.index("--workers")
        if i + 1 < len(sys.argv):
            workers = sys.argv[i + 1]

    env = dict(os.environ)
    if "--full" not in argv:
        env.update(FAST_ENV)
        print("profile=FAST (local OCR; cloud/VLM/TrOCR/matcher off)", flush=True)
    else:
        print("profile=FULL (product residuals on)", flush=True)

    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "scripts/run_hackathon_1000_cascade.py"),
        "--zip",
        str(ZIP),
        "--out-dir",
        str(OUT),
        "--documents",
        ",".join(docs),
        "--workers",
        workers,
        "--resume",
    ]
    print(
        f"Running workers={workers} docs={len(docs)} out={OUT}",
        flush=True,
    )
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
