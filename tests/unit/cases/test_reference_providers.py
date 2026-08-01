from packages.reference_providers import MemberReference, member_reference_passes


def test_member_reference_requires_multiple_exact_attributes():
    record = MemberReference("M1", "Jane Doe", "2000-01-01", None, "eligibility", "1")
    assert member_reference_passes(
        record, member_id="M1", dob="2000-01-01", name_similarity=.95
    )
    assert not member_reference_passes(
        record, member_id="M1", dob="2000-01-02", name_similarity=.99
    )
    assert not member_reference_passes(
        record, member_id="M1", dob="2000-01-01", name_similarity=.99,
        contradictory_evidence=True,
    )
