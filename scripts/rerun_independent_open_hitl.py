#!/usr/bin/env python3
"""Redo Independent open HITL through the consolidated case router.

Routes each open HITL doc:
  FIELD_INK     → complete-inplace (insured twin + claim_decision) when extract
                  exists; else full cascade --no-resume
  UNSTRUCTURED  → DI heuristics via unstructured_reg_fallback + router promote

Usage:
  python3 -u scripts/rerun_independent_open_hitl.py \\
    --ledger-a evaluation_results/hackathon_600_independent_v13c \\
    --ledger-b evaluation_results/hackathon_400_remainder_independent_v13c
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_ZIP = ROOT / "data" / "Hackathon - 1000 Claims.zip"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _latest(ledger: Path) -> dict[str, dict]:
    by: dict[str, dict] = {}
    if not ledger.is_file():
        return by
    for line in ledger.open(encoding="utf-8"):
        row = json.loads(line)
        by[row["claim_id"]] = row
    return by


def _claim_dir(out_dir: Path, claim_id: str) -> Path:
    return out_dir / "claims" / claim_id


def _append(ledger: Path, row: dict) -> None:
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _complete_inplace(out_dir: Path, claim_id: str, document: str) -> dict:
    claim = _claim_dir(out_dir, claim_id)
    extract = claim / "extract" / "ExtractionResult.json"
    if not extract.is_file():
        return {"ok": False, "error": "NO_EXTRACTION"}
    final = claim / "final"
    if final.exists():
        shutil.rmtree(final)
    final.mkdir(parents=True)
    logs = claim / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.complete_from_extraction",
            str(extract),
            str(final),
            "--document-family",
            "CMS1500",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    (logs / "independent_case_complete.log").write_text(
        (rc.stdout or "") + (rc.stderr or ""), encoding="utf-8"
    )
    if rc.returncode != 0:
        return {"ok": False, "error": (rc.stderr or rc.stdout or "")[-400:]}
    decision = json.loads((final / "DecisionResult.json").read_text(encoding="utf-8"))
    cd = decision.get("claim_decision") or {}
    stp = bool(cd.get("stp_eligible")) or str(cd.get("disposition") or "").startswith(
        "STP_"
    )
    review = bool(decision.get("review_required")) and not stp
    disposition = "TRUE_STP" if stp else ("HITL" if review else "TRUE_STP")
    return {
        "ok": True,
        "disposition": disposition,
        "true_stp": disposition == "TRUE_STP",
        "hitl_track": None if disposition == "TRUE_STP" else "FIELD_INK",
        "critical_blockers": list(cd.get("critical_blockers") or []),
        "claim_decision": cd.get("disposition"),
        "reason_codes": list(cd.get("reason_codes") or []),
    }


def _unstructured_di(document: str, zip_path: Path) -> dict:
    from PIL import Image

    from packages.extraction_recovery.independent_case_router import (
        classify_independent_case,
        promote_unstructured_fields,
    )
    from packages.extraction_recovery.unstructured_reg_fallback import (
        run_unstructured_reg_fallback,
    )
    from workers.ocr_engine_factories import wire_package_ocr_providers

    wire_package_ocr_providers()
    with ZipFile(zip_path) as zf:
        page = Image.open(BytesIO(zf.read(document))).convert("RGB")
        try:
            fb = run_unstructured_reg_fallback(page)
        finally:
            page.close()
    route = classify_independent_case(
        fb.di_text,
        registration_ok=False,
        field_ink_hitl=False,
    )
    if route.path.value == "MAILROOM_REG":
        return {
            "ok": True,
            "disposition": "REGISTRATION_FAILED",
            "true_stp": False,
            "hitl_track": None,
            "critical_blockers": None,
            "fields": {},
            "route": route.to_dict(),
            "unstructured_reason": "MAILROOM_OR_FAX",
        }
    disposition, blockers = promote_unstructured_fields(fb.fields)
    return {
        "ok": True,
        "disposition": disposition,
        "true_stp": disposition == "TRUE_STP",
        "hitl_track": "UNSTRUCTURED_DI" if disposition == "HITL" else None,
        "critical_blockers": blockers if disposition == "HITL" else None,
        "fields": dict(fb.fields or {}),
        "route": route.to_dict(),
        "unstructured_reason": fb.reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-a", type=Path, required=True)
    parser.add_argument("--ledger-b", type=Path, default=None)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    os.environ.setdefault("CDP_UNSTRUCTURED_REG_FALLBACK", "1")
    os.environ.setdefault("CDP_UNSTRUCTURED_REG_AGENT", "0")
    os.environ.setdefault("CDP_AZURE_DI_MIN_INTERVAL_SECONDS", "0")

    ledgers = [args.ledger_a]
    if args.ledger_b:
        ledgers.append(args.ledger_b)

    open_rows: list[tuple[Path, dict]] = []
    for out_dir in ledgers:
        out_dir = out_dir if out_dir.is_absolute() else ROOT / out_dir
        by = _latest(out_dir / "results.jsonl")
        for row in by.values():
            if row.get("disposition") != "HITL":
                continue
            open_rows.append((out_dir, row))
    open_rows.sort(key=lambda item: item[1].get("claim_id") or "")
    if args.limit and args.limit > 0:
        open_rows = open_rows[: args.limit]

    print(f"independent_open_hitl n={len(open_rows)} ts={_utc()}", flush=True)
    counts = {"TRUE_STP": 0, "HITL": 0, "REGISTRATION_FAILED": 0, "ERROR": 0}

    for i, (out_dir, prior) in enumerate(open_rows, 1):
        started = time.time()
        claim_id = prior["claim_id"]
        document = prior.get("document") or claim_id.replace("__", "/")
        track = prior.get("hitl_track") or "FIELD_INK"
        result: dict
        try:
            if track == "FIELD_INK":
                result = _complete_inplace(out_dir, claim_id, document)
                if not result.get("ok") and result.get("error") == "NO_EXTRACTION":
                    # Fall back to unstructured DI classify (may still be CMS).
                    result = _unstructured_di(document, args.zip)
            else:
                result = _unstructured_di(document, args.zip)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}

        if not result.get("ok"):
            disposition = "ERROR"
            row = {
                **{k: prior.get(k) for k in ("claim_id", "document", "bundle_id", "group_id")},
                "finished": True,
                "registration_ok": prior.get("registration_ok"),
                "allows_cms_geometry": prior.get("allows_cms_geometry"),
                "completed": False,
                "true_stp": False,
                "disposition": disposition,
                "hitl_track": prior.get("hitl_track"),
                "critical_blockers": prior.get("critical_blockers"),
                "error": result.get("error"),
                "elapsed_sec": round(time.time() - started, 3),
                "ts": _utc(),
                "strategy_id": "independent-case-router-v1",
                "prior_disposition": prior.get("disposition"),
            }
        else:
            disposition = str(result["disposition"])
            row = {
                "finished": True,
                "claim_id": claim_id,
                "document": document,
                "bundle_id": prior.get("bundle_id"),
                "group_id": prior.get("group_id"),
                "registration_ok": bool(prior.get("registration_ok"))
                if track == "FIELD_INK"
                else False,
                "allows_cms_geometry": prior.get("allows_cms_geometry"),
                "completed": disposition in {"TRUE_STP", "HITL"},
                "true_stp": bool(result.get("true_stp")),
                "disposition": disposition,
                "hitl_track": result.get("hitl_track"),
                "critical_blockers": result.get("critical_blockers"),
                "unstructured_reg_fallback": (
                    {
                        "attempted": True,
                        "reason": result.get("unstructured_reason"),
                        "fields": result.get("fields") or {},
                        "route": result.get("route"),
                    }
                    if track != "FIELD_INK" or result.get("fields") is not None
                    else prior.get("unstructured_reg_fallback")
                ),
                "claim_decision": result.get("claim_decision"),
                "reason_codes": result.get("reason_codes"),
                "error": None,
                "elapsed_sec": round(time.time() - started, 3),
                "ts": _utc(),
                "strategy_id": "independent-case-router-v1",
                "prior_disposition": prior.get("disposition"),
                "prior_hitl_track": track,
            }
        _append(out_dir / "results.jsonl", row)
        claim_out = _claim_dir(out_dir, claim_id)
        claim_out.mkdir(parents=True, exist_ok=True)
        (claim_out / "result.json").write_text(
            json.dumps(row, indent=2) + "\n", encoding="utf-8"
        )
        counts[disposition] = counts.get(disposition, 0) + 1
        print(
            f"progress {i}/{len(open_rows)} {claim_id} prior={track} "
            f"disp={disposition} sec={row['elapsed_sec']}",
            flush=True,
        )

    summary = {
        "mode": "independent-case-router-v1-open-hitl",
        "n": len(open_rows),
        "counts": counts,
        "generated_at": _utc(),
    }
    print(f"independent_open_hitl_done {json.dumps(summary)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
