#!/usr/bin/env python3
"""Build agent ground truth for Hackathon claims from observed OCR consensus.

Honesty
-------
Hackathon ZIP has no vendor field labels. This script creates **agent GT**:

  GOLD   — ≥2 route engines agree after span-select + field-shape
  SILVER — single shaped engine OR AUTO_ACCEPTED with HARD_VALIDATION / line-sum
  skip   — conflict / empty / label-contaminated / unreadable (no invented ink)

Seed visual labels from ``score_hackathon_gt_accuracy.SEED_VISUAL_GT`` win on
overlap (human/agent visual read beats consensus).

Writes:
  evaluation_data/hackathon_agent_gt/field_truth.json
  evaluation_results/<run>/gt_accuracy.json  (optional --score-run)
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys_path_note = str(ROOT)

import sys

sys.path.insert(0, str(ROOT))

from packages.extraction_recovery.field_cascade import semantic_accept
from packages.extraction_recovery.span_selection import (
    select_field_span,
    span_datatype_for_field,
)
from scripts.score_hackathon_gt_accuracy import (
    CRITICAL,
    SEED_VISUAL_GT,
    _canon_date,
    _canon_id,
    _canon_money,
    _canon_name,
    score,
)

DEFAULT_GT = ROOT / "evaluation_data" / "hackathon_agent_gt" / "field_truth.json"
AUTO = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED", "ACCEPTED", "AUTO"}
ROUTE_ENGINES = {"paddleocr", "rapidocr", "tesseract", "tesseract_digits"}


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_key(field: str, value: str) -> str:
    if field in {"patient_dob", "date_of_birth"}:
        return _canon_date(value)
    if field in {"insured_id_number", "member_id"}:
        return _canon_id(value)
    if field in {"patient_name", "insured_name"}:
        return _canon_name(value)
    if field in {"total_charge", "total_charges"}:
        return _canon_money(value)
    return str(value or "").strip().upper()


def _display_for(field: str, value: str) -> str:
    """Canonical display form for GT expected_value."""
    if field in {"patient_dob", "date_of_birth"}:
        return _canon_date(value)
    if field in {"total_charge", "total_charges"}:
        return _canon_money(value)
    if field in {"insured_id_number", "member_id"}:
        # Keep alphanumeric member ids as observed compact form.
        return _canon_id(value)
    # Names: prefer spaced uppercase tokens from the winning display.
    text = re.sub(r"[^A-Za-z0-9,.\- ]", " ", value or "")
    text = re.sub(r"\s+", " ", text).strip(" .,")
    return text.upper()


def _shaped_candidates(field: str, ocr_field: dict[str, Any]) -> list[tuple[str, str, float]]:
    """Return (engine, shaped_value, conf) after span-select + semantic_accept."""
    datatype = span_datatype_for_field(field, "")
    out: list[tuple[str, str, float]] = []
    for cand in ocr_field.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        engine = str(cand.get("engine") or "").casefold()
        if engine not in ROUTE_ENGINES:
            continue
        raw = str(cand.get("raw_value") or cand.get("value") or "")
        seed = str(cand.get("value") or raw or "").strip()
        if not seed and not raw.strip():
            continue
        span = select_field_span(seed or raw, datatype, field)
        selected = (span.selected_text or "").strip()
        if not selected:
            continue
        ok, _reason = semantic_accept(field, selected)
        if not ok:
            continue
        conf = float(cand.get("raw_confidence") or 0.0)
        out.append((engine, selected, conf))
    return out


def _consensus_for_field(
    field: str,
    ocr_field: dict[str, Any] | None,
    result_field: dict[str, Any] | None,
) -> dict[str, Any] | None:
    shaped = _shaped_candidates(field, ocr_field or {})
    by_key: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for engine, value, conf in shaped:
        key = _normalize_key(field, value)
        if key:
            by_key[key].append((engine, value, conf))

    # Prefer multi-engine agreement (distinct engines).
    best_key = None
    best_group: list[tuple[str, str, float]] = []
    for key, group in by_key.items():
        engines = {e for e, _, _ in group}
        if len(engines) >= 2 and (
            best_key is None
            or len(engines) > len({e for e, _, _ in best_group})
            or max(c for _, _, c in group) > max((c for _, _, c in best_group), default=0)
        ):
            best_key, best_group = key, group

    if best_key and len({e for e, _, _ in best_group}) >= 2:
        # Prefer higher-confidence display among agreeing engines.
        display = max(best_group, key=lambda item: item[2])[1]
        return {
            "expected_value": _display_for(field, display),
            "source": "multi_engine_consensus:"
            + "+".join(sorted({e for e, _, _ in best_group})),
            "confidence": "GOLD",
        }

    # SILVER: AUTO_ACCEPTED with hard validation / line-sum, if shaped.
    if result_field:
        disp = str(result_field.get("disp") or "")
        value = str(result_field.get("value") or "").strip()
        reasons = set(result_field.get("reasons") or [])
        if disp in AUTO and value:
            ok, _ = semantic_accept(field, value)
            hard = bool(
                reasons
                & {
                    "HARD_VALIDATION_PASSED",
                    "DATE_VALID",
                    "LINE_TOTALS_RECONCILED",
                    "FORMAT_VALID",
                }
            )
            if ok and hard:
                return {
                    "expected_value": _display_for(field, value),
                    "source": "auto_accepted+"
                    + (
                        "line_sum"
                        if "LINE_TOTALS_RECONCILED" in reasons
                        else "hard_validation"
                    ),
                    "confidence": "SILVER",
                }

    # SILVER: single shaped engine with conf ≥ 0.90 and no competing shaped key.
    if len(by_key) == 1:
        key, group = next(iter(by_key.items()))
        top = max(group, key=lambda item: item[2])
        if top[2] >= 0.90:
            return {
                "expected_value": _display_for(field, top[1]),
                "source": f"single_engine_shaped:{top[0]}",
                "confidence": "SILVER",
            }

    return None


def build_from_run(run_dir: Path) -> dict[str, dict[str, Any]]:
    claims: dict[str, dict[str, Any]] = {}
    claims_dir = run_dir / "claims"
    if not claims_dir.exists():
        return claims
    for claim_dir in sorted(claims_dir.iterdir()):
        if not claim_dir.is_dir():
            continue
        result_path = claim_dir / "result.json"
        ocr_path = claim_dir / "ocr" / "OCRCandidates.json"
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("completed"):
            continue
        ocr_by_field: dict[str, dict[str, Any]] = {}
        if ocr_path.exists():
            ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
            for item in ocr.get("fields") or []:
                if isinstance(item, dict) and item.get("field"):
                    ocr_by_field[str(item["field"])] = item
        result_fields = result.get("fields") or {}
        field_gt: dict[str, Any] = {}
        for field in CRITICAL:
            meta = _consensus_for_field(
                field,
                ocr_by_field.get(field),
                result_fields.get(field) if isinstance(result_fields.get(field), dict) else None,
            )
            if meta:
                field_gt[field] = meta
        if not field_gt:
            continue
        claims[claim_dir.name] = {
            "document": result.get("document") or claim_dir.name.replace("__", "/"),
            "fields": field_gt,
            "run_source": str(run_dir.name),
        }
    return claims


def merge_claims(*sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Later sources override earlier for the same claim+field; SEED should be last."""
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        for claim_id, payload in source.items():
            slot = merged.setdefault(
                claim_id,
                {
                    "document": payload.get("document"),
                    "fields": {},
                    "run_source": payload.get("run_source"),
                },
            )
            if payload.get("document"):
                slot["document"] = payload["document"]
            if payload.get("run_source"):
                sources_list = slot.setdefault("run_sources", [])
                if isinstance(sources_list, list) and payload["run_source"] not in sources_list:
                    sources_list.append(payload["run_source"])
            for field, meta in (payload.get("fields") or {}).items():
                slot["fields"][field] = meta
    return merged


