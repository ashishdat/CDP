import xml.etree.ElementTree as ET

from evaluation.autonomous_run0 import attribute_failures, experiment_plan


def test_failure_attribution_does_not_blanket_whitelist_baseline_count(tmp_path):
    suite = ET.Element("testsuite")
    cases = [
        ("test_missing", "FileNotFoundError: evaluation_data/truth.json"),
        ("test_ui", "File at path apps/evaluation_ui/dist/index.html does not exist"),
        ("test_hash", "frozen configuration changed: config/router_frozen_v1.yaml"),
    ]
    for name, message in cases:
        case = ET.SubElement(suite, "testcase", classname="tests.example", name=name)
        failure = ET.SubElement(case, "failure", message=message)
        failure.text = message
    path = tmp_path / "suite.xml"
    ET.ElementTree(suite).write(path, encoding="utf-8")
    failures, signature = attribute_failures(path)
    assert [row["category"] for row in failures] == [
        "FROZEN_CHECKSUM_MISMATCH",
        "MISSING_GOVERNED_DATASET",
        "UI_NOT_BUILT",
    ]
    assert signature["failure_count"] == 3
    assert signature["new_failures_allowed"] is False


def test_run0_selects_exactly_three_cdp_controlled_experiments():
    priorities = [
        {"rank": 1, "field": "provider_name", "failure_reason": "A_EXTRACTION_DEFECT",
         "fixability": "EXTERNAL_EVIDENCE_REQUIRED", "recommended_experiment_family": "none",
         "nearest_unlock_claims": 0},
        *[
            {"rank": rank, "field": f"field_{rank}", "failure_reason": "A_EXTRACTION_DEFECT",
             "fixability": "CDP_CONTROLLED", "recommended_experiment_family": "localization",
             "nearest_unlock_claims": 0}
            for rank in range(2, 7)
        ],
    ]
    plan = experiment_plan(priorities)
    assert plan["selected_count"] == 3
    assert len(plan["experiments"]) == 3
    assert all(item["status"] == "NOT_EVALUABLE" for item in plan["experiments"])
    assert all(item["parameters"]["mode"] == "EVALUATION_OVERLAY_ONLY"
               for item in plan["experiments"])
