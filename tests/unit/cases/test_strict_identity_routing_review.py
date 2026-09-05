import json
from pathlib import Path

import pytest

from evaluation.build_strict_identity_routing_review import build, score


def _record(index: int, *, fixed: bool = False, conflict: bool = False) -> dict:
    page_id = f"page-{index:03d}"
    sha = f"{index + 1:064x}"
    return {
        "source_page_id": page_id,
        "source_page_sha256": sha,
        "package_id": f"package-{index % 3}",
        "source_asset_id": f"asset-{index}",
        "source_page_number": 1,
        "candidate_class": "CMS1500" if fixed else "UNKNOWN",
        "ocr_provenance": {"rendered_page_sha256": sha},
        "routing_result": {"router_nomination": "CMS1500" if fixed else "UNKNOWN_UNSTRUCTURED"},
        "production_chain": {
            "fixed_extractor_authorized": fixed,
            "verified_identity_family": "CMS1500" if fixed else None,
            "decision_reason_codes": [],
        },
        "form_identity": {
            "localization_allowed": fixed,
            "family_eligibility": {},
            "conflicting_anchors": {"CMS1500": ["CONFLICT"] if conflict else []},
        },
    }


def _write(directory: Path, records: list[dict]) -> None:
    directory.mkdir()
    for record in records:
        (directory / f"{record['source_page_id']}.json").write_text(json.dumps(record), "utf-8")


def test_builds_prediction_blind_priority_queues_with_review_controls(tmp_path):
    current_records = [
        _record(0, fixed=True),
        _record(1, conflict=True),
        *[_record(index) for index in range(2, 12)],
    ]
    preceding_records = json.loads(json.dumps(current_records))
    preceding_records[2]["form_identity"]["localization_allowed"] = True
    current, preceding, output = (
        tmp_path / "current",
        tmp_path / "preceding",
        tmp_path / "output",
    )
    _write(current, current_records)
    _write(preceding, preceding_records)

    result = build(current, preceding, output, rapid_size=5)

    rapid = json.loads((output / "rapid_blind_queue.json").read_text("utf-8"))
    full = json.loads((output / "full_blind_queue.json").read_text("utf-8"))
    coordinator = json.loads((output / "coordinator_risk_manifest.json").read_text("utf-8"))
    assert result["rapid_pages"] == 5
    assert result["full_pages"] == 12
    assert rapid["status"] == "PRELIMINARY"
    assert full["records"][0]["source_page_id"] == "page-000"
    assert all(
        "candidate_class" not in record
        and "router_nomination" not in record
        and "risk_reasons" not in record
        for record in full["records"]
    )
    assert full["records"][0]["required_independent_reviews"] == 2
    assert full["records"][1]["required_independent_reviews"] == 2
    assert coordinator["access"] == "COORDINATOR_ONLY_NOT_FOR_INITIAL_ANNOTATORS"
    assert result["double_review_pages"] >= 4
    assert result["status"] == "BLOCKED_HUMAN_LABELS"


def test_rejects_stale_page_sha_and_page_set_mismatch(tmp_path):
    current, preceding = tmp_path / "current", tmp_path / "preceding"
    record = _record(0)
    stale = json.loads(json.dumps(record))
    stale["ocr_provenance"]["rendered_page_sha256"] = "f" * 64
    _write(current, [stale])
    _write(preceding, [record])
    with pytest.raises(ValueError, match="PAGE_SHA_MISMATCH"):
        build(current, preceding, tmp_path / "output")


def test_rejects_different_policy_page_sets(tmp_path):
    current, preceding = tmp_path / "current", tmp_path / "preceding"
    _write(current, [_record(0)])
    _write(preceding, [_record(0), _record(1)])
    with pytest.raises(ValueError, match="CURRENT_PRECEDING_PAGE_SET_MISMATCH"):
        build(current, preceding, tmp_path / "output")


