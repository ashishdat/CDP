#!/usr/bin/env python3
"""Run one Independent HITL program phase (governance-preserving).

Phases are defined in ``config/independent_hitl_program_v1.yaml``.
This runner selects the cohort and executes the allowed redo path only.

Usage:
  python3 -u scripts/run_independent_hitl_phase.py --phase H1_CHARGE \\
    --ledger-a evaluation_results/hackathon_600_independent_v13c \\
    --ledger-b evaluation_results/hackathon_400_remainder_independent_v13c
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CFG_PATH = ROOT / "config" / "independent_hitl_program_v1.yaml"


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


def _load_cfg() -> dict:
    return dict(yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")) or {})


def _select_cohort(
    rows: dict[str, dict], phase_cfg: dict
) -> list[dict]:
    track = phase_cfg.get("hitl_track")
    exact = phase_cfg.get("critical_blockers_exact")
    any_blockers = phase_cfg.get("critical_blockers_any")
    min_blockers = int(phase_cfg.get("min_blockers") or 0)
    exclude_exact_singles = bool(phase_cfg.get("exclude_exact_singles"))
    out: list[dict] = []
    for row in rows.values():
        if row.get("disposition") != "HITL":
            continue
        if track and row.get("hitl_track") != track:
            continue
        miss = sorted(row.get("critical_blockers") or [])
        if exact is not None and miss != list(exact):
            continue
        if any_blockers is not None:
            if not set(miss) & set(any_blockers):
                continue
        if min_blockers and len(miss) < min_blockers:
            continue
        if exclude_exact_singles and len(miss) == 1 and miss[0] in {
            "total_charge",
            "patient_dob",
        }:
            # Owned by H1_CHARGE / H2_DOB.
            continue
        out.append(row)
    out.sort(key=lambda r: r.get("claim_id") or "")
    return out


def _append(ledger: Path, row: dict) -> None:
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _complete_inplace(out_dir: Path, claim_id: str) -> dict:
    claim = out_dir / "claims" / claim_id
    extract = claim / "extract" / "ExtractionResult.json"
    if not extract.is_file():
        return {"ok": False, "error": "NO_EXTRACTION"}
    final = claim / "final"
    if final.exists():
        import shutil

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
    (logs / f"hitl_phase_complete.log").write_text(
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
        "blocking": list(cd.get("blocking_unresolved_fields") or []),
    }


def _cascade_documents(out_dir: Path, documents: list[str]) -> int:
    if not documents:
        return 0
    env = os.environ.copy()
    # Product residuals on; respect program kill switches if caller set them.
    env.setdefault("CDP_AZURE_DI_CHARGE_RESIDUAL", "1")
    env.setdefault("CDP_AZURE_DI_CHARGE_ACCEPT", "1")
    env.setdefault("CDP_AZURE_DI_CHARGE_CORROBORATE", "1")
    env.setdefault("CDP_GPT4O_CROP_RESIDUAL", "1")
    env.setdefault("CDP_CLOUD_STOP_LADDER", "1")
    env.setdefault("CDP_CONFLICT_AGENT", "1")
    env.setdefault("CDP_AZURE_DI_MIN_INTERVAL_SECONDS", "0")
    env.setdefault("PYTHONUNBUFFERED", "1")
    docs = ",".join(documents)
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "scripts" / "run_hackathon_1000_cascade.py"),
        "--out-dir",
        str(out_dir),
        "--documents",
        docs,
        "--no-resume",
        "--workers",
        "1",
    ]
    print(f"cascade n={len(documents)} out={out_dir}", flush=True)
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


def _unstructured_rerun(documents: list[str], zip_path: Path) -> list[dict]:
    from io import BytesIO
    from zipfile import ZipFile

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
    results: list[dict] = []
    with ZipFile(zip_path) as zf:
        for document in documents:
            started = time.time()
            page = Image.open(BytesIO(zf.read(document))).convert("RGB")
            try:
                fb = run_unstructured_reg_fallback(page)
            finally:
                page.close()
            route = classify_independent_case(fb.di_text or "")
            if route.path.value == "MAILROOM_REG":
                results.append(
                    {
                        "document": document,
                        "disposition": "REGISTRATION_FAILED",
                        "true_stp": False,
                        "hitl_track": None,
                        "fields": {},
                        "route": route.to_dict(),
                        "elapsed_sec": round(time.time() - started, 3),
                    }
                )
                continue
            disposition, blockers = promote_unstructured_fields(fb.fields)
            results.append(
                {
                    "document": document,
                    "disposition": disposition,
                    "true_stp": disposition == "TRUE_STP",
                    "hitl_track": "UNSTRUCTURED_DI" if disposition == "HITL" else None,
                    "critical_blockers": blockers if disposition == "HITL" else None,
                    "fields": dict(fb.fields or {}),
                    "route": route.to_dict(),
                    "elapsed_sec": round(time.time() - started, 3),
                }
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, help="Phase key from YAML")
    parser.add_argument("--ledger-a", type=Path, required=True)
    parser.add_argument("--ledger-b", type=Path, default=None)
    parser.add_argument(
        "--zip",
        type=Path,
        default=ROOT / "data" / "Hackathon - 1000 Claims.zip",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--mode",
        choices=("cascade", "complete", "unstructured", "auto"),
        default="auto",
        help="Execution mode (auto picks from phase)",
    )
    args = parser.parse_args()

    cfg = _load_cfg()
    phase_cfg = (cfg.get("phases") or {}).get(args.phase)
    if not phase_cfg:
        print(f"unknown phase {args.phase}", file=sys.stderr)
        return 2

    ledgers = [args.ledger_a if args.ledger_a.is_absolute() else ROOT / args.ledger_a]
    if args.ledger_b:
        ledgers.append(
            args.ledger_b if args.ledger_b.is_absolute() else ROOT / args.ledger_b
        )

    # Merge latest HITL rows with owning ledger
    owned: list[tuple[Path, dict]] = []
    for out_dir in ledgers:
        by = _latest(out_dir / "results.jsonl")
        for row in _select_cohort(by, phase_cfg):
            owned.append((out_dir, row))
    owned.sort(key=lambda item: item[1].get("claim_id") or "")
    if args.limit and args.limit > 0:
        owned = owned[: args.limit]

    mode = args.mode
    if mode == "auto":
        if args.phase.startswith("H5") or phase_cfg.get("hitl_track") == "UNSTRUCTURED_DI":
            mode = "unstructured"
        elif args.phase in {"H1_CHARGE", "H2_DOB", "H4_MULTI"}:
            mode = "cascade"
        else:
            mode = "complete"

    print(
        f"hitl_phase={args.phase} mode={mode} n={len(owned)} ts={_utc()}",
        flush=True,
    )
    if not owned:
        print("empty cohort", flush=True)
        return 0

    counts = {"TRUE_STP": 0, "HITL": 0, "REGISTRATION_FAILED": 0, "ERROR": 0}

    if mode == "cascade":
        by_ledger: dict[Path, list[str]] = {}
        for out_dir, row in owned:
            doc = row.get("document") or row["claim_id"].replace("__", "/")
            by_ledger.setdefault(out_dir, []).append(doc)
        for out_dir, docs in by_ledger.items():
            rc = _cascade_documents(out_dir, docs)
            if rc != 0:
                print(f"cascade_rc={rc} out={out_dir}", flush=True)
        # Recount from ledgers
        for out_dir, prior in owned:
            by = _latest(out_dir / "results.jsonl")
            row = by.get(prior["claim_id"]) or prior
            counts[str(row.get("disposition") or "ERROR")] = (
                counts.get(str(row.get("disposition") or "ERROR"), 0) + 1
            )
    elif mode == "unstructured":
        for out_dir, prior in owned:
            doc = prior.get("document") or prior["claim_id"].replace("__", "/")
            try:
                result = _unstructured_rerun([doc], args.zip)[0]
            except Exception as exc:  # noqa: BLE001
                result = {"disposition": "ERROR", "error": f"{type(exc).__name__}:{exc}"}
            disposition = str(result.get("disposition") or "ERROR")
            row = {
                "finished": True,
                "claim_id": prior["claim_id"],
                "document": doc,
                "bundle_id": prior.get("bundle_id"),
                "group_id": prior.get("group_id"),
                "registration_ok": False,
                "allows_cms_geometry": False,
                "completed": disposition in {"TRUE_STP", "HITL"},
                "true_stp": bool(result.get("true_stp")),
                "disposition": disposition,
                "hitl_track": result.get("hitl_track"),
                "critical_blockers": result.get("critical_blockers"),
                "unstructured_reg_fallback": {
                    "attempted": True,
                    "fields": result.get("fields") or {},
                    "route": result.get("route"),
                },
                "program_phase": args.phase,
                "elapsed_sec": result.get("elapsed_sec"),
                "ts": _utc(),
                "strategy_id": f"independent-hitl-program:{args.phase}",
                "prior_disposition": prior.get("disposition"),
                "error": result.get("error"),
            }
            _append(out_dir / "results.jsonl", row)
            counts[disposition] = counts.get(disposition, 0) + 1
            print(
                f"progress {prior['claim_id']} disp={disposition}",
                flush=True,
            )
    else:  # complete inplace
        for out_dir, prior in owned:
            started = time.time()
            result = _complete_inplace(out_dir, prior["claim_id"])
            if not result.get("ok"):
                disposition = "ERROR"
                row = {
                    **{k: prior.get(k) for k in ("claim_id", "document", "bundle_id", "group_id")},
                    "finished": True,
                    "disposition": disposition,
                    "error": result.get("error"),
                    "program_phase": args.phase,
                    "ts": _utc(),
                    "strategy_id": f"independent-hitl-program:{args.phase}",
                }
            else:
                disposition = str(result["disposition"])
                row = {
                    "finished": True,
                    "claim_id": prior["claim_id"],
                    "document": prior.get("document"),
                    "bundle_id": prior.get("bundle_id"),
                    "group_id": prior.get("group_id"),
                    "registration_ok": True,
                    "allows_cms_geometry": True,
                    "completed": disposition in {"TRUE_STP", "HITL"},
                    "true_stp": bool(result.get("true_stp")),
                    "disposition": disposition,
                    "hitl_track": result.get("hitl_track"),
                    "critical_blockers": result.get("critical_blockers"),
                    "claim_decision": result.get("claim_decision"),
                    "reason_codes": result.get("reason_codes"),
                    "program_phase": args.phase,
                    "elapsed_sec": round(time.time() - started, 3),
                    "ts": _utc(),
                    "strategy_id": f"independent-hitl-program:{args.phase}",
                    "prior_disposition": prior.get("disposition"),
                    "error": None,
                }
            _append(out_dir / "results.jsonl", row)
            counts[disposition] = counts.get(disposition, 0) + 1
            print(
                f"progress {prior['claim_id']} disp={disposition}",
                flush=True,
            )

    summary = {
        "phase": args.phase,
        "mode": mode,
        "n": len(owned),
        "counts": counts,
        "generated_at": _utc(),
        "governance": cfg.get("governance"),
    }
    out = ROOT / "docs" / "metrics" / f"independent_hitl_phase_{args.phase.lower()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"hitl_phase_done {json.dumps(summary)}", flush=True)
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
