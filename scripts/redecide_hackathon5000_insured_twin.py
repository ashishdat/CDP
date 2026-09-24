#!/usr/bin/env python3
"""Decision-only redecide for Hackathon-5000 sample HITL (frozen extract).

Applies insured_name SAME/twin claim_decision unlocks without re-OCR.
Rewrites ledger rows in-place for flipped claims.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation_results" / "hackathon5000_sample_200_v1"


def _complete(extract: Path, final: Path) -> int:
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "scripts.complete_from_extraction",
            str(extract),
            str(final),
            "--document-family",
            "CMS1500",
        ],
        cwd=str(ROOT),
    )


def main() -> int:
    ledger = OUT / "results.jsonl"
    rows = [json.loads(line) for line in ledger.open(encoding="utf-8")]
    hitl = [r for r in rows if r.get("disposition") == "HITL"]
    print(f"redecide hitl={len(hitl)} out={OUT}", flush=True)
    flipped = 0
    still = 0
    for row in hitl:
        cid = row["claim_id"]
        claim = OUT / "claims" / cid
        extract = claim / "extract" / "ExtractionResult.json"
        if not extract.is_file():
            print(f"SKIP {cid} no extract", flush=True)
            still += 1
            continue
        final = claim / "final"
        if final.exists():
            shutil.rmtree(final)
        final.mkdir(parents=True, exist_ok=True)
        rc = _complete(extract, final)
        decision_path = final / "DecisionResult.json"
        if rc != 0 or not decision_path.is_file():
            print(f"FAIL {cid} rc={rc}", flush=True)
            still += 1
            continue
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        status = str(decision.get("claim_status") or "")
        review = bool(decision.get("review_required"))
        true_stp = status in {"STP_SAFE", "STP_STANDARD"} and not review
        new_disp = "TRUE_STP" if true_stp else "HITL"
        row["disposition"] = new_disp
        row["true_stp"] = true_stp
        row["completed"] = True
        row["review_required"] = review
        row["claim_status"] = status
        row["critical_blockers"] = decision.get("critical_blockers") or []
        row["redecide"] = "insured_name_same_twin_v1"
        # Refresh result.json
        (claim / "result.json").write_text(
            json.dumps(row, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"{'FLIP' if true_stp else 'HITL'} {cid} → {status} "
            f"blockers={row['critical_blockers']}",
            flush=True,
        )
        if true_stp:
            flipped += 1
        else:
            still += 1

    # Rewrite ledger with updated rows (latest by claim_id)
    by_id = {r["claim_id"]: r for r in rows}
    with ledger.open("w", encoding="utf-8") as handle:
        for row in by_id.values():
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    stp = sum(1 for r in by_id.values() if r.get("disposition") == "TRUE_STP")
    n = len(by_id)
    print(
        json.dumps(
            {
                "flipped": flipped,
                "still_hitl": still,
                "n": n,
                "true_stp": stp,
                "claim_page_stp": round(stp / n, 4) if n else 0,
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
