#!/usr/bin/env python3
"""Reprocess an operational cohort through OCR→…→complete (field-cascade-v6).

Default: held-out Sample A (`fix_sample`) for independent STP/HITL measurement.
Sample B was the cascade-v5 tuning cohort — do not treat Sample B rescores as
independent generalization.

Usage:
  python3 scripts/reprocess_ops_cascade.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRITICAL = (
    "patient_dob",
    "total_charge",
    "patient_name",
    "insured_id_number",
    "insured_name",
)


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
    from packages.extraction_recovery.gap_taxonomy import classify_field_gap

    final = json.loads((claim_dir / "final/FinalClaim.json").read_text())
    decision = final.get("decision") or final
    fields: dict = {}
    for fd in decision.get("field_decisions") or []:
        name = fd.get("field_name")
        if name in CRITICAL:
            fields[name] = {
                "disp": fd.get("disposition"),
                "value": fd.get("selected_value"),
                "reasons": (fd.get("reason_codes") or [])[:6],
            }
    ocr = json.loads((claim_dir / "ocr/OCRCandidates.json").read_text())
    lines = ocr.get("service_lines") or []
    observed = [
        line
        for line in lines
        if line.get("status") == "OBSERVED" and line.get("charges")
    ]
    gaps = []
    for blocker in decision.get("critical_blockers") or []:
        field_info = fields.get(blocker) or {}
        observed_text = str(field_info.get("value") or "")
        gap = classify_field_gap(
            blocker,
            observed_text=observed_text,
            accepted=False,
            service_line_charges=len(observed),
            reason_codes=field_info.get("reasons") or [],
        )
        if gap is not None:
            gaps.append(
                {
                    "field": gap.field_name,
                    "gap_class": gap.gap_class,
                    "action": gap.action,
                    "evidence": gap.evidence,
                }
            )
    return {
        "claim": claim_dir.name,
        "ok": True,
        "review_required": bool(
            decision.get("review_required") or final.get("review_required")
        ),
        "claim_status": decision.get("claim_status") or final.get("claim_status"),
        "critical_blockers": decision.get("critical_blockers") or [],
        "stp_eligible": bool(final.get("stp_eligible") or decision.get("stp_eligible")),
        "fields": fields,
        "service_lines_observed": len(observed),
        "service_line_charges": [line.get("charges") for line in observed],
        "gap_classes": gaps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src",
        type=Path,
        default=ROOT / "evaluation_results/operational_e2e_100_v1_fix_sample",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT
        / "evaluation_results/operational_e2e_100_v1_std_sample_a_cascade_v6",
    )
    parser.add_argument("--strategy-label", default="field-cascade-v7")
    args = parser.parse_args()

    src = args.src if args.src.is_absolute() else ROOT / args.src
    out = args.out if args.out.is_absolute() else ROOT / args.out
    if not src.is_dir():
        print(f"missing source {src}", file=sys.stderr)
        return 2
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    claim_names = sorted(p.name for p in (src / "live").iterdir() if p.is_dir())
    rows: list[dict] = []
    for name in claim_names:
        claim_src = src / "live" / name
        try:
            geom = _geometry_dir(claim_src)
        except FileNotFoundError as exc:
            rows.append({"claim": name, "ok": False, "error": str(exc), "skipped": True})
            continue

        claim_out = out / "live" / claim_src.name
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
    gap_counter: Counter[str] = Counter()
    auto = {name: 0 for name in CRITICAL}
    true_stp = 0
    completed = 0
    processed = [r for r in rows if not r.get("skipped")]
    for row in rows:
        if not row.get("ok"):
            continue
        completed += 1
        if not row.get("review_required"):
            true_stp += 1
        for blocker in row.get("critical_blockers") or []:
            blockers[blocker] += 1
        for gap in row.get("gap_classes") or []:
            gap_counter[str(gap["gap_class"])] += 1
        for name in CRITICAL:
            disp = ((row.get("fields") or {}).get(name) or {}).get("disp")
            if disp in {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"}:
                auto[name] += 1

    try:
        cohort = str(src.relative_to(ROOT))
    except ValueError:
        cohort = str(src)

    summary = {
        "cohort": cohort,
        "independent_of_sample_b_tuning": src.name.endswith("fix_sample"),
        "summary": {
            "attempted": len(rows),
            "with_geometry": len(processed),
            "completed": f"{completed}/{len(processed) if processed else 1}",
            "true_stp": f"{true_stp}/{max(completed, 1)}",
            "patient_dob_auto": f"{auto['patient_dob']}/{max(completed, 1)}",
            "total_charge_auto": f"{auto['total_charge']}/{max(completed, 1)}",
            "patient_name_auto": f"{auto['patient_name']}/{max(completed, 1)}",
            "insured_id_auto": f"{auto['insured_id_number']}/{max(completed, 1)}",
            "insured_name_auto": f"{auto['insured_name']}/{max(completed, 1)}",
        },
        "blockers": dict(blockers),
        "gap_classes": dict(gap_counter),
        "strategy": args.strategy_label,
    }
    (out / "cascade_v6_reprocess.json").write_text(json.dumps(rows, indent=2) + "\n")
    (out / "metrics_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    failures = [r for r in processed if not r.get("ok")]
    return 0 if not failures and completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
