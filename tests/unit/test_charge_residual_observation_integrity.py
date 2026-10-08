from types import SimpleNamespace
import pytest
from PIL import Image
from packages.extraction_recovery.charge_azure_di_residual import (
    _shape_charge_text, _recognize_with_azure_read_engine, residual_candidate_dict,
    promote_currency_shaped, run_charge_azure_di_residual, ChargeAzureDiResidualResult,
)


@pytest.mark.parametrize("raw",["28. TOTAL CHARGE","ENT? 28. TOTAL CHARGE S 45000 29. AMOUN $"])
def test_rejected_caption_cannot_reenter_through_di_adapter(raw):
    engine=SimpleNamespace(recognize=lambda request:[SimpleNamespace(raw_value=raw,raw_confidence=.99)])
    result=_recognize_with_azure_read_engine(engine,Image.new("RGB",(200,80)),"total_charge",review_only=True)
    assert result.raw_value == raw
    assert not result.currency_shaped
    assert residual_candidate_dict(promote_currency_shaped(result)) is None


def test_confidence_and_promotion_preserve_the_observed_reader(monkeypatch):
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_ACCEPT","1")
    engine=SimpleNamespace(recognize=lambda request:[SimpleNamespace(
        raw_value="$450.00",raw_confidence=.73,calibrated_confidence=.99)])
    result=_recognize_with_azure_read_engine(engine,Image.new("RGB",(200,80)),"total_charge",review_only=True)
    candidate=residual_candidate_dict(promote_currency_shaped(result))
    assert candidate["value"] == "450.00"
    assert candidate["raw_confidence"] == .73
    assert candidate["calibrated_confidence"] is None


def test_missing_confidence_is_not_a_calibrated_preset():
    result=ChargeAzureDiResidualResult(True,True,False,"450.00","450.00",True,"OBSERVED")
    candidate=residual_candidate_dict(result)
    assert candidate["raw_confidence"] == 0
    assert candidate["calibrated_confidence"] is None


def test_expanded_retry_keeps_its_actual_crop_and_confidence(monkeypatch):
    monkeypatch.setenv("CDP_AZURE_DI_CHARGE_RESIDUAL","1")
    class Reader:
        calls=0
        def recognize_crop(self,crop,field):
            self.calls+=1
            value="450.00" if self.calls == 2 else None
            return ChargeAzureDiResidualResult(True,True,True,value,value,bool(value),"OBSERVED",raw_confidence=.91)
    reader=Reader();box=(100,80,220,130)
    result=run_charge_azure_di_residual(image=Image.new("RGB",(400,200)),bbox=box,
        field_name="total_charge",gap_class="CHARGE_LOCAL_EXHAUSTED",engine=reader)
    candidate=residual_candidate_dict(result,bbox=box,image_size=(400,200))
    assert reader.calls == 2
    assert result.observation_bbox != box
    assert tuple(candidate["bounding_box"][k] for k in ("x0","y0","x1","y1")) == result.observation_bbox
    assert candidate["raw_confidence"] == .91
