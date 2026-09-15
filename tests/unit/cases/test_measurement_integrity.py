"""Measurement-integrity guards for evaluation UI reports.

Fails if EXTRACTION_HARNESS metrics are presented as operational KPIs
(Total Ingested / production STP) or if photometric V3_300 observations are
treated as independent claims without provenance.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "apps" / "evaluation_ui" / "public" / "reports" / "evaluation.json"
APP = ROOT / "apps" / "evaluation_ui" / "src" / "App.tsx"
FORBIDDEN_OPERATIONAL_LABELS = {
    "Total Ingested",
    "STP Rate",
    "production STP",
}


def test_evaluation_report_declares_extraction_harness_scope() -> None:
    report = json.loads(REPORT.read_text())
    integrity = report["measurement_integrity"]
    assert integrity["measurement_scope"] == "EXTRACTION_HARNESS"
    assert report["report_metadata"]["measurement_scope"] == "EXTRACTION_HARNESS"
    assert report["evaluation_metrics"]["measurement_scope"] == "EXTRACTION_HARNESS"
    assert report["evaluation_metrics"]["identity_supplied_by_harness"] is True


def test_independent_sample_size_is_not_photometric_observation_count() -> None:
    report = json.loads(REPORT.read_text())
    integrity = report["measurement_integrity"]
    independent = integrity["independent_source_documents"]
    photometric = integrity["photometric_observations"]
    assert independent == 100
    assert photometric == 300
    assert independent < photometric
    note = integrity["photometric_stress"]["independence_note"].lower()
    assert "100" in note and ("not" in note or "share" in note or "clone" in note)


def test_stp_metric_is_named_as_proxy_not_production_stp() -> None:
    report = json.loads(REPORT.read_text())
    evaluation = report["evaluation_metrics"]
    assert evaluation["metric_name_stp"] == "golden_pack_claim_stp_proxy"
    labels = report["measurement_integrity"]["required_display_labels"]
    assert "proxy" in labels["stp"].lower()
    forbidden = set(report["measurement_integrity"]["forbidden_operational_labels"])
    assert FORBIDDEN_OPERATIONAL_LABELS.issubset(forbidden)


def test_operational_completion_is_scoped_separately_from_harness() -> None:
    report = json.loads(REPORT.read_text())
    ops = report["operational_metrics"]
    baseline = report["measurement_integrity"]["operational_baseline"]
    assert ops["measurement_scope"] == "OPERATIONAL_E2E"
    assert ops["total_documents"] is None
    assert ops["document_stp_rate"] is None
    assert baseline["operational_completion_rate"] == 0.39
    assert baseline["final_claim_count"] == 39
    assert baseline["incomplete_count"] == 61
    assert (
        report["evaluation_metrics"]["golden_pack_claim_stp_proxy"]
        != baseline["operational_completion_rate"]
    )


def test_ui_source_does_not_bind_harness_docs_as_total_ingested() -> None:
    app = APP.read_text()
    # MetricCard labels must not present harness counts as Total Ingested / STP Rate.
    assert not re.search(r'label=\{?"Total Ingested"\}?', app)
    assert not re.search(r'label=\{?"STP Rate"\}?', app)
    assert "Golden Pack Claim STP Proxy" in app
    assert "Operational Completion" in app
    assert "Independent Source Docs" in app
    assert "useGovernedKpis" not in app
    assert "const operationalIngested = rawDocsForMetrics.length" in app
