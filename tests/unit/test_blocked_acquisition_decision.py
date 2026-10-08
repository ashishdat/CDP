from tests.unit.cases.test_evidence_decision_service import context
from packages.evidence_decision import EvidenceDecisionService, FieldDisposition

def test_unexecuted_ocr_is_not_reported_as_empty_observation():
    decision=EvidenceDecisionService().decide(context(candidates=[],hard_validation_passed=False,
        deterministic_evidence={'OCR_ACQUISITION_BLOCKED_LOCAL_ALIGNMENT'}))
    assert decision.disposition != FieldDisposition.AUTO_ACCEPTED
    assert 'OCR_ACQUISITION_BLOCKED_LOCAL_ALIGNMENT' in decision.reason_codes
    assert 'EMPTY_CROP' not in decision.reason_codes

def test_observed_empty_crop_keeps_existing_recovery():
    decision=EvidenceDecisionService().decide(context(candidates=[],hard_validation_passed=False,deterministic_evidence=set()))
    assert decision.disposition != FieldDisposition.AUTO_ACCEPTED
    assert 'EMPTY_CROP' in decision.reason_codes
