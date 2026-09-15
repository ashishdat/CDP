#!/usr/bin/env python3
"""Reprocess sample-B claims through OCR→…→complete with Phase-3 cascade.

Usage:
  python3 scripts/reprocess_sample_b_cascade_v2.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "evaluation_results/operational_e2e_100_v1_fix_sample_b"
OUT = ROOT / "evaluation_results/operational_e2e_100_v1_std_sample_b_cascade_v3"
CRITICAL = ("patient_dob", "total_charge", "patient_name", "insured_id_number", "insured_name")


def _run(module: str, *args: str) -> None:
    cmd = [sys.executable, "-m", module, *args]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def _geometry_dir(claim_src: Path) -> Path:
    hits = list(claim_src.glob("application/*/GeometryResult.json"))
    if not hits:
        raise FileNotFoundError(f"No GeometryResult under {claim_src}")
    return hits[0].parent


def _summarize_claim(claim_dir: Path) -> dict:
    final = json.loads((claim_dir / "final/FinalClaim.json").read_text())
    decision = final.get("decision") or final
    fields = {}
    for fd in decision.get("field_decisions") or []:
        name = fd.get("field_name")
        if name in CRITICAL:
            fields[name] = {
                "disp": fd.get("disposition"),
                "value": fd.get("selected_value"),
                "reasons": (fd.get("reason_codes") or [])[:6],
            }
    ocr_path = claim_dir / "ocr/OCRCandidates.json"
    ocr = json.loads(ocr_path.read_text())
    lines = ocr.get("service_lines") or []
    observed = [line for line in lines if line.get("status") == "OBSERVED" and line.get("charges")]
    return {
        "claim": claim_dir.name,
        "ok": True,
        "review_required": bool(decision.get("review_required") or final.get("review_required")),
        "claim_status": decision.get("claim_status") or final.get("claim_status"),
        "critical_blockers": decision.get("critical_blockers") or [],
        "stp_eligible": bool(final.get("stp_eligible") or decision.get("stp_eligible")),
        "fields": fields,
        "service_lines_observed": len(observed),
        "service_line_charges": [line.get("charges") for line in observed],
    }


def main() -> int:
    if not SRC.is_dir():
        print(f"missing source {SRC}", file=sys.stderr)
        return 2
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    # Keep the independent sample-B six used for cascade v1 metrics.
    seed = ROOT / "evaluation_results/operational_e2e_100_v1_std_sample_b_cascade_v1/live"
    claim_names = sorted(p.name for p in seed.iterdir() if p.is_dir()) if seed.is_dir() else []
    rows = []
    for name in claim_names:
        claim_src = SRC / "live" / name
        if not claim_src.is_dir():
            rows.append({"claim": name, "ok": False, "error": "source claim missing"})
            continue
        claim_out = OUT / "live" / claim_src.name
        geom = _geometry_dir(claim_src)
        ocr_dir = claim_out / "ocr"
        rank_dir = claim_out / "rank"
        val_dir = claim_out / "validate"
        extract_dir = claim_out / "extract"
        final_dir = claim_out / "final"
        try:
            _run("scripts.ocr_from_geometry", str(geom), str(ocr_dir))
            _run(
                "scripts.rank_from_ocr",
                str(ocr_dir / "OCRCandidates.json"),
                str(rank_dir),
            )
            _run(
                "scripts.validate_from_ranked",
                str(rank_dir / "RankedCandidates.json"),
                str(val_dir),
                "--template-id",
                "cms1500",
                "--template-version",
                "02-12",
            )
            _run(
                "scripts.assemble_extraction_result",
                str(ocr_dir / "OCRCandidates.json"),
                str(rank_dir / "RankedCandidates.json"),
                str(val_dir / "ValidationResults.json"),
                str(extract_dir),
            )
            _run(
                "scripts.complete_from_extraction",
                str(extract_dir / "ExtractionResult.json"),
                str(final_dir),
                "--document-family",
                "CMS1500",
            )
            rows.append(_summarize_claim(claim_out))
        except Exception as exc:  # noqa: BLE001 — batch continues
            rows.append(
                {
                    "claim": claim_src.name,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    blockers: Counter[str] = Counter()
    auto = {name: 0 for name in CRITICAL}
    true_stp = 0
    completed = 0
    for row in rows:
        if not row.get("ok"):
            continue
        completed += 1
        if not row.get("review_required"):
            true_stp += 1
        for blocker in row.get("critical_blockers") or []:
            blockers[blocker] += 1
        for name in CRITICAL:
            disp = ((row.get("fields") or {}).get(name) or {}).get("disp")
            if disp in {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"}:
                auto[name] += 1

    summary = {
        "summary": {
            "completed": f"{completed}/{len(rows)}",
            "true_stp": f"{true_stp}/{max(completed, 1)}",
            "patient_dob_auto": f"{auto['patient_dob']}/{max(completed, 1)}",
            "total_charge_auto": f"{auto['total_charge']}/{max(completed, 1)}",
            "patient_name_auto": f"{auto['patient_name']}/{max(completed, 1)}",
            "insured_id_auto": f"{auto['insured_id_number']}/{max(completed, 1)}",
            "insured_name_auto": f"{auto['insured_name']}/{max(completed, 1)}",
        },
        "blockers": dict(blockers),
        "strategy": "field-cascade-v3",
    }
    (OUT / "cascade_v3_reprocess.json").write_text(json.dumps(rows, indent=2) + "\n")
    (OUT / "metrics_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if completed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
