from datetime import UTC, datetime
from uuid import uuid4

import pytest

from packages.table_contracts import CellCandidate, CellLabel


def test_review_only_candidate_cannot_be_automatic():
    with pytest.raises(ValueError, match="review-only"):
        CellCandidate(
            candidate_id=uuid4(), document_id="A-01", page_number=1,
            document_family="CMS1500", table_type="CMS1500_SERVICE_LINES",
            table_bbox=(0, 0, 20, 20), table_index=0, row_index=0,
            column_name="procedure_code", cell_bbox=(0, 0, 10, 10),
            raw_text="99213", normalized_value="99213", confidence=0.9,
            provider="test", provider_version="1", template_version="1",
            preprocessing_profile="original", image_sha256="a" * 64,
            automatically_acceptable=True,
        )


def make_label(**overrides):
    values = {
        "label_id": uuid4(), "document_id": "A-01", "page_number": 1,
        "document_family": "CMS1500", "table_type": "CMS1500_SERVICE_LINES",
        "table_index": 0, "row_index": 0, "column_name": "procedure_code",
        "expected_value": "99213", "normalized_expected_value": "99213",
        "bbox": (0, 0, 10, 10), "image_sha256": "a" * 64,
        "writing_type": "PRINTED", "reviewer_id": "one",
        "reviewed_at": datetime.now(UTC), "approval_status": "APPROVED",
        "source": "HUMAN_REVIEW",
    }
    values.update(overrides)
    return CellLabel(**values)
