#!/usr/bin/env python3
"""Full hackathon-1000 ops complete-inplace with latest charge authority arch."""

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
OUT = ROOT / "evaluation_results" / "hackathon_1000_stp_recovery_latest_arch"
WORKERS = 8
ARCH_TAG = "e2e_authority_v1+cash_ruling+bleed_clear"


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
                "elapsed_sec": round(time.time() - t0, 3),
                "reprocess": "complete_latest_arch",
                "arch": ARCH_TAG,
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
            "reprocess": "complete_latest_arch",
            "arch": ARCH_TAG,
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
            "reprocess": "complete_latest_arch",
            "arch": ARCH_TAG,
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
    # Prefer unique claim_ids that have frozen extracts.
    seen: set[str] = set()
    targets: list[dict] = []
    for row in prior:
        cid = row["claim_id"]
        if cid in seen:
            continue
        if not row.get("registration_ok", True):
            continue
        if not (SRC / "claims" / cid / "extract" / "ExtractionResult.json").exists():
            continue
        seen.add(cid)
        targets.append(row)

    log(
        f"START complete_latest_arch targets={len(targets)} workers={WORKERS} arch={ARCH_TAG}",
        log_path,
    )
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

    # Charge HITL remaining (blocker or bleed soup).
    charge_hitl = 0
    for item in rows:
        if not item.get("completed") or item.get("true_stp"):
            continue
        blockers = item.get("critical_blockers") or []
        if any("charge" in str(b).lower() or "total" in str(b).lower() for b in blockers):
            charge_hitl += 1
            continue
        fc = OUT / "claims" / item["claim_id"] / "final" / "FinalClaim.json"
        if fc.exists() and "BLEED_CENTS" in fc.read_text():
            charge_hitl += 1

    summary = {
        "title": "Hackathon-1000 complete-inplace with latest charge authority arch",
        "updated_at": utc(),
        "src_run": str(SRC),
        "reprocess": "complete_latest_arch",
        "arch": ARCH_TAG,
        "targets": len(targets),
        "unique_claims_completed": completed,
        "completed": completed,
        "true_stp": true_stp,
        "true_stp_rate_of_completed": round(true_stp / completed, 6) if completed else 0.0,
        "hitl": hitl,
        "hitl_rate_of_completed": round(hitl / completed, 6) if completed else 0.0,
        "flipped_to_true_stp": flipped,
        "lost_stp": lost,
        "net_delta": flipped - lost,
        "charge_hitl_remaining": charge_hitl,
        "stage_failures": stage_fail,
        "elapsed_sec": round(time.time() - t0, 3),
        "run_status": "COMPLETE",
        "note": (
            "Source geometry_95_verify has 1000 docs listed; "
            f"{len(targets)} unique registration-ok extracts available for complete-inplace. "
            "Metrics are unique claim_id (no ledger dups)."
        ),
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
    metrics = ROOT / "docs" / "metrics" / "stp_recovery_latest_arch_1000.json"
    metrics.write_text(json.dumps(summary, indent=2))
    log(f"DONE {json.dumps(summary)}", log_path)

    # Refresh E2E taxonomy against this run.
    tax = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_e2e_hitl_taxonomy.py"),
            "--run",
            str(OUT.relative_to(ROOT)),
            "--out",
            "docs/metrics/stp_hitl_taxonomy_latest.json",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log(f"taxonomy_exit={tax.returncode}", log_path)
    if tax.stdout:
        log(tax.stdout[-1500:], log_path)
    return 0 if stage_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
