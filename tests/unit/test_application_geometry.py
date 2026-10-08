from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

from app import resolve_registered_geometry
from packages.domain.enums import ClaimFormType
from packages.templates.models import FieldRegion, ReferenceDimensions, Template


def registration():
    return {'status':'SUCCESS','accepted':True,'evidence':{'accepted':True,'corner_validity':True},
            'transform_matrix':[[1,0,0],[0,1,0],[0,0,1]],'template_id':'test','template_version':'1','page_number':1}


def test_rejection_never_enters_geometry(monkeypatch):
    forbidden=Mock(side_effect=AssertionError('Geometry executed'))
    monkeypatch.setattr('packages.geometry.engine.GeometryEngine.resolve',forbidden)
    with pytest.raises(ValueError):resolve_registered_geometry([],{'accepted':False},None)
    forbidden.assert_not_called()


def test_accepted_rectified_frame_does_not_refit_registration(monkeypatch):
    forbidden=Mock(side_effect=AssertionError('Registration refit'))
    monkeypatch.setattr('packages.geometry.engine.register',forbidden)
    template=Template(template_id='test',version='1',form_type=ClaimFormType.CMS1500,
        reference_dimensions=ReferenceDimensions(width_px=40,height_px=40),anchor_definitions=[],
        field_regions=[FieldRegion(field_name='test',x0=5,y0=5,x1=30,y1=30,field_type='text')])
    registry=SimpleNamespace(get=lambda *a:template)
    pixels=np.full((40,40),255,np.uint8);pixels[12:18,12:18]=0
    with Image.fromarray(pixels) as image:
        result=resolve_registered_geometry([image],registration(),registry)
    assert result['status']=='SUCCESS'
    assert result['template_id']=='test'
    assert result['template_version']=='1'
    assert result['template_fingerprint']
    assert result['fields'][0]['result']['text_envelope']=={'x0':12,'y0':12,'x1':18,'y1':18}
    forbidden.assert_not_called()


def test_first_geometry_failure_stops_fields():
    template=SimpleNamespace(reference_dimensions=SimpleNamespace(width_px=40,height_px=40),
        field_regions=[SimpleNamespace(field_name='outside',x0=35,y0=5,x1=50,y1=30),
                       SimpleNamespace(field_name='later',x0=5,y0=5,x1=30,y1=30)])
    with Image.new('L',(40,40),255) as image:
        result=resolve_registered_geometry([image],registration(),SimpleNamespace(get=lambda *a:template))
    assert result['status']=='FAILED'
    assert len(result['fields'])==1
