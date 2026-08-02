import json

from packages.retraining import CorrectionMemory, JsonlCorrectionSink, correction_example


def test_memory_is_tenant_and_field_scoped_and_bounded(tmp_path):
    path = tmp_path / "corrections.jsonl"
    sink = JsonlCorrectionSink(path)
    sink.append(correction_example("d1", "type_of_bill", "I17", "117", None, "alice", "tenant-a"))
    sink.append(correction_example("d2", "type_of_bill", "Ill", "111", None, "bob", "tenant-a"))
    sink.append(correction_example("d3", "patient_sex", "E", "F", None, "alice", "tenant-a"))
    sink.append(correction_example("d4", "type_of_bill", "X", "999", None, "mallory", "tenant-b"))
    examples = CorrectionMemory(path, limit=1).exemplars("type_of_bill", "tenant-a")
    assert examples == [{"observed": "Ill", "corrected": "111"}]


def test_memory_skips_malformed_lines(tmp_path):
    path = tmp_path / "corrections.jsonl"
    path.write_text("not-json\n" + json.dumps({"field_name": "x", "corrected_value": "Y"}) + "\n")
    assert CorrectionMemory(path).exemplars("x") == [{"observed": "", "corrected": "Y"}]


def test_correction_patterns_require_distinct_documents_and_reviewers(tmp_path):
    path = tmp_path / "corrections.jsonl"
    sink = JsonlCorrectionSink(path)
    for index in range(5):
        sink.append(correction_example(
            f"doc-{index}", "type_of_bill", "I17", "117", None,
            "reviewer-a" if index % 2 == 0 else "reviewer-b",
        ))
    candidate = CorrectionMemory(path).promotion_candidates()[0]
    assert candidate.promotion_eligible
    assert candidate.agreement_ratio == 1.0


def test_inconsistent_correction_pattern_is_not_promotion_eligible(tmp_path):
    path = tmp_path / "corrections.jsonl"
    sink = JsonlCorrectionSink(path)
    for index, corrected in enumerate(["117", "117", "117", "117", "111"]):
        sink.append(correction_example(
            f"doc-{index}", "type_of_bill", "I17", corrected, None,
            "reviewer-a" if index % 2 == 0 else "reviewer-b",
        ))
    assert not CorrectionMemory(path).promotion_candidates()[0].promotion_eligible
