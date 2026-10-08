"""Regression inputs taken from the stopped run's provider observations."""
import pytest
from packages.extraction_recovery.dob_azure_di_residual import _shape_dob_text, residual_candidate_dict, DobAzureDiResidualResult

@pytest.mark.parametrize("raw",[
    ".YY 1 1/965M DD 130 MM 01",
    "YY 1 DD 1 no 20 1017 N MM",
    "09 119 62",
    "MM DD YY 3 0 SM 1",
])
def test_caption_and_partial_digits_cannot_create_date_candidates(raw):
    value,shaped=_shape_dob_text("patient_dob",raw)
    assert value is None and not shaped
    result=DobAzureDiResidualResult(True,True,True,value,raw,shaped,"AZURE_DI_UNSHAPED")
    assert residual_candidate_dict(result) is None
    assert result.raw_value==raw

@pytest.mark.parametrize("raw",["09/13/1962","DOB: 01/30/1965","05/30/1947"])
def test_intact_observed_dates_survive(raw):
    value,shaped=_shape_dob_text("patient_dob",raw)
    assert shaped and value in raw

def test_multiple_observed_dates_remain_unresolved():
    assert _shape_dob_text("patient_dob","09/13/1962 or 09/19/1962")== (None,False)

def test_explicit_future_year_is_not_rewritten_to_past():
    assert _shape_dob_text("patient_dob","01/30/2074")== (None,False)



def test_clean_ordered_components_are_observed_but_ruling_digits_are_not_dropped():
    assert _shape_dob_text("patient_dob","02\n15\n2006",allow_ordered_components=True)==("02/15/2006",True)
    assert _shape_dob_text("patient_dob","09\n119\n62",allow_ordered_components=True)==(None,False)

def test_spatial_date_normalization_retains_two_digit_year_policy():
    assert _shape_dob_text("patient_dob","09/13/62")==("09/13/1962",True)



def test_component_acquisition_uses_recorded_cell_without_expanding_geometry(monkeypatch):
    from PIL import Image
    import sys
    from types import SimpleNamespace
    from scripts.ocr_from_geometry import _recognize_dob_cells_for_engine
    sizes=[];values=iter(["09","13","1962"])
    def read(crop,**kwargs):
        sizes.append(crop.size)
        return next(values)
    monkeypatch.setitem(sys.modules,"pytesseract",SimpleNamespace(image_to_string=read))
    candidates,attempts,_=_recognize_dob_cells_for_engine(Image.new("L",(1712,2216),255),
        (674,433,882,458),None,("tesseract",),canonical_cell=(672,420,883,465))
    assert len(candidates)==1
    assert all(height==43*3 for width,height in sizes)
    assert candidates[0]["bounding_box"]["y0"]==421
    assert candidates[0]["bounding_box"]["y1"]==464
    assert all(a["component_bbox"][3]<=465 for a in attempts if "component_bbox"in a)


def test_explicit_future_cell_year_is_not_century_repaired(monkeypatch):
    from PIL import Image
    import sys
    from types import SimpleNamespace
    from scripts.ocr_from_geometry import _recognize_dob_cells_for_engine
    values=iter(["05","30","2074"])
    monkeypatch.setitem(sys.modules,"pytesseract",SimpleNamespace(image_to_string=lambda *a,**k:next(values)))
    candidates,attempts,reason=_recognize_dob_cells_for_engine(Image.new("L",(120,30),255),(0,0,120,30),None,("tesseract",))
    assert not candidates and reason=="DOB_EXPLICIT_FUTURE_YEAR"
    assert attempts[-1]["observation"]["parts"]["YY"]=="2074"
