"""Prepare editable, truth-free inputs for safely reducing HITL.

The command uses frozen inference output only.  It never converts a prediction
into an authoritative label and never activates a route.  Instead it produces
review/reference and route-promotion templates that an owner can complete.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from packages.hitl_optimization import identity_key, route_key


def _reason(row: dict[str, Any]) -> str:
    return str((row.get("provenance") or {}).get("reason") or "UNKNOWN")


def _field(row: dict[str, Any]) -> str:
    return str((row.get("field_identity") or {}).get("semantic_field") or "UNKNOWN")


def _family(row: dict[str, Any]) -> str:
    return str((row.get("field_identity") or {}).get("document_family") or "UNKNOWN")


def prepare(predictions: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    review = [row for row in predictions if row.get("review_required")]
    critical = set(policy["critical_identity_fields"])
    reference_reasons = set(policy["reference_required_reasons"])
    references: list[dict[str, Any]] = []
    route_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in review:
        field = _field(row)
        needs_reference = field in critical or _reason(row) in reference_reasons
        if needs_reference:
            identity = row.get("field_identity") or {}
            references.append({
                "identity_key": identity_key(row),
                "document_id": identity.get("document_id"),
                "page_number": identity.get("page_number"),
                "document_family": _family(row),
                "field_name": field,
                "current_candidate": row.get("normalized_value") or row.get("selected_value"),
                "reference_value": "",
                "decision": "PENDING",
                "reference_provider": "",
                "reference_dataset_version": "",
                "matching_attributes": "",
                "contradictions": "",
                "approved_by": "",
                "approved_at": "",
                "comment": "",
            })
        else:
            route_rows[route_key(row)].append(row)

    routes = []
    for key, rows in sorted(route_rows.items()):
        validations = Counter(
            validation
            for row in rows
            for validation in (row.get("validation_results") or [])
        )
        routes.append({
            "route_key": key,
            "document_family": _family(rows[0]),
            "field_name": _field(rows[0]),
            "review_fields": len(rows),
            "observed_validations": dict(sorted(validations.items())),
            "status": "PROPOSED",
            "holdout_field_count": 0,
            "selective_accuracy": None,
            "critical_false_accepts": None,
            "invalid_crop_abstention": None,
            "approved_by": "",
            "approved_at": "",
            "comment": "",
        })

    by_reason = Counter(_reason(row) for row in review)
    by_field = Counter(_field(row) for row in review)
    by_family = Counter(_family(row) for row in review)
    return {
        "summary": {
            "total_fields": len(predictions),
            "already_automated_fields": len(predictions) - len(review),
            "review_fields": len(review),
            "current_hitl_rate": len(review) / len(predictions) if predictions else 0.0,
            "reference_decisions_to_complete": len(references),
            "routes_to_validate": len(routes),
            "ground_truth_loaded": False,
            "automatic_approvals_created": 0,
        },
        "by_reason": dict(by_reason.most_common()),
        "by_field": dict(by_field.most_common()),
        "by_family": dict(by_family.most_common()),
        "reference_rows": references,
        "route_rows": routes,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_readme(path: Path, result: dict[str, Any]) -> None:
    summary = result["summary"]
    content = f"""# HITL closure kit

Generated from frozen inference without loading evaluation truth.

## Current state

- Total fields: {summary['total_fields']}
- Already automated: {summary['already_automated_fields']}
- Review-routed: {summary['review_fields']}
- Current HITL rate: {summary['current_hitl_rate']:.2%}
- Reference decisions to complete: {summary['reference_decisions_to_complete']}
- Field/family routes to validate: {summary['routes_to_validate']}

## What to edit

1. Open `reference_decisions_template.csv`.
2. Enter an independently verified `reference_value` and supporting provider/version.
3. Set `decision` to `REFERENCE_VERIFIED` only after multi-attribute verification.
4. Use `REFERENCE_CONTRADICTION` for conflicting evidence; otherwise leave `PENDING`.
5. Do not activate anything in `active_routes_template.yaml` until its frozen holdout passes.

The `current_candidate` column is convenience evidence, not ground truth. It must
not be copied into `reference_value` without independent verification.
"""
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=Path("config/evaluation/hitl_optimization.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    policy = yaml.safe_load(args.policy.read_text(encoding="utf-8"))
    result = prepare(predictions, policy)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps({key: value for key, value in result.items() if not key.endswith("_rows")}, indent=2),
        encoding="utf-8",
    )
    (args.output / "reference_decisions_template.json").write_text(
        json.dumps(result["reference_rows"], indent=2), encoding="utf-8"
    )
    _write_csv(args.output / "reference_decisions_template.csv", result["reference_rows"])
    (args.output / "active_routes_template.yaml").write_text(
        yaml.safe_dump(result["route_rows"], sort_keys=False), encoding="utf-8"
    )
    _write_readme(args.output / "README.md", result)
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
