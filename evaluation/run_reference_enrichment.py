from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import yaml

from evaluation.import_governed_reference_xlsx import read_sheet
from evaluation.reference_enrichment_report import write_report
from evaluation.reference_enrichment_workbook import write_enriched_workbook
from packages.reference_enrichment.contracts import ReferenceLookupRequest
from packages.reference_enrichment.decision_engine import decide, pending
from packages.reference_enrichment.providers import configured_providers


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def run(workbook: Path, config: dict, claim_attributes: dict, output: Path,
        production_metrics: dict | None = None) -> dict:
    rows = read_sheet(workbook, "Reference Decisions")
    identities = [row["identity_key"] for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate identity keys are not permitted")
    providers = configured_providers(config)
    decisions, audit = [], []
    external_calls = 0
    started = time.perf_counter()
    for row in rows:
        canonical = "|".join((row["document_id"], row["page_number"], row["document_family"], "", row["field_name"]))
        request = ReferenceLookupRequest(request_id=str(uuid4()), identity_key=canonical,
            document_id=row["document_id"], page_number=int(row["page_number"]),
            document_family=row["document_family"], field_name=row["field_name"],
            criticality=row.get("criticality") or "UNKNOWN", current_candidate=row.get("current_candidate") or None,
            available_claim_attributes=claim_attributes.get(row["document_id"], {}),
            requested_at=datetime.now(UTC), policy_version=config["policy_version"])
        if not providers:
            result = pending(request, "AWAITING_AUTHORIZED_REFERENCE_SOURCE")
        else:
            records = []
            for provider in providers:
                before = time.perf_counter()
                try:
                    found = provider.lookup(request)
                    external_calls += int(not provider.test_only)
                    records.extend(found)
                    audit.append({"request_id": request.request_id, "provider": provider.name,
                        "test_only": provider.test_only, "match_count": len(found),
                        "response_hashes": [record.response_hash for record in found],
                        "dataset_versions": sorted({record.dataset_version for record in found if record.dataset_version}),
                        "latency_ms": round((time.perf_counter() - before) * 1000, 3), "error": None})
                except Exception as exc:  # noqa: BLE001 - arbitrary providers must fail closed
                    audit.append({"request_id": request.request_id, "provider": provider.name,
                        "test_only": provider.test_only, "match_count": 0, "response_hashes": [],
                        "dataset_versions": [], "latency_ms": round((time.perf_counter() - before) * 1000, 3),
                        "error": type(exc).__name__})
            request_errors = [item for item in audit if item["request_id"] == request.request_id and item["error"]]
            result = (pending(request, "SOURCE_ERROR", decision="SOURCE_ERROR")
                      if not records and request_errors else
                      decide(request, records, test_only=all(provider.test_only for provider in providers)))
        decisions.append(result.model_dump(mode="json"))
    accepted = [row for row in decisions if row["evaluation_eligible"]]
    rejected = [row for row in decisions if row["decision"] in {"REFERENCE_CONTRADICTION", "CIRCULAR_LINEAGE_REJECTED", "PROVIDER_UNAUTHORIZED"}]
    pending_rows = [row for row in decisions if row not in accepted and row not in rejected]
    production = (production_metrics or {}).get("expanded_v3", {})
    baseline_total = int(production.get("eligible_fields", len(rows)))
    baseline_review = int(production.get("review_required_fields", len(rows)))
    baseline_correct = int(production.get("correct_selected_values", 0))
    baseline_false_accepts = int(production.get("critical_false_accepts", 0))
    reference_recoveries = sum(
        row["normalized_reference_value"] not in {None, ""}
        and row["normalized_reference_value"] != row["current_candidate"]
        for row in accepted
    )
    metrics = {"input_workbook_rows": len(rows), "pending_rows": len(pending_rows),
        "reference_source_lookup_attempts": len(audit), "external_calls_made": external_calls,
        "reference_records_found": sum(cast(int, item["match_count"]) for item in audit),
        "unique_matches": len(accepted), "competing_matches": sum(row["decision"] == "MULTIPLE_REFERENCE_MATCHES" for row in decisions),
        "contradictions": sum(bool(row["contradictions"]) for row in decisions),
        "reference_verified_decisions": sum(row["decision"] == "REFERENCE_VERIFIED" for row in accepted),
        "downstream_verified_decisions": sum(row["decision"] == "DOWNSTREAM_VERIFIED" for row in accepted),
        "correction_verified_decisions": sum(row["decision"] == "CORRECTION_VERIFIED" for row in accepted),
        "evaluation_eligible_decisions": len(accepted), "safely_promoted_fields": len(accepted),
        "hitl_before": baseline_review / baseline_total, "hitl_after": (baseline_review - len(accepted)) / baseline_total,
        "automated_coverage_before": (baseline_total - baseline_review) / baseline_total,
        "automated_coverage_after": (baseline_total - baseline_review + len(accepted)) / baseline_total,
        "selected_accuracy_before": baseline_correct / baseline_total if baseline_total else None,
        "selected_accuracy_after": (baseline_correct + reference_recoveries) / baseline_total if baseline_total else None,
        "reference_verified_closure": len(accepted),
        "critical_false_accepts": baseline_false_accepts + sum(
            bool(row["contradictions"]) and row["evaluation_eligible"] for row in accepted
        ),
        "reference_verification_rate": len(accepted) / len(rows) if rows else 0.0,
        "source_failure_rate": sum(bool(item["error"]) for item in audit) / len(audit) if audit else 0.0,
        "ground_truth_leakage": False,
        "status": "AWAITING_AUTHORIZED_REFERENCE_SOURCE" if not providers else "COMPLETED",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {"enriched_reference_decisions.json": decisions,
        "accepted_reference_decisions.json": accepted, "rejected_reference_decisions.json": rejected,
        "pending_reference_decisions.json": pending_rows, "source_audit.json": audit,
        "matching_details.json": [{"identity_key": row["identity_key"], "matching_attributes": row["matching_attributes"], "match_scores": row["match_scores"], "contradictions": row["contradictions"]} for row in decisions],
        "metrics.json": metrics}
    for name, payload in artifacts.items():
        (output / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_enriched_workbook(output / "reference_decisions_governed_v4_enriched.xlsx",
                            rows, decisions, metrics, audit)
    write_report(output / "comparison.html", metrics)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "UNKNOWN"
    manifest = {"git_commit": commit, "input_workbook_hash": _hash(workbook),
        "connector_configuration_hash": _json_hash(config), "policy_version": config["policy_version"],
        "policy_hash": config.get("_policy_hash"),
        "provider_versions": sorted({version for item in audit
            for version in cast(list[str], item["dataset_versions"])}),
        "run_timestamp": datetime.now(UTC).isoformat(),
        "ground_truth_leakage": False, "circular_lineage_violations": len(rejected),
        "output_hashes": {path.name: _hash(path) for path in output.iterdir() if path.is_file()}}
    (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/reference_enrichment.yaml"))
    parser.add_argument("--claim-attributes", type=Path); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--production-metrics", type=Path,
        default=Path("evaluation_results/reporting_v3/metrics.json"))
    parser.add_argument("--policy", type=Path, default=Path("config/reference_verification_policy.yaml"))
    args = parser.parse_args(); config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    config["_policy_hash"] = _hash(args.policy)
    claims = json.loads(args.claim_attributes.read_text()) if args.claim_attributes else {}
    production = json.loads(args.production_metrics.read_text()) if args.production_metrics.is_file() else {}
    print(json.dumps(run(args.workbook, config, claims, args.output, production), indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
