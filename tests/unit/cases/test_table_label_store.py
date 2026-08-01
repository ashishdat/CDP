from datetime import UTC, datetime

import pytest

from packages.table_label_store import TableLabelStore
from tests.unit.cases.test_table_contracts import make_label


def test_duplicate_and_contradictory_labels_are_rejected(tmp_path):
    store = TableLabelStore(tmp_path / "labels.jsonl")
    label = make_label()
    store.append(label)
    with pytest.raises(ValueError, match="duplicate"):
        store.append(label)
    with pytest.raises(ValueError, match="contradictory"):
        store.append(make_label(expected_value="99214", normalized_expected_value="99214"))


def test_critical_label_requires_independent_second_approval(tmp_path):
    store = TableLabelStore(tmp_path / "labels.jsonl", {"procedure_code"})
    with pytest.raises(ValueError, match="second approval"):
        store.append(make_label())
    store.append(make_label(
        second_reviewer_id="two",
        second_approval_at=datetime.now(UTC),
    ))


def test_corrected_label_requires_second_approval(tmp_path):
    store = TableLabelStore(tmp_path / "labels.jsonl")
    with pytest.raises(ValueError, match="second approval"):
        store.append(make_label(disposition="CORRECTED"))


def test_structural_disposition_requires_blank_value_and_comment(tmp_path):
    store = TableLabelStore(tmp_path / "labels.jsonl")
    with pytest.raises(ValueError, match="blank expected"):
        store.append(make_label(disposition="NOT_APPLICABLE"))
    with pytest.raises(ValueError, match="review comment"):
        store.append(make_label(
            disposition="NOT_APPLICABLE",
            expected_value="",
            normalized_expected_value="",
        ))
    store.append(make_label(
        disposition="NOT_APPLICABLE",
        expected_value="",
        normalized_expected_value="",
        review_comment="Contains a form header, not claim data.",
        approval_status="REJECTED",
    ))


def test_image_hash_mismatch_is_rejected(tmp_path):
    store = TableLabelStore(tmp_path / "labels.jsonl")
    store.append(make_label())
    image_root = tmp_path / "images"
    image_root.mkdir()
    (image_root / "A-01.png").write_bytes(b"wrong image")
    with pytest.raises(ValueError, match="image hash mismatch"):
        store.approved(image_root)
