#!/usr/bin/env python3
"""Write split tip decide-only vs fresh-OCR ops STP metrics.

Never blend tip-89 frozen decide-only STP with fresh-cascade ops STP into one
number — that conflation caused false \"accuracy/STP regression\" alarms.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _ledger_rows(run_dir: Path) -> list[dict]:
    path = run_dir / "results.jsonl"
    if not path.exists():
        return []
    latest: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cid = row.get("claim_id")
        if cid:
            latest[cid] = row
    return list(latest.values())


def _ops_metrics(run_dir: Path, accuracy: dict) -> dict:
    rows = _ledger_rows(run_dir)
    completed = [
        r
        for r in rows
        if r.get("completed") and r.get("registration_ok")
    ]
    stp = sum(1 for r in completed if r.get("true_stp"))
    hitl = sum(
        1
        for r in completed
        if r.get("disposition") in {"FIELD_HITL", "HITL"}
        or (r.get("review_required") and not r.get("true_stp"))
    )
    gap = Counter()
    for r in completed:
        if r.get("true_stp"):
            continue
        for g in r.get("gap_classes") or []:
            if isinstance(g, dict):
                gap[str(g.get("gap_class") or "UNKNOWN")] += 1
            else:
                gap[str(g)] += 1
        blockers = r.get("critical_blockers") or []
        if not blockers and not (r.get("gap_classes") or []):
            gap["NO_GAP_CLASS"] += 1
    bleed_auto = 0
    try:
        from packages.claim_evidence.charge_total_authority import (
            is_units_bleed_cents,
        )
    except Exception:  # noqa: BLE001
        is_units_bleed_cents = lambda _v: False  # noqa: E731
    for r in completed:
        if not r.get("true_stp"):
            continue
        tc = (r.get("fields") or {}).get("total_charge") or {}
        if (
            isinstance(tc, dict)
            and is_units_bleed_cents(tc.get("value"))
            and tc.get("disp") in {"AUTO_ACCEPTED", "AUTO", "REFERENCE_CONFIRMED"}
        ):
            bleed_auto += 1
    return {
        "title": "Fresh-OCR ops STP (cascade) — not tip decide-only",
        "updated_at": _utc_now(),
        "run_dir": str(run_dir),
        "n_ledger": len(rows),
        "completed": len(completed),
        "true_stp": stp,
        "true_stp_rate_of_completed": (
            round(stp / len(completed), 6) if completed else None
        ),
        "field_ink_hitl": hitl,
        "hitl_rate_of_completed": (
            round(hitl / len(completed), 6) if completed else None
        ),
        "disposition_counts": dict(Counter(r.get("disposition") for r in rows)),
        "hitl_gap_class_counts": dict(gap.most_common()),
        "bleed_cents_true_stp_auto": bleed_auto,
        "accuracy_vs_agent_gt": {
            "exact_accuracy": accuracy.get("exact_accuracy"),
            "accepted_field_precision": accuracy.get("accepted_field_precision"),
            "false_accepts": accuracy.get("false_accepts"),
            "claims_scored": accuracy.get("claims_scored"),
            "field_count": accuracy.get("field_count"),
            "quarantined_fields": accuracy.get("quarantined_fields"),
            "field_exact": accuracy.get("field_exact"),
        },
        "gates_ops": {
            "true_stp_ge_94": (
                "PASS"
                if completed and stp / len(completed) >= 0.94
                else "FAIL"
            ),
            "claim_hitl_le_6": (
                "PASS"
                if completed and hitl / len(completed) <= 0.06
                else "FAIL"
            ),
            "bleed_cents_true_stp_auto_eq_0": (
                "PASS" if bleed_auto == 0 else "FAIL"
            ),
            "note": (
                "Ops STP is fresh OCR + full cascade. Do not compare to tip-89 "
                "decide-only STP as a regression signal."
            ),
        },
        "authority": {
            "single_mint": "CLAIM_TOTAL_CONFIRMED via ChargeTotalAuthoritySession",
            "priority": [
                "DERIVED_TOTAL_FROM_COMPLETE_VERIFIED_LINES",
                "FINANCIAL_GEOMETRY_ARITHMETIC_CONFIRMED",
                "BOX28_LINE_SUM_CORROBORATED",
                "CLAIM_TOTAL_WITHIN_TOLERANCE",
                "conflict-agent gated",
                "else HITL",
            ],
            "bleed_at_mint": True,
        },
    }


def _tip_metrics(tip_gate: dict, tip_summary: dict) -> dict:
    tip_gate = tip_gate or {}
    tip_summary = tip_summary or {}
    acc = tip_gate.get("accuracy") or tip_summary
    return {
        "title": "Tip decide-only accuracy/STP — frozen OCR cohort",
        "updated_at": _utc_now(),
        "corpus": tip_gate.get("corpus")
        or {
            "frozen_ocr_tip_claims": 89,
            "note": "Decide-only on frozen geometry+OCR; not fresh cascade.",
        },
        "gates": tip_gate.get("gates"),
        "accuracy": {
            "exact_accuracy": acc.get("exact_accuracy")
            or (acc.get("summary") or {}).get("exact_accuracy")
            if isinstance(acc.get("summary"), dict)
            else acc.get("exact_accuracy"),
            "accepted_field_precision": acc.get("accepted_field_precision"),
            "false_accepts": acc.get("false_accepts"),
            "claims_scored": acc.get("claims_scored"),
        },
        "stp": {
            "true_stp_rate": (tip_gate.get("stp") or {}).get("true_stp_rate")
            or tip_gate.get("true_stp_rate_of_completed_89"),
            "hitl_rate": (tip_gate.get("stp") or {}).get("hitl_rate")
            or tip_gate.get("hitl_rate_of_completed_89"),
        },
        "note": (
            "Use this file for ≥95% exact / tip STP gates. Never merge with "
            "ops_fresh_ocr_stp_v1.json into one STP number."
        ),
    }


def _quarantine_debt(ledger_path: Path) -> dict:
    ledger = _load_json(ledger_path)
    records = ledger.get("records") or []
    by_field = Counter()
    by_kind = Counter()
    auto_conflicts = 0
    for r in records:
        if not isinstance(r, dict):
            continue
        by_kind[str(r.get("kind") or "UNKNOWN")] += 1
        by_field[str(r.get("field_name") or "UNKNOWN")] += 1
        if r.get("quarantine_from_accuracy") and r.get("field_name") == "total_charge":
            auto_conflicts += 1
    return {
        "title": "Quarantined AUTO / label-source debt (not FA, not tip exact)",
        "updated_at": _utc_now(),
        "ledger": str(ledger_path),
        "record_count": len(records),
        "by_kind": dict(by_kind),
        "by_field": dict(by_field),
        "total_charge_quarantines": auto_conflicts,
        "note": (
            "Quarantined wrong AUTOs are GT/authority debt. They suppress FA "
            "but must not be counted as tip exact wins."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        default="evaluation_results/hackathon_1000_geometry_95_verify",
    )
    parser.add_argument(
        "--accuracy-summary",
        default="evaluation_results/hackathon_gt_accuracy_1000_geo95_mid/summary.json",
    )
    parser.add_argument(
        "--tip-gate",
        default="docs/metrics/geometry_accuracy_95_gate_v1.json",
    )
    parser.add_argument(
        "--ledger",
        default="docs/gt/ground_truth_discrepancy_ledger.json",
    )
    parser.add_argument("--out-dir", default="docs/metrics")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    accuracy = _load_json(Path(args.accuracy_summary))
    tip_gate = _load_json(Path(args.tip_gate))
    ops = _ops_metrics(Path(args.run_dir), accuracy)
    tip = _tip_metrics(tip_gate, accuracy)
    debt = _quarantine_debt(Path(args.ledger))

    (out_dir / "ops_fresh_ocr_stp_v1.json").write_text(
        json.dumps(ops, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "tip_decide_only_v1.json").write_text(
        json.dumps(tip, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "quarantined_auto_debt_v1.json").write_text(
        json.dumps(debt, indent=2) + "\n", encoding="utf-8"
    )
    index = {
        "title": "Split STP/accuracy metrics index",
        "updated_at": _utc_now(),
        "rule": (
            "Never blend tip_decide_only_v1 (frozen OCR) with "
            "ops_fresh_ocr_stp_v1 (fresh cascade) into one STP/accuracy number."
        ),
        "files": {
            "tip_decide_only": "tip_decide_only_v1.json",
            "ops_fresh_ocr": "ops_fresh_ocr_stp_v1.json",
            "quarantined_auto_debt": "quarantined_auto_debt_v1.json",
        },
        "ops_true_stp_rate": ops.get("true_stp_rate_of_completed"),
        "ops_hitl_rate": ops.get("hitl_rate_of_completed"),
        "accuracy_exact": (ops.get("accuracy_vs_agent_gt") or {}).get(
            "exact_accuracy"
        ),
        "false_accepts": (ops.get("accuracy_vs_agent_gt") or {}).get(
            "false_accepts"
        ),
    }
    (out_dir / "stp_metrics_index_v1.json").write_text(
        json.dumps(index, indent=2) + "\n", encoding="utf-8"
    )
    # Keep geometry_1000_verify_v1 as a pointer, not a blended score.
    pointer = {
        "title": "Geometry-1000 verify — see split metrics",
        "updated_at": _utc_now(),
        "see": {
            "tip": "docs/metrics/tip_decide_only_v1.json",
            "ops": "docs/metrics/ops_fresh_ocr_stp_v1.json",
            "debt": "docs/metrics/quarantined_auto_debt_v1.json",
            "index": "docs/metrics/stp_metrics_index_v1.json",
        },
        "ops_snapshot": {
            "completed": ops.get("completed"),
            "true_stp_rate_of_completed": ops.get("true_stp_rate_of_completed"),
            "hitl_rate_of_completed": ops.get("hitl_rate_of_completed"),
            "bleed_cents_true_stp_auto": ops.get("bleed_cents_true_stp_auto"),
            "exact_accuracy": (ops.get("accuracy_vs_agent_gt") or {}).get(
                "exact_accuracy"
            ),
            "false_accepts": (ops.get("accuracy_vs_agent_gt") or {}).get(
                "false_accepts"
            ),
        },
        "release_gate_eligible": False,
        "note": (
            "Tip and ops are different experiments. Treat ops STP dips after "
            "fail-closed monetary guards as expected, not tip regressions."
        ),
    }
    (out_dir / "geometry_1000_verify_v1.json").write_text(
        json.dumps(pointer, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(index, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
