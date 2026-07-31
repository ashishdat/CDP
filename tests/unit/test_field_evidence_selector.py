from packages.domain.common import BoundingBox
from packages.ocr.contracts import OCRCandidate
from workers.unstructured_extraction.evidence_selector import (
    FieldEvidenceSelector,
    PageFieldEvidence,
)


def _candidate(value, confidence):
    return OCRCandidate(
        value=value, raw_value=value or "", engine="test", model_name="test",
        model_version="1", preprocessing_variant="original",
        raw_confidence=confidence, calibrated_confidence=confidence,
        bounding_box=BoundingBox(
            x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100
        ),
        latency_ms=1,
    )


def test_different_fields_can_select_different_pages():
    selector = FieldEvidenceSelector(.5)
    identity = selector.select([
        PageFieldEvidence("patient_name", 2, "claim", _candidate("JANE", .95), .9, .9, .9, True),
        PageFieldEvidence("patient_name", 3, "receipt", _candidate("JANE", .6), .7, .5, .8, True),
    ])
    clinical = selector.select([
        PageFieldEvidence("diagnosis", 2, "claim", _candidate(None, .9), .9, .2, .9, False),
        PageFieldEvidence("diagnosis", 3, "receipt", _candidate("F41.1", .9), .8, .95, .9, True),
    ])
    assert identity.selected.page_number == 2
    assert clinical.selected.page_number == 3


def test_high_confidence_candidate_failing_validation_is_rejected():
    result = FieldEvidenceSelector(.5).select([
        PageFieldEvidence("npi", 1, "claim", _candidate("WRONG", .99), .9, .9, .9, False)
    ])
    assert result.selected is None


def test_close_runner_up_routes_critical_field_to_review():
    selector = FieldEvidenceSelector(minimum_score=.5, minimum_margin=.08)
    result = selector.select([
        PageFieldEvidence("patient_name", 2, "claim", _candidate("JANE", .90), .9, .9, .9, True),
        PageFieldEvidence("patient_name", 3, "claim", _candidate("JANE", .88), .9, .9, .9, True),
    ], critical=True)
    assert result.selected is None
    assert result.reason == "winning_page_margin_below_threshold"
    assert result.review_required


def test_empty_strong_anchor_cannot_win():
    result = FieldEvidenceSelector(.5).select([
        PageFieldEvidence("member_id", 1, "cover", _candidate(None, .99), 1, 1, 1, True),
        PageFieldEvidence("member_id", 2, "claim", _candidate("M123", .8), .8, .8, .8, True),
    ])
    assert result.selected is not None
    assert result.selected.page_number == 2
