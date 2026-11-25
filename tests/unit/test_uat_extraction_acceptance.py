from types import SimpleNamespace

from packages.ocr.text_extraction import TextLine
from workers.unstructured_extraction.extraction_acceptance import ExtractionAcceptance


def page(text):
    return SimpleNamespace(lines=[TextLine(text, 0, 0, 100, 20, .95)])


ASSETS = [{'sha256': 'recorded-image-hash', 'width': 100, 'height': 100}]


def candidate(value, confidence=.95):
    return {'value': value, 'raw_confidence': confidence, 'evidence_reference': 'page:1:field',
            'field_association': 'DIRECT_LABEL'}


def test_photo_extraction_does_not_require_identity_provider():
    result = ExtractionAcceptance().decide('PERSON_PHOTO', [page('')], expected_pages=1,
                                           assets=ASSETS, candidates={})
    assert result['extraction_stp_eligible']
    assert result['asset_only']
    assert not result['correctness_verified']


def test_photo_without_persisted_asset_cannot_complete():
    result = ExtractionAcceptance().decide('PERSON_PHOTO', [page('')], expected_pages=1,
                                           assets=[], candidates={})
    assert not result['extraction_stp_eligible']
    assert 'PAGE_ASSET_NOT_PERSISTED' in result['reason_codes']


def test_complete_pathology_extraction_does_not_require_medical_signoff():
    result = ExtractionAcceptance().decide('PATH', [page('REPORT BIOCHEMISTRY')], expected_pages=1,
        assets=ASSETS, candidates={'patient_name': [candidate('JANE DOE')],
                                   'report_date': [candidate('29/06/2026')]})
    assert result['extraction_stp_eligible']


def test_missing_invalid_or_conflicting_fields_still_require_review():
    service = ExtractionAcceptance()
    result = service.decide('PATH', [page('BIOCHEMISTRY')], expected_pages=1,
        assets=ASSETS, candidates={'patient_name': [candidate('JANE DOE'), candidate('JOHN DOE')],
                                   'report_date': [candidate('31/02/2026')]})
    assert not result['extraction_stp_eligible']
    assert 'CONFLICTING_VALUES:patient_name' in result['reason_codes']
    assert 'MISSING_OR_INVALID:report_date' in result['reason_codes']


def test_low_confidence_and_missing_page_cannot_complete():
    result = ExtractionAcceptance().decide('PATH', [page('BIOCHEMISTRY')], expected_pages=2,
        assets=ASSETS, candidates={'patient_name': [candidate('JANE DOE', .4)],
                                   'report_date': [candidate('29/06/2026')]})
    assert not result['extraction_stp_eligible']
    assert 'LOW_OCR_CONFIDENCE:patient_name' in result['reason_codes']
    assert 'PAGE_EXTRACTION_INCOMPLETE' in result['reason_codes']
