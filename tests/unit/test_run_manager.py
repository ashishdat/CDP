import json

import pytest

from scripts.run_manager import METRICS, RunManager


def test_blocked_run_never_reports_measurements(tmp_path):
    manager = RunManager({"dataset_id": "DEVELOPMENT_DATASET_V1"},
                         versions={}, output_root=tmp_path)
    directory = manager.finish_blocked(
        reasons=["Missing <runtime>"], dataset_verification={"verified": True}, evidence={},
    )
    run = json.loads((directory / "run.json").read_text())
    summary = json.loads((directory / "summary.json").read_text())
    assert run["status"] == "blocked"
    assert run["end"] >= run["start"]
    assert run["processed_documents"] == 0
    assert set(run["metrics"]) == set(METRICS)
    assert all(metric["value"] is None for metric in run["metrics"].values())
    assert summary["top_20_incorrect_fields"]["status"] == "unavailable"
    assert "Missing &lt;runtime&gt;" in (directory / "dashboard.html").read_text()
    with pytest.raises(ValueError, match="already finalized"):
        manager.finish_blocked(reasons=[], dataset_verification={}, evidence={})
