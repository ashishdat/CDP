import pytest
from dataclasses import replace
from packages.candidate_reconciliation import Decision, EvidenceReconciler
from packages.criticality import CriticalityLevel
from tests.unit.cases.test_evidence_reconciliation import _candidate
from packages.extraction_recovery.gpt4o_crop_residual import Gpt4oCropResidualResult, residual_candidate_dict


def test_id_caption_consensus_cannot_borrow_valid_id_validation():
    caption = "1a, INSURED'S I.D. NUMBER (For Program in ltem 1)"
    result = EvidenceReconciler().reconcile("insured_id_number", [
        _candidate(caption, "paddleocr"), _candidate(caption, "rapidocr"),
        _candidate("7EEA96E4191", "anthropic_claude_crop", .42)],
        CriticalityLevel.C3, deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"})
    assert result.selected_value != caption
    assert result.decision != Decision.ACCEPT
    assert len(result.candidate_ids) == 3


def test_member_dependent_suffix_delimiter_is_preserved():
    result = EvidenceReconciler().reconcile("insured_id_number", [
        _candidate("OSC75126744-01", "paddleocr"),
        _candidate("OSC75126744-01", "rapidocr")], CriticalityLevel.C3,
        deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"})
    assert result.selected_value == "OSC75126744-01"


@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), -1, 1.1, True])
def test_missing_or_invalid_cloud_confidence_never_gets_default_probability(confidence):
    result = Gpt4oCropResidualResult(attempted=True, configured=True, review_only=True,
        value="600.00", raw_value="600.00", shaped=True, insufficient_evidence=False,
        reason="OBSERVED", confidence=confidence)
    candidate = residual_candidate_dict(result, bbox=(1,1,90,40), image_size=(100,50))
    assert candidate["raw_confidence"] == 0
    assert candidate["calibrated_confidence"] is None
    assert candidate["confidence_source"] == "NOT_REPORTED"


def test_self_reported_cloud_confidence_is_not_calibration():
    result = Gpt4oCropResidualResult(attempted=True, configured=True, review_only=True,
        value="600.00", raw_value="600.00", shaped=True, insufficient_evidence=False,
        reason="OBSERVED", confidence=.97)
    candidate = residual_candidate_dict(result, bbox=(1,1,90,40), image_size=(100,50))
    assert candidate["raw_confidence"] == .97
    assert candidate["calibrated_confidence"] is None


@pytest.mark.parametrize("different_version_pixels, expected", [(False, 4), (True, 6)])
def test_probe_cache_is_pixel_specific_page_scoped_and_never_accepts_failure(monkeypatch, different_version_pixels, expected):
    from PIL import Image
    from packages.templates.registry import TemplateRegistry
    from workers.page_detection import template_selector as module
    from workers.page_detection.template_alignment import _failure
    registry = TemplateRegistry.load_from_directory()
    original = registry.load_reference_image
    def load(template):
        image = original(template)
        if different_version_pixels and template.template_id == "cms1500" and template.version == "03":
            image.putpixel((0,0), 0 if image.getpixel((0,0)) else 255)
        return image
    monkeypatch.setattr(registry, "load_reference_image", load)
    monkeypatch.setattr(module, "compute_grid_signature", lambda image: None)
    monkeypatch.setattr(module, "signature_similarity", lambda *args: 0.0)
    calls = []
    def align(image, reference, **kwargs):
        calls.append((image, kwargs))
        return _failure("sift", "CONTROL_REJECTED")
    monkeypatch.setattr(module, "align_to_reference", align)
    result = module.TemplateSelector(registry).select([
        Image.new("L", (64,64), 255), Image.new("L", (64,64), 254)], text_lines={})
    assert len(calls) == expected
    assert result.template_id is None
    assert all(not c["diagnostics"].get("registration_gates_passed") for c in result.candidate_templates)



def test_hinted_arbitrator_cannot_supply_independent_id_confirmation():
    native = _candidate("OSC75126744-01", "paddleocr", .9)
    hinted = replace(_candidate("OSC75126744-01", "anthropic_claude_crop", .99),
                     prior_hints_supplied=True)
    result = EvidenceReconciler().reconcile("insured_id_number", [native, hinted],
        CriticalityLevel.C3, deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"})
    assert "MULTI_ENGINE_AGREEMENT" not in result.rationale_codes
    assert len(result.candidate_ids) == 2


def test_hinted_cloud_amount_cannot_mint_e2_or_strong_charge_evidence():
    from packages.evidence.builder import build_evidence_bundle
    from packages.evidence.models import EvidenceClass
    candidates = [_candidate("600.00", "azure_document_intelligence_read", .9),
        replace(_candidate("600.00", "anthropic_claude_crop", .99), prior_hints_supplied=True)]
    bundle = build_evidence_bundle(field_name="total_charge", candidates=candidates,
        registration_confidence=.99, wrong_crop_suspected=False,
        deterministic_evidence={"FORMAT_VALID"}, hard_validation_passed=True)
    assert not any(i.evidence_class == EvidenceClass.E2 and i.independent for i in bundle.items)
    assert len(bundle.candidate_ids) == 2


def test_hint_lineage_survives_typed_candidate_roundtrip():
    from dataclasses import asdict
    from pydantic import TypeAdapter
    from packages.ocr.contracts import OCRCandidate
    candidate = replace(_candidate("600.00", "anthropic_claude_crop", .99), prior_hints_supplied=True)
    loaded = TypeAdapter(OCRCandidate).validate_python(asdict(candidate))
    assert loaded.prior_hints_supplied is True



def test_review_only_ocr_cannot_supply_confirmation():
    native = _candidate("OSC75126744-01", "paddleocr", .9)
    shadow = replace(_candidate("OSC75126744-01", "trocr", .99), shadow_review_only=True)
    result = EvidenceReconciler().reconcile("insured_id_number", [native, shadow],
        CriticalityLevel.C3, deterministic_evidence={"HARD_VALIDATION_PASSED", "FORMAT_VALID"})
    assert "MULTI_ENGINE_AGREEMENT" not in result.rationale_codes
    assert len(result.candidate_ids) == 2


def test_cloud_candidate_records_actual_retry_bbox_and_hint_lineage():
    result = Gpt4oCropResidualResult(attempted=True, configured=True, review_only=True,
        value="600.00", raw_value="600.00", shaped=True, insufficient_evidence=False,
        reason="OBSERVED", confidence=.97, prior_hints_supplied=True,
        observation_bbox=(1,2,99,48))
    candidate = residual_candidate_dict(result, bbox=(10,10,90,40), image_size=(100,50))
    assert candidate["bbox"] == [1,2,99,48]
    assert candidate["bounding_box"]["x0"] == 1
    assert candidate["prior_hints_supplied"] is True
    assert candidate["shadow_review_only"] is True



def test_runtime_architecture_follows_release_without_stale_environment_cache(monkeypatch):
    from packages.architecture import load_redesign_stack
    monkeypatch.delenv("CDP_RELEASE_MANIFEST", raising=False)
    monkeypatch.setenv("CDP_PIPELINE_RELEASE", "extraction-v2")
    assert load_redesign_stack().version == "redesign-stack-v1"
    monkeypatch.setenv("CDP_PIPELINE_RELEASE", "extraction-v3")
    assert load_redesign_stack().version == "redesign-stack-v3"
    monkeypatch.setenv("CDP_PIPELINE_RELEASE", "extraction-v2")
    assert load_redesign_stack().version == "redesign-stack-v1"
