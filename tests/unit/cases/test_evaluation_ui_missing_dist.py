"""Unit tests for Evaluation UI missing dist/ handling."""

from pathlib import Path

from fastapi.testclient import TestClient

import apps.evaluation_ui.main as evaluation_ui_main
from apps.evaluation_ui.main import app


def test_evaluation_ui_missing_dist_returns_503_json(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(evaluation_ui_main, "DIST_DIR", tmp_path / "missing-dist")
    client = TestClient(app)

    res = client.get("/", headers={"Accept": "application/json"})
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "ui_build_unavailable"
    assert "npm run build" in body["detail"]
    assert "apps/evaluation_ui" in body["detail"]


def test_evaluation_ui_missing_dist_returns_503_html(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(evaluation_ui_main, "DIST_DIR", tmp_path / "missing-dist")
    client = TestClient(app)

    res = client.get("/", headers={"Accept": "text/html"})
    assert res.status_code == 503
    assert "text/html" in res.headers.get("content-type", "")
    assert "npm run build" in res.text
    assert "apps/evaluation_ui" in res.text


def test_evaluation_ui_health_ok_when_dist_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(evaluation_ui_main, "DIST_DIR", tmp_path / "missing-dist")
    client = TestClient(app)

    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
