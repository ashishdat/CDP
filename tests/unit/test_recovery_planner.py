from packages.recovery.diagnosis import Cause, diagnose
from packages.recovery.planner import Strategy, plan_recovery


def test_generic_registration_gate_fails_closed():
    diagnosis = diagnose(["unsafe_perspective_distortion"])
    assert diagnosis.primary_cause is Cause.UNDETERMINED
    plan = plan_recovery(diagnosis, strategy_available=True)
    assert plan.strategy is Strategy.HUMAN_QUEUE
    assert plan.executable is False


def test_explicit_missing_asset_allows_one_reference_attempt():
    diagnosis = diagnose(["reference_missing"], asset_missing=True)
    plan = plan_recovery(diagnosis, strategy_available=True)
    assert diagnosis.primary_cause is Cause.MISSING_ASSET
    assert plan.strategy is Strategy.REFERENCE_RECOVERY
    assert plan.executable is True
    assert plan.max_attempts == 1


def test_unknown_document_never_gets_a_template_guess():
    diagnosis = diagnose([], document_unknown=True)
    plan = plan_recovery(diagnosis, strategy_available=True)
    assert diagnosis.primary_cause is Cause.UNKNOWN_DOCUMENT
    assert plan.strategy is Strategy.HUMAN_QUEUE
    assert plan.executable is False


def test_contract_failure_is_not_retried():
    diagnosis = diagnose(["missing_extraction_result"], contract_failure=True)
    plan = plan_recovery(diagnosis, strategy_available=True)
    assert plan.strategy is Strategy.NONE
    assert plan.executable is False
