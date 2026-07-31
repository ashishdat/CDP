from packages.authorized_reference_validation import (
    ReferenceEvidence,
    critical_reference_acceptance,
)


def test_name_only_fuzzy_match_never_accepts_critical_field():
    assert not critical_reference_acceptance(
        ReferenceEvidence(patient_name_score=1.0)
    )


def test_member_id_dob_and_name_can_accept():
    assert critical_reference_acceptance(ReferenceEvidence(
        member_id_exact=True, dob_exact=True, patient_name_score=.95
    ))


def test_provider_npi_and_name_can_accept():
    assert critical_reference_acceptance(ReferenceEvidence(
        provider_npi_exact=True, provider_name_score=.9
    ))
