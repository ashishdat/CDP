"""Explain every correct-candidate selection failure under reconciliation v2."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from evaluation.normalizers import NormalizerRegistry


def main() -> int:
    normalizers = NormalizerRegistry.from_yaml("config/evaluation/normalization_rules.yaml")
    decisions = {
        (row["document_id"], row["field_name"]): row
        for row in json.loads(Path("evaluation_results/current_v2_router/details.json").read_text())
    }
    sources = []
    for path in (
        Path("evaluation_results/structured_rollout/cms1500/details.json"),
        Path("evaluation_results/structured_rollout/ub04/details.json"),
    ):
        sources.extend(json.loads(path.read_text()))
    failures = []
    governed = []
    funnel = Counter()
    for source in sources:
        key = (source["document_id"], source["field_name"])
        decision = decisions.get(key)
        if not decision or decision["extraction_correct"]:
            continue
        expected = normalizers.normalize(key[1], source["expected"])
        candidates = source.get("all_candidates", [])
        correct = [
            item for item in candidates
            if normalizers.normalize(key[1], item.get("normalized")) == expected
        ]
        if not correct:
            continue
        funnel["correct_candidate_exists"] += 1
        governed_reason = _governed_reason(key[1], correct, decision)
        if governed_reason:
            governed.append({
                "document_id": key[0],
                "field_name": key[1],
                "reason": governed_reason,
                "candidate_count": len(correct),
            })
            continue
        diagnostics = decision.get("reconciliation_diagnostics", [])
        correct_scores = [
            item for item in diagnostics
            if normalizers.normalize(key[1], item["value"]) == expected
        ]
        eligible = bool(correct_scores)
        funnel["eligible"] += eligible
        funnel["survives_filtering"] += eligible
        funnel["reaches_scoring"] += eligible
        if eligible:
            funnel["loses_scoring_or_tiebreak"] += 1
        selected_score = max(
            (item for item in diagnostics if item["value"] == str(decision["selected_value"]).upper()),
            key=lambda item: item["final_score"], default=None,
        )
        correct_score = max(correct_scores, key=lambda item: item["final_score"], default=None)
        classification = _classify(correct_score, selected_score, decision)
        rejection_stage = (
            "ELIGIBILITY_OR_DOMINANCE_FILTER"
            if not eligible
            else "SCORING_OR_TIE_BREAK"
        )
        failures.append({
            "document_id": key[0], "field_name": key[1],
            "correct_candidate": correct,
            "selected_candidate": decision["selected_value"],
            "correct_score": correct_score,
            "selected_score": selected_score,
            "final_margin": decision["value_margin"],
            "rejection_reason": decision["reason"],
            "classification": classification,
            "rejection_stage": rejection_stage,
            "semantic_reference_status": "REFERENCE_UNAVAILABLE",
        })
    metrics = {
        "policy_version": "reconciliation_v2",
        "selection_failures": len(failures),
        "governed_non_selection_cases": len(governed),
        "governed_classification": dict(Counter(
            row["reason"] for row in governed
        ).most_common()),
        "oracle_funnel": dict(funnel),
        "classification": dict(Counter(
            row["classification"] for row in failures
        ).most_common()),
        "target_less_than_three_met": len(failures) < 3,
    }
    output = Path("evaluation_results/reconciliation_oracle")
    output.mkdir(parents=True, exist_ok=True)
    (output / "details.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
    (output / "governed.json").write_text(json.dumps(governed, indent=2), encoding="utf-8")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


def _classify(correct, selected, decision):
    if not correct:
        return "CORRECT_CANDIDATE_INCORRECTLY_FILTERED"
    if not selected:
        return "TIE_BREAK_FAILURE"
    correct_components = correct["score_components"]
    selected_components = selected["score_components"]
    if correct_components["validation"] > selected_components["validation"]:
        return "VALIDATION_DOMINANCE_FAILURE"
    if correct_components["consensus"] > selected_components["consensus"]:
        return "CONSENSUS_NOT_REWARDED"
    if decision["reason"] == "AMBIGUOUS_VALUE" or correct["final_score"] == selected["final_score"]:
        return "TIE_BREAK_FAILURE"
    return "ENGINE_CONFIDENCE_MISCALIBRATION"


def _governed_reason(field_name, correct_candidates, decision):
    if any(
        str(candidate.get("normalized") or "").upper() in {"UNKNOWN", "NA", "N/A"}
        for candidate in correct_candidates
    ):
        return "GROUND_TRUTH_OUTPUT_SEMANTIC_DISAGREEMENT"
    if field_name in {"patient_first", "patient_last"} and decision.get("reason") == (
        "REFERENCE_REQUIRED"
    ):
        return "CRITICAL_NAME_REFERENCE_BLOCKED"
    validations = {
        validation
        for candidate in correct_candidates
        for validation in candidate.get("validation_results", [])
    }
    if "fixed_width_output_projection" in validations:
        return "OUTPUT_PROJECTION_NOT_VISIBLE_OCR"
    if validations and validations <= {"NEEDS_REVIEW"}:
        return "UNREADABLE_REVIEW_ONLY_CANDIDATE"
    return None


if __name__ == "__main__":
    raise SystemExit(main())
