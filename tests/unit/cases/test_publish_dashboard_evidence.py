import json
from pathlib import Path

from PIL import Image

from evaluation.publish_dashboard_evidence import publish


def test_publish_dashboard_adds_evidence_and_optimization(tmp_path: Path) -> None:
    image = tmp_path / "crop.png"
    Image.new("RGB", (20, 10), "white").save(image)
    report_path = tmp_path / "public" / "reports" / "evaluation.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({
        "llm_diverted_fields": 2, "llm_diversion_rate": 0.2,
        "report_metadata": {},
    }), encoding="utf-8")
    details_path = tmp_path / "details.json"
    details_path.write_text(json.dumps([{
        "field_identity": {"document_id": "D1", "document_family": "CMS1500", "semantic_field": "dob"},
        "expected_value": "01012000", "selected_value": "01/01/2000",
        "normalized_value": "01012000", "provider": "paddle", "confidence": 0.9,
        "selected_correct": True, "provenance": {"crop_path": str(image), "original_page": str(image)},
    }]), encoding="utf-8")
    optimization_path = tmp_path / "optimization.json"
    optimization_path.write_text(json.dumps({
        "total_fields": 10, "baseline_correct": 8, "azure_correct_recoveries": 1,
        "paddle_correct_recoveries": 1, "deterministic_derived_recoveries": 1,
    }), encoding="utf-8")

    result = publish(
        report_path,
        details_path,
        optimization_path,
        tmp_path / "no-local-first.json",
        tmp_path / "runtime" / "evaluation.json",
    )
    published = json.loads(report_path.read_text(encoding="utf-8"))

    assert result["published_fields"] == 1
    assert published["field_evidence"][0]["crop_url"].startswith("/reports/evidence/")
    assert published["optimization_metrics"]["llm_incremental_recovery_rate"] == 0.1
    assert published["report_metadata"]["production_generalization_claim"] is False
    assert published["document_family_report"]["rows"][0]["document_family"] == "CMS-1500 professional claim"
    assert published["document_family_report"]["total"]["evaluated_fields"] == 1
