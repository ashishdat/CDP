from PIL import Image
from types import SimpleNamespace
from scripts import ocr_from_geometry as module
from packages.extraction_recovery.gpt4o_crop_residual import _dob_cell_bboxes as cloud_cells


def test_native_and_cloud_read_the_same_registered_subcells():
    band=(674,421,882,464)
    assert list(module._dob_cell_bboxes(band).values()) == cloud_cells(band)
    assert cloud_cells(band)[2][0] == 798
    assert cloud_cells(band)[2][2] == 868


def test_successful_identical_reads_do_not_repeat_candidates(monkeypatch):
    calls=[]
    def read(*args):
        calls.append(args)
        return [{"engine":"rapidocr","value":"06/12/1987"}], [{"engine":"rapidocr","observation":{"parts":{"MM":"06","DD":"12","YY":"1987"}}}], "DOB_CELLS_ASSEMBLED"
    monkeypatch.setattr(module,"_recognize_dob_cells_for_engine_uncached",read)
    image=Image.new("L",(1712,2214),255);cell=(672,420,883,465)
    first=module._recognize_dob_cells_for_engine(image,cell,None,("rapidocr",),cell)
    second=module._recognize_dob_cells_for_engine(image,(674,443,882,459),None,("rapidocr",),cell)
    assert len(calls) == 1 and first[0]
    assert not second[0]
    assert second[1][0]["new_reader_observation"] is False
    assert second[1][0]["reason"] == "DOB_IDENTICAL_SUCCESSFUL_READ_REUSED"


def test_unqualified_single_month_and_single_day_remain_incomplete():
    assert not module.dob_boxed_cells_complete("3","22","1959")
    assert module.dob_boxed_cells_complete("3","22","1959",qualified_single_month=True)
    assert not module.dob_boxed_cells_complete("3","2","1959",qualified_single_month=True)


def test_one_digit_month_requires_observed_caption_and_complete_numeric_word():
    from packages.ocr_router import OCRObservation
    from packages.ocr_contracts import TextLine
    observations=iter([
        OCRObservation((TextLine("MM",5,10,50,30,.99),TextLine("3",25,75,55,115,.95))),
        OCRObservation((TextLine("DD",5,10,50,30,.99),TextLine("22",25,75,65,115,.96))),
        OCRObservation((TextLine("YY",5,10,50,30,.99),TextLine("1959",20,75,100,115,.97)))])
    router=SimpleNamespace(route=lambda request:SimpleNamespace(attempts=[SimpleNamespace(
        engine="rapidocr",reason="OBSERVED",latency_ns=0,observation=next(observations))]))
    image=Image.new("L",(1712,2214),255);cell=(672,420,883,465)
    candidates,attempts,reason=module._recognize_dob_cells_for_engine(image,cell,router,("rapidocr",),cell)
    assert candidates[0]["value"] == "03/22/1959"
    assert candidates[0]["engine"] == "rapidocr"
    assert candidates[0]["raw_confidence"] == .95
    assert attempts[-1]["observation"]["qualified_single_month"]



def test_ub04_compact_date_keeps_literal_year_and_rejects_ambiguous_short_dates():
    from packages.extraction_recovery.compact_birthdate import compact_birthdate
    assert compact_birthdate("08031987") == "1987-08-03"
    assert compact_birthdate("2131957") == "1957-02-13"
    assert compact_birthdate("1121957") is None
    assert compact_birthdate("0711987") is None  # Could be a clipped 07/16/1987.
    assert compact_birthdate("02311987") is None
    assert compact_birthdate("01012099") is None
    assert compact_birthdate("YY 1 DD 1 no 20 1017 N MM") is None


def test_ub04_normalization_cannot_alter_other_fields_or_invent_a_reader():
    from packages.extraction_recovery.compact_birthdate import normalize_ub04_birthdate_candidates
    original={"engine":"rapidocr","value":"2131957","raw_value":"2131957", "raw_confidence":.81,"shadow_review_only":True}
    actual=normalize_ub04_birthdate_candidates("patient_dob",[original])[0]
    assert actual["value"] == "1957-02-13"
    assert actual["engine"] == "rapidocr" and actual["raw_confidence"] == .81
    assert actual["raw_value"] == "2131957" and actual["shadow_review_only"]
    assert normalize_ub04_birthdate_candidates("insured_id_number",[original])[0] == original
    altered={**original,"value":"2131957","raw_value":"021319578"}
    assert normalize_ub04_birthdate_candidates("patient_dob",[altered])[0]["value"] == "2131957"


