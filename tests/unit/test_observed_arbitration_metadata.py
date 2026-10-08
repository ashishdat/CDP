from PIL import Image
from packages.extraction_recovery.conflict_agent import _agent_candidate, maybe_attach_conflict_agent_to_field_row, maybe_resolve_financial_conflict
from tests.unit.cases.test_conflict_agent import _FakeEngine

def test_provider_confidence_is_preserved_and_not_declared_calibrated(monkeypatch):
    monkeypatch.setenv('CDP_CONFLICT_AGENT','1');monkeypatch.setenv('CDP_GPT4O_CROP_RESIDUAL','1')
    row={'field':'patient_dob','ocr_region':[0,0,100,50],'candidates':[{'engine':'tesseract','value':'09/13/1962'},{'engine':'rapidocr','value':'09/19/1962'}]}
    result=maybe_attach_conflict_agent_to_field_row(row,image=Image.new('RGB',(100,50)),engine=_FakeEngine('09/13/1962'))
    candidate=result['candidates'][0]
    assert candidate['raw_confidence']==.95
    assert candidate['calibrated_confidence'] is None
    assert candidate['prior_hints_supplied'] is True

def test_unknown_or_nonfinite_confidence_is_never_fabricated():
    for confidence in [None,float('nan'),float('inf'),1.1,-.1]:
        c=_agent_candidate(value='09/13/1962',bbox=(0,0,100,50),image=Image.new('RGB',(100,50)),reason='TEST',variant='test',confidence=confidence)
        assert c['raw_confidence']==0 and c['calibrated_confidence'] is None

def test_financial_side_reply_does_not_become_amount_reader(monkeypatch):
    monkeypatch.setenv('CDP_CONFLICT_AGENT','1');monkeypatch.setenv('CDP_GPT4O_CROP_RESIDUAL','1')
    fields=[{'field':'total_charge','ocr_region':[0,0,100,50],'candidates':[{'engine':'paddleocr','value':'783.00'}]}]
    result,_=maybe_resolve_financial_conflict(image=Image.new('RGB',(100,50)),fields=fields,service_lines=[{'charges':'261.00'},{'charges':'261.00'}],engine=_FakeEngine('BOX28'))
    assert result[0]['candidates']==fields[0]['candidates']
    assert not result[0]['cascade']['accepted']

def test_future_partial_year_cannot_veto_valid_birthdate():
    from packages.extraction_recovery.dob_confirmation import dob_component_conflicts
    assert not dob_component_conflicts([{'engine':'tesseract','value':'09/13/1962'}],[{'engine':'rapidocr','observation':{'parts':{'YY':'2078'}}}])
