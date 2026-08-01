from packages.reference_decisions import (
    MemberMatchEvidence,
    ProviderMatchEvidence,
    ReferenceDecision,
    decide_member,
    decide_provider,
)


def test_name_only_member_match_is_review_required():
    evidence = MemberMatchEvidence(False, False, .99, True)
    assert decide_member(evidence) == ReferenceDecision.HUMAN_REVIEW_REQUIRED


def test_member_requires_exact_id_dob_name_and_no_contradiction():
    verified = MemberMatchEvidence(True, True, .95, True, True)
    assert decide_member(verified) == ReferenceDecision.REFERENCE_VERIFIED
    assert decide_member(MemberMatchEvidence(True, True, .95, False)) == ReferenceDecision.REFERENCE_CONTRADICTION


def test_provider_requires_npi_and_name():
    assert decide_provider(ProviderMatchEvidence(True, .94, None)) == ReferenceDecision.REFERENCE_VERIFIED
    assert decide_provider(ProviderMatchEvidence(False, .99, True)) == ReferenceDecision.HUMAN_REVIEW_REQUIRED
