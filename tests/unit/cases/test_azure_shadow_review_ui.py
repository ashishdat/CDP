import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from evaluation.annotation_app import azure_shadow_review as azure
from evaluation.annotation_app import real_data_review as real


def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def setup(tmp_path, monkeypatch):
    root = tmp_path / "source"
    image = root / "pkg" / "a.tif"
    image.parent.mkdir(parents=True)
    Image.new("L", (20, 20), 255).save(image)
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    closure = tmp_path / "closure"
    source = tmp_path / "source.json"
    dump(source, {"records": [{"sha256": sha, "relative_path": "pkg/a.tif"}]})
    dump(
        closure / "source_inventory.json",
        {"assets": [{"asset_id": "asset", "package_id": "package", "sha256": sha}]},
    )
    dump(
        closure / "document_boundaries.json",
        {
            "candidates": [
                {
                    "asset_ids": ["asset"],
                    "candidate_document_id": "doc",
                    "boundary_state": "CANDIDATE",
                }
            ]
        },
    )
    dump(
        closure / "page_classification.json",
        {
            "pages": [
                {
                    "asset_id": "asset",
                    "package_id": "package",
                    "page_id": "page",
                    "page_number": 1,
                    "classification": "UNKNOWN",
                }
            ]
        },
    )
    queue = tmp_path / "queue.json"
    dump(
        queue,
        {
            "records": [
                {
                    "package_id": "package",
                    "source_asset_id": "asset",
                    "source_page_id": "page",
                    "candidate_class": "UB04",
                    "classification_confidence": 0.8,
                    "candidate_record_sha256": "a" * 64,
                    "source_quality_band": "UNKNOWN",
                }
            ]
        },
    )
    monkeypatch.setattr(real, "SOURCE_ROOT", root)
    monkeypatch.setattr(real, "SOURCE_RECORDS", source)
    monkeypatch.setattr(real, "CLOSURE", closure)
    monkeypatch.setattr(real, "REAL_EVAL", tmp_path / "none")
    monkeypatch.setattr(azure, "QUEUE", queue)
    monkeypatch.setattr(azure, "PAGE_EVENTS", tmp_path / "pages.jsonl")
    monkeypatch.setattr(azure, "ANNOTATIONS", tmp_path / "annotations.jsonl")
    monkeypatch.setattr(azure, "ADJUDICATIONS", tmp_path / "adjudications.jsonl")
    app = FastAPI()
    app.include_router(azure.router)
    return TestClient(app)


def test_page_review_persists_and_queue_resumes(tmp_path, monkeypatch):
    c = setup(tmp_path, monkeypatch)
    h = {"X-Reviewer-ID": "reviewer"}
    screen = c.get("/real-review/fast-track/0", headers=h)
    assert "0 reviewed" in screen.text and "CDP and Azure predictions are hidden" in screen.text
    response = c.post(
        "/real-review/fast-track/0/page-review",
        headers=h,
        data={
            "action": "CONFIRM",
            "reviewed_class": "UB04",
            "reviewed_quality_band": "MEDIUM",
            "boundary_action": "CONFIRM_DOCUMENT_START",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    event = json.loads(azure.PAGE_EVENTS.read_text())
    assert event["reviewed_class"] == "UB04" and event["reviewed_quality_band"] == "MEDIUM"
    assert "1 reviewed" in c.get("/real-review/fast-track/", headers=h).text


def test_blind_dual_annotation_requires_independent_reviewers(tmp_path, monkeypatch):
    c = setup(tmp_path, monkeypatch)
    data = {
        "field_name": "NPI",
        "state": "VALUE",
        "value": "1234567893",
        "source_region_sha256": "b" * 64,
    }
    assert (
        c.post(
            "/real-review/fast-track/0/annotation",
            headers={"X-Reviewer-ID": "a"},
            data=data | {"annotator_role": "ANNOTATOR_A"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        c.post(
            "/real-review/fast-track/0/annotation",
            headers={"X-Reviewer-ID": "a"},
            data=data | {"annotator_role": "ANNOTATOR_B"},
        ).status_code
        == 409
    )
    assert (
        c.post(
            "/real-review/fast-track/0/annotation",
            headers={"X-Reviewer-ID": "b"},
            data=data | {"annotator_role": "ANNOTATOR_B"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    raw = azure.ANNOTATIONS.read_text()
    assert 'prediction_visible": false' in raw


def test_disagreement_requires_independent_adjudicator(tmp_path, monkeypatch):
    c = setup(tmp_path, monkeypatch)
    base = {"field_name": "NPI", "state": "VALUE", "source_region_sha256": "b" * 64}
    for who, role, value in [("a", "ANNOTATOR_A", "123"), ("b", "ANNOTATOR_B", "456")]:
        c.post(
            "/real-review/fast-track/0/annotation",
            headers={"X-Reviewer-ID": who},
            data=base | {"annotator_role": role, "value": value},
        )
    assert (
        c.get(
            "/real-review/fast-track/0/adjudication/NPI", headers={"X-Reviewer-ID": "a"}
        ).status_code
        == 403
    )
    assert (
        c.get(
            "/real-review/fast-track/0/adjudication/NPI", headers={"X-Reviewer-ID": "judge"}
        ).status_code
        == 200
    )
    result = c.post(
        "/real-review/fast-track/0/adjudication/NPI",
        headers={"X-Reviewer-ID": "judge"},
        data={"state": "VALUE", "value": "456"},
        follow_redirects=False,
    )
    assert result.status_code == 303
    assert json.loads(azure.ADJUDICATIONS.read_text())["authority"] == "HUMAN_ADJUDICATED"
