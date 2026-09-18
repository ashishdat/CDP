import json

import pytest

from evaluation.frontier_policy_audit import audit_frontier
from evaluation.production_readiness import FRONTIER


@pytest.mark.skipif(
    not (FRONTIER / "manifest.json").is_file(),
    reason="private evidence_frontier_v2 artifacts not installed",
)
def test_frozen_80_percent_stp_is_policy_correct_but_not_production_authority(tmp_path):
    report = audit_frontier(output=tmp_path / "audit.json")

    assert report["stp_claims_audited"] == 96
    assert report["evaluation_stp_rate"] == .80
    assert report["all_assertions_pass"] is True
    assert report["production_stp_eligible_claims"] == 0
    assert report["violation_counts"] == {}
    assert all(row["evaluation_stp_qualified"] for row in report["claims"])
    assert all(not row["production_stp_eligible"] for row in report["claims"])
    assert json.loads((tmp_path / "audit.json").read_text("utf-8")) == report
