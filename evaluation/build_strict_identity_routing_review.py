"""Build prediction-blind routing review queues from frozen decision checkpoints.

Queue artifacts contain page lineage and review requirements only. Candidate
predictions and risk reasons remain in a coordinator-only manifest so initial
annotators cannot see model output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

ALLOWED_LABELS = {
    "CMS1500",
    "UB04",
    "OTHER_CLAIM_FORM",
    "SUPPORTING_DOCUMENT",
    "NON_CLAIM",
    "UNKNOWN",
}
STANDARD_CLASSES = {"CMS1500", "UB04"}
ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "evaluation_data/strict_identity_replay_v3/pages"
PRECEDING = ROOT / "evaluation_data/strict_identity_replay_v2/pages"
OUTPUT = ROOT / "evaluation_data/strict_identity_routing_review"


def _load(directory: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text("utf-8"))
        page_id = record["source_page_id"]
        if page_id in records:
            raise ValueError(f"DUPLICATE_PAGE_ID:{page_id}")
        if record.get("source_page_sha256") != record.get("ocr_provenance", {}).get(
            "rendered_page_sha256"
        ):
            raise ValueError(f"PAGE_SHA_MISMATCH:{page_id}")
        records[page_id] = record
    return records


def _conflict(record: dict[str, Any]) -> bool:
    return any(
        bool(values)
        for values in record.get("form_identity", {}).get("conflicting_anchors", {}).values()
    )


def _near_miss(record: dict[str, Any]) -> bool:
    eligibility = record.get("form_identity", {}).get("family_eligibility", {})
    return any(
        not values.get("eligible")
        and values.get("high_value_anchor_count", 0) >= 2
        and sum(not bool(passed) for passed in values.get("authorization_gates", {}).values()) <= 2
        for values in eligibility.values()
    )


def _risk(record: dict[str, Any], preceding: dict[str, Any] | None) -> tuple[int, list[str]]:
    chain = record["production_chain"]
    nomination = record["routing_result"]["router_nomination"]
    reasons: list[str] = []
    if chain["fixed_extractor_authorized"]:
        reasons.append("FIXED_EXTRACTOR_AUTHORIZED")
    if nomination in STANDARD_CLASSES:
        reasons.append("STANDARD_ROUTER_NOMINATION")
    if "STANDARD_IDENTITY_CLASSIFICATION_MISMATCH" in chain["decision_reason_codes"]:
        reasons.append("FAMILY_MISMATCH")
    if _conflict(record):
        reasons.append("CONFLICTING_IDENTITY")
    if _near_miss(record):
        reasons.append("THRESHOLD_NEAR_MISS")
    if (
        preceding
        and preceding.get("form_identity", {}).get("localization_allowed", False)
        and not chain["fixed_extractor_authorized"]
    ):
        reasons.append("PRECEDING_POLICY_AUTHORIZED_CURRENT_REJECTED")
    priority = (
        0
        if "FIXED_EXTRACTOR_AUTHORIZED" in reasons
        else 1
        if "STANDARD_ROUTER_NOMINATION" in reasons
        else 2
        if any(
            reason in reasons
            for reason in ("FAMILY_MISMATCH", "CONFLICTING_IDENTITY", "THRESHOLD_NEAR_MISS")
        )
        else 3
        if "PRECEDING_POLICY_AUTHORIZED_CURRENT_REJECTED" in reasons
        else 4
    )
    return priority, reasons


def _package_round_robin(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for record in sorted(records, key=lambda item: (item["package_id"], item["source_page_id"])):
        grouped[record["package_id"]].append(record)
    ordered: list[dict[str, Any]] = []
    while grouped:
        for package_id in sorted(grouped):
            ordered.append(grouped[package_id].popleft())
            if not grouped[package_id]:
                del grouped[package_id]
    return ordered


def build(
    current_dir: Path = CURRENT,
    preceding_dir: Path = PRECEDING,
    output: Path = OUTPUT,
    rapid_size: int = 300,
) -> dict[str, Any]:
    current = _load(current_dir)
    preceding = _load(preceding_dir)
    if set(current) != set(preceding):
        raise ValueError("CURRENT_PRECEDING_PAGE_SET_MISMATCH")

    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    audit: dict[str, dict[str, Any]] = {}
    for page_id, record in current.items():
        priority, reasons = _risk(record, preceding.get(page_id))
        buckets[priority].append(record)
        audit[page_id] = {
            "priority": priority,
            "risk_reasons": reasons,
            "current_candidate_class": record["candidate_class"],
            "current_router_nomination": record["routing_result"]["router_nomination"],
            "current_fixed_authorized": record["production_chain"]["fixed_extractor_authorized"],
            "preceding_localization_allowed": preceding[page_id]
            .get("form_identity", {})
            .get("localization_allowed", False),
        }

    ordered: list[dict[str, Any]] = []
    for priority in range(5):
        ordered.extend(_package_round_robin(buckets[priority]))

    remainder_ids = [
        record["source_page_id"]
        for record in ordered
        if audit[record["source_page_id"]]["priority"] == 4
    ]
    double_review_remainder = set(
        sorted(
            remainder_ids,
            key=lambda page_id: hashlib.sha256(
                f"strict-identity-review-v1:{page_id}".encode()
            ).hexdigest(),
        )[: math.ceil(len(remainder_ids) * 0.20)]
    )

    blind_records = []
    for position, record in enumerate(ordered, 1):
        page_id = record["source_page_id"]
        hard_confuser = audit[page_id]["priority"] < 4
        blind_records.append(
            {
                "queue_position": position,
                "source_page_id": page_id,
                "source_page_sha256": record["source_page_sha256"],
                "package_id": record["package_id"],
                "blind_task_id": hashlib.sha256(
                    f"routing-review:{page_id}:{record['source_page_sha256']}".encode()
                ).hexdigest(),
                "local_image_reference": f"source-page://{page_id}",
                "allowed_labels": sorted(ALLOWED_LABELS),
                "reviewer_role": "ASSIGNED_AT_REVIEW",
                "required_reviewer_roles": ["REVIEWER_A", "REVIEWER_B"],
                "required_independent_reviews": (
                    2 if hard_confuser or page_id in double_review_remainder else 1
                ),
                "disagreement_requires_independent_adjudicator": True,
                "review_state": "REVIEW_REQUIRED",
            }
        )

    output.mkdir(parents=True, exist_ok=True)
    common = {
        "schema_version": "strict-identity-routing-review-v1",
        "blind_initial_annotation": True,
        "predictions_in_queue": False,
        "trusted_ground_truth": False,
        "label_authority_required": "INDEPENDENT_HUMAN_REVIEW_AND_ADJUDICATION",
        "total_replay_pages": len(blind_records),
    }
    rapid: dict[str, Any] = {
        **common,
        "mode": "rapid",
        "status": "PRELIMINARY",
        "records": blind_records[:rapid_size],
    }
    full: dict[str, Any] = {
        **common,
        "mode": "full",
        "status": "CORPUS_WIDE",
        "records": blind_records,
    }
    coordinator = {
        "schema_version": common["schema_version"],
        "access": "COORDINATOR_ONLY_NOT_FOR_INITIAL_ANNOTATORS",
        "current_policy_pages": len(current),
        "preceding_policy_pages": len(preceding),
        "rapid_size": len(rapid["records"]),
        "risk_counts": {
            reason: sum(reason in values["risk_reasons"] for values in audit.values())
            for reason in sorted(
                {reason for values in audit.values() for reason in values["risk_reasons"]}
            )
        },
        "records": audit,
    }
    provenance = {
        "status": "BLOCKED_HUMAN_LABELS",
        "admissible_trusted_labels": 0,
        "source_system_ground_truth_records": 0,
        "independently_adjudicated_page_labels": 0,
        "replay_pages": len(current),
        "search_findings": {
            "azure_live_shadow_trusted_labels": 0,
            "azure_live_shadow_pages_reviewed": 0,
            "real_eval_trusted_labels": 0,
            "real_eval_exact_bindings": 0,
            "offline_field_labels_rejected": "NO_EXACT_REPLAY_PAGE_ID_AND_SHA_LINEAGE",
        },
        "accuracy_scoring_authorized": False,
    }
    for name, value in (
        ("rapid_blind_queue.json", rapid),
        ("full_blind_queue.json", full),
        ("coordinator_risk_manifest.json", coordinator),
        ("trusted_label_provenance.json", provenance),
    ):
        (output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + chr(10), "utf-8")
    return {
        "rapid_pages": len(rapid["records"]),
        "rapid_double_review_pages": sum(
            record["required_independent_reviews"] == 2 for record in rapid["records"]
        ),
        "full_pages": len(full["records"]),
        "double_review_pages": sum(
            record["required_independent_reviews"] == 2 for record in blind_records
        ),
        "status": provenance["status"],
        "risk_counts": coordinator["risk_counts"],
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _wilson(successes: int, total: int) -> dict[str, float | int] | None:
    if total == 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return {
        "numerator": successes,
        "denominator": total,
        "estimate": proportion,
        "lower": max(0.0, center - margin),
        "upper": min(1.0, center + margin),
    }


def score(
    queue_path: Path,
    current_dir: Path,
    reviews_path: Path,
    adjudications_path: Path,
    output: Path | None = None,
) -> dict[str, Any]:
    queue = json.loads(queue_path.read_text("utf-8"))
    tasks = {record["blind_task_id"]: record for record in queue["records"]}
    current = _load(current_dir)
    reviews_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for review in _read_jsonl(reviews_path):
        task = tasks.get(review.get("blind_task_id"))
        if task is None:
            raise ValueError("UNKNOWN_BLIND_TASK")
        if (
            review.get("source_page_id") != task["source_page_id"]
            or review.get("source_page_sha256") != task["source_page_sha256"]
        ):
            raise ValueError("REVIEW_PAGE_LINEAGE_MISMATCH")
        if review.get("reviewed_label") not in ALLOWED_LABELS:
            raise ValueError("INVALID_REVIEW_LABEL")
        if (
            review.get("review_status") != "COMPLETED"
            or not review.get("reviewer_id")
            or not review.get("review_session_id")
            or review.get("reviewer_role") not in {"REVIEWER_A", "REVIEWER_B"}
        ):
            raise ValueError("INCOMPLETE_REVIEW_AUTHORITY")
        reviews_by_task[review["blind_task_id"]].append(review)

    adjudications = {row["blind_task_id"]: row for row in _read_jsonl(adjudications_path)}
    labels: dict[str, str] = {}
    pending_reviews = 0
    pending_adjudications = 0
    agreements = disagreements = adjudication_count = 0
    completed_reviews = 0
    for task_id, task in tasks.items():
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for review in reviews_by_task.get(task_id, []):
            unique[(review["reviewer_id"], review["review_session_id"])] = review
        reviews = list(unique.values())
        completed_reviews += len(reviews)
        required = int(task["required_independent_reviews"])
        if len(reviews) < required:
            pending_reviews += required - len(reviews)
            continue
        selected = reviews[:required]
        if required == 2:
            if (
                selected[0]["reviewer_id"] == selected[1]["reviewer_id"]
                or selected[0]["review_session_id"] == selected[1]["review_session_id"]
                or selected[0]["reviewer_role"] == selected[1]["reviewer_role"]
            ):
                raise ValueError("REVIEWS_NOT_INDEPENDENT")
            if selected[0]["reviewed_label"] == selected[1]["reviewed_label"]:
                agreements += 1
                labels[task_id] = selected[0]["reviewed_label"]
            else:
                disagreements += 1
                adjudication = adjudications.get(task_id)
                if adjudication is None:
                    pending_adjudications += 1
                    continue
                if (
                    adjudication.get("adjudicator_id")
                    in {review["reviewer_id"] for review in selected}
                    or adjudication.get("adjudication_session_id")
                    in {review["review_session_id"] for review in selected}
                    or adjudication.get("final_label") not in ALLOWED_LABELS
                    or adjudication.get("adjudication_status") != "COMPLETED"
                ):
                    raise ValueError("ADJUDICATION_NOT_INDEPENDENT_OR_COMPLETE")
                labels[task_id] = adjudication["final_label"]
                adjudication_count += 1
        else:
            labels[task_id] = selected[0]["reviewed_label"]

    progress = {
        "rapid_tasks_generated": len(tasks) if queue["mode"] == "rapid" else 300,
        "full_tasks_generated": int(queue["total_replay_pages"]),
        "completed_reviews": completed_reviews,
        "pending_reviews": pending_reviews,
        "pending_adjudications": pending_adjudications,
        "scorable_pages": len(labels),
        "unscorable_pages": len(tasks) - len(labels),
    }
    metric_names = (
        "overall_exact_accuracy",
        "macro_f1",
        "per_class",
        "confusion_matrix",
        "cms1500_precision",
        "cms1500_recall",
        "ub04_precision",
        "ub04_recall",
        "fixed_authorization_precision",
        "fixed_authorization_recall",
        "false_standard_authorization",
        "authorization_coverage",
        "page_review_abstention_rate",
        "reviewer_agreement",
    )
    if len(labels) != len(tasks) or pending_reviews or pending_adjudications:
        result: dict[str, Any] = {
            "status": "BLOCKED_HUMAN_LABELS",
            "reason": "BLOCKED_HUMAN_LABELS",
            "progress": progress,
            "metrics": {name: None for name in metric_names},
            "metric_scope": {
                "routing_accuracy": "BLOCKED_HUMAN_LABELS",
                "field_extraction_accuracy": "NOT_EVALUATED",
                "accepted_field_precision": "NOT_EVALUATED",
                "page_review_rate": "ROUTING_ONLY",
                "field_hitl": "NOT_EVALUATED",
                "claim_hitl_stp": "NOT_EVALUATED",
                "cached_replay_timing": "SEPARATE_EXISTING_ARTIFACT",
                "fresh_latency_and_cost": "NOT_EVALUATED",
            },
        }
        if output:
            output.write_text(json.dumps(result, indent=2, sort_keys=True) + chr(10), "utf-8")
        return result

    truth = {tasks[task_id]["source_page_id"]: label for task_id, label in labels.items()}
    classes = sorted(ALLOWED_LABELS)
    confusion = {actual: {predicted: 0 for predicted in classes} for actual in classes}
    correct = 0
    for page_id, actual in truth.items():
        predicted = current[page_id]["candidate_class"]
        if predicted not in ALLOWED_LABELS:
            predicted = "UNKNOWN"
        confusion[actual][predicted] += 1
        correct += actual == predicted

    per_class: dict[str, Any] = {}
    f1_values = []
    for label in classes:
        tp = confusion[label][label]
        predicted_total = sum(confusion[actual][label] for actual in classes)
        actual_total = sum(confusion[label].values())
        precision = tp / predicted_total if predicted_total else 0.0
        recall = tp / actual_total if actual_total else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        per_class[label] = {
            "support": actual_total,
            "precision": _wilson(tp, predicted_total),
            "recall": _wilson(tp, actual_total),
            "f1": f1,
        }

    authorized = [
        (page_id, record)
        for page_id, record in current.items()
        if page_id in truth and record["production_chain"]["fixed_extractor_authorized"]
    ]
    correct_authorized = sum(
        truth[page_id] == record["production_chain"]["verified_identity_family"]
        for page_id, record in authorized
    )
    true_standard = sum(label in STANDARD_CLASSES for label in truth.values())
    false_authorized = len(authorized) - correct_authorized
    abstained = sum(
        current[page_id]["candidate_class"] in {"UNKNOWN", "SUPPORTING_DOCUMENT"}
        for page_id in truth
    )
    double_reviewed = agreements + disagreements
    result = {
        "status": (
            "ROUTING_PRELIMINARY" if queue["mode"] == "rapid" else "ROUTING_CORPUS_EVALUATED"
        ),
        "reason": None,
        "progress": progress,
        "metrics": {
            "overall_exact_accuracy": _wilson(correct, len(truth)),
            "macro_f1": sum(f1_values) / len(f1_values),
            "per_class": per_class,
            "confusion_matrix": confusion,
            "cms1500_precision": per_class["CMS1500"]["precision"],
            "cms1500_recall": per_class["CMS1500"]["recall"],
            "ub04_precision": per_class["UB04"]["precision"],
            "ub04_recall": per_class["UB04"]["recall"],
            "fixed_authorization_precision": _wilson(correct_authorized, len(authorized)),
            "fixed_authorization_recall": _wilson(correct_authorized, true_standard),
            "false_standard_authorization": _wilson(false_authorized, len(authorized)),
            "authorization_coverage": _wilson(len(authorized), len(truth)),
            "page_review_abstention_rate": _wilson(abstained, len(truth)),
            "reviewer_agreement": _wilson(agreements, double_reviewed),
            "disagreement_count": disagreements,
            "adjudication_count": adjudication_count,
        },
    }
    if output:
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + chr(10), "utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-dir", type=Path, default=CURRENT)
    parser.add_argument("--preceding-dir", type=Path, default=PRECEDING)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--rapid-size", type=int, default=300)
    parser.add_argument("--score-queue", type=Path)
    parser.add_argument("--reviews", type=Path, default=OUTPUT / "reviews.jsonl")
    parser.add_argument("--adjudications", type=Path, default=OUTPUT / "adjudications.jsonl")
    parser.add_argument("--score-output", type=Path, default=OUTPUT / "routing_metrics.json")
    args = parser.parse_args()
    result = (
        score(
            args.score_queue,
            args.current_dir,
            args.reviews,
            args.adjudications,
            args.score_output,
        )
        if args.score_queue
        else build(args.current_dir, args.preceding_dir, args.output, args.rapid_size)
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
