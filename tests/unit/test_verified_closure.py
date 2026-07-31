import json
from pathlib import Path

import pytest

from packages.authorized_reference_pilot import (
    AuthorizedJsonMemberProvider,
    AuthorizedJsonProviderDirectory,
)
from packages.verified_closure import VerifiedClosureWorkflow


def test_verified_closure_requires_second_actor_and_exports_training(tmp_path: Path):
    crop = tmp_path / "crop.png"
    crop.write_bytes(b"crop")
    task = {
        "task_id": "t", "document_id": "d", "field_name": "patient_first",
        "document_family": "CMS1500", "status": "OPEN", "primary_crop": str(crop),
        "ocr_candidates": ["unclear"],
    }
    flow = VerifiedClosureWorkflow(tmp_path / "audit.jsonl", tmp_path / "labels.jsonl")
    submitted = flow.submit(task, corrected_value="Jane", reviewer="alice", reason="scan")
    with pytest.raises(ValueError, match="role separation"):
        flow.approve(submitted, approver="alice", validator="alice")
    approved = flow.approve(submitted, approver="bob", validator="bob")
    assert approved["status"] == "VERIFIED_BY_HUMAN"
    assert (tmp_path / "labels.jsonl").is_file()


def test_reference_pilot_requires_id_dob_name_and_no_contradiction(tmp_path: Path):
    path = tmp_path / "authorized.json"
    path.write_text(json.dumps([{
        "member_id": "M1", "name": "Jane Doe", "dob": "2000-01-01",
        "address": "1 Main St", "source_system": "eligibility", "record_version": "v1",
    }]))
    provider = AuthorizedJsonMemberProvider(path, provider_name="pilot", dataset_version="v1")
    assert provider.decide(
        member_id="M1", dob="2000-01-01", name_similarity=.95,
        address_contradiction=False,
    ).decision == "REFERENCE_VERIFIED"
    assert provider.decide(
        member_id="M1", dob="2000-01-01", name_similarity=.99,
        address_contradiction=True,
    ).decision == "HUMAN_REVIEW_REQUIRED"


def test_provider_reference_requires_exact_npi_name_and_no_contradiction(tmp_path: Path):
    path = tmp_path / "providers.json"
    path.write_text(json.dumps([{
        "npi": "1234567893", "name": "Jane Clinic", "address": "1 Main St",
        "source_system": "provider_master", "record_version": "v1",
    }]))
    provider = AuthorizedJsonProviderDirectory(
        path, provider_name="provider-master", dataset_version="v1"
    )
    assert provider.decide(
        npi="1234567893", name_similarity=.95, address_contradiction=False
    ).decision == "REFERENCE_VERIFIED"
    assert provider.decide(
        npi="1234567893", name_similarity=.99, address_contradiction=True
    ).decision == "HUMAN_REVIEW_REQUIRED"
