#!/usr/bin/env python3
"""Full ops cohort complete-inplace redecide (frozen extract/OCR)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "evaluation_results" / "hackathon_1000_geometry_95_verify"
OUT = ROOT / "evaluation_results" / "hackathon_1000_stp_recovery_complete_v1"
WORKERS = 8


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str, log_path: Path) -> None:
    line = f"{utc()} {msg}"
    print(line, flush=True)
    with log_path.open("a") as fh:
        fh.write(line + "\n")


def process(row: dict, src: Path, out: Path) -> dict:
    cid = row["claim_id"]
    src_claim = src / "claims" / cid
    claim_out = out / "claims" / cid
    claim_out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
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
                "finished": True,
                "claim_id": cid,
                "document": row.get("document"),
                "registration_ok": True,
                "completed": False,
                "true_stp": False,
                "disposition": "STAGE_FAILURE",
                "error": ((rc.stderr or rc.stdout or "")[-500:]),
                "prior_true_stp": bool(row.get("true_stp")),
                "prior_disposition": row.get("disposition"),
                "prior_blockers": row.get("critical_blockers"),
                "elapsed_sec": round(time.time() - t0, 3),
                "reprocess": "complete_inplace_v1",
                "ts": utc(),
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
        fields = {}
        for fd in dec.get("field_decisions") or []:
            name = fd.get("field_name")
            if name:
                fields[name] = {
                    "disp": fd.get("disposition"),
                    "value": fd.get("selected_value"),
                    "reasons": fd.get("reason_codes") or [],
                }
        result = {
            "finished": True,
            "claim_id": cid,
            "document": row.get("document"),
            "registration_ok": True,
            "completed": True,
            "true_stp": true_stp,
            "disposition": "TRUE_STP" if true_stp else "HITL",
            "critical_blockers": dec.get("critical_blockers") or [],
            "fields": fields,
            "prior_true_stp": bool(row.get("true_stp")),
            "prior_disposition": row.get("disposition"),
            "prior_blockers": row.get("critical_blockers"),
            "elapsed_sec": round(time.time() - t0, 3),
            "reprocess": "complete_inplace_v1",
            "ts": utc(),
        }
        (claim_out / "result.json").write_text(json.dumps(result, indent=2))
        return result
    except Exception as exc:  # noqa: BLE001
        result = {
            "finished": True,
            "claim_id": cid,
            "document": row.get("document"),
            "registration_ok": True,
            "completed": False,
            "true_stp": False,
            "disposition": "WORKER_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-800:],
            "prior_true_stp": bool(row.get("true_stp")),
            "elapsed_sec": round(time.time() - t0, 3),
            "reprocess": "complete_inplace_v1",
            "ts": utc(),
        }
        (claim_out / "result.json").write_text(json.dumps(result, indent=2))
        return result


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    (OUT / "claims").mkdir()
    log_path = OUT / "run.log"
    ledger = OUT / "results.jsonl"

    prior = [
        json.loads(line)
        for line in (SRC / "results.jsonl").read_text().splitlines()
        if line.strip()
    ]
    targets = []
    for row in prior:
        if not row.get("registration_ok"):
            continue
        cid = row["claim_id"]
        if not (SRC / "claims" / cid / "extract" / "ExtractionResult.json").exists():
            continue
        targets.append(row)

    log(f"START complete_v1 targets={len(targets)} workers={WORKERS}", log_path)
    rows: list[dict] = []
    flipped = 0
    lost = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(process, row, SRC, OUT): row for row in targets}
        for i, fut in enumerate(as_completed(futs), 1):
            row = fut.result()
            rows.append(row)
            if row.get("true_stp") and not row.get("prior_true_stp"):
                flipped += 1
            if row.get("prior_true_stp") and not row.get("true_stp"):
                lost += 1
            with ledger.open("a") as fh:
                fh.write(json.dumps(row) + "\n")
            if i % 25 == 0 or i == len(targets):
                stp = sum(1 for item in rows if item.get("true_stp"))
                done = sum(1 for item in rows if item.get("completed"))
                log(
                    f"progress {i}/{len(targets)} completed={done} true_stp={stp} "
                    f"flipped={flipped} lost={lost} elapsed={time.time() - t0:.1f}s",
                    log_path,
                )

    completed = sum(1 for item in rows if item.get("completed"))
    true_stp = sum(1 for item in rows if item.get("true_stp") and item.get("completed"))
    hitl = sum(1 for item in rows if item.get("completed") and not item.get("true_stp"))
    stage_fail = sum(1 for item in rows if item.get("disposition") == "STAGE_FAILURE")
    summary = {
        "title": "Full ops complete-inplace with cash ruling-split geometry",
        "updated_at": utc(),
        "src_run": str(SRC),
        "reprocess": "complete_inplace_v1",
        "targets": len(targets),
        "completed": completed,
        "true_stp": true_stp,
        "true_stp_rate_of_completed": round(true_stp / completed, 6) if completed else 0.0,
        "hitl": hitl,
        "hitl_rate_of_completed": round(hitl / completed, 6) if completed else 0.0,
        "flipped_to_true_stp": flipped,
        "lost_stp": lost,
        "stage_failures": stage_fail,
        "elapsed_sec": round(time.time() - t0, 3),
        "run_status": "COMPLETE",
        "flipped_ids": sorted(
            item["claim_id"]
            for item in rows
            if item.get("true_stp") and not item.get("prior_true_stp")
        ),
        "lost_ids": sorted(
            item["claim_id"]
            for item in rows
            if item.get("prior_true_stp") and not item.get("true_stp")
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    log(f"DONE {json.dumps(summary)}", log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
