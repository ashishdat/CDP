import json
import sys

from evaluation.merge_crop_candidate_routes import main


def test_merge_preserves_original_and_marks_auxiliary(tmp_path, monkeypatch) -> None:
    original = tmp_path / "original.json"
    retuned = tmp_path / "retuned.json"
    output = tmp_path / "merged.json"
    original.write_text(json.dumps([{"value": "A"}]))
    retuned.write_text(json.dumps([{"value": "B"}]))
    monkeypatch.setattr(sys, "argv", ["merge", "--original", str(original),
        "--retuned", str(retuned), "--output", str(output)])
    assert main() == 0
    rows = json.loads(output.read_text())
    assert [row["crop_route"] for row in rows] == [
        "ORIGINAL", "BORDER_AWARE_AUXILIARY"
    ]
