from packages.authoritative_references import (
    AddressVerificationResult,
    UnconfiguredAddressReferenceProvider,
    address_can_auto_accept,
)
from workers.cascade.reconciliation import (
    FieldDisposition,
    claim_can_finalize,
)


def test_missing_address_provider_awaits_authorized_dataset():
    result = UnconfiguredAddressReferenceProvider().verify_address(
        po_box="30757", postal_code="84130-0757", city="SALT LAKE CITY", state="UT"
    )
    assert not result.verified
    assert "AWAITING_AUTHORIZED_DATASET" in result.reason_codes
    assert not address_can_auto_accept(result)


def test_only_fully_authorized_consistent_address_can_auto_accept():
    result = AddressVerificationResult(
        verified=True,
        normalized_address="PO BOX 30757, SALT LAKE CITY, UT 84130-0757",
        provider_name="authorized-test",
        provider_version="1",
        matched_attributes=("po_box", "postal_code", "city", "state"),
        contradictions=(),
        confidence=0.99,
        reference_record_id="hashed-id",
        reason_codes=("REFERENCE_VERIFIED",),
        authorized=True,
        automatic_acceptance_permitted=True,
    )
    assert address_can_auto_accept(result)
    assert not address_can_auto_accept(
        AddressVerificationResult(**{**result.__dict__, "contradictions": ("CITY_MISMATCH",)})
    )


def test_unverified_derived_critical_field_blocks_finalization():
    assert not claim_can_finalize(
        {"address": FieldDisposition.HUMAN_REVIEW_REQUIRED}, {"address"}
    )


def test_human_approval_can_resolve_derived_field():
    assert claim_can_finalize(
        {"address": FieldDisposition.VERIFIED_BY_HUMAN}, {"address"}
    )
