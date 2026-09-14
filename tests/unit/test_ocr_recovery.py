from packages.recovery.diagnosis import Cause, diagnose
from packages.recovery.ocr_recovery import decide_ocr_recovery
from packages.recovery.planner import Strategy, plan_recovery


def test_regional_ocr_empty_authorizes_one_alternate_profile():
    diagnosis = diagnose(["regional_ocr_empty"], ocr_attempted=True)
    assert diagnosis.primary_cause is Cause.OCR_FAILURE
    assert diagnosis.confidence == "MEDIUM"
    plan = plan_recovery(diagnosis, strategy_available=True)
    assert plan.strategy is Strategy.ALTERNATIVE_OCR
    assert plan.executable is True
    assert plan.max_attempts == 1


def test_decide_ocr_recovery_uses_mild_alternate_profile():
    decision = decide_ocr_recovery(primary_profile="DIGIT_PRESERVING_V2", primary_text="")
    assert decision.attempt_alternate is True
    assert decision.alternate_profile == "GENERAL_TEXT"
    assert decision.strategy is Strategy.ALTERNATIVE_OCR


def test_decide_ocr_recovery_skips_when_primary_has_text():
    decision = decide_ocr_recovery(primary_profile="DIGIT_PRESERVING_V2", primary_text="123")
    assert decision.attempt_alternate is False
