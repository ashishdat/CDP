from evaluation.trusted_training_export import build_training_manifest


def _row(doc, source="APPROVED_CORRECTION", value="DOE", family="CMS-1500"):
    return {
        "document_hash": doc, "crop_hash": f"crop-{doc}", "field_name": "patient_last",
        "trusted_value": value, "label_source": source, "document_family": family,
    }


def test_only_independent_labels_are_exported_and_split_by_document():
    result = build_training_manifest([_row("a"), _row("b", "AZURE_OUTPUT")], minimum_samples=1)
    assert len(result["samples"]) == 1
    assert result["samples"][0]["dataset_split"] in {"TRAIN", "VALIDATION", "HOLDOUT"}


def test_conflicting_labels_are_excluded():
    rows = [_row("a"), {**_row("a", value="ROE"), "crop_hash": "crop-2"}]
    result = build_training_manifest(rows)
    assert result["samples"] == []
    assert result["metrics"]["conflicting_document_fields"] == 1
