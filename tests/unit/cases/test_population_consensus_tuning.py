from evaluation.apply_population_consensus_tuning import tune


def _row(document: str, *, cross: bool = False, review: bool = True) -> dict:
    return {
        "field_identity": {
            "document_id": document,
            "document_family": "UB04",
            "semantic_field": "description",
        },
        "selected_value": "Ancillary Code Detox",
        "normalized_value": "ANCILLARYCODEDETOX",
        "review_required": review,
        "validation_results": ["CROSS_FAMILY_AGREEMENT"] if cross else [],
    }


def test_population_requires_three_documents_and_cross_engine_anchor():
    rows = [_row("C-01"), _row("C-02", cross=True), _row("C-03")]
    tuned, metrics = tune(rows)
    assert metrics["population_promoted_fields"] == 3
    assert not any(row["review_required"] for row in tuned)


def test_population_without_anchor_remains_review_only():
    rows = [_row("C-01"), _row("C-02"), _row("C-03")]
    tuned, metrics = tune(rows)
    assert metrics["population_promoted_fields"] == 0
    assert all(row["review_required"] for row in tuned)
