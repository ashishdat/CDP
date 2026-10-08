import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from packages.domain.common import BoundingBox
from packages.evidence.builder import build_evidence_bundle
from packages.ocr.contracts import OCRCandidate
from packages.ocr.provenance import EvidenceProvenance
from scripts import ocr_from_geometry as ocr


def candidate(engine, *, shared):
    tag = 'shared' if shared else engine
    x = 0 if shared or engine == 'rapidocr' else 300
    box = BoundingBox(x0=x, y0=0, x1=x + 100, y1=30, image_width=500, image_height=30)
    provenance = EvidenceProvenance(
        source_representation_id=tag, crop_sha256=tag, localization_id=tag,
        preprocessing_profile=tag, engine_family=engine, bbox=box)
    return OCRCandidate(value='01/02/2000', raw_value='01/02/2000', engine=engine,
                        model_name=engine, model_version='test', preprocessing_variant=tag,
                        raw_confidence=.99, calibrated_confidence=None, latency_ms=0,
                        bounding_box=box, provenance=provenance)


def evidence(candidates):
    return build_evidence_bundle(field_name='patient_dob', candidates=candidates,
                                 registration_confidence=.99, wrong_crop_suspected=False,
                                 deterministic_evidence={'DATE_VALID'}, hard_validation_passed=True)


@pytest.mark.parametrize('engines', [
    ('rapidocr', 'paddleocr'), ('anthropic_claude_crop', 'rapidocr'),
    ('anthropic_claude_crop', 'azure_gpt4o_crop'),
])
def test_calendar_helper_cannot_override_correlated_observations(engines):
    bundle = evidence([candidate(engine, shared=True) for engine in engines])
    assert not any(e.evidence_class.value == 'E2' and e.independent for e in bundle.items)


def test_independent_calendar_reads_still_confirm():
    bundle = evidence([candidate('rapidocr', shared=False), candidate('paddleocr', shared=False)])
    assert any(e.evidence_class.value == 'E2' and e.independent for e in bundle.items)


def test_one_calendar_read_never_becomes_independent_agreement():
    bundle = evidence([candidate('rapidocr', shared=False)])
    assert not any(e.evidence_class.value == 'E2' and e.independent for e in bundle.items)


def test_tesseract_cell_recovery_keeps_actual_reader(monkeypatch):
    reads = iter(['01', '02', '2000'])
    monkeypatch.setitem(sys.modules, 'pytesseract', SimpleNamespace(
        image_to_string=lambda *args, **kwargs: next(reads)))
    monkeypatch.setattr(ocr, '_recognize_dob_cells_for_engine',
                        _only_tesseract(ocr._recognize_dob_cells_for_engine))
    candidates, _, _ = ocr._recognize_dob_cells(
        Image.new('L', (120, 30), 255), (0, 0, 120, 30), None, ('rapidocr', 'paddleocr'))
    assert len(candidates) == 1
    assert candidates[0]['engine'] == 'tesseract'


def _only_tesseract(original):
    def read(image, band, router, engines):
        return original(image, band, router, engines) if engines == ('tesseract',) else ([], [], 'EMPTY')
    return read


def test_impossible_cell_date_cannot_stop_valid_reader_recovery(monkeypatch):
    reads = iter(['02', '30', '2000'])
    monkeypatch.setitem(sys.modules, 'pytesseract', SimpleNamespace(
        image_to_string=lambda *args, **kwargs: next(reads)))
    candidates, _, _ = ocr._recognize_dob_cells_for_engine(
        Image.new('L', (120, 30), 255), (0, 0, 120, 30), None, ('tesseract',))
    assert candidates == []
