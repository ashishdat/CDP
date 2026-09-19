"""Tests for QR decode helpers, authorized member join, and selective risk."""

from __future__ import annotations

import json
from pathlib import Path

from packages.calibration.selective_risk import RiskCoverageLedger
from packages.package_intelligence.qr_decode import qr_supports_cms1500_family
from packages.reference_enrichment.authorized_member_join import (
    join_member_by_id,
    load_authorized_member_index,
)


def test_qr_supports_nucc_cms_marker():
    assert qr_supports_cms1500_family(("http://www.nucc.org/",))
    assert not qr_supports_cms1500_family(("SEP-001",))


def test_authorized_member_join_exact_id_only(tmp_path: Path, monkeypatch):
    index = tmp_path / "members.json"
    index.write_text(
        json.dumps(
            {
                "97739518": {
                    "patient_name": "CMUNAULANI AIALL",
                    "patient_dob": "1980-01-01",
                    "source": "INTAKE",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CDP_AUTHORIZED_MEMBER_INDEX", str(index))
    hit = join_member_by_id("97739518")
    assert hit is not None
    assert hit.patient_name == "CMUNAULANI AIALL"
    assert join_member_by_id("00000000") is None
    assert load_authorized_member_index()


def test_member_join_abstains_without_authorized_index(monkeypatch):
    monkeypatch.delenv("CDP_AUTHORIZED_MEMBER_INDEX", raising=False)
    assert join_member_by_id("97739518") is None


def test_selective_risk_requires_600_error_free_before_fit():
    ledger = RiskCoverageLedger()
    for i in range(100):
        ledger.record("BOX28_MATCHES_LINE_SUM", accepted=True, correct=True)
    ready = ledger.readiness()
    assert ready["adjudicated_accepts"] == 100
    assert ready["ready_to_fit_thresholds"] is False
    # 100 error-free accepts still have Wilson upper > 0.5% — gate not met yet.
    assert ledger.patterns["BOX28_MATCHES_LINE_SUM"].wilson_upper() > 0.005
    assert ledger.coverage_curve() == []
    for i in range(500):
        ledger.record("BOX28_MATCHES_LINE_SUM", accepted=True, correct=True)
    assert ledger.patterns["BOX28_MATCHES_LINE_SUM"].meets_precision_gate()
    curve = ledger.coverage_curve()
    assert curve and curve[0]["pattern"] == "BOX28_MATCHES_LINE_SUM"
