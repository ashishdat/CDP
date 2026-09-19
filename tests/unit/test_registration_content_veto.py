"""Identity-ROI veto requires a second reader; disabled DI is not the failure."""

from __future__ import annotations

from PIL import Image

from app import _terminal_failure_reason
from packages.recovery.registration_content import (
    configure_registration_region_ocr,
    identity_roi_reads_insurance_row,
    validate_cms1500_registration_content,
)

_BOX = (0, 0, 8, 8)


def _page() -> Image.Image:
    return Image.new("RGB", (16, 16), "white")


def test_patient_label_is_not_an_insurance_row():
    assert not identity_roi_reads_insurance_row(
        "2. PATIENT'S NAME THOMAS, DARLENE",
        "07 16 1946",
    )


def test_two_insurance_tokens_without_a_name_label_reject():
    assert identity_roi_reads_insurance_row("MEDICARE MEDICAID", "")


def test_single_noisy_pass_cannot_veto_when_confirm_reads_the_name():
    configure_registration_region_ocr(
        lambda _image, _box: "MEDICARE MEDICAID",
        confirm_factory=lambda _image, _box: "2. PATIENT'S NAME THOMAS, DARLENE",
    )
    result = validate_cms1500_registration_content(
        _page(),
        patient_name_box=_BOX,
        patient_dob_box=_BOX,
    )
    assert result.accepted is True
    assert result.reason == "CONTENT_VETO_UNCORROBORATED"


def test_agreeing_readers_still_reject_the_insurance_row():
    configure_registration_region_ocr(
        lambda _image, _box: "MEDICARE MEDICAID",
        confirm_factory=lambda _image, _box: "TRICARE FECA",
    )
    result = validate_cms1500_registration_content(
        _page(),
        patient_name_box=_BOX,
        patient_dob_box=_BOX,
    )
    assert result.accepted is False
    assert result.reason == "IDENTITY_ROI_READS_INSURANCE_TYPE_ROW"


def test_disabled_azure_di_does_not_mask_the_learned_matcher_reason():
    reason = _terminal_failure_reason(
        [
            {"attempt": "learned_matcher", "reason": "insufficient_good_matches"},
            {
                "attempt": "azure_di_page_corners",
                "reason": "AZURE_DI_PAGE_CORNERS_DISABLED_LOW_COST",
            },
        ]
    )
    assert reason == "insufficient_good_matches"


def test_extraction_v3_pins_the_aligned_cms1500_template(monkeypatch):
    """v02-12 name box sits on the insurance-type row of the aligned page."""
    from workers.page_detection.template_selector import TemplateSelector

    monkeypatch.setenv("CDP_PIPELINE_RELEASE", "extraction-v3")
    monkeypatch.delenv("CDP_RELEASE_MANIFEST", raising=False)
    pinned = TemplateSelector._preferred_template_versions()
    assert pinned["cms1500"] == "03"
