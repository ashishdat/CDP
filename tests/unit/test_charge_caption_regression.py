"""Original-source caption failures must not become whole-dollar amounts."""
import pytest
from packages.extraction_recovery.span_selection import select_field_span

@pytest.mark.parametrize('raw', ['8. TOTAL CHARGE\n29', '12\n8. TOTAL CHARGE', '28. TOTAL CHARGE 450', '.TOTALCHARGE\n29', '8.TOTALCHARGE 2','8.TOTALCHARGE2'])
def test_caption_contaminated_integer_requires_localization(raw):
    result = select_field_span(raw, 'CURRENCY', 'total_charge')
    assert result.selected_text == ''
    assert 'CAPTION_CONTAMINATED_AMOUNT_REQUIRES_LOCALIZATION' in result.reason_codes

@pytest.mark.parametrize('raw,expected', [('28. TOTAL CHARGE $450.00','450.00'),('212.00','212.00'),('450','450.00')])
def test_clean_amounts_and_explicit_decimal_are_preserved(raw,expected):
    assert select_field_span(raw,'CURRENCY','total_charge').selected_text == expected

def test_service_line_whole_dollars_remain_supported():
    assert select_field_span('225','CURRENCY','charges').selected_text == '225.00'

@pytest.mark.parametrize('raw',['8.TOTALCHARGE 2','8.TOTALCHARGE2','.TOTALCHARGE\n29','12\n8. TOTAL CHARGE'])
def test_monetary_portfolio_cannot_join_caption_digits(raw):
    from packages.ocr_portfolio import shape_monetary
    assert shape_monetary(raw) is None

def test_monetary_portfolio_keeps_explicit_amount_beside_caption():
    from packages.ocr_portfolio import shape_monetary
    assert shape_monetary('28. TOTAL CHARGE $450.00') == '450.00'

@pytest.mark.parametrize('selective',['0','1'])
def test_primary_confirmation_and_raw_retry_cannot_reintroduce_rejected_caption(monkeypatch,selective):
    from types import SimpleNamespace
    from PIL import Image
    from packages.ocr_contracts import TextLine
    from packages.ocr_router import OCRObservation, OCRAttempt, OCRRoutingResult
    from scripts import ocr_from_geometry as module
    observation=OCRObservation((TextLine('8. TOTAL CHARGE',0,0,80,10,.95),TextLine('29',0,12,15,22,.95)))
    class Router:
        def route(self,request):
            attempt=OCRAttempt((request.engine_order or ('paddleocr',))[0],observation,1,'OBSERVED')
            return OCRRoutingResult(attempt,(attempt,),'OBSERVED')
    monkeypatch.setenv('CDP_OCR_SELECTIVE_CONFIRM',selective)
    monkeypatch.setattr(module,'_preprocessing_registry',lambda:SimpleNamespace(apply=lambda image,*args:SimpleNamespace(image=image,profile='identity',version='test')))
    candidates,attempts,_=module._recognize_one(Image.new('L',(100,30),255),'total_charge',(0,0,100,30),Router(),'currency',engine_order=('paddleocr','rapidocr'))
    assert not candidates
    assert any(a.get('amount_observation_rejection') for a in attempts)
    assert attempts[0]['observation']['lines'][1]['text']=='29'
