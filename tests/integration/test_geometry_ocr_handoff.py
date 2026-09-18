"""Exercise the on-disk producer/consumer handoff, with synthetic upstream evidence."""
import json
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from PIL import Image

import app
from packages.domain.enums import BundleType
from packages.ocr_router import ENGINE_ORDER, OCRObservation, OCRRouter
from packages.templates.registry import TemplateRegistry
from scripts.ocr_from_geometry import run
from workers.page_detection.registration_telemetry import COLLECTION, RegistrationTrace
from workers.page_detection.router import PageRoutingResult
from workers.page_detection.template_selector import TemplateSelection
from workers.page_detection.text_extraction import TextLine


def test_geometry_artifact_resumes_ocr_without_manual_enrichment(tmp_path, monkeypatch):
    stream=BytesIO()
    with Image.new('L',(1712,2214),255) as image:image.save(stream,format='TIFF')
    payload=stream.getvalue();archive=tmp_path/'source.zip'
    with ZipFile(archive,'w') as z:z.writestr('claim.tiff',payload)
    manager=SimpleNamespace(root=archive,describe=dict,verify=lambda:{'verified':True})
    monkeypatch.setattr(app.DatasetManager,'load',lambda *a:manager)
    monkeypatch.setattr('workers.cascade.tesseract_adapter.TesseractTextExtractor.extract',lambda *a:[])
    registry=TemplateRegistry.load_from_directory(canonical_dir=None)
    # Pin frozen V2 identity — canonical registration package is 02-12 only.
    template=registry.get("cms1500", "02-12")
    monkeypatch.setattr('workers.page_detection.router.PageRoutingService.route',lambda *a:PageRoutingResult(BundleType.A_CMS1500_SINGLE,1,template,{}, {},False,[]))
    monkeypatch.setattr('workers.page_detection.template_selector.TemplateSelector.select',lambda *a,**k:TemplateSelection(template.template_id,1.,'SYNTHETIC',[],template.version,1))
    matrix=[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]
    accepted={'status':'SUCCESS','accepted':True,'reason':'SYNTHETIC_ACCEPTED',
              'page_number':1,'template_id':template.template_id,'template_version':template.version,
              'transform_matrix':matrix,'evidence':{'accepted':True,'corner_validity':True,'transform_matrix':matrix}}
    def registration(*args):
        trace=RegistrationTrace();COLLECTION.get().append(trace)
        trace.emit('Registration Started','OBSERVED',coverage_observation={'stage':'Input image','reference':{'size':[1712,2214]}})
        return accepted
    monkeypatch.setattr(app,'register_classified_document',registration)
    path,state=app.process_one(document='claim.tiff',output_root=tmp_path/'application')
    assert state['stages']['geometry']=='SUCCESS'
    telemetry=json.loads((path.parent/'geometry_telemetry.json').read_text())
    assert telemetry['registration_evidence']==accepted['evidence']
    assert telemetry['document_id']==sha256(payload).hexdigest()
    assert telemetry['source']=={'archive':str(archive),'entry':'claim.tiff'}
    seen=[]
    def provider(req):
        seen.append(req.bbox)
        return OCRObservation((TextLine('synthetic',*req.bbox,.9),))
    router=OCRRouter(lambda a:True,factories={n:lambda:provider for n in ENGINE_ORDER})
    monkeypatch.setattr('scripts.ocr_from_geometry.OCRRouter',lambda *a:router)
    forbidden=Mock(side_effect=AssertionError('Upstream execution during OCR resume'))
    monkeypatch.setattr('workers.page_detection.template_alignment.align_to_reference',forbidden)
    monkeypatch.setattr('packages.geometry.engine.GeometryEngine.resolve',forbidden)
    result=run(path.parent,tmp_path/'ocr')
    assert result['status']=='COMPLETED' and len(result['fields'])==25
    # Field-cascade may invoke the router multiple times per field (primary,
    # confirmation, recovery variants) and may pad/adjust crop boxes.
    assert len(seen) >= 25
    forbidden.assert_not_called()
    # The unchanged consumer still rejects a mismatched source identity.
    telemetry['document_id']='wrong'
    (path.parent/'geometry_telemetry.json').write_text(json.dumps(telemetry))
    with pytest.raises(ValueError,match='Source TIFF hash mismatch'):run(path.parent,tmp_path/'bad')
    assert len(seen) >= 25
