import copy
import json
from hashlib import sha256

import pytest

from scripts.auto_adjudicate import (
    CHANNELS, AutoAdjudicationEngine, observation, field_evidence, load_extraction,
)


def evidence(state="SUPPORT"):
    return {k: observation(state, "Synthetic deterministic test evidence") for k in CHANNELS}


def field():
    raw = {"raw_value": "001", "value": "001", "engine": "test", "raw_confidence": 0.9}
    winner = {"candidate_id": "f:0", "field_id": "f", "winner": "f:0", "is_winner": True, "ocr_candidate": raw}
    validation = {"candidate_id": "f:0", "field_id": "f", "normalized_value": "001", "status": "VALID"}
    return {"field_name": "f", "normalized_value": "001", "ranked_candidate": winner,
            "validation": validation, "candidate_validations": [validation], "status": "VALID",
            "ocr": {"candidates": [raw]}, "alternatives": []}


def test_all_eight_support_auto_verified():
    result = AutoAdjudicationEngine().adjudicate("f", "001", evidence())
    assert result["status"] == "AUTO_VERIFIED"
    assert result["confidence"] == 100
    assert not result["review_required"]


@pytest.mark.parametrize("channel", CHANNELS)
def test_any_missing_source_prevents_auto_verification(channel):
    e = evidence()
    e[channel] = observation()
    result = AutoAdjudicationEngine().adjudicate("f", "001", e)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["confidence"] == 87.5


def test_disagreement_requires_review_and_sets_conflict_flag():
    e = evidence()
    e["validator"] = observation("CONTRADICT", "Invalid")
    r = AutoAdjudicationEngine().adjudicate("f", "001", e)
    assert (r["status"], r["evidence_state"], r["confidence"]) == ("REVIEW_REQUIRED", "CONFLICT", 0)


def test_no_value_is_unknown_even_with_support():
    assert AutoAdjudicationEngine().adjudicate("f", None, evidence())["status"] == "UNKNOWN"


def test_lineage_conflict_cannot_auto_verify():
    r = AutoAdjudicationEngine().adjudicate("f", "001", evidence(), integrity_errors=["Wrong candidate"])
    assert r["status"] == "CONFLICT" and r["review_required"]


def test_adapter_preserves_inputs_and_does_not_invent_missing_evidence():
    f = field()
    before = copy.deepcopy(f)
    e, errors = field_evidence(f)
    assert f == before and not errors
    for channel in ("historical_pattern", "geometry_confidence", "registration_confidence", "business_rules", "cross_field_validation"):
        assert e[channel]["state"] == "UNKNOWN"


def test_valid_alternative_conflicts_without_raw_normalization_comparison():
    f = field()
    r = copy.deepcopy(f["ranked_candidate"])
    r.update(candidate_id="f:1", is_winner=False)
    f["alternatives"] = [r]
    f["candidate_validations"].append({"candidate_id": "f:1", "field_id": "f", "status": "VALID", "normalized_value": "002"})
    e, _ = field_evidence(f)
    assert e["ranking"]["state"] == "CONTRADICT"


def test_existing_policy_veto_and_cross_field_contradiction():
    decision = {"deterministic_checks": {"f": {"status": "PASS", "cross_field_evidence": []}},
                "field_decisions": [{"field_name": "f", "disposition": "HUMAN_REVIEW_REQUIRED"}],
                "claim_facts": {"contradictions": [{"metadata": {"supported_fields": ["f"]}}]}}
    e, _ = field_evidence(field(), decision)
    assert e["business_rules"]["state"] == "UNKNOWN"
    assert e["cross_field_validation"]["state"] == "CONTRADICT"


def test_tampered_source_is_rejected(tmp_path):
    source = tmp_path / "source.json"
    source.write_text("changed")
    p = tmp_path / "extraction.json"
    p.write_text(json.dumps({"type": "ExtractionResult", "status": "ASSEMBLED", "field_results": [field()],
                            "source_artifacts": {"ocr": {"path": str(source), "sha256": sha256(b"original").hexdigest()}}}))
    with pytest.raises(ValueError, match="hash mismatch"):
        load_extraction(p)


def test_invalid_evidence_channel_is_rejected():
    with pytest.raises(ValueError):
        AutoAdjudicationEngine().adjudicate("f", "1", {})
