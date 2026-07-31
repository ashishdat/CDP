"""Freeze v2/v3 contracts and truth artifacts from governed evaluation sources."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evaluation.reporting_v3_common import (
    assert_unique,
    contract_checksum,
    normalize,
    sha256_file,
)

RESULTS = Path("evaluation_results")
CONTRACTS = Path("evaluation_data/contracts")
PILOT = RESULTS / "table_crop_quality_pilot"


def _source_rows() -> dict[tuple[str, str], dict]:
    rows = []
    for path in (
        RESULTS / "structured_rollout/cms1500/details.json",
        RESULTS / "structured_rollout/ub04/details.json",
    ):
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    for family in ("laboratory_invoice", "statement", "psychological_receipt", "cms_attachment"):
        rows.extend(json.loads(
            (RESULTS / f"attachment_rollout/{family}/details.json").read_text(encoding="utf-8")
        ))
    return {(row["document_id"], row["field_name"]): row for row in rows}


def _v2() -> tuple[list[dict], list[dict], list[dict]]:
    decisions = json.loads(
        (RESULTS / "current_v2_router/details.json").read_text(encoding="utf-8")
    )
    sources = _source_rows()
    fields, labels, predictions = [], [], []
    for row in decisions:
        source = sources[(row["document_id"], row["field_name"])]
        family = source.get("family") or source.get("document_family") or (
            "CMS1500" if row["document_id"].startswith("A-") else
            "UB04" if row["document_id"].startswith("C-") else "attachment"
        )
        identity = {
            "document_id": row["document_id"], "page_number": row.get("expected_page", 1),
            "document_family": family, "form_version": source.get("form_version"),
            "form_locator": source.get("form_locator"),
            "service_line_number": source.get("service_line_number"),
            "semantic_field": row["field_name"],
        }
        data_type = source.get("data_type") or "text"
        fields.append({
            "field_identity": identity, "eligibility_status": "ELIGIBLE",
            "criticality": "CRITICAL" if row["critical"] else "NONCRITICAL",
            "expected_data_type": data_type, "normalization_policy_version": "v2",
            "label_version": "extraction-v2",
        })
        labels.append({
            "field_identity": identity, "expected_value": source.get("expected"),
            "normalized_expected_value": normalize(source.get("expected"), data_type),
            "label_version": "extraction-v2", "approval_status": "FROZEN_EVALUATION_LABEL",
        })
        predictions.append({
            "field_identity": identity, "selected_value": row.get("selected_value"),
            "normalized_value": normalize(row.get("selected_value"), data_type),
            "candidate_status": "REVIEW_ONLY" if row["review_required"] else "AUTO_ACCEPTED",
            "review_required": row["review_required"], "provider": "extraction-v2-reconciliation",
            "provider_version": row.get("reconciliation_policy", "v2"),
            "confidence": row.get("value_score", row.get("score", 0.0)),
            "validation_results": [], "crop_quality": "LEGACY_VALIDATED",
            "row_status": "NOT_APPLICABLE", "provenance": {
                "selected_page": row.get("selected_page"),
                "expected_page_evaluation_only": row.get("expected_page"),
                "reason": row.get("reason"),
            },
            "automatically_acceptable": not row["review_required"],
        })
    return fields, labels, predictions


def _table() -> tuple[list[dict], list[dict], list[str]]:
    manifest = {
        row["candidate_id"]: row
        for row in (
            json.loads(line)
            for line in (PILOT / "pilot_manifest.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    events = [
        json.loads(line)
        for line in Path(
            "evaluation_data/table_labels/crop_quality_pilot_review_events.jsonl"
        ).read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    generic = lambda value: re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    value_counts = Counter(
        (manifest[row["candidate_id"]]["document_id"], generic(row.get("expected_value")))
        for row in events if generic(row.get("expected_value"))
    )
    invalid = {
        row["candidate_id"] for row in events
        if value_counts[(
            manifest[row["candidate_id"]]["document_id"],
            generic(row.get("expected_value")),
        )] >= 3
    }
    fields, labels = [], []
    for event in events:
        if event["candidate_id"] in invalid:
            continue
        item = manifest[event["candidate_id"]]
        identity = {
            "document_id": item["document_id"], "page_number": item["page_number"],
            "document_family": item["document_family"], "form_version": item["form_version"],
            "form_locator": item["form_locator"],
            "service_line_number": item["service_line_number"],
            "semantic_field": item["semantic_field_name"],
        }
        fields.append({
            "field_identity": identity, "eligibility_status": "ELIGIBLE",
            "criticality": "NONCRITICAL", "expected_data_type": item["data_type"],
            "normalization_policy_version": "table-v3",
            "label_version": "crop-pilot-v3", "candidate_id": event["candidate_id"],
        })
        labels.append({
            "field_identity": identity, "expected_value": event.get("expected_value"),
            "normalized_expected_value": normalize(
                event.get("expected_value"), item["data_type"]
            ),
            "label_version": "crop-pilot-v3", "approval_status": event["status"],
            "disposition": event["disposition"], "candidate_id": event["candidate_id"],
        })
    return fields, labels, sorted(invalid)


def _write_contract(version: str, fields: list[dict], created_at: str) -> dict:
    assert_unique(fields)
    document_hashes = {}
    for row in fields:
        document_id = row["field_identity"]["document_id"]
        asset = RESULTS / "assets" / f"{document_id}.png"
        if asset.is_file():
            document_hashes[document_id] = sha256_file(asset)
    contract = {
        "contract_version": version, "created_at": created_at,
        "dataset_version": "claims-idp-evaluation-2026-07",
        "normalization_policy_version": "v3", "document_hashes": document_hashes,
        "eligible_field_count": len(fields), "fields": fields,
    }
    contract["contract_sha256"] = contract_checksum(contract)
    return contract


def main() -> int:
    CONTRACTS.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC).isoformat()
    v2_fields, v2_labels, v2_predictions = _v2()
    table_fields, table_labels, invalid = _table()
    if len(v2_fields) != 214 or len(table_fields) != 25:
        raise RuntimeError(
            f"contract gate failed: v2={len(v2_fields)}, table={len(table_fields)}"
        )
    v2 = _write_contract("extraction-v2", v2_fields, created_at)
    v3 = _write_contract("evaluation-contract-v3", v2_fields + table_fields, created_at)
    for name, contract in (("evaluation_contract_v2", v2), ("evaluation_contract_v3", v3)):
        path = CONTRACTS / f"{name}.json"
        path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
        (CONTRACTS / f"{name}.sha256").write_text(
            contract["contract_sha256"] + "\n", encoding="ascii"
        )
    Path("config/evaluation/evaluation_contract_v3.yaml").write_text(
        yaml.safe_dump(v3, sort_keys=False), encoding="utf-8"
    )
    (CONTRACTS / "evaluation_contract_v2_labels.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in v2_labels) + "\n",
        encoding="utf-8",
    )
    (CONTRACTS / "approved_cell_labels.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in table_labels) + "\n",
        encoding="utf-8",
    )
    migration = RESULTS / "predictions_v2"
    migration.mkdir(exist_ok=True)
    (migration / "predictions.json").write_text(
        json.dumps(v2_predictions, indent=2), encoding="utf-8"
    )
    summary = {
        "v2_fields": len(v2_fields), "v3_fields": len(v3["fields"]),
        "table_fields": len(table_fields), "invalid_repeated_labels_excluded": len(invalid),
        "invalid_candidate_ids": invalid, "v3_contract_sha256": v3["contract_sha256"],
    }
    (CONTRACTS / "freeze_manifest.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