def test_missing_dob_reader_is_not_reported_as_empty_digits(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules,"pytesseract",None)
    image=Image.new("L",(1712,2214),255);cell=(672,420,883,465)
    candidates,attempts,reason=module._recognize_dob_cells_for_engine_uncached(image,cell,None,("tesseract",),cell)
    assert not candidates and reason == "DOB_READER_UNAVAILABLE"
    assert attempts[0]["reader_failed"] is True
    assert not attempts[0].get("observation")


def test_dob_reader_failures_are_visible_and_not_cached(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules,"pytesseract",SimpleNamespace())
    calls=[]
    def failed(*args):
        calls.append(args);raise RuntimeError("controlled native reader failure")
    monkeypatch.setattr(module,"_tesseract_text_with_confidence",failed)
    image=Image.new("L",(1712,2214),255);cell=(672,420,883,465)
    first=module._recognize_dob_cells_for_engine(image,cell,None,("tesseract",),cell)
    count=len(calls)
    second=module._recognize_dob_cells_for_engine(image,cell,None,("tesseract",),cell)
    assert any(a.get("reader_failed") for a in first[1])
    assert len(calls)==2*count and count>0
    assert not any(a.get("reason")=="DOB_IDENTICAL_EMPTY_READ_REUSED" for a in second[1])



def test_single_one_month_is_not_authorized_as_a_clipped_twelve():
    assert not module.dob_boxed_cells_complete("1","23","1959",qualified_single_month=True)


def test_literal_component_fallback_is_one_reader_and_preserves_actual_confidence():
    from packages.extraction_recovery.dob_literal_components import read_literal_components
    from packages.ocr_contracts import TextLine
    readings=iter([
        [TextLine("MM",5,5,35,20,.9),TextLine("09",20,30,50,70,.91)],
        [TextLine("DD",5,5,35,20,.9),TextLine("23",20,30,50,70,.92)],
        [TextLine("YY",5,5,35,20,.9),TextLine("1941",20,30,60,70,.93)]])
    reader=SimpleNamespace(extract=lambda crop:next(readings))
    result,trace=read_literal_components(Image.new("L",(300,100),255),
        {"MM":(0,0,100,100),"DD":(100,0,200,100),"YY":(200,0,300,100)},
        extractor=reader,preprocess=lambda image:image)
    assert result["value"] == "09/23/1941"
    assert result["engine"] == "tesseract" and result["raw_confidence"] == .91
    assert all(a["engine"]=="tesseract" for a in trace)


def test_literal_component_fallback_rejects_multiple_numeric_values_in_one_cell():
    from packages.extraction_recovery.dob_literal_components import read_literal_components
    from packages.ocr_contracts import TextLine
    readings=iter([[TextLine("09",20,30,40,70,.9),TextLine("11",50,30,70,70,.9)],
        [TextLine("23",20,30,40,70,.9)],[TextLine("1941",20,30,70,70,.9)]])
    result,trace=read_literal_components(Image.new("L",(300,100),255),
        {"MM":(0,0,100,100),"DD":(100,0,200,100),"YY":(200,0,300,100)},
        extractor=SimpleNamespace(extract=lambda image:next(readings)),preprocess=lambda image:image)
    assert result is None



def test_ruling_crossing_date_ink_does_not_shorten_approved_crop():
    from PIL import ImageDraw
    image=Image.new("L",(1712,2214),255);draw=ImageDraw.Draw(image)
    draw.line((672,459,882,459),fill=0)
    draw.line((724,451,724,463),fill=0,width=3)
    assert module._dob_bbox_before_bottom_ruling(image,(672,420,883,465),preserve_crossing_ink=True) == (672,420,883,465)


def test_static_dob_divider_does_not_authorize_extra_crop():
    from PIL import ImageDraw
    image=Image.new("L",(1712,2214),255);draw=ImageDraw.Draw(image)
    draw.line((672,459,882,459),fill=0)
    draw.line((740,450,740,464),fill=0,width=3)
    assert module._dob_bbox_before_bottom_ruling(image,(672,420,883,465)) == (672,420,883,459)



def test_literal_month_cannot_drop_first_digit_of_split_twelve():
    from packages.extraction_recovery.dob_literal_components import read_literal_components
    from packages.ocr_contracts import TextLine
    readings=iter([[TextLine("MM",5,5,35,20,.9),TextLine("1",20,30,30,70,.9),TextLine("2",40,30,50,70,.9)],
        [TextLine("23",20,30,50,70,.9)],[TextLine("1941",20,30,70,70,.9)]])
    result,_=read_literal_components(Image.new("L",(300,100),255),
        {"MM":(0,0,100,100),"DD":(100,0,200,100),"YY":(200,0,300,100)},
        extractor=SimpleNamespace(extract=lambda image:next(readings)),preprocess=lambda image:image)
    assert result is None
