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
