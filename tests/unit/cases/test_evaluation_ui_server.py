"""Unit tests for Evaluation UI server."""

import pytest
from fastapi.testclient import TestClient

from apps.evaluation_ui.main import DIST_DIR, app


def test_evaluation_ui_health_and_index():
    client = TestClient(app)

    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    if not (DIST_DIR / "index.html").is_file():
        pytest.skip("UI bundle not built; run `npm run build` in apps/evaluation_ui")
    res = client.get("/")
    assert res.status_code == 200
    assert "IDP" in res.text or "Claims" in res.text
