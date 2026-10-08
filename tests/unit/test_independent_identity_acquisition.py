from PIL import Image
from packages.extraction_recovery.cloud_stop_ladder import should_skip_second_cloud
from packages.extraction_recovery.name_azure_di_confirm import maybe_confirm_name_with_azure_di,ObservedNameCrop
from packages.extraction_recovery.dob_azure_di_residual import DobAzureDiResidualResult,residual_candidate_dict


def test_one_vision_name_does_not_block_independent_acquisition(monkeypatch):
    monkeypatch.setenv("CDP_CLOUD_STOP_LADDER","1")
    row={"field":"patient_name","canonical_region":[5,5,180,40],
        "gpt4o_crop_residual":{"value":"SMITH, JOHN","shaped":True,"review_only":False},
        "candidates":[{"engine":"anthropic_claude_crop","value":"SMITH, JOHN"}]}
    assert not should_skip_second_cloud(row)
    calls=[]
    def reader(image,name):
        calls.append(name)
        return ObservedNameCrop("SMITH, JOHN",.74,(0,0,188,48))
    updated=maybe_confirm_name_with_azure_di(row,image=Image.new("RGB",(200,80)),reader=reader)
    assert calls == ["patient_name"]
    candidate=updated["candidates"][0]
    assert candidate["raw_confidence"] == .74
    assert candidate["calibrated_confidence"] is None
    assert candidate["bounding_box"]["x1"] == 188
    maybe_confirm_name_with_azure_di(updated,image=Image.new("RGB",(200,80)),reader=reader)
    assert len(calls) == 1


def test_disagreeing_di_name_is_retained_as_review_evidence(monkeypatch):
    monkeypatch.setenv("CDP_CLOUD_STOP_LADDER","1")
    row={"field":"patient_name","canonical_region":[5,5,180,40],
        "candidates":[{"engine":"anthropic_claude_crop","value":"SMITH, JOHN"}]}
    updated=maybe_confirm_name_with_azure_di(row,image=Image.new("RGB",(200,80)),
        reader=lambda *args:ObservedNameCrop("JONES, MARY",.99,(5,5,180,40)))
    assert len(updated["candidates"]) == 1
    assert updated["attempts"][-1]["reason"] == "NAME_DI_DISAGREES"
    assert not (updated.get("cascade") or {}).get("accepted")


def test_di_dob_raw_score_is_not_calibration():
    result=DobAzureDiResidualResult(True,True,False,"07/23/1957","07/23/1957",True,"OBSERVED",raw_confidence=.77)
    candidate=residual_candidate_dict(result)
    assert candidate["raw_confidence"] == .77
    assert candidate["calibrated_confidence"] is None
