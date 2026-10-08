from types import SimpleNamespace
from PIL import Image
from packages.extraction_recovery.id_azure_di_confirm import maybe_confirm_id_with_azure_di


def test_independent_id_is_literal_and_does_not_replace_rival(monkeypatch):
    monkeypatch.setenv('CDP_AZURE_DI_ID_CONFIRM','1')
    row={'field':'insured_id_number','canonical_region':[5,5,180,40],
         'candidates':[{'engine':'rapidocr','value':'OSC75126744-01'}]}
    calls=[]
    def read(request):
        calls.append(request)
        return [SimpleNamespace(raw_value='0SC75126744-01',raw_confidence=.93)]
    engine=SimpleNamespace(recognize=read)
    result=maybe_confirm_id_with_azure_di(row,image=Image.new('RGB',(200,80)),engine=engine)
    assert [c['value'] for c in result['candidates']] == ['OSC75126744-01','0SC75126744-01']
    assert result['candidates'][-1]['raw_confidence'] == .93
    assert result['candidates'][-1]['calibrated_confidence'] is None
    assert not (result.get('cascade') or {}).get('accepted')
    maybe_confirm_id_with_azure_di(result,image=Image.new('RGB',(200,80)),engine=engine)
    assert len(calls) == 1


def test_header_only_id_does_not_become_an_identifier(monkeypatch):
    monkeypatch.setenv('CDP_AZURE_DI_ID_CONFIRM','1')
    row={'field':'insured_id_number','canonical_region':[5,5,180,40],'candidates':[]}
    engine=SimpleNamespace(recognize=lambda request:[SimpleNamespace(raw_value="1a INSURED'S I.D. NUMBER",raw_confidence=.99)])
    result=maybe_confirm_id_with_azure_di(row,image=Image.new('RGB',(200,80)),engine=engine)
    assert not result['candidates']
    assert result['id_di_confirmation']['reason'] == 'ID_DI_UNSHAPED'
