from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import evaluation.table_labeling_app as labeling
from evaluation.quarantine_table_labels import REASON


def _item(tmp_path: Path) -> dict:
    crop = tmp_path / "crop.png"
    crop.write_bytes(b"image")
    return {
        "candidate_id": "candidate",
        "crop_path": str(crop),
        "crop_quality_status": "VALID_SINGLE_CELL",
    }


def test_ocr_suggestion_cannot_default_to_approved(tmp_path: Path, monkeypatch):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        '{"candidate_id":"candidate","document_id":"D","document_family":"UB04",'
        '"form_locator":"FL42","semantic_field_name":"revenue_code",'
        '"service_line_number":1,"crop_path":"missing","row_context_path":"missing",'
        '"ocr_suggestion":"0251","crop_quality_status":"VALID_SINGLE_CELL"}\n'
    )
    monkeypatch.setattr(labeling, "PILOT", manifest)
    monkeypatch.setenv("TABLE_REVIEWER_ID", "reviewer-1")
    response = TestClient(labeling.app).get("/cell/candidate")
    assert "PENDING_REVIEW" in response.text
    assert "name=expected_value value=''" in response.text
    assert "Unverified OCR suggestion." in response.text
    assert "Semantic field <input value='revenue_code' readonly>" in response.text
    assert "disabled" in response.text


def test_submission_rules_and_independent_approval(tmp_path: Path):
    item = _item(tmp_path)
    with pytest.raises(ValueError, match="visual verification"):
        labeling.validate_submission(item, "APPROVED", "0251", "", False)
    with pytest.raises(ValueError, match="cannot be empty"):
        labeling.validate_submission(item, "APPROVED", "", "", True)
    with pytest.raises(ValueError, match="BLANK_CONFIRMED"):
        labeling.validate_submission(item, "UNREADABLE", "", "", True)
    with pytest.raises(ValueError, match="comment"):
        labeling.validate_submission(
            item, "WRONG_CELL_BOUNDARY", "bad", "", True
        )


def test_quarantine_reason_makes_old_labels_ineligible():
    event = {
        "evaluation_eligible": False,
        "training_eligible": False,
        "quarantine_reason": REASON,
    }
    assert event == {
        "evaluation_eligible": False,
        "training_eligible": False,
        "quarantine_reason": "SOURCE_CROP_GEOMETRY_NOT_VALIDATED",
    }
