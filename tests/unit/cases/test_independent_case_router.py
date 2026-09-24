"""Unit tests for Independent case router."""

from __future__ import annotations

from packages.document_finance.families import DocumentFamily
from packages.extraction_recovery.independent_case_router import (
    CasePath,
    classify_independent_case,
    promote_unstructured_fields,
)


def test_mailroom_separator_routes_to_reg():
    text = """
*00BREAK00*
Document Separator
Used to Separate Each Transaction
SourceHOV, Inc
"""
    route = classify_independent_case(text)
    assert route.path is CasePath.MAILROOM_REG
    assert route.disposition_policy.value == "KEEP_REG"


def test_fax_boilerplate_routes_to_reg():
    text = """
FAX IMAGE - ORIGINAL SOURCE MAY BE BAD, THEREFORE BETTER IMAGE QUALITY CANNOT BE OBTAINED
08/18/2026
"""
    route = classify_independent_case(text)
    assert route.path is CasePath.MAILROOM_REG


def test_ub04_routes_to_unstructured_di():
    text = """
UB-04 CMS-1450
TYPE OF BILL 0212
8 PATIENT NAME
10 BIRTHDATE
47 TOTAL CHARGES
"""
    route = classify_independent_case(text)
    assert route.path is CasePath.UNSTRUCTURED_DI
    assert route.family is DocumentFamily.UB04
    assert route.hitl_track == "UNSTRUCTURED_DI"


def test_cms1500_routes_to_geometry():
    text = """
HEALTH INSURANCE CLAIM FORM
NATIONAL UNIFORM CLAIM COMMITTEE NUCC
CMS-1500
28. TOTAL CHARGE
"""
    route = classify_independent_case(text)
    assert route.path is CasePath.CMS_GEOMETRY
    assert route.family is DocumentFamily.CMS1500


def test_field_ink_hitl_routes_to_residual():
    route = classify_independent_case(
        "HEALTH INSURANCE CLAIM FORM NUCC CMS-1500",
        registration_ok=True,
        field_ink_hitl=True,
    )
    assert route.path is CasePath.FIELD_INK_RESIDUAL
    assert route.hitl_track == "FIELD_INK"


def test_promote_unstructured_fields():
    assert promote_unstructured_fields({})[0] == "REGISTRATION_FAILED"
    assert (
        promote_unstructured_fields(
            {
                "patient_name": "A",
                "patient_dob": "01/01/1970",
                "insured_id_number": "123456789",
                "total_charge": "10.00",
            }
        )[0]
        == "TRUE_STP"
    )
    disp, blockers = promote_unstructured_fields(
        {"patient_name": "A", "patient_dob": "01/01/1970"}
    )
    assert disp == "HITL"
    assert "total_charge" in blockers
