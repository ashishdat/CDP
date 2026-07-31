import json
from pathlib import Path

from evaluation import accuracy_channels


def test_accuracy_channels_keep_full_and_eligible_denominators(tmp_path, monkeypatch):
    results = tmp_path / "evaluation_results"
    (results / "current_v2_router").mkdir(parents=True)
    (results / "remaining_error_pareto").mkdir()
    (results / "current_v2_router/metrics.json").write_text(json.dumps({
        "evaluated_visible_fields": 214,
        "extraction_accuracy": 191 / 214,
        "critical_false_accepts": 0,
    }))
    details = [
        {"reason": "SELECTED", "extraction_correct": True, "review_required": False}
        for _ in range(125)
    ] + [
        {"reason": "REVIEW_ONLY_CROSS_FIELD_DERIVATION", "extraction_correct": True,
         "review_required": True}
    ] + [
        {"reason": "INSUFFICIENT_EVIDENCE", "extraction_correct": index < 65,
         "review_required": True}
        for index in range(88)
    ]
    (results / "current_v2_router/details.json").write_text(json.dumps(details))
    (results / "remaining_error_pareto/metrics.json").write_text(json.dumps({
        "by_category": {
            "REFERENCE_BLOCKED": 9,
            "UNREADABLE_REQUIRES_REVIEW": 13,
            "GROUND_TRUTH_OUTPUT_SEMANTIC_DISAGREEMENT": 1,
        }
    }))
    monkeypatch.chdir(tmp_path)

    assert accuracy_channels.main() == 0
    report = json.loads(Path("evaluation_results/accuracy_channels.json").read_text())
    assert report["VISIBLE_FIELD_DENOMINATOR"] == 214
    assert report["AUTOMATICALLY_ELIGIBLE_FIELDS"] == 125
    assert report["AUTOMATICALLY_ACCEPTED_FIELDS"] == 125
    assert report["AUTOMATICALLY_INCORRECT_FIELDS"] == 0
    assert report["ABSTAINED_FIELDS"] == 89
    assert report["DERIVED_REVIEW_ONLY_FIELDS"] == 1
    assert report["AUTOMATED_EXTRACTION_ACCURACY"] == 191 / 214
    assert report["PRODUCTION_AUTOMATED_ACCURACY"] == 191 / 214
    assert report["FINAL_VALIDATED_ACCURACY"] is None
