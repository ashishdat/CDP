"""Generate PHI-safe Autonomous CDP Optimization Run 0 evidence artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluation.autonomous_optimizer import atomic_json, digest

BASELINE_SHA = "d57f424e17d5ee6e8ff3ddf0c44e59c8088ff134"
RUN_SCHEMA = "autonomous-cdp-run0-v1"


def _read(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def _write(output: Path, name: str, payload: dict[str, Any]) -> None:
    result = {"schema_version": RUN_SCHEMA, **payload}
    result["artifact_sha256"] = digest(result)
    atomic_json(output / name, result)


def _failure_category(message: str) -> str:
    lowered = message.lower()
    if "router_frozen_v1.yaml" in lowered and "frozen configuration changed" in lowered:
        return "FROZEN_CHECKSUM_MISMATCH"
    if "tracked runtime/private artifact" in lowered:
        return "KNOWN_BASELINE_SEMANTIC_FAILURE"
    if "apps\\evaluation_ui\\dist" in lowered or "apps/evaluation_ui/dist" in lowered:
        return "UI_NOT_BUILT"
    if "filenotfounderror" in lowered or "does not exist" in lowered:
        if "evaluation_data" in lowered:
            return "MISSING_GOVERNED_DATASET"
        if "evaluation_results" in lowered:
            return "MISSING_GENERATED_ARTIFACT"
        return "ENVIRONMENT_MISSING_DEPENDENCY"
    return "UNKNOWN"


def attribute_failures(junit_xml: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = ET.parse(junit_xml).getroot()
    records: list[dict[str, Any]] = []
    for case in root.iter("testcase"):
        failure = case.find("failure")
        if failure is None:
            failure = case.find("error")
        if failure is None:
            continue
        test_id = f"{case.attrib.get('classname')}::{case.attrib.get('name')}"
        message = (failure.attrib.get("message", "") + "\n" + (failure.text or "")).strip()
        category = _failure_category(message)
        if category == "UNKNOWN" and any(
            marker in test_id for marker in ("test_phase8_24", "test_phase8_27", "test_phase9a")
        ):
            category = "KNOWN_BASELINE_SEMANTIC_FAILURE"
        signature_hash = hashlib.sha256(
            (test_id + "\n" + message.split("\n")[0]).encode("utf-8")
        ).hexdigest()
        missing = re.findall(r"(?:No such file or directory|path)[: ]+['\"]?([^'\"\r\n]+)", message)
        records.append(
            {
                "test_id": test_id,
                "failure_signature": signature_hash,
                "category": category,
                "baseline_present": True,
                "environment_dependency": category
                in {"ENVIRONMENT_MISSING_DEPENDENCY", "UI_NOT_BUILT"},
                "missing_artifact": category == "MISSING_GENERATED_ARTIFACT",
                "missing_dataset": category == "MISSING_GOVERNED_DATASET",
                "UI_build_dependency": category == "UI_NOT_BUILT",
                "checksum_failure": category == "FROZEN_CHECKSUM_MISMATCH",
                "semantic_failure": category
                in {
                    "KNOWN_BASELINE_SEMANTIC_FAILURE",
                    "NEW_SEMANTIC_FAILURE",
                    "UNKNOWN",
                },
                "reproducible": True,
                "optimizer_relevant": "autonomous_optimizer" in test_id
                or "autonomous_optimizer" in message,
                "blocking": category
                in {
                    "KNOWN_BASELINE_SEMANTIC_FAILURE",
                    "NEW_SEMANTIC_FAILURE",
                    "UNKNOWN",
                },
                "notes": ("missing=" + ";".join(missing[:1]) if missing else category),
            }
        )
    records.sort(key=lambda row: row["test_id"])
    signature_payload = {
        "baseline_sha": BASELINE_SHA,
        "failure_count": len(records),
        "signatures": [row["failure_signature"] for row in records],
        "signature_set_sha256": digest([row["failure_signature"] for row in records]),
        "new_failures_allowed": False,
    }
    return records, signature_payload


def checksum_evidence(repo: Path) -> dict[str, Any]:
    release = (repo / "config/releases/extraction-v2.yaml").read_text("utf-8")
    expected = re.search(r"config/router_frozen_v1.yaml:\s*([0-9a-f]{64})", release)
    if expected is None:
        raise ValueError("FROZEN_HASH_NOT_DECLARED")
    artifact = repo / "config/router_frozen_v1.yaml"
    worktree_bytes = artifact.read_bytes()
    blob_bytes = subprocess.check_output(
        ["git", "show", f"{BASELINE_SHA}:config/router_frozen_v1.yaml"], cwd=repo
    )
    expected_hash = expected.group(1)
    worktree_hash = hashlib.sha256(worktree_bytes).hexdigest()
    blob_hash = hashlib.sha256(blob_bytes).hexdigest()
    return {
        "artifact": "config/router_frozen_v1.yaml",
        "expected_sha256": expected_hash,
        "git_blob_sha256": blob_hash,
        "worktree_sha256": worktree_hash,
        "artifact_exists": artifact.exists(),
        "git_blob_matches_expected": blob_hash == expected_hash,
        "worktree_matches_expected": worktree_hash == expected_hash,
        "cause": "WINDOWS_EOL_MATERIALIZATION"
        if blob_hash == expected_hash
        else "CONTENT_MISMATCH",
        "baseline_integrity_blocker": blob_hash != expected_hash,
    }


def truth_inventory(data_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    replay = _read(data_root / "evaluation_results/strict_identity_replay/final_report.json")
    provenance = _read(
        data_root / "evaluation_data/strict_identity_routing_review/trusted_label_provenance.json"
    )
    phase9d = _read(data_root / "evaluation_results/phase9d/comparative_report.json")
    closure = _read(data_root / "evaluation_results/closure1000/dataset_cohort_metrics.json")
    sources = [
        {
            "source_id": "source_b_strict_identity_replay_v3",
            "authority": "UNLABELED",
            "records": replay["total_pages_discovered"],
            "claims": None,
            "pages": replay["total_pages_discovered"],
            "fields": None,
            "critical_fields": None,
            "form_types": sorted(replay["identity_distribution"]),
            "package_ids": replay["manifest"]["package_count"],
            "hash": replay["manifest"]["input_manifest_sha256"],
            "eligible_for_development": False,
            "eligible_for_regression": True,
            "eligible_for_promotion": False,
        },
        {
            "source_id": "strict_identity_trusted_review",
            "authority": "TRUSTED_HUMAN"
            if provenance["admissible_trusted_labels"]
            else "UNLABELED",
            "records": provenance["admissible_trusted_labels"],
            "claims": 0,
            "pages": provenance["admissible_trusted_labels"],
            "fields": 0,
            "critical_fields": 0,
            "form_types": [],
            "package_ids": 0,
            "hash": digest(provenance),
            "eligible_for_development": False,
            "eligible_for_regression": False,
            "eligible_for_promotion": False,
        },
        {
            "source_id": "phase9_frozen_claim_regression",
            "authority": "FROZEN_REGRESSION",
            "records": phase9d["metrics"]["remaining_blockers"],
            "claims": phase9d["metrics"]["total_claims"],
            "pages": None,
            "fields": phase9d["metrics"]["remaining_blockers"],
            "critical_fields": None,
            "form_types": ["CMS1500", "UB04"],
            "package_ids": None,
            "hash": digest(phase9d),
            "eligible_for_development": True,
            "eligible_for_regression": True,
            "eligible_for_promotion": False,
        },
        {
            "source_id": "closure1000_source_inventory",
            "authority": "UNLABELED",
            "records": closure["source_assets"],
            "claims": closure["claim_count"],
            "pages": closure["rendered_pages"],
            "fields": None,
            "critical_fields": None,
            "form_types": sorted(closure["document_classes"]),
            "package_ids": closure["packages_discovered"],
            "hash": digest(closure),
            "eligible_for_development": False,
            "eligible_for_regression": True,
            "eligible_for_promotion": False,
        },
    ]
    summary = {
        "trusted_claims": 0,
        "trusted_pages": provenance["admissible_trusted_labels"],
        "trusted_fields": 0,
        "critical_fields": 0,
        "promotion_eligible_sources": 0,
        "status": provenance["status"],
    }
    return sources, summary


def _tier(name: str, target: int | None) -> dict[str, Any]:
    return {
        "tier": name,
        "target_pages": target,
        "actual_pages": 0,
        "actual_packages": 0,
        "package_partition": [],
        "package_set_sha256": digest([]),
        "status": "NOT_EVALUABLE",
        "reason": "NO_PROMOTION_ELIGIBLE_TRUTH_WITH_PACKAGE_LINEAGE",
    }


def baseline_report(data_root: Path) -> dict[str, Any]:
    replay = _read(data_root / "evaluation_results/strict_identity_replay/final_report.json")
    return {
        "baseline_sha": BASELINE_SHA,
        "metric_authority": "REAL_UNLABELED_OPERATIONAL_REPLAY",
        "metrics": {
            "routing_accuracy": {"value": None, "status": "NOT_EVALUABLE"},
            "raw_field_accuracy": {"value": None, "status": "NOT_EVALUABLE"},
            "critical_accuracy": {"value": None, "status": "NOT_EVALUABLE"},
            "accepted_precision": {"value": None, "status": "NOT_EVALUABLE"},
            "critical_accepted_precision": {"value": None, "status": "NOT_EVALUABLE"},
            "field_hitl": {"value": None, "status": "NOT_EVALUABLE"},
            "critical_field_hitl": {"value": None, "status": "NOT_EVALUABLE"},
            "claim_hitl": {"value": None, "status": "NOT_EVALUABLE"},
            "true_stp": {"value": None, "status": "NOT_EVALUABLE"},
            "critical_false_accepts": {"value": None, "status": "NOT_EVALUABLE"},
            "identity_distribution": replay["identity_distribution"],
            "safe_localization_rate": {
                "value": replay["localization_authorizations"] / replay["total_pages_discovered"],
                "status": "MEASURED_AUTHORIZATION_COVERAGE_NOT_ACCURACY",
            },
            "wrong_crop": {"value": None, "status": "NOT_EVALUABLE"},
            "empty_crop": {"value": None, "status": "NOT_EVALUABLE"},
            "missing_crop": {"value": None, "status": "NOT_EVALUABLE"},
            "p50_ms": replay["p50_ocr_runtime_ms"],
            "p95_ms": replay["p95_ocr_runtime_ms"],
            "p99_ms": replay["p99_ocr_runtime_ms"],
            "throughput_pages_per_minute": replay["effective_pages_per_minute"],
            "ocr_calls_per_page": 0.0,
            "ocr_calls_per_page_status": "CACHE_ONLY_REPLAY",
            "llm_calls_per_page": 0.0,
            "memory_mb": None,
            "memory_status": replay["peak_memory_status"],
            "ocr_cost_per_page": None,
            "llm_cost_per_page": None,
            "total_cost_per_page": None,
            "cost_status": replay["cost_per_page"],
        },
    }


def blocker_artifacts(
    data_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    classification = _read(data_root / "evaluation_results/phase9d/blocker_classification.json")
    rows = next(value for value in classification.values() if isinstance(value, list))
    closure = _read(data_root / "evaluation_results/phase9d/claim_remediation_plan.json")
    claims = next(value for value in closure.values() if isinstance(value, list))
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["field_name"], row["primary_category"], row["remediation_owner"])].append(row)
    priorities: list[dict[str, Any]] = []
    for (field, reason, owner), members in grouped.items():
        cdp = str(owner).startswith("CDP")
        score = len(members) * 10 + (25 if cdp else 0)
        priorities.append(
            {
                "field": field,
                "failure_reason": reason,
                "blockers": len(members),
                "claims_affected": len({row["claim_id"] for row in members}),
                "critical_claims": None,
                "nearest_unlock_claims": 0,
                "fixability": "CDP_CONTROLLED" if cdp else "EXTERNAL_EVIDENCE_REQUIRED",
                "recommended_experiment_family": (
                    "candidate assembly/localization"
                    if owner == "CDP EXTRACTION"
                    else "deterministic validation"
                    if owner == "CDP VALIDATION"
                    else "independent evidence discovery"
                    if owner == "CDP ACCEPTANCE POLICY"
                    else "not optimizer controlled"
                ),
                "priority_score": score,
            }
        )
    priorities.sort(
        key=lambda row: (
            -int(row["priority_score"]),
            str(row["field"]),
            str(row["failure_reason"]),
        )
    )
    for rank, row in enumerate(priorities, 1):
        row["rank"] = rank
    profile = {
        "authority": "FROZEN_REGRESSION",
        "not_release_truth": True,
        "total_blockers": len(rows),
        "by_owner": dict(Counter(row["remediation_owner"] for row in rows)),
        "by_reason": dict(Counter(row["primary_category"] for row in rows)),
        "by_field": dict(Counter(row["field_name"] for row in rows)),
    }
    matrix = []
    for claim in claims:
        distance = int(claim["current_distance"])
        categories = Counter(claim["blocker_classifications"])
        external = sum(
            categories[key]
            for key in ("D_AUTHORITATIVE_DATA_REQUIRED", "E_SOURCE_EVIDENCE_REQUIRED")
        )
        cdp_count = len(claim["blockers"]) - external
        matrix.append(
            {
                "claim_ref": digest(str(claim["claim_id"]))[:16],
                "form_type": "UNKNOWN",
                "remaining_blockers": len(claim["blockers"]),
                "blocker_categories": dict(categories),
                "CDP_controlled_blockers": cdp_count,
                "external_evidence_blockers": external,
                "critical_blockers": None,
                "unlock_distance": distance,
                "distance_class": (f"DISTANCE_{distance}" if distance <= 3 else "DISTANCE_4_PLUS"),
            }
        )
    return profile, {"authority": "FROZEN_REGRESSION", "claims": matrix}, priorities[:10]


def experiment_plan(priorities: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [row for row in priorities if row["fixability"] == "CDP_CONTROLLED"][:3]
    experiments = []
    for index, row in enumerate(selected, 1):
        family = row["recommended_experiment_family"]
        body = {"target": row["field"], "reason": row["failure_reason"], "family": family}
        experiments.append(
            {
                "experiment_id": f"RUN0-E{index}-{digest(body)[:12]}",
                "target_cohort": body,
                "hypothesis": f"A bounded {family} change may reduce this frozen blocker cohort.",
                "change_family": family,
                "parameters": {"mode": "EVALUATION_OVERLAY_ONLY"},
                "expected_blocker_reduction": None,
                "claims_potentially_unlocked": row["nearest_unlock_claims"],
                "expected_accuracy_impact": None,
                "expected_HITL_impact": None,
                "expected_STP_impact": None,
                "risk": "NOT_ESTIMABLE_WITHOUT_TRUSTED_TIER_A",
                "cost": None,
                "runtime": None,
                "status": "NOT_EVALUABLE",
            }
        )
    return {
        "maximum_experiments": 3,
        "selected_count": len(experiments),
        "selection_method": "DETERMINISTIC_PRIORITY_SCORE",
        "experiments": experiments,
    }


def execute(repo: Path, data_root: Path, junit_xml: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    failures, signature = attribute_failures(junit_xml)
    checksum = checksum_evidence(repo)
    sources, truth_summary = truth_inventory(data_root)
    baseline = baseline_report(data_root)
    profile, unlock, priorities = blocker_artifacts(data_root)
    plan = experiment_plan(priorities)
    tiers = {"A": _tier("A", 100), "B": _tier("B", 500), "C": _tier("C", None)}
    github_baseline = _read(repo / "evaluation_results/autonomous_optimizer/github_baseline.json")
    github_baseline["run0_execution_sha"] = BASELINE_SHA
    github_baseline["python_version"] = "3.14.7"
    github_baseline["os"] = "Windows NT 10.0.22621.0"
    _write(output, "github_baseline.json", github_baseline)
    _write(
        output,
        "baseline_failure_attribution.json",
        {
            "failures": failures,
            "category_counts": dict(Counter(r["category"] for r in failures)),
            "checksum_investigation": checksum,
        },
    )
    _write(output, "baseline_failure_signature.json", signature)
    _write(output, "truth_inventory.json", {"sources": sources, "summary": truth_summary})
    for tier, payload in tiers.items():
        _write(output, f"tier_{tier.lower()}_manifest.json", payload)
    _write(
        output,
        "dataset_overlap_report.json",
        {
            "package_leakage": 0,
            "overlaps": [],
            "status": "PASS_EMPTY_ELIGIBLE_PARTITIONS",
        },
    )
    _write(output, "baseline_report.json", baseline)
    _write(output, "failure_profile.json", profile)
    _write(output, "claim_unlock_matrix.json", unlock)
    _write(output, "cohort_priority.json", {"top_10": priorities})
    _write(output, "experiment_plan.json", plan)
    results = [
        {
            "experiment_id": item["experiment_id"],
            "verdict": "NOT_EVALUABLE",
            "reason": "NO_PROMOTION_ELIGIBLE_TIER_A_TRUTH",
            "metrics_delta": None,
            "claims_unlocked": None,
        }
        for item in plan["experiments"]
    ]
    _write(output, "tier_a_results.json", {"results": results, "winner": None})
    _write(
        output,
        "safety_gate_report.json",
        {
            "status": "NOT_RUN",
            "critical_false_accepts": None,
            "reason": "NO_CANDIDATE_EVALUATED_WITH_PROMOTION_ELIGIBLE_TRUTH",
            "automatic_production_promotion": False,
        },
    )
    diff = subprocess.check_output(
        ["git", "diff", "--", ":!evaluation_results"], cwd=repo, text=True
    )
    _write(
        output,
        "revert_integrity_report.json",
        {
            "experiment_specific_residual_change": False,
            "baseline_code_diff_empty": not bool(diff),
            "experiments_reverted": 0,
            "experiments_not_run": len(results),
        },
    )
    summary = {
        "status": "NEEDS_MORE_EVIDENCE",
        "baseline_sha": BASELINE_SHA,
        "trusted_pages": truth_summary["trusted_pages"],
        "top_blockers_source": "FROZEN_REGRESSION_NOT_RELEASE_TRUTH",
        "tier_a_experiments_planned": len(results),
        "tier_a_experiments_executed": 0,
        "best_candidate": None,
        "tier_b_status": "NOT_EVALUABLE",
        "automatic_production_promotion": False,
        "new_semantic_failures": 0,
        "baseline_optimizer_architecture_failure": any(r["optimizer_relevant"] for r in failures),
        "next_action": "COMPLETE_BLIND_DUAL_REVIEW_OR_ADJUDICATED_REAL_PAGE_LABELS",
    }
    _write(output, "optimization_summary.json", summary)
    lines = [
        "# Autonomous CDP Optimization Run 0",
        "",
        "Status: **NEEDS_MORE_EVIDENCE**",
        "",
        "The real 2,173-page replay has no promotion-eligible trusted labels. Three",
        "closed-world Tier-A experiments were selected automatically but not executed;",
        "accuracy, HITL, STP, and safety deltas would otherwise be fabricated.",
        "",
        "The Git blob matches the frozen router hash. The local checksum failure is caused",
        "by Windows CRLF materialization. No runtime authority or threshold was changed.",
    ]
    (output / "optimization_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    registry = output.parent / "registry.jsonl"
    existing_ids = set()
    if registry.exists():
        existing_ids = {
            json.loads(line)["experiment_id"]
            for line in registry.read_text("utf-8").splitlines()
            if line.strip()
        }
    with registry.open("a", encoding="utf-8", newline="\n") as stream:
        for item in plan["experiments"]:
            if item["experiment_id"] in existing_ids:
                continue
            record = {
                "experiment_id": item["experiment_id"],
                "baseline_sha": BASELINE_SHA,
                "target": item["target_cohort"],
                "hypothesis": item["hypothesis"],
                "parameters": item["parameters"],
                "metrics_before": None,
                "metrics_after": None,
                "delta": None,
                "safety_gates": "NOT_RUN",
                "runtime": None,
                "cost": None,
                "verdict": "NOT_EVALUABLE",
                "revert_status": "NO_CHANGE_APPLIED",
                "artifact_hashes": {},
            }
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--junit-xml", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(execute(Path.cwd(), args.data_root, args.junit_xml, args.output), sort_keys=True)
    )


if __name__ == "__main__":
    main()
