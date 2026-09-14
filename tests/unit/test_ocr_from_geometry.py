from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PIL import Image
from packages.ocr_router import OCRRouter, OCRObservation, ENGINE_ORDER
from workers.page_detection.text_extraction import TextLine
from scripts.ocr_from_geometry import recognize_regions


def geometry():
    box=dict(x0=2,y0=3,x1=12,y1=15)
    return {'status':'SUCCESS','coordinate_frame':'rectified_template_pixels',
            'fields':[{'field':'test','result':{'aligned_roi':box,'safe_cell':box}}]}


def test_candidates_preserve_regions_and_raw_text():
    calls=[]
    def recognize(request):
        calls.append(request.bbox)
        return OCRObservation((TextLine(' raw ',2,3,12,15,.8),))
    router=OCRRouter(lambda a: True,factories={name:lambda:recognize for name in ENGINE_ORDER})
    with Image.new('L',(20,20)) as im:rows=recognize_regions(im,geometry(),router)
    assert calls==[(2,3,12,15)]
    c=rows[0]['candidates'][0]
    assert c['raw_value']==' raw '
    assert c['value']==' raw '
    assert c['validation_results']==()
    assert len(rows[0]['attempts'])==1


def test_invalid_region_stops_before_providers():
    g=geometry();g['fields'][0]['result']['aligned_roi']=dict(x0=0,y0=0,x1=20,y1=20)
    router=Mock()
    with Image.new('L',(20,20)) as im,pytest.raises(ValueError):recognize_regions(im,g,router)
    router.route.assert_not_called()


def test_blank_observations_do_not_invent_candidates():
    router=OCRRouter(lambda a:True,factories={name:lambda:lambda req:OCRObservation(()) for name in ENGINE_ORDER})
    with Image.new('L',(20,20)) as im:rows=recognize_regions(im,geometry(),router)
    assert rows[0]['candidates']==[]
    assert rows[0]['status']=='NO_OBSERVATION'
