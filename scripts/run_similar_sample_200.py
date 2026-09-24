#!/usr/bin/env python3
"""Run product-gate test on 200 stratified docs from Hackathon Drive zip."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "evaluation_results/similar_sample_200_v1/selected_documents.txt"
OUT = ROOT / "evaluation_results/similar_sample_200_v1"
ZIP = ROOT / "data/Hackathon - 1000 Claims.zip"

def main() -> int:
    docs = [ln.strip() for ln in DOCS.read_text().splitlines() if ln.strip()]
    assert len(docs) == 200, len(docs)
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-u", str(ROOT / "scripts/run_hackathon_1000_cascade.py"),
        "--zip", str(ZIP),
        "--out-dir", str(OUT),
        "--documents", ",".join(docs),
        "--workers", "2",
        "--no-resume" if "--fresh" in sys.argv else "--resume",
    ]
    # Always resume by default for crash safety
    if "--fresh" not in sys.argv:
        cmd = [c for c in cmd if c != "--no-resume"]
        if "--resume" not in cmd:
            cmd.append("--resume")
    print("Running:", " ".join(cmd[:8]), f"... ({len(docs)} docs)", flush=True)
    return subprocess.call(cmd)

if __name__ == "__main__":
    raise SystemExit(main())
