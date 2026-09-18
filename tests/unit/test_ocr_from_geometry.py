from unittest.mock import Mock

import pytest
from PIL import Image

from packages.ocr_router import ENGINE_ORDER, OCRObservation, OCRRouter
from scripts.ocr_from_geometry import recognize_regions
from workers.page_detection.text_extraction import TextLine


@pytest.fixture(autouse=True)
def _clear_ocr_field_scope(monkeypatch):
    """Unit geometry OCR must not inherit operational STP field-scope env."""
    monkeypatch.delenv("CDP_OCR_FIELD_SCOPE", raising=False)


def geometry():
    box={"x0": 2,"y0": 3,"x1": 12,"y1": 15}
    return {'status':'SUCCESS','coordinate_frame':'rectified_template_pixels',
            'fields':[{'field':'test','result':{'aligned_roi':box,'safe_cell':box}}]}


def test_candidates_preserve_regions_and_raw_text():
    calls=[]
    def recognize(request):
        calls.append(request.bbox)
        return OCRObservation((TextLine(' raw ',2,3,12,15,.8),))
    router=OCRRouter(lambda a: True,factories={name:lambda:recognize for name in ENGINE_ORDER})
    with Image.new('L',(20,20)) as im:rows=recognize_regions(im,geometry(),router)
    # Field cascade may confirm across engines; every call must use the geometry ROI.
    assert calls and all(box == (2, 3, 12, 15) for box in calls)
    c=rows[0]['candidates'][0]
    assert c['raw_value']==' raw '
    # Span selection may trim; raw_value remains the unmodified OCR observation.
    assert c['value'].strip()=='raw'
    assert c['validation_results']==()
    assert len(rows[0]['attempts'])>=1


def test_invalid_region_stops_before_providers():
    g=geometry();g['fields'][0]['result']['aligned_roi']={"x0": 0,"y0": 0,"x1": 20,"y1": 20}
    router=Mock()
    with Image.new('L',(20,20)) as im,pytest.raises(ValueError):recognize_regions(im,g,router)
    router.route.assert_not_called()


def test_blank_observations_do_not_invent_candidates():
    router=OCRRouter(lambda a:True,factories={name:lambda:lambda req:OCRObservation(()) for name in ENGINE_ORDER})
    with Image.new('L',(20,20)) as im:rows=recognize_regions(im,geometry(),router)
    assert rows[0]['candidates']==[]
    assert rows[0]['status']=='NO_OBSERVATION'
