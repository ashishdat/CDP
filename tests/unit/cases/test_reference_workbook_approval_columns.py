from evaluation.import_governed_reference_xlsx import read_sheet
from evaluation.reference_enrichment_workbook import write_enriched_workbook


def test_workbook_includes_governed_approval_columns(tmp_path) -> None:
    path = tmp_path / "review.xlsx"
    original = [{"identity_key": "A|1|CMS1500||name", "document_id": "A",
        "page_number": "1", "document_family": "CMS1500", "field_name": "name"}]
    decision = {"identity_key": original[0]["identity_key"], "reference_value": "X",
        "decision": "REFERENCE_VERIFIED", "source_tier": "TIER_A_APPROVED_CORRECTION",
        "reference_provider": "manual", "reference_dataset_version": "v1",
        "source_record_id": "1", "source_lineage": "source", "matching_attributes": "id",
        "contradictions": "", "independent_truth": True, "approval_method": "visual",
        "evaluation_eligible": True, "decision_reason": "confirmed",
        "approved_by": "reviewer-1", "approved_at": "2026-08-01T10:00:00Z",
        "second_approved_by": "reviewer-2", "second_approved_at": "2026-08-01T10:05:00Z",
        "label_strength": "TIER_A_APPROVED_CORRECTION"}
    write_enriched_workbook(path, original, [decision], {}, [])
    row = read_sheet(path, "Reference Decisions")[0]
    assert row["approved_by"] == "reviewer-1"
    assert row["second_approved_by"] == "reviewer-2"
    assert row["label_strength"] == "TIER_A_APPROVED_CORRECTION"