def write_gt(path: Path, claims: dict[str, dict[str, Any]]) -> dict[str, Any]:
    conf = Counter()
    field_n = Counter()
    for payload in claims.values():
        for field, meta in (payload.get("fields") or {}).items():
            conf[str(meta.get("confidence") or "?")] += 1
            field_n[field] += 1
    payload = {
        "dataset": "Hackathon - 1000 Claims.zip",
        "created_by": "agent_consensus_gt_v2",
        "created_at": _utc(),
        "methodology": [
            "No vendor labels on Hackathon ZIP — this is agent-created GT.",
            "GOLD: ≥2 OCR engines agree after span-select + field-shape gate.",
            "SILVER: AUTO_ACCEPTED with hard validation/line-sum, or single high-conf shaped engine.",
            "Conflicts / empty / label-contaminated / unreadable ink → no GT (abstain).",
            "Seed visual ROI labels (SEED_VISUAL_GT) override consensus on overlap.",
            "Never invent DOB/amounts/IDs when ink is ambiguous.",
        ],
        "stats": {
            "claims": len(claims),
            "field_labels": sum(field_n.values()),
            "by_confidence": dict(conf),
            "by_field": dict(field_n),
        },
        "claims": claims,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        action="append",
        default=[],
        help="Cascade run dir(s) to mine consensus from (repeatable).",
    )
    parser.add_argument("--gt", type=Path, default=DEFAULT_GT)
    parser.add_argument(
        "--score-run",
        type=Path,
        action="append",
        default=[],
        help="Optional run dir(s) to score against the written GT.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "evaluation_results" / "hackathon_gt_accuracy",
    )
    args = parser.parse_args()

    run_dirs = args.run_dir or [
        ROOT / "evaluation_results" / "hackathon_50_cascade_v11",
        ROOT / "evaluation_results" / "hackathon_300_cascade_v11",
    ]
    mined: list[dict[str, dict[str, Any]]] = []
    for run_dir in run_dirs:
        run_dir = run_dir if run_dir.is_absolute() else ROOT / run_dir
        mined.append(build_from_run(run_dir))
        print(f"mined {run_dir.name}: {len(mined[-1])} claims", flush=True)

    claims = merge_claims(*mined, SEED_VISUAL_GT)
    gt = write_gt(args.gt, claims)
    print(
        json.dumps(
            {
                "gt_path": str(args.gt),
                "stats": gt["stats"],
                "seed_claims": len(SEED_VISUAL_GT),
            },
            indent=2,
        ),
        flush=True,
    )

    score_runs = args.score_run or run_dirs
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for run_dir in score_runs:
        run_dir = run_dir if run_dir.is_absolute() else ROOT / run_dir
        if not run_dir.exists():
            continue
        summary = score(run_dir, gt)
        out = args.out_dir / f"{run_dir.name}_gt_accuracy.json"
        # also drop next to the run
        run_out = run_dir / "gt_accuracy.json"
        text = json.dumps(summary, indent=2) + "\n"
        out.write_text(text, encoding="utf-8")
        run_out.write_text(text, encoding="utf-8")
        slim = {k: summary[k] for k in summary if k != "claims"}
        print(f"scored {run_dir.name}: {json.dumps(slim, indent=2)}", flush=True)
        # metrics mirror
        metrics = ROOT / "docs" / "metrics" / f"{run_dir.name}_gt_accuracy.json"
        metrics.write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
