from packages.extraction_recovery.dob_confirmation import dob_component_conflicts
from packages.extraction_recovery.dob_trocr_residual import DobTrOCRResidualResult, residual_candidate_dict

def test_hinted_or_review_only_component_cannot_veto_blind_date():
    candidates=[{'engine':'paddleocr','value':'11/27/1969'}]
    attempt={'engine':'claude','observation':{'parts':{'YY':'1949'}}}
    assert dob_component_conflicts(candidates,[attempt])
    assert not dob_component_conflicts(candidates,[{**attempt,'prior_hints_supplied':True}])
    assert not dob_component_conflicts(candidates,[{**attempt,'shadow_review_only':True}])

def test_trocr_score_is_raw_not_calibrated():
    result=DobTrOCRResidualResult(attempted=True,configured=True,review_only=True,
        value='11/27/1969',raw_value='11/27/1969',date_shaped=True,reason='OBSERVED',confidence=.97)
    candidate=residual_candidate_dict(result)
    assert candidate['raw_confidence']==.97
    assert candidate['calibrated_confidence'] is None
    assert candidate['shadow_review_only']