def test_scoring_blocks_with_null_metrics_until_reviews_complete(tmp_path):
    current, preceding, output = (
        tmp_path / "current",
        tmp_path / "preceding",
        tmp_path / "output",
    )
    records = [_record(0, fixed=True), _record(1)]
    _write(current, records)
    _write(preceding, json.loads(json.dumps(records)))
    build(current, preceding, output, rapid_size=2)

    result = score(
        output / "rapid_blind_queue.json",
        current,
        output / "reviews.jsonl",
        output / "adjudications.jsonl",
    )

    assert result["status"] == "BLOCKED_HUMAN_LABELS"
    assert result["reason"] == "BLOCKED_HUMAN_LABELS"
    assert result["progress"]["scorable_pages"] == 0
    assert result["progress"]["unscorable_pages"] == 2
    assert all(value is None for value in result["metrics"].values())


def test_scoring_uses_only_complete_independent_reviews(tmp_path):
    current, preceding, output = (
        tmp_path / "current",
        tmp_path / "preceding",
        tmp_path / "output",
    )
    records = [_record(0, fixed=True), _record(1)]
    _write(current, records)
    _write(preceding, json.loads(json.dumps(records)))
    build(current, preceding, output, rapid_size=2)
    queue = json.loads((output / "rapid_blind_queue.json").read_text("utf-8"))
    reviews = []
    for task in queue["records"]:
        label = "CMS1500" if task["source_page_id"] == "page-000" else "UNKNOWN"
        for index in range(task["required_independent_reviews"]):
            reviews.append(
                {
                    "blind_task_id": task["blind_task_id"],
                    "source_page_id": task["source_page_id"],
                    "source_page_sha256": task["source_page_sha256"],
                    "reviewed_label": label,
                    "review_status": "COMPLETED",
                    "reviewer_id": f"reviewer-{index}",
                    "review_session_id": f"session-{task['source_page_id']}-{index}",
                    "reviewer_role": "REVIEWER_A" if index == 0 else "REVIEWER_B",
                }
            )
    (output / "reviews.jsonl").write_text(
        chr(10).join(json.dumps(row) for row in reviews) + chr(10), "utf-8"
    )

    result = score(
        output / "rapid_blind_queue.json",
        current,
        output / "reviews.jsonl",
        output / "adjudications.jsonl",
    )

    assert result["status"] == "ROUTING_PRELIMINARY"
    assert result["metrics"]["overall_exact_accuracy"]["numerator"] == 2
    assert result["metrics"]["overall_exact_accuracy"]["denominator"] == 2
    assert result["metrics"]["fixed_authorization_precision"]["numerator"] == 1
    assert result["metrics"]["false_standard_authorization"]["numerator"] == 0


def test_scoring_rejects_non_independent_dual_review(tmp_path):
    current, preceding, output = (
        tmp_path / "current",
        tmp_path / "preceding",
        tmp_path / "output",
    )
    records = [_record(0, fixed=True)]
    _write(current, records)
    _write(preceding, json.loads(json.dumps(records)))
    build(current, preceding, output, rapid_size=1)
    task = json.loads((output / "rapid_blind_queue.json").read_text("utf-8"))["records"][0]
    review = {
        "blind_task_id": task["blind_task_id"],
        "source_page_id": task["source_page_id"],
        "source_page_sha256": task["source_page_sha256"],
        "reviewed_label": "CMS1500",
        "review_status": "COMPLETED",
        "reviewer_id": "same-reviewer",
        "review_session_id": "same-session",
        "reviewer_role": "REVIEWER_A",
    }
    (output / "reviews.jsonl").write_text(
        json.dumps(review) + chr(10) + json.dumps(review) + chr(10), "utf-8"
    )

    result = score(
        output / "rapid_blind_queue.json",
        current,
        output / "reviews.jsonl",
        output / "adjudications.jsonl",
    )
    assert result["status"] == "BLOCKED_HUMAN_LABELS"
