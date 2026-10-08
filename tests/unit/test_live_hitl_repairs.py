import pytest
from PIL import Image

@pytest.mark.parametrize('raw,kept',[('09\n119\n62',False),('09/19/1962',True)])
def test_confirmation_cannot_invent_date_from_malformed_components(monkeypatch,raw,kept):
    from packages.ocr_contracts import TextLine
    from packages.ocr_router import OCRObservation,OCRAttempt,OCRRoutingResult
    from scripts.ocr_from_geometry import _recognize_one
    monkeypatch.setenv('CDP_OCR_SELECTIVE_CONFIRM','1')
    class Router:
        def route(self,request):
            engine=request.engine_order[0];text='09/13/1962' if engine=='paddleocr' else raw
            obs=OCRObservation(tuple(TextLine(t,0,i*10,80,i*10+9,.95)for i,t in enumerate(text.splitlines())))
            a=OCRAttempt(engine,obs,1,'OBSERVED');return OCRRoutingResult(a,(a,),'OBSERVED')
    c,a,_=_recognize_one(Image.new('L',(100,50),255),'patient_dob',(0,0,100,50),Router(),'date',engine_order=('paddleocr','rapidocr'))
    assert any(x['engine']=='rapidocr'for x in c)==kept
    if not kept:assert a[-1]['dob_observation_rejection']=='UNSUPPORTED_DATE_TOKEN_ASSEMBLY'

def test_conflict_recommendation_retains_all_real_independent_agreeing_readers(monkeypatch):
    from packages.extraction_recovery.conflict_agent import maybe_attach_conflict_agent_to_field_row
    from tests.unit.cases.test_conflict_agent import _FakeEngine
    monkeypatch.setenv('CDP_CONFLICT_AGENT','1')
    row={'field':'patient_dob','ocr_region':[0,0,100,50],'candidates':[
        {'engine':'azure_document_intelligence_read','value':'12/31/1996'},
        {'engine':'tesseract','value':'12/31/1996'},
        {'engine':'rapidocr','value':'03/31/1996'}],'attempts':[]}
    r=maybe_attach_conflict_agent_to_field_row(row,image=Image.new('RGB',(100,50)),engine=_FakeEngine('12/31/1996'))
    engines=[c['engine']for c in r['candidates']]
    assert engines.count('azure_document_intelligence_read')==1
    assert engines.count('tesseract')==1
    assert engines.count('rapidocr')==1  # A genuine rival is retained.
    assert engines.count('anthropic_claude_crop')==1

def test_template_probe_is_bounded_but_selected_registration_keeps_recovery(monkeypatch):
    from types import SimpleNamespace
    from workers.page_detection import template_alignment as module
    policies=[]
    monkeypatch.setattr(module,'observe_coverage',lambda *a,**k:None)
    monkeypatch.setattr(module,'assess_template_compatibility',lambda *a,**k:SimpleNamespace(status='UNKNOWN'))
    monkeypatch.setattr(module,'_cheap_alignment',lambda *a:module._failure('cheap','TEST_MISS'))
    def sift(source,reference,policy):
        policies.append(policy);return module._failure('sift','TEST_MISS')
    monkeypatch.setattr(module,'_sift_alignment',sift)
    image=Image.new('L',(64,64),0)
    result=module.align_to_reference(image,image,allow_recovery=False)
    assert not result.accepted and len(policies)==1
    policies.clear()
    result=module.align_to_reference(image,image)  # Full selected-template path.
    assert not result.accepted and len(policies)>1
    baseline=module.DEFAULT_REGISTRATION_POLICY
    for policy in policies:
        for key in ['min_inliers','min_inlier_ratio','min_coverage_ratio','max_reprojection_error']:
            assert getattr(policy,key)==getattr(baseline,key)

def test_exhausted_probe_budget_never_accepts_unexamined_bundle(monkeypatch):
    from packages.templates.registry import TemplateRegistry
    from workers.page_detection import template_selector as module
    clock=iter([0,100]);monkeypatch.setattr(module,'perf_counter',lambda:next(clock))
    monkeypatch.setattr(module,'compute_grid_signature',lambda image:None)
    monkeypatch.setattr(module,'signature_similarity',lambda *args:0.0)
    monkeypatch.setattr(module,'align_to_reference',lambda *args,**kwargs:pytest.fail('Expired budget must not start native matching'))
    r=module.TemplateSelector(TemplateRegistry.load_from_directory()).select([Image.new('L',(64,64),255)],text_lines={})
    assert r.template_id is None and r.reason=='TEMPLATE_PROBE_BUDGET_EXHAUSTED'
    from packages.recovery.independent_failures import failure_category
    assert failure_category({'disposition':'REGISTRATION_FAILED','registration_ok':False,'registration_reason':r.reason})=='RUNTIME_ERROR'

def test_page_routing_budget_retains_unknown_pages_and_no_partial_winner(monkeypatch):
    import time
    from types import SimpleNamespace
    from packages.templates.registry import TemplateRegistry
    from packages.domain.enums import ClaimFormType,PageRole
    from workers.page_detection import router as module
    registry=TemplateRegistry.load_from_directory(canonical_dir=None)
    image=Image.new('L',(64,64),255)
    router=module.PageRoutingService(registry.latest_for_form_type(ClaimFormType.CMS1500),
        registry.latest_for_form_type(ClaimFormType.UB04),cms_reference_image=image)
    monkeypatch.setattr(router,'_extract_anchor_lines',lambda image:None)
    clock=iter([0,0,100]);monkeypatch.setattr(time,'perf_counter',lambda:next(clock))
    def alignment(*args,**kwargs):
        assert kwargs['allow_recovery'] is False
        return SimpleNamespace(success=True,alignment_score=.99,good_match_count=20,evidence=None)
    monkeypatch.setattr(module,'align_to_reference',alignment)
    result=router.route_multipage_bundle([image,image])
    assert result.selected_page_number is None and result.needs_review
    assert all(role==PageRole.UNKNOWN for role in result.page_roles.values())
    assert result.reason_codes==['PAGE_ROUTING_PROBE_BUDGET_EXHAUSTED']
