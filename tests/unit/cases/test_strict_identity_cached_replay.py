import json
from pathlib import Path

from evaluation.real_archive_classification import Observation, PageRef
from evaluation.strict_identity_cached_replay import (
    OCR_CONFIG_VERSION,
    PREPROCESSING_VERSION,
    _failure_result,
    _summary,
    atomic_write_json,
    available_memory_mb,
    finalize_existing_replay,
    observation_from_cache,
    ocr_cache_key,
    safe_worker_count,
    valid_cache_record,
    valid_page_checkpoint,
)
from workers.page_detection.text_extraction import TextLine


def _page(tmp_path: Path) -> PageRef:
    return PageRef(
        archive_id="archive",
        package_id="package",
        asset_id="asset",
        page_id="page",
        page_number=2,
        asset_page_count=3,
        asset_sequence=1,
        asset_path=tmp_path / "source.tif",
        asset_sha256="a" * 64,
        page_sha256="b" * 64,
    )


def _cache(page: PageRef, version: str = "1.4.4") -> dict:
    return {
        "source_asset_sha256": page.asset_sha256,
        "frame_index": 1,
        "rendered_page_sha256": page.page_sha256,
        "ocr_engine": "rapidocr",
        "ocr_engine_version": version,
        "preprocessing_version": PREPROCESSING_VERSION,
        "ocr_config_version": OCR_CONFIG_VERSION,
        "cache_key": ocr_cache_key(page, version),
        "status": "OCR_EXECUTED",
        "tokens": [{"text": "UB-04", "bbox": [1, 2, 3, 4], "confidence": 0.99}],
    }


def test_valid_cache_hit_and_cached_contract_matches_fresh(tmp_path):
    page = _page(tmp_path)
    record = _cache(page)
    assert valid_cache_record(record, page, "1.4.4")
    cached = observation_from_cache(record)
    fresh = Observation((TextLine("UB-04", 1, 2, 3, 4, 0.99),), 10, "rapidocr", "1.4.4")
    assert cached.lines == fresh.lines
    assert cached.engine == fresh.engine
    assert cached.engine_version == fresh.engine_version


def test_stale_page_hash_is_rejected(tmp_path):
    page = _page(tmp_path)
    record = _cache(page)
    record["rendered_page_sha256"] = "c" * 64
    assert not valid_cache_record(record, page, "1.4.4")


def test_ocr_config_version_change_invalidates_cache(tmp_path):
    page = _page(tmp_path)
    record = _cache(page)
    record["ocr_config_version"] = "old"
    assert not valid_cache_record(record, page, "1.4.4")


def test_preprocessing_version_change_invalidates_cache(tmp_path):
    page = _page(tmp_path)
    record = _cache(page)
    record["preprocessing_version"] = "different"
    assert not valid_cache_record(record, page, "1.4.4")


def test_resume_skips_only_complete_hash_valid_page(tmp_path):
    page = _page(tmp_path)
    checkpoint = {
        "source_page_id": page.page_id,
        "source_page_sha256": page.page_sha256,
        "candidate_class": "OTHER_CLAIM_FORM",
        "form_identity": {"localization_allowed": False},
        "routing_result": {"route": "OTHER_CLAIM_FORM"},
        "ocr_provenance": _cache(page),
    }
    assert valid_page_checkpoint(checkpoint, page, "1.4.4")
    checkpoint["ocr_provenance"]["frame_index"] = 0
    assert not valid_page_checkpoint(checkpoint, page, "1.4.4")


def test_atomic_checkpoint_leaves_complete_json_and_ignores_orphan_temp(tmp_path):
    target = tmp_path / "pages" / "page.json"
    atomic_write_json(target, {"complete": True})
    orphan = target.with_name(".page.json.orphan.tmp")
    orphan.write_text("{", "utf-8")
    assert json.loads(target.read_text("utf-8")) == {"complete": True}


def test_failed_ocr_is_hash_accounted_and_fail_closed(tmp_path):
    page = _page(tmp_path)
    failed = _failure_result(page, "1.4.4", RuntimeError("sensitive message"))
    assert failed["ocr_provenance"]["status"] == "OCR_FAILED"
    assert failed["candidate_class"] == "UNKNOWN"
    assert not failed["form_identity"]["localization_allowed"]
    assert failed["failure"] == {"error_type": "RuntimeError", "message_persisted": False}


