import pytest

from packages.handwriting_dataset import AppendOnlyHandwritingDataset


def test_approved_label_is_append_only_and_training_is_quality_gated(tmp_path):
    dataset = AppendOnlyHandwritingDataset(tmp_path / "approved.jsonl")
    dataset.approve(
        crop=b"crop",
        crop_reference="s3://review/crop.png",
        field_name="patient_name",
        ocr_value="J0HN",
        corrected_value="JOHN",
        reviewer="reviewer-a",
        validator="validator-b",
        approved_by="reviewer-a",
        document_family="cms1500",
    )
    with pytest.raises(ValueError, match="insufficient diverse"):
        dataset.training_manifest()
    assert len(dataset.path.read_text().splitlines()) == 1


def test_same_person_cannot_be_only_reviewer_validator_and_approver(tmp_path):
    with pytest.raises(ValueError, match="separation"):
        AppendOnlyHandwritingDataset(tmp_path / "approved.jsonl").approve(
            crop=b"crop", crop_reference="crop.png", field_name="name",
            ocr_value=None, corrected_value="JANE", reviewer="one",
            validator="one", approved_by="one", document_family="receipt",
        )
