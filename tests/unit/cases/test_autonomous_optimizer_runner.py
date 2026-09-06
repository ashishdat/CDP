import json

from evaluation.autonomous_optimizer_runner import run_manifest


def metric(pages, **changes):
    value = {
        "evaluated_pages": pages,
        "accepted_precision": 0.99,
        "source_accuracy": 0.90,
        "hitl_rate": 0.20,
        "critical_false_accepts": 0,
        "latency_ms_per_page": 100.0,
        "cost_usd_per_page": 0.01,
        "cohort_sha256": f"cohort-{pages}",
        "truth_sha256": "truth",
    }
    value.update(changes)
    return value


def manifest():
    return {
        "schema_version": "autonomous-cdp-run-v1",
        "baseline_sha": "a" * 40,
        "experiment_type": "PREPROCESSING_PROFILE",
        "cohort_key": "B/LOW/npi/INVALID/rapidocr",
        "change": {"profile": "adaptive-threshold-v2"},
        "tiers": {
            tier: {"baseline": metric(pages), "candidate": metric(pages)}
            for tier, pages in (("A", 100), ("B", 500), ("C", 1000))
        },
    }


def test_manifest_runner_qualifies_only_after_all_tiers(tmp_path):
    source = tmp_path / "run.json"
    source.write_text(json.dumps(manifest()), encoding="utf-8")
    report = run_manifest(source, tmp_path / "output")
    assert report["status"] == "QUALIFIED"
    assert set(report["decisions"]) == {"A", "B", "C"}
    assert report["qualification"]["runtime_activation"] is False


def test_manifest_runner_stops_immediately_on_safety_failure(tmp_path):
    payload = manifest()
    payload["tiers"]["A"]["candidate"]["critical_false_accepts"] = 1
    source = tmp_path / "run.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    report = run_manifest(source, tmp_path / "output")
    assert report["status"] == "REVERTED"
    assert set(report["decisions"]) == {"A"}
    assert "CRITICAL_FALSE_ACCEPT" in report["decisions"]["A"]["reasons"]


def test_manifest_runner_resumes_hash_bound_completed_tiers(tmp_path):
    source = tmp_path / "run.json"
    source.write_text(json.dumps(manifest()), encoding="utf-8")
    first = run_manifest(source, tmp_path / "output")
    second = run_manifest(source, tmp_path / "output")
    assert first["experiment_id"] == second["experiment_id"]
    assert all(second["decisions"][tier]["resumed"] for tier in ("A", "B", "C"))
