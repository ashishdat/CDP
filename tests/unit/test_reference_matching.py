from packages.reference_matching import ReferenceMatcher, ReferenceRecord


class Provider:
    def candidates(self, member_id, provider_npi):
        return [
            ReferenceRecord(
                "member-1", member_id="A123", patient_name="CHRISTOPH SIMPSON",
                patient_dob="1979-06-21", address="10 MAIN ST",
            )
        ]


def test_reference_match_requires_exact_identifier_or_demographic_evidence():
    match = ReferenceMatcher(Provider(), minimum_score=.90).verify({
        "member_id": "A123",
        "patient_name": "CHRISTOPHER SIMPSON",
        "patient_dob": "1979-06-21",
        "address": "10 MAIN STREET",
    })
    assert match is not None
    assert "member_id" in match.exact_fields
    assert match.verified
