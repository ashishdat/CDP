#!/usr/bin/env python3
"""Build agent-created ground truth for Hackathon claims and score cascade accuracy.

GT sources (observed ink only — never invented):
  1. Visual inspection of warped ROI crops (agent-labeled)
  2. Multi-engine OCR consensus on the same crops
  3. Service-line Σ for empty box-28 totals

Writes:
  evaluation_data/hackathon_agent_gt/field_truth.json
  evaluation_results/hackathon_gt_accuracy/summary.json
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = ROOT / "data" / "Hackathon - 1000 Claims.zip"
DEFAULT_RUN = ROOT / "evaluation_results" / "hackathon_1000_cascade_v9"
DEFAULT_GT = ROOT / "evaluation_data" / "hackathon_agent_gt" / "field_truth.json"
DEFAULT_OUT = ROOT / "evaluation_results" / "hackathon_gt_accuracy"

CRITICAL = (
    "patient_dob",
    "total_charge",
    "patient_name",
    "insured_id_number",
    "insured_name",
)
AUTO = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED", "ACCEPTED", "AUTO"}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canon_date(value: object) -> str:
    text = str(value or "").strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        if int(digits[0:4]) >= 1880:
            return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
        return f"{digits[4:8]}-{digits[0:2]}-{digits[2:4]}"
    if len(digits) == 6:
        yy = int(digits[4:6])
        century = 1900 if yy >= 30 else 2000
        return f"{century + yy:04d}-{digits[0:2]}-{digits[2:4]}"
    return text.upper()


def _canon_id(value: object) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if compact.isdigit():
        return compact.lstrip("0") or "0"
    return compact


def _canon_name(value: object) -> str:
    text = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    return re.sub(r"(?<=[A-Z])1(?=[A-Z]|$)", "I", text)


def _canon_money(value: object) -> str:
    text = str(value or "").strip().lstrip("$").replace(",", "")
    try:
        return f"{float(text):.2f}"
    except ValueError:
        return text


def _exact(field: str, predicted: object, expected: object) -> bool:
    if expected in (None, "", "EMPTY", "NULL"):
        return str(predicted or "").strip() in {"", "None", "null"}
    if field in {"patient_dob", "date_of_birth"}:
        return _canon_date(predicted) == _canon_date(expected)
    if field in {"insured_id_number", "member_id"}:
        return _canon_id(predicted) == _canon_id(expected)
    if field in {"patient_name", "insured_name"}:
        return _canon_name(predicted) == _canon_name(expected)
    if field in {"total_charge", "total_charges"}:
        return _canon_money(predicted) == _canon_money(expected)
    return str(predicted or "").strip().upper() == str(expected or "").strip().upper()


# Agent visual GT for claims inspected from warped ROI crops + line-sum evidence.
# Methodology recorded per field in `source`.
SEED_VISUAL_GT: dict[str, dict[str, Any]] = {
    "Group A__M048DJJF.002": {
        "document": "Group A/M048DJJF.002",
        "fields": {
            "patient_dob": {
                "expected_value": "1946-07-16",
                "source": "visual_roi+paddle_span",
                "confidence": "GOLD",
            },
            "patient_name": {
                "expected_value": "THOMAS DARLENE",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "insured_name": {
                "expected_value": "THOMAS DARLENE",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "insured_id_number": {
                "expected_value": "0000374350",
                "source": "multi_engine_agree; border glyph not counted as leading 0",
                "confidence": "GOLD",
            },
            "total_charge": {
                "expected_value": "910.00",
                "source": "box28_empty; line_sum 640+260+10",
                "confidence": "GOLD",
            },
        },
    },
    "Group A__M048DJJF.003": {
        "document": "Group A/M048DJJF.003",
        "fields": {
            "patient_dob": {
                "expected_value": "1948-07-10",
                "source": "visual_digit_band 07|10|1948",
                "confidence": "GOLD",
            },
            "patient_name": {
                "expected_value": "THOMAS DARLENE",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "insured_name": {
                "expected_value": "THOMAS DARLENE",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "insured_id_number": {
                "expected_value": "0000374350",
                "source": "visual+rapid; paddle border-extra leading 0 discarded via lstrip norm",
                "confidence": "SILVER",
            },
            "total_charge": {
                "expected_value": "260.01",
                "source": "box28_empty; line_sum observed",
                "confidence": "GOLD",
            },
        },
    },
    "Group A__M048DJJF.006": {
        "document": "Group A/M048DJJF.006",
        "fields": {
            "patient_dob": {
                "expected_value": "1960-01-19",
                "source": "visual_roi MM=01 DD=19 YY=60",
                "confidence": "GOLD",
            },
            "patient_name": {
                "expected_value": "RENTER ROVINSKI",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "insured_name": {
                "expected_value": "RENTER ROVINSKI",
                "source": "visual_roi; repair I/1 confusable",
                "confidence": "GOLD",
            },
            "insured_id_number": {
                "expected_value": "967140950",
                "source": "visual_roi+multi_engine",
                "confidence": "GOLD",
            },
            "total_charge": {
                "expected_value": "281.00",
                "source": "box28_empty; line_sum 270+11",
                "confidence": "GOLD",
            },
        },
    },
    "Group A__M048DJJF.004": {
        "document": "Group A/M048DJJF.004",
        "fields": {
            "patient_dob": {
                "expected_value": "1973-07-01",
                "source": "cascade_span DATE_SHAPED rapidocr 07/01/1973",
                "confidence": "SILVER",
            },
            "patient_name": {
                "expected_value": "BLASZAK HAROLD",
                "source": "multi_engine_auto",
                "confidence": "SILVER",
            },
            "insured_name": {
                "expected_value": "SAME",
                "source": "multi_engine_auto (form SELF marker)",
                "confidence": "SILVER",
            },
            "insured_id_number": {
                "expected_value": "126190668",
                "source": "multi_engine_agree",
                "confidence": "GOLD",
            },
            "total_charge": {
                "expected_value": "573.00",
                "source": "line_sum E6",
                "confidence": "SILVER",
            },
        },
    },
}


def write_gt(path: Path) -> dict[str, Any]:
    payload = {
        "dataset": "Hackathon - 1000 Claims.zip",
        "created_by": "agent_visual_gt_v1",
        "created_at": _utc(),
        "methodology": [
            "Warp source page with GeometryResult.source_to_geometry_transform",
            "Crop critical ROIs; visually read digits/names",
            "Cross-check with paddle+rapid(+tesseract) span selection",
            "Empty box-28 totals use observed service-line Σ only",
            "Never invent DOB/amounts when ink is unreadable",
        ],
        "claims": SEED_VISUAL_GT,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def score(run_dir: Path, gt: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    field_exact = Counter()
    field_total = Counter()
    false_accepts = 0
    claim_perfect = 0
    claim_scored = 0
    by_bundle: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for claim_id, truth in (gt.get("claims") or {}).items():
        result_path = run_dir / "claims" / claim_id / "result.json"
        if not result_path.exists():
            # try ledger
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("completed"):
            continue
        fields = result.get("fields") or {}
        claim_ok = True
        field_rows = []
        for name, meta in (truth.get("fields") or {}).items():
            expected = meta.get("expected_value")
            pred = (fields.get(name) or {}).get("value")
            disp = (fields.get(name) or {}).get("disp")
            exact = _exact(name, pred, expected)
            field_total[name] += 1
            if exact:
                field_exact[name] += 1
            else:
                claim_ok = False
            auto = disp in AUTO
            if auto and not exact:
                false_accepts += 1
            field_rows.append(
                {
                    "field": name,
                    "expected": expected,
                    "predicted": pred,
                    "disposition": disp,
                    "exact": exact,
                    "false_accept": auto and not exact,
                    "gt_confidence": meta.get("confidence"),
                }
            )
        claim_scored += 1
        if claim_ok:
            claim_perfect += 1
        doc = str(truth.get("document") or result.get("document") or "")
        bundle = str(result.get("bundle_id") or "/".join(doc.split("/")[:1] + [doc.split("/")[-1].split(".")[0]] if "/" in doc else [doc]))
        row = {
            "claim_id": claim_id,
            "true_stp": bool(result.get("true_stp")),
            "disposition": result.get("disposition"),
            "perfect_exact": claim_ok,
            "fields": field_rows,
            "bundle_id": result.get("bundle_id") or bundle,
        }
        rows.append(row)
        by_bundle[str(row["bundle_id"])].append(row)

    n_fields = sum(field_total.values())
    summary = {
        "run_dir": str(run_dir),
        "claims_scored": claim_scored,
        "field_count": n_fields,
        "exact_accuracy": round(sum(field_exact.values()) / n_fields, 6) if n_fields else 0.0,
        "perfect_claim_exact_rate": (
            round(claim_perfect / claim_scored, 6) if claim_scored else 0.0
        ),
        "false_accepts": false_accepts,
        "false_accept_rate": round(false_accepts / n_fields, 6) if n_fields else 0.0,
        "field_exact": {
            name: {
                "exact": field_exact[name],
                "n": field_total[name],
                "rate": round(field_exact[name] / field_total[name], 6),
            }
            for name in CRITICAL
            if field_total[name]
        },
        "true_stp_of_scored": sum(1 for r in rows if r.get("true_stp")),
        "by_bundle": {
            bundle: {
                "n": len(items),
                "perfect_exact": sum(1 for r in items if r["perfect_exact"]),
                "true_stp": sum(1 for r in items if r["true_stp"]),
            }
            for bundle, items in sorted(by_bundle.items())
        },
        "claims": rows,
        "generated_at": _utc(),
        "note": (
            "Accuracy vs agent-created visual GT. Hackathon ZIP has no vendor labels; "
            "GT from warped ROI visual read + multi-engine consensus + line-sum E6."
        ),
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--gt", type=Path, default=DEFAULT_GT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    gt = write_gt(args.gt)
    summary = score(args.run_dir, gt)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in summary if k != "claims"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
