import json
from pathlib import Path

from evaluation import population_reconciliation


def test_population_reconciliation_balances_and_does_not_assume_review(tmp_path, monkeypatch):
    results = tmp_path / "evaluation_results"
    (results / "atomic_all").mkdir(parents=True)
    (results / "current_v2_router").mkdir()
    (results / "remaining_error_pareto").mkdir()
    (results / "atomic_all" / "evaluation.json").write_text(
        json.dumps({"field_count": 366})
    )
    (results / "current_v2_router" / "metrics.json").write_text(json.dumps({
        "evaluated_visible_fields": 214,
        "extraction_accuracy": 180 / 214,
        "critical_fields_routed_to_review": 4,
    }))
    (results / "remaining_error_pareto" / "metrics.json").write_text(
        json.dumps({"remaining_errors": 34})
    )
    (results / "accuracy_channels.json").write_text(json.dumps({
        "REFERENCE_BLOCKED_FIELDS": 4,
        "HUMAN_VERIFIED_FINAL_ACCURACY": None,
    }))
    monkeypatch.chdir(tmp_path)

    assert population_reconciliation.main() == 0
    report = json.loads(
        Path("evaluation_results/population_reconciliation.json").read_text()
    )
    assert report["mutually_exclusive_population"] == {
        "correct_automated_visible_fields": 180,
        "scoped_visible_field_failures": 34,
        "expected_blank_or_not_applicable": 152,
        "excluded_or_unclassified": 0,
    }
    assert all(report["invariants"].values())