def test_available_memory_uses_current_system_measurement(monkeypatch):
    memory = type("Memory", (), {"available": 3 * 1024 * 1024})()
    monkeypatch.setattr(
        "evaluation.strict_identity_cached_replay.psutil.virtual_memory", lambda: memory
    )
    assert available_memory_mb() == 3

def test_worker_pool_is_bounded_by_config_memory_and_cpu():
    assert safe_worker_count(99, free_memory_mb=50_000, logical_cpus=16) == 8
    assert safe_worker_count(8, free_memory_mb=1_500, logical_cpus=16) == 1
    assert safe_worker_count(8, free_memory_mb=50_000, logical_cpus=4) == 2

def test_summary_includes_complete_safety_and_execution_contract(tmp_path, monkeypatch):
    page = _page(tmp_path)
    record = {
        "source_page_id": page.page_id,
        "candidate_class": "OTHER_CLAIM_FORM",
        "reason_codes": ["STANDARD_IDENTITY_CLASSIFICATION_MISMATCH"],
        "form_identity": {
            "localization_allowed": False,
            "conflicting_anchors": {"CMS1500": ["NONCANONICAL_CLAIM"]},
        },
        "ocr": {"latency_ms": 12.0},
        "ocr_provenance": {"status": "CACHE_HIT"},
    }
    monkeypatch.setattr("evaluation.strict_identity_cached_replay.time.perf_counter", lambda: 2.0)
    summary = _summary([page], [record], 1.0, 1)

    assert summary["cache_hit_rate"] == 1.0
    assert summary["retries"] == 0
    assert summary["identity_distribution"] == {
        "CMS1500": 0,
        "UB04": 0,
        "OTHER_CLAIM_FORM": 1,
        "UNKNOWN": 0,
        "NON_CLAIM": 0,
    }
    assert summary["cms1500_localization_calls"] == 0
    assert summary["ub04_localization_calls"] == 0
    assert summary["family_mismatch_blocks"] == 1
    assert summary["conflicting_identity_evidence"] == 1
    assert summary["peak_memory_mb"] is None
    assert summary["peak_memory_status"] == "NOT_CAPTURED"

def test_finalize_existing_replay_enriches_old_report_without_ocr(tmp_path, monkeypatch):
    output = tmp_path / "run"
    report = tmp_path / "report"
    (output / "pages").mkdir(parents=True)
    (output / "failures").mkdir()
    page = _page(tmp_path)
    record = {
        "source_page_id": page.page_id,
        "candidate_class": "OTHER_CLAIM_FORM",
        "reason_codes": [],
        "form_identity": {"localization_allowed": False, "conflicting_anchors": {}},
        "ocr": {"latency_ms": 12.0},
        "ocr_provenance": {"status": "OCR_EXECUTED"},
    }
    atomic_write_json(output / "pages" / "page.json", record)
    old_summary = {
        "total_pages_discovered": 1,
        "wall_clock_seconds": 10.0,
        "worker_count": 1,
        "complete": True,
        "all_input_pages_accounted_for": True,
        "stale_records_rejected": 0,
        "canaries": [{"ub04_rejected": True, "ub04_localization_calls": 0}],
        "real_data_classification_accuracy": "NOT_EVALUABLE_WITHOUT_TRUSTED_LABELS",
        "manifest": {
            "assets": 1,
            "rendered_pages": 1,
            "package_count": 1,
            "input_manifest_sha256": "a" * 64,
        },
    }
    atomic_write_json(output / "summary_partial.json", old_summary)
    atomic_write_json(
        output / "memory_peak.json",
        {
            "peak_worker_tree_memory_bytes": 2 * 1024 * 1024,
            "sampling_started_at": "2026-09-04T00:00:00+00:00",
            "sample_interval_seconds": 2,
        },
    )
    monkeypatch.setattr("evaluation.strict_identity_cached_replay.time.perf_counter", lambda: 20.0)

    summary = finalize_existing_replay(output, report)

    assert summary["wall_clock_seconds"] == 10.0
    assert summary["cache_hit_rate"] == 0.0
    assert summary["identity_distribution"]["UB04"] == 0
    assert summary["critical_routing_violations"] == 0
    assert summary["peak_memory_mb"] == 2.0
    assert summary["peak_memory_status"] == "OBSERVED_DURING_PARTIAL_REPLAY_WINDOW"
    assert json.loads((report / "final_report.json").read_text("utf-8")) == summary
    assert "NOT_EVALUABLE_WITHOUT_TRUSTED_LABELS" in (report / "final_report.md").read_text(
        "utf-8"
    )
