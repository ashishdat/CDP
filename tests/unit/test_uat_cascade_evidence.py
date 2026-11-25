from packages.ocr.text_extraction import TextLine
from workers.unstructured_extraction.uat_evidence import locate_value


def test_llm_value_must_be_present_in_ocr():
    sources=[(1,[TextLine('10/02/1973',10,10,120,30,.95)])]
    assert locate_value('11/10/1973',sources) is None
    assert locate_value('10/02/1973',sources)['raw_confidence']==.95


def test_matching_text_on_another_page_is_not_crop_evidence():
    sources=[(1,[TextLine('JANE DOE',10,10,120,30,.95)])]
    assert locate_value('JANE DOE',sources,page_number=2) is None


def test_matching_text_outside_the_sent_crop_is_not_evidence():
    sources=[(1,[TextLine('JANE DOE',10,10,120,30,.95)])]
    assert locate_value('JANE DOE',sources,page_number=1,region=(200,200,400,400)) is None
    assert locate_value('JANE DOE',sources,page_number=1,region=(0,0,150,50))
