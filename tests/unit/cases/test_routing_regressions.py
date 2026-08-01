import pytest

from packages.domain.common import BoundingBox
from packages.ocr.contracts import OCRCandidate
from workers.unstructured_extraction.evidence_selector import (
    FieldEvidenceSelector,
    PageFieldEvidence,
)


def _evidence(page, value, *, family=.8, anchor=.8, quality=.8, ocr=.8, valid=True):
    candidate = OCRCandidate(
        value=value, raw_value=value or "", engine="test", model_name="test",
        model_version="1", preprocessing_variant="original",
        raw_confidence=ocr, calibrated_confidence=ocr,
        bounding_box=BoundingBox(
            x0=1, y0=1, x1=5, y1=5, image_width=10, image_height=10
        ),
        latency_ms=1,
    )
    return PageFieldEvidence(
        "field", page, "family", candidate, family, anchor, quality, valid
    )


@pytest.mark.parametrize(
    ("scenario", "evidence", "expected"),
    [
        ("page_2_not_page_3", [_evidence(2, "RIGHT", ocr=.95), _evidence(3, "WRONG", ocr=.5)], 2),
        ("repeated_labels", [_evidence(1, "A", ocr=.6), _evidence(2, "B", ocr=.95)], 2),
        ("cover_summary", [_evidence(1, None, anchor=1), _evidence(2, "ID", anchor=.7)], 2),
        ("partial_identity", [_evidence(1, "JO", ocr=.5), _evidence(3, "JOHN", ocr=.95)], 3),
        ("same_family_pages", [_evidence(2, "X", ocr=.9), _evidence(4, "X", ocr=.6)], 2),
        ("strong_anchor_empty", [_evidence(1, None, anchor=1), _evidence(4, "X", anchor=.5)], 4),
    ],
)
def test_page_routing_regression_scenarios(scenario, evidence, expected):
    result = FieldEvidenceSelector(.5, .05).select(evidence)
    assert result.selected is not None, scenario
    assert result.selected.page_number == expected
