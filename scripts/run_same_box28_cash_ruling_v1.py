#!/usr/bin/env python3
"""Redecide same-Box28 bleed HITL cohort with cash-ruling CONFIRMED mint."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "evaluation_results" / "hackathon_1000_stp_recovery_complete_v1"
OUT = ROOT / "evaluation_results" / "hackathon_1000_stp_recovery_same_box28_cash_v1"

# Claim-level HITL with BLEED_CENTS_GEOMETRY/LINE_SUM and DI cash ruling raw.
COHORT = [
    "Group A__M048DJKH.007",
    "Group A__M048DJKH.008",
    "Group A__M048DJKH.009",
    "Group A__M048DJKH.013",
    "Group A__M048DJKH.017",
    "Group A__M048DJKH.019",
    "Group A__M048DJKH.022",
    "Group A__M048DJKH.030",
    "Group A__M048DJKH.038",
    "Group A__M048DJKH.039",
    "Group A__M048DJKH.041",
]


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def process(cid: str) -> dict:
    src_claim = SRC / "claims" / cid
    claim_out = OUT / "claims" / cid
    claim_out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for name in ("extract", "ocr", "final", "logs"):
        path = claim_out / name
        if path.exists():
            shutil.rmtree(path)
    shutil.copytree(src_claim / "extract", claim_out / "extract")
    if (src_claim / "ocr").exists():
        shutil.copytree(src_claim / "ocr", claim_out / "ocr")
    final = claim_out / "final"
    final.mkdir()
    logs = claim_out / "logs"
    logs.mkdir()
    prior = json.loads((src_claim / "result.json").read_text())
    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.complete_from_extraction",
            str(claim_out / "extract" / "ExtractionResult.json"),
            str(final),
            "--document-family",
            "CMS1500",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    (logs / "complete.log").write_text((rc.stdout or "") + (rc.stderr or ""))
    if rc.returncode != 0:
        result = {
            "claim_id": cid,
            "completed": False,
            "true_stp": False,
            "disposition": "STAGE_FAILURE",
            "error": (rc.stderr or rc.stdout or "")[-500:],
            "prior_true_stp": bool(prior.get("true_stp")),
            "elapsed_sec": round(time.time() - t0, 3),
        }
        (claim_out / "result.json").write_text(json.dumps(result, indent=2))
        return result

    dec = json.loads((final / "DecisionResult.json").read_text())
    fc = json.loads((final / "FinalClaim.json").read_text())
    true_stp = (
        bool(fc.get("stp_eligible"))
        and not fc.get("review_required")
        and str(dec.get("claim_status")) == "STP_SAFE"
    )
    blob = json.dumps(fc)
    tc = None
    for fd in dec.get("field_decisions") or []:
        if fd.get("field_name") == "total_charge":
            tc = {
                "disp": fd.get("disposition"),
                "value": fd.get("selected_value"),
                "reasons": fd.get("reason_codes") or [],
            }
            break
    result = {
        "claim_id": cid,
        "completed": True,
        "true_stp": true_stp,
        "disposition": "TRUE_STP" if true_stp else "HITL",
        "claim_status": dec.get("claim_status"),
        "decision_reason": fc.get("decision_reason"),
        "total_charge": tc,
        "has_cash_ruling": "CASH_RULING_PRINTED_CENTS" in blob,
        "has_geometry_blocked": "BLEED_CENTS_GEOMETRY_BLOCKED" in blob,
        "has_line_sum_blocked": "BLEED_CENTS_LINE_SUM_BLOCKED" in blob,
        "has_confirmed": "CLAIM_TOTAL_CONFIRMED" in blob,
        "prior_true_stp": bool(prior.get("true_stp")),
        "prior_disposition": prior.get("disposition"),
        "elapsed_sec": round(time.time() - t0, 3),
        "ts": utc(),
    }
    (claim_out / "result.json").write_text(json.dumps(result, indent=2))
    return result


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    (OUT / "claims").mkdir()
    rows = []
    for cid in COHORT:
        row = process(cid)
        rows.append(row)
        print(
            f"{cid}: {row.get('disposition')} tc={row.get('total_charge')} "
            f"cash={row.get('has_cash_ruling')} geo_block={row.get('has_geometry_blocked')} "
            f"confirmed={row.get('has_confirmed')}",
            flush=True,
        )
    flipped = [r["claim_id"] for r in rows if r.get("true_stp") and not r.get("prior_true_stp")]
    still_hitl = [r["claim_id"] for r in rows if r.get("completed") and not r.get("true_stp")]
    summary = {
        "title": "Same-Box28 cash ruling printed-cents clear",
        "updated_at": utc(),
        "cohort": COHORT,
        "completed": sum(1 for r in rows if r.get("completed")),
        "true_stp": sum(1 for r in rows if r.get("true_stp")),
        "flipped": len(flipped),
        "flipped_ids": flipped,
        "still_hitl": len(still_hitl),
        "still_hitl_ids": still_hitl,
        "rows": rows,
        "page_check": (
            "FG/line-sum mint CASH_RULING_PRINTED_CENTS when DI raw is $ NNN :CC; "
            "BLEED_CENTS_GEOMETRY/LINE_SUM_BLOCKED cleared; field binds printed cents."
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    metrics = ROOT / "docs" / "metrics" / "stp_recovery_same_box28_cash_v1.json"
    metrics.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in summary if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
