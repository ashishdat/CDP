from evaluation.create_cell_label_manifest import select_candidates
from evaluation.evaluate_table_shadow import REQUIRED_PROVENANCE


def _candidate(family: str, column: str, row: int, raw: str) -> dict:
    return {
        "candidate_id": f"{family}-{column}-{row}",
        "document_id": family,
        "page_number": 1,
        "document_family": family,
        "column_name": column,
        "row_index": row,
        "raw_text": raw,
    }


def test_manifest_selection_balances_observed_content_and_columns():
    candidates = [
        _candidate("UB04", "charge", 0, ""),
        _candidate("UB04", "charge", 1, "10.00"),
        _candidate("UB04", "revenue_code", 0, ""),
        _candidate("UB04", "revenue_code", 1, "0450"),
        _candidate("CMS1500", "procedure_code", 0, "99213"),
        _candidate("CMS1500", "procedure_code", 1, ""),
    ]

    selected = select_candidates(candidates, limit=6)

    assert {item["column_name"] for item in selected} == {
        "charge",
        "revenue_code",
        "procedure_code",
    }
    assert {bool(item["raw_text"]) for item in selected} == {False, True}


def test_required_provenance_covers_visual_and_ocr_lineage():
    assert {
        "source_image",
        "aligned_page",
        "grid_overlay",
        "cell_crop",
        "geometry_provider",
        "raw_ocr_provider",
    }.issubset(REQUIRED_PROVENANCE)
