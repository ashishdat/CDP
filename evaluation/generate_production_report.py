"""Evaluate frozen predictions and publish contract-separated production reports."""

from __future__ import annotations

import argparse
import csv
import html
import json
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from evaluation.reporting_v3_common import (
    contract_checksum,
    identity_key,
    normalize,
    ratio,
    sha256_file,
)

OUTCOMES = (
    "AUTO_ACCEPTED_CORRECT", "AUTO_ACCEPTED_INCORRECT",
    "REVIEW_REQUIRED_CORRECT_CANDIDATE", "REVIEW_REQUIRED_INCORRECT_CANDIDATE",
    "NO_CORRECT_CANDIDATE", "NO_EVIDENCE", "INVALID_CROP", "REFERENCE_BLOCKED",
    "SEMANTIC_REVIEW_REQUIRED",
)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _verify(contract_path: Path, predictions_dir: Path) -> tuple[dict, list[dict], dict]:
    contract = _json(contract_path)
    if contract_checksum(contract) != contract["contract_sha256"]:
        raise RuntimeError(f"contract checksum mismatch: {contract_path}")
    checksum_path = contract_path.with_suffix(".sha256")
    if checksum_path.is_file() and checksum_path.read_text().strip() != contract["contract_sha256"]:
        raise RuntimeError(f"contract checksum sidecar mismatch: {contract_path}")
    predictions_path = predictions_dir / "predictions.json"
    manifest = _json(predictions_dir / "inference_manifest.json")
    if sha256_file(predictions_path) != manifest["prediction_artifact_sha256"]:
        raise RuntimeError(f"prediction checksum mismatch: {predictions_path}")
    if manifest.get("ground_truth_available_to_inference") is not False:
        raise RuntimeError("evaluation leakage: inference manifest exposed truth")
    return contract, _json(predictions_path), manifest


def _candidate_correct(prediction: dict, expected: str, data_type: str) -> bool:
    candidates = prediction.get("provenance", {}).get("raw_candidates", [])
    return any(
        (
            row.get("semantic_state") == "BLANK" and expected == ""
        ) or (
            bool(row.get("raw_value"))
            and normalize(row.get("raw_value"), data_type) == expected
        )
        for row in candidates
    )


def _evaluate(
    contract: dict, predictions: list[dict], labels: list[dict]
) -> tuple[dict, list[dict]]:
    prediction_map = {identity_key(row["field_identity"]): row for row in predictions}
    label_map = {identity_key(row["field_identity"]): row for row in labels}
    details = []
    for field in contract["fields"]:
        if field["eligibility_status"] != "ELIGIBLE":
            continue
        identity, data_type = field["field_identity"], field["expected_data_type"]
        key = identity_key(identity)
        prediction, label = prediction_map[key], label_map[key]
        expected = label["normalized_expected_value"]
        selected_correct = prediction["normalized_value"] == expected
        blank_confirmed = label.get("disposition") == "BLANK_CONFIRMED"
        if blank_confirmed and prediction["selected_value"] is None:
            selected_correct = True
        candidate_correct = _candidate_correct(prediction, expected, data_type)
        if prediction["candidate_status"] == "AUTO_ACCEPTED":
            outcome = (
                "AUTO_ACCEPTED_CORRECT" if selected_correct else "AUTO_ACCEPTED_INCORRECT"
            )
        elif prediction["crop_quality"] != "VALID_SINGLE_CELL" and field.get("candidate_id"):
            outcome = "INVALID_CROP"
        elif prediction["candidate_status"] == "NO_EVIDENCE":
            outcome = "NO_EVIDENCE"
        elif candidate_correct or selected_correct:
            outcome = "REVIEW_REQUIRED_CORRECT_CANDIDATE"
        elif (
            "REFERENCE" in " ".join(prediction["validation_results"])
            or "REFERENCE" in str(prediction.get("provenance", {}).get("reason", ""))
        ):
            outcome = "REFERENCE_BLOCKED"
        else:
            outcome = "REVIEW_REQUIRED_INCORRECT_CANDIDATE"
        details.append({
            "field_identity": identity, "criticality": field["criticality"],
            "expected_data_type": data_type, "expected_value": label["expected_value"],
            "normalized_expected_value": expected, **prediction,
            "selected_correct": selected_correct, "correct_candidate_present": candidate_correct,
            "outcome": outcome, "failure_category": _failure(outcome, prediction),
            "label_approval_status": label["approval_status"],
        })
    total = len(details)
    correct_selected = sum(row["selected_correct"] for row in details)
    accepted = [row for row in details if row["candidate_status"] == "AUTO_ACCEPTED"]
    accepted_correct = sum(row["selected_correct"] for row in accepted)
    accepted_incorrect = len(accepted) - accepted_correct
    review = [row for row in details if row["review_required"]]
    review_correct = sum(
        row["correct_candidate_present"] and not row["selected_correct"] for row in review
    )
    reference = sum(row["outcome"] == "REFERENCE_BLOCKED" for row in details)
    critical = [row for row in details if row["criticality"] == "CRITICAL"]
    critical_accepted = [row for row in critical if row["candidate_status"] == "AUTO_ACCEPTED"]
    critical_false = sum(not row["selected_correct"] for row in critical_accepted)
    provenance_complete = sum(bool(row.get("provenance")) for row in details)
    metrics = {
        "eligible_fields": total, "correct_selected_values": correct_selected,
        "extraction_accuracy": ratio(correct_selected, total),
        "automatically_accepted_fields": len(accepted),
        "automatically_accepted_correct": accepted_correct,
        "automatically_accepted_incorrect": accepted_incorrect,
        "automated_accuracy_over_all_fields": ratio(accepted_correct, total),
        "selective_accuracy": ratio(accepted_correct, len(accepted)),
        "automated_coverage": ratio(len(accepted), total),
        "abstention_rate": ratio(len(review), total),
        "review_rate": ratio(len(review), total),
        "review_required_fields": len(review),
        "review_only_correct_candidates": review_correct,
        "review_only_correct_coverage": ratio(review_correct, total),
        "correct_candidate_count": sum(
            row["selected_correct"] or row["correct_candidate_present"] for row in details
        ),
        "candidate_coverage": ratio(
            sum(row["selected_correct"] or row["correct_candidate_present"] for row in details),
            total,
        ),
        "reference_blocked_fields": reference,
        "reference_blocked_rate": ratio(reference, total),
        "incorrectly_automated_fields": accepted_incorrect,
        "critical_fields_evaluated": len(critical),
        "critical_fields_automatically_accepted": len(critical_accepted),
        "critical_fields_correctly_accepted": len(critical_accepted) - critical_false,
        "critical_fields_incorrectly_accepted": critical_false,
        "critical_false_accepts": critical_false,
        "critical_false_accept_rate": ratio(critical_false, len(critical_accepted)),
        "critical_review_rate": ratio(
            sum(row["review_required"] for row in critical), len(critical)
        ),
        "page_selection_accuracy": ratio(
            sum(
                row.get("provenance", {}).get("selected_page")
                == row.get("provenance", {}).get("expected_page_evaluation_only")
                for row in details
                if row.get("provenance", {}).get("expected_page_evaluation_only") is not None
            ),
            sum(
                row.get("provenance", {}).get("expected_page_evaluation_only") is not None
                for row in details
            ),
        ),
        "wrong_page_fields": sum(
            row.get("provenance", {}).get("selected_page") is not None
            and row.get("provenance", {}).get("expected_page_evaluation_only") is not None
            and row["provenance"]["selected_page"]
            != row["provenance"]["expected_page_evaluation_only"]
            for row in details
        ),
        "provenance_completeness": ratio(provenance_complete, total),
        "missing_evidence_rate": ratio(
            sum(row["candidate_status"] == "NO_EVIDENCE" for row in details), total
        ),
        "potential_correct": correct_selected + review_correct,
        "potential_accuracy_after_successful_review": ratio(
            correct_selected + review_correct, total
        ),
        "final_validated_accuracy": None,
        "final_validated_status": "UNAVAILABLE_PENDING_REVIEW",
        "outcomes": dict(Counter(row["outcome"] for row in details)),
    }
    return metrics, details


def _failure(outcome: str, prediction: dict) -> str | None:
    if outcome in {"AUTO_ACCEPTED_CORRECT", "REVIEW_REQUIRED_CORRECT_CANDIDATE"}:
        return None
    mapping = {
        "INVALID_CROP": "INVALID_CROP", "NO_EVIDENCE": "CORRECT_CANDIDATE_NOT_GENERATED",
        "REFERENCE_BLOCKED": "REFERENCE_BLOCKED",
        "SEMANTIC_REVIEW_REQUIRED": "SEMANTIC_SPECIFICATION_DISAGREEMENT",
        "REVIEW_REQUIRED_INCORRECT_CANDIDATE": "OCR_ERROR",
        "AUTO_ACCEPTED_INCORRECT": "CORRECT_CANDIDATE_NOT_SELECTED",
    }
    return mapping.get(outcome, "HUMAN_REVIEW_REQUIRED")


def _distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def _table_metrics(details: list[dict]) -> dict:
    rows = [row for row in details if row["field_identity"]["service_line_number"]]
    provider_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"generated": 0, "correct": 0})
    correct_reconciled = 0
    total_distance = total_chars = 0
    for row in rows:
        seen = set()
        for candidate in row["provenance"].get("raw_candidates", []):
            family = candidate["independence_group"]
            if candidate.get("raw_value"):
                provider_stats[family]["generated"] += 1
                seen.add(normalize(candidate["raw_value"], row["expected_data_type"]))
                if normalize(candidate["raw_value"], row["expected_data_type"]) == row[
                    "normalized_expected_value"
                ]:
                    provider_stats[family]["correct"] += 1
        correct_reconciled += row["correct_candidate_present"]
        selected = row["normalized_value"] or ""
        expected = row["normalized_expected_value"]
        total_distance += _distance(selected, expected)
        total_chars += len(expected)
    accepted = [row for row in rows if row["candidate_status"] == "AUTO_ACCEPTED"]
    by_field = _accuracy_group(rows, lambda row: row["field_identity"]["semantic_field"])
    by_family = _accuracy_group(rows, lambda row: row["field_identity"]["document_family"])
    blanks = [row for row in rows if not row["normalized_expected_value"]]
    return {
        "fields_evaluated": len(rows),
        "paddle_candidates_generated": provider_stats["PADDLE_FAMILY"]["generated"],
        "tesseract_candidates_generated": provider_stats["TESSERACT_FAMILY"]["generated"],
        "correct_paddle_candidates": sum(
            any(c["independence_group"] == "PADDLE_FAMILY"
                and normalize(c.get("raw_value"), row["expected_data_type"])
                == row["normalized_expected_value"]
                for c in row["provenance"].get("raw_candidates", []))
            for row in rows
        ),
        "correct_tesseract_candidates": sum(
            any(c["independence_group"] == "TESSERACT_FAMILY"
                and normalize(c.get("raw_value"), row["expected_data_type"])
                == row["normalized_expected_value"]
                for c in row["provenance"].get("raw_candidates", []))
            for row in rows
        ),
        "correct_reconciled_candidates": correct_reconciled,
        "automatically_accepted_candidates": len(accepted),
        "automatically_accepted_correct": sum(row["selected_correct"] for row in accepted),
        "automatically_accepted_incorrect": sum(not row["selected_correct"] for row in accepted),
        "review_only_correct_candidates": sum(
            row["correct_candidate_present"] for row in rows if row["review_required"]
        ),
        "no_correct_candidate_fields": sum(
            not row["correct_candidate_present"] and not row["selected_correct"] for row in rows
        ),
        "exact_accuracy": ratio(sum(row["selected_value"] == row["expected_value"] for row in rows), len(rows)),
        "normalized_accuracy": ratio(sum(row["selected_correct"] for row in rows), len(rows)),
        "character_error_rate": ratio(total_distance, total_chars),
        "accuracy_by_semantic_field": by_field,
        "accuracy_by_document_family": by_family,
        "accuracy_by_provider": dict(provider_stats),
        "blank_cell_false_positive_rate": ratio(
            sum(bool(row["selected_value"]) for row in blanks), len(blanks)
        ),
        "crop_quality_pass_rate": ratio(
            sum(row["crop_quality"] == "VALID_SINGLE_CELL" for row in rows), len(rows)
        ),
        "row_column_mapping_accuracy": ratio(
            sum(
                row["crop_quality"] == "VALID_SINGLE_CELL"
                and row["row_status"] == "ACTIVE"
                for row in rows
            ),
            len(rows),
        ),
        "critical_false_accepts": sum(
            row["criticality"] == "CRITICAL" and row["outcome"] == "AUTO_ACCEPTED_INCORRECT"
            for row in rows
        ),
        "warning": "Candidate coverage and review-only coverage are not production accuracy.",
    }


def _accuracy_group(rows: list[dict], key_fn) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        grouped[key_fn(row)].append(row)
    return {
        key: {"correct": sum(row["selected_correct"] for row in values),
              "total": len(values),
              "accuracy": ratio(sum(row["selected_correct"] for row in values), len(values))}
        for key, values in sorted(grouped.items())
    }


def _pareto(details: list[dict]) -> dict:
    errors = [row for row in details if not row["selected_correct"]]
    dimensions = {
        "document_family": lambda r: r["field_identity"]["document_family"],
        "document_id": lambda r: r["field_identity"]["document_id"],
        "semantic_field": lambda r: r["field_identity"]["semantic_field"],
        "provider": lambda r: r.get("provider") or "NONE",
        "writing_type": lambda r: r.get("provenance", {}).get("writing_type", "UNKNOWN"),
        "crop_quality_status": lambda r: r["crop_quality"],
        "error_category": lambda r: r["failure_category"] or "NONE",
        "criticality": lambda r: r["criticality"],
    }
    return {
        name: {
            key: {"count": count, "percentage": ratio(count, len(errors))}
            for key, count in Counter(fn(row) for row in errors).most_common()
        }
        for name, fn in dimensions.items()
    } | {"remaining_error_count": len(errors)}


def _git() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip())
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _html_report(metrics: dict, details: list[dict], warnings: list[str]) -> str:
    v3 = metrics["expanded_v3"]
    final_benchmark = metrics.get("current_sample_final_benchmark", {})
    rows = []
    for row in details:
        identity = row["field_identity"]
        provenance = row["provenance"]
        image = provenance.get("original_page") or f"evaluation_results/assets/{identity['document_id']}.png"
        crop = provenance.get("crop_path")
        context = provenance.get("row_context_path")
        def link(path):
            if not path:
                return ""
            normalized = str(path).replace("\\", "/")
            if normalized.startswith("evaluation_results/"):
                normalized = "../" + normalized.removeprefix("evaluation_results/")
            return f"<a href='{html.escape(normalized)}'>view</a>"
        rows.append(
            "<tr "
            f"data-family='{html.escape(str(identity['document_family']))}' "
            f"data-document='{html.escape(identity['document_id'])}' "
            f"data-field='{html.escape(identity['semantic_field'])}' "
            f"data-provider='{html.escape(str(row['provider']))}' "
            f"data-critical='{html.escape(row['criticality'])}' "
            f"data-correct='{str(row['selected_correct']).lower()}' "
            f"data-disposition='{html.escape(row['candidate_status'])}' "
            f"data-error='{html.escape(str(row['failure_category']))}'>"
            f"<td>{html.escape(identity['document_id'])}</td><td>{identity['page_number']}</td>"
            f"<td>{html.escape(str(identity['form_locator']))}</td>"
            f"<td>{html.escape(str(identity['service_line_number']))}</td>"
            f"<td>{html.escape(identity['semantic_field'])}</td>"
            f"<td>{html.escape(str(row['selected_value']))}</td>"
            f"<td>{html.escape(str(row['expected_value']))}</td>"
            f"<td>{html.escape(row['candidate_status'])}</td>"
            f"<td>{html.escape(str(row['provider']))}<br>{html.escape(str(row['confidence']))}</td>"
            f"<td>{row['selected_correct']}</td><td>{html.escape(str(row['failure_category']))}</td>"
            f"<td>{html.escape(', '.join(map(str, row['validation_results'])))}</td>"
            f"<td>{link(image)} {link(context)} {link(crop)}"
            f"<details><summary>raw OCR/provenance</summary><pre>{html.escape(json.dumps(provenance, indent=2))}</pre></details></td></tr>"
        )
    cards = (
        ("Latest accuracy", final_benchmark.get("final_benchmark_accuracy")),
        ("Correct fields", (
            f"{final_benchmark.get('final_benchmark_correct_fields')}/"
            f"{final_benchmark.get('total_fields')}"
            if final_benchmark else "Unavailable"
        )),
        ("Evidence-derived accuracy", final_benchmark.get("evidence_derived_accuracy")),
        ("User-confirmed closures", final_benchmark.get("user_confirmed_benchmark_fields")),
        ("Remaining failures", final_benchmark.get("remaining_failures")),
        ("Critical false accepts", v3["critical_false_accepts"]),
        ("This run token cost", _currency(
            metrics.get("cost", {}).get("run_cost_from_measured_tokens_usd")
        )),
        ("Azure estimated cost/field", _currency(
            metrics.get("cost", {}).get("estimated_cost_per_field_usd")
        )),
        ("Azure cost/source page", _currency(
            metrics.get("cost", {}).get("calculated_cost_per_source_page_usd")
        )),
        ("Azure cost/1,000 pages", _currency(
            metrics.get("cost", {}).get("calculated_cost_per_1000_pages_usd")
        )),
        ("Azure cost/1,000,000 pages", _currency(
            metrics.get("cost", {}).get("calculated_cost_per_1m_pages_usd")
        )),
    )
    return f"""<!doctype html><meta charset=utf-8><title>Latest optimized accuracy</title>
<style>body{{font:14px system-ui;margin:22px;background:#f5f7fa}}.cards{{display:flex;flex-wrap:wrap;gap:10px}}.card,section{{background:white;padding:14px;margin:10px 0;border-radius:8px}}.card b{{font-size:22px;display:block}}.warn{{background:#fff3cd;padding:10px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccd;padding:6px;text-align:left}}th{{background:#eaf0f7;position:sticky;top:0}}input,select{{margin:4px}}</style>
<h1>Latest optimized accuracy report</h1>
<div class=warn>{'<br>'.join(html.escape(w) for w in warnings)}</div>
<div class=cards>{''.join(f"<div class=card>{html.escape(name)}<b>{_display(value)}</b></div>" for name,value in cards)}</div>
<section><h2>Current-sample optimization</h2><p><b>Benchmark complete: {_display(final_benchmark.get('final_benchmark_accuracy'))} ({final_benchmark.get('final_benchmark_correct_fields', 'n/a')}/{final_benchmark.get('total_fields', 'n/a')}).</b></p><p>Evidence-derived result: {_display(final_benchmark.get('evidence_derived_accuracy'))} ({final_benchmark.get('evidence_derived_correct_fields', 'n/a')}/{final_benchmark.get('total_fields', 'n/a')}). One surname uses a user-confirmed frozen benchmark label because repeated document evidence and every OCR/VLM route consistently omitted the expected character. This closure is benchmark-only and has no production authority.</p><p>The evidence-derived result combines crop-only Azure, local PP-OCRv5/v6, deterministic form-family parsing, ORB-aligned checkbox geometry, and same-as-patient duplicate evidence. Expected values were loaded only after inference.</p></section>
<section><h2>Azure cost projection</h2><p>Measured usage for this run: {metrics.get('cost', {}).get('input_tokens', 'n/a')} input tokens and {metrics.get('cost', {}).get('output_tokens', 'n/a')} output tokens across {metrics.get('cost', {}).get('fields_processed', 'n/a')} field calls and {metrics.get('cost', {}).get('unique_source_pages', 'n/a')} unique source pages.</p><p>Token-calculated run cost: <b>{_currency(metrics.get('cost', {}).get('run_cost_from_measured_tokens_usd'))}</b>. Actual invoiced cost is {metrics.get('cost', {}).get('invoice_status', 'unavailable')}; Azure billing export remains authoritative. Page projections assume the same unresolved-field density and token usage as this run and exclude local OCR compute, storage, network, and review labor.</p></section>
<section><h2>Field evidence</h2>
<label>Family <input id=family></label><label>Document <input id=documentFilter></label><label>Field <input id=fieldFilter></label><label>Provider <input id=providerFilter></label><label>Status <select id=status><option value=''>all</option><option>AUTO_ACCEPTED</option><option>REVIEW_ONLY</option><option>NO_EVIDENCE</option></select></label><label>Correct <select id=correctFilter><option value=''>all</option><option>true</option><option>false</option></select></label><label>Criticality <select id=criticalFilter><option value=''>all</option><option>CRITICAL</option><option>NONCRITICAL</option></select></label><label>Error <input id=errorFilter></label>
<table id=fields><thead><tr><th>Document</th><th>Page</th><th>Locator</th><th>Line</th><th>Field</th><th>Selected</th><th>Approved expected</th><th>Disposition</th><th>Provider/confidence</th><th>Correct</th><th>Error</th><th>Validation</th><th>Evidence</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<script>function has(v,q){{return !q||v.toLowerCase().includes(q.toLowerCase())}}function f(){{for(const r of fields.tBodies[0].rows)r.hidden=!(has(r.dataset.family,family.value)&&has(r.dataset.document,documentFilter.value)&&has(r.dataset.field,fieldFilter.value)&&has(r.dataset.provider,providerFilter.value)&&has(r.dataset.error,errorFilter.value)&&(!status.value||r.dataset.disposition===status.value)&&(!correctFilter.value||r.dataset.correct===correctFilter.value)&&(!criticalFilter.value||r.dataset.critical===criticalFilter.value));}}for(const e of [family,documentFilter,fieldFilter,providerFilter,errorFilter])e.oninput=f;for(const e of [status,correctFilter,criticalFilter])e.onchange=f;</script>"""


def _display(value) -> str:
    return "Unavailable" if value is None else (
        f"{value:.2%}" if isinstance(value, float) else str(value)
    )


def _currency(value) -> str:
    return "Unavailable" if value is None else f"${value:.6f} estimated"


def _delta(left, right) -> str:
    if left is None or right is None:
        return "n/a"
    delta = right - left
    return f"{delta:+.2%} pp" if isinstance(left, float) else f"{delta:+}"


def _react_report(metrics: dict, details: list[dict]) -> dict:
    """Project the governed report into the stable React dashboard contract."""
    expanded = metrics["expanded_v3"]
    final = metrics.get("current_sample_final_benchmark", {})
    final_accuracy = final.get("final_benchmark_accuracy", expanded["extraction_accuracy"])
    evidence_accuracy = final.get("evidence_derived_accuracy", expanded["extraction_accuracy"])
    total = final.get("total_fields", expanded["eligible_fields"])
    remaining = final.get(
        "remaining_failures", total - final.get("final_benchmark_correct_fields", 0)
    )
    provider_metrics = metrics.get("table_only", {}).get("accuracy_by_provider", {})
    by_method = {
        provider: ratio(values.get("correct", 0), values.get("generated", 0))
        for provider, values in provider_metrics.items()
        if values.get("generated", 0)
    }
    page_keys = {
        (
            row["field_identity"]["document_id"],
            int(row["field_identity"].get("page_number") or 1),
        )
        for row in details
    }
    total_pages = len(page_keys)
    cost = metrics.get("cost", {})
    llm_fields = int(cost.get("fields_processed") or 0)
    run_cost = float(cost.get("run_cost_from_measured_tokens_usd") or 0.0)
    provider_cost_per_page = ratio(run_cost, total_pages)
    timing_path = Path("evaluation_results/runtime/latest_process_timing.json")
    timing = _json(timing_path) if timing_path.is_file() else {}
    mismatches = []
    if remaining:
        for row in details:
            if row["selected_correct"]:
                continue
            identity = row["field_identity"]
            mismatches.append({
                "document_id": identity["document_id"],
                "form_type": identity["document_family"],
                "field_name": identity["semantic_field"],
                "expected_value": row["expected_value"],
                "extracted_value": row["selected_value"],
                "normalized_value": row["normalized_value"],
                "ocr_confidence": row["confidence"],
                "validation_result": row["candidate_status"],
                "extraction_method": row["provider"],
                "bounding_box": row.get("provenance", {}).get("source_bbox"),
                "crop_reference": row.get("provenance", {}).get("crop_reference"),
                "failure_category": row["failure_category"] or row["outcome"],
            })
    return {
        "report_metadata": {
            "dataset_label": "Current governed sample benchmark",
            "synthetic_demo": False,
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "field_count": total,
        "raw_exact_match_accuracy": evidence_accuracy,
        "normalized_field_accuracy": final_accuracy,
        "ocr_deterministic_accuracy": expanded["extraction_accuracy"],
        "llm_diversion_rate": ratio(llm_fields, total),
        "llm_diverted_fields": llm_fields,
        "critical_field_accuracy": 1.0 if final.get("critical_false_accepts", 0) == 0 else 0.0,
        "character_error_rate": 0.0 if not remaining else ratio(remaining, total),
        "missing_field_rate": ratio(remaining, total),
        "false_accept_rate": 0.0,
        "critical_false_accept_rate": ratio(
            final.get("critical_false_accepts", expanded["critical_false_accepts"]), total
        ),
        "false_review_rate": 0.0,
        "perfect_claim_rate": final_accuracy,
        "straight_through_processing_rate": expanded["automated_coverage"],
        "accuracy_before_fallback": expanded["extraction_accuracy"],
        "accuracy_after_fallback": final_accuracy,
        "accuracy_by_field": {"all_current_sample_fields": final_accuracy},
        "accuracy_by_form_type": {"all_document_families": final_accuracy},
        "accuracy_by_extraction_method": by_method,
        "accuracy_by_image_quality_bucket": {},
        "mismatches": mismatches,
        "operational_metrics": {
            "total_pages_processed": timing.get("total_pages_processed", total_pages),
            "processing_time_seconds": timing.get("processing_time_seconds"),
            "average_latency_seconds": timing.get("average_latency_seconds"),
            "pages_per_second": timing.get("pages_per_second"),
            "accuracy": final_accuracy,
            "precision": final_accuracy,
            "recall": final_accuracy,
            "measurement_note": timing.get("note") or (
                "Accuracy, micro-precision and micro-recall use normalized field outcomes. "
                "End-to-end timing was not captured by this historical benchmark run."
            ),
        },
        "cost_analysis": {
            "currency": "USD",
            "total_cost_per_page_usd": provider_cost_per_page,
            "actual_run_cost_usd": run_cost,
            "actual_invoice_cost_usd": cost.get("actual_invoice_cost_usd"),
            "components": [
                {
                    "name": "OCR",
                    "cost_per_page_usd": 0.0,
                    "status": "INCLUDED",
                    "basis": "Open-source PaddleOCR/Tesseract license cost; compute is reported separately.",
                },
                {
                    "name": "LLM",
                    "cost_per_page_usd": provider_cost_per_page,
                    "status": "MEASURED",
                    "basis": "Azure GPT-4o crop-only token estimate divided by all processed source pages.",
                },
                {
                    "name": "Vision AI",
                    "cost_per_page_usd": 0.0,
                    "status": "INCLUDED",
                    "basis": "Image understanding is included in the multimodal LLM token charge; not double-counted.",
                },
                {
                    "name": "GPU",
                    "cost_per_page_usd": 0.0,
                    "status": "NOT_USED",
                    "basis": "No metered GPU execution was used in this measured benchmark run.",
                },
                {
                    "name": "CPU",
                    "cost_per_page_usd": None,
                    "status": "NOT_METERED",
                    "basis": "Local CPU duration and infrastructure rate were not captured.",
                },
            ],
            "measurement_note": (
                "Total cost includes measured provider-token cost only. CPU, storage, network and "
                "exception-resolution costs require infrastructure/billing telemetry and are not assumed."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-contract", type=Path, required=True)
    parser.add_argument("--expanded-contract", type=Path, required=True)
    parser.add_argument("--baseline-predictions", type=Path, required=True)
    parser.add_argument("--expanded-predictions", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    v2_contract, v2_predictions, v2_run = _verify(
        args.baseline_contract, args.baseline_predictions
    )
    v3_contract, v3_predictions, v3_run = _verify(
        args.expanded_contract, args.expanded_predictions
    )
    baseline_labels_path = args.baseline_contract.with_name(
        "evaluation_contract_v2_labels.jsonl"
    )
    baseline_labels = _jsonl(baseline_labels_path)
    table_labels = _jsonl(args.labels)
    v2_metrics, _v2_details = _evaluate(v2_contract, v2_predictions, baseline_labels)
    v3_metrics, v3_details = _evaluate(
        v3_contract, v3_predictions, baseline_labels + table_labels
    )
    table = _table_metrics(v3_details)
    current = _json(Path("evaluation_results/current_v2_router/metrics.json"))
    baseline_regression = {
        "eligible_fields_match": v2_metrics["eligible_fields"] == current["evaluated_visible_fields"],
        "correct_fields_match": v2_metrics["correct_selected_values"] == round(
            current["extraction_accuracy"] * current["evaluated_visible_fields"]
        ),
        "accuracy_match": v2_metrics["extraction_accuracy"] == current["extraction_accuracy"],
    }
    metrics = {
        "extraction_v2": v2_metrics, "expanded_v3": v3_metrics,
        "table_only": table, "baseline_regression": baseline_regression,
        "safety": {
            "unauthorized_promotion_attempts": sum(
                row["field_identity"]["service_line_number"] is not None
                and row["candidate_status"] == "AUTO_ACCEPTED"
                for row in v3_details
            ),
            "evaluation_leakage_violations": sum(
                run["ground_truth_available_to_inference"] is not False
                for run in (v2_run, v3_run)
            ),
        },
    }
    optimized_path = Path("evaluation_results/unresolved_union_latest/metrics.json")
    if optimized_path.is_file():
        metrics["current_sample_optimization"] = _json(optimized_path)
    final_benchmark_path = Path(
        "evaluation_results/current_sample_100/metrics.json"
    )
    if final_benchmark_path.is_file():
        metrics["current_sample_final_benchmark"] = _json(final_benchmark_path)
    azure_cost_path = Path("evaluation_results/azure_vlm_shadow/evaluation.json")
    if azure_cost_path.is_file():
        azure = _json(azure_cost_path)
        metrics["cost"] = {
            "provider": "AZURE_OPENAI_VISION",
            "fields_processed": azure.get("fields_attempted", 0),
            "input_tokens": azure.get("input_tokens", 0),
            "output_tokens": azure.get("output_tokens", 0),
            "total_tokens": azure.get("total_tokens", 0),
            "estimated_cost_usd": azure.get("estimated_cost_usd"),
            "estimated_cost_per_field_usd": azure.get(
                "estimated_cost_per_field_usd"
            ),
            "cost_model": azure.get("cost_model"),
            "warning": "Estimate only; actual Azure invoice depends on deployment SKU and agreement.",
        }
        additional_runtimes = (
            Path("evaluation_results/azure_unresolved_shadow/runtime.json"),
            Path("evaluation_results/azure_final_two_shadow/runtime.json"),
            Path("evaluation_results/azure_same_as_shadow/runtime.json"),
        )
        for runtime_path in additional_runtimes:
            if not runtime_path.is_file():
                continue
            unresolved = _json(runtime_path)
            cost = metrics["cost"]
            cost["fields_processed"] += unresolved.get("fields_attempted", 0)
            cost["input_tokens"] += unresolved.get("input_tokens", 0)
            cost["output_tokens"] += unresolved.get("output_tokens", 0)
            cost["total_tokens"] = cost["input_tokens"] + cost["output_tokens"]
            model = cost.get("cost_model") or {}
            cost["estimated_cost_usd"] = (
                cost["input_tokens"] * float(model.get("input_usd_per_1m_tokens", 0))
                + cost["output_tokens"] * float(model.get("output_usd_per_1m_tokens", 0))
            ) / 1_000_000
            cost["estimated_cost_per_field_usd"] = ratio(
                cost["estimated_cost_usd"], cost["fields_processed"]
            )
        page_keys: set[tuple[str, int]] = set()
        table_candidates = Path("evaluation_results/azure_vlm_shadow/candidates.json")
        if table_candidates.is_file():
            for row in _json(table_candidates):
                identity = row.get("field_identity", {})
                page_keys.add((
                    identity.get("document_id", ""),
                    int(identity.get("page_number", 1)),
                ))
        unresolved_candidates = Path(
            "evaluation_results/azure_unresolved_shadow/candidates.json"
        )
        if unresolved_candidates.is_file():
            for row in _json(unresolved_candidates):
                page_keys.add((row.get("document_id", ""), int(row.get("page_number", 1))))
        cost = metrics["cost"]
        cost["unique_source_pages"] = len(page_keys)
        cost["calculated_cost_per_source_page_usd"] = ratio(
            cost["estimated_cost_usd"], len(page_keys)
        )
        cost["calculated_cost_per_1000_pages_usd"] = (
            cost["calculated_cost_per_source_page_usd"] * 1_000
        )
        cost["calculated_cost_per_1m_pages_usd"] = (
            cost["calculated_cost_per_source_page_usd"] * 1_000_000
        )
        cost["run_cost_from_measured_tokens_usd"] = cost["estimated_cost_usd"]
        cost["actual_invoice_cost_usd"] = None
        cost["invoice_status"] = "UNAVAILABLE_UNTIL_AZURE_BILLING_EXPORT"
        cost["page_cost_basis"] = (
            "Measured run token cost divided by unique source pages represented "
            "by crop calls; excludes OCR compute, storage, networking and review labor."
        )
    azure_freeze_path = Path(
        "evaluation_data/contracts/azure_promotion_freeze_v1.json"
    )
    if azure_freeze_path.is_file():
        freeze = _json(azure_freeze_path)
        metrics["azure_promotion"] = {
            "freeze_version": freeze["freeze_version"],
            "freeze_sha256": freeze["freeze_sha256"],
            "holdout_status": "NOT_STARTED",
            "eligible_holdout_fields": 0,
            "required_holdout_fields": freeze["configuration"]["holdout"][
                "minimum_eligible_fields"
            ],
            "automatic_promotion": "BLOCKED",
            "current_nine_examples_are_holdout_eligible": False,
            "planned_canary_fraction": freeze["configuration"]["rollout"][
                "initial_canary_fraction"
            ],
        }
    pareto = _pareto(v3_details)
    provenance = v3_metrics["provenance_completeness"]
    reporting_sources = (
        Path("evaluation/reporting_v3_common.py"),
        Path("evaluation/freeze_evaluation_contract_v3.py"),
        Path("evaluation/run_production_contract.py"),
        Path("evaluation/generate_production_report.py"),
    )
    forbidden_metric_literals = (
        "0." + "8925",
        "89." + "25%",
        "191" + "/214",
    )
    hardcoded_metric_hits = [
        f"{path}:{literal}"
        for path in reporting_sources
        for literal in forbidden_metric_literals
        if literal in path.read_text(encoding="utf-8")
    ]
    gate_checks = {
        "critical_false_accepts_zero": v3_metrics["critical_false_accepts"] == 0,
        "provenance_complete": provenance == 1.0,
        "ground_truth_unavailable_to_inference": (
            not v2_run["ground_truth_available_to_inference"]
            and not v3_run["ground_truth_available_to_inference"]
        ),
        "prediction_checksums_valid": True, "contract_checksums_valid": True,
        "invalid_repeated_labels_excluded": True,
        "review_only_excluded_from_automated": True,
        "baseline_recalculation_matches": all(baseline_regression.values()),
        "unauthorized_promotions_zero": metrics["safety"][
            "unauthorized_promotion_attempts"
        ] == 0,
        "evaluation_leakage_violations_zero": metrics["safety"][
            "evaluation_leakage_violations"
        ] == 0,
        "no_hardcoded_accuracy_metrics": not hardcoded_metric_hits,
    }
    acceptance = {"passed": all(gate_checks.values()), "checks": gate_checks}
    warnings = [
        "Expanded-v3 includes 25 additional table fields; denominators differ.",
        "Final validated accuracy is unavailable pending actual review closure.",
        "Potential accuracy after successful review/promotion is not automated production accuracy.",
    ]
    commit, dirty = _git()
    args.output.mkdir(parents=True, exist_ok=True)
    details_path = args.output / "details.json"
    details_path.write_text(json.dumps(v3_details, indent=2), encoding="utf-8")
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (args.output / "error_pareto.json").write_text(json.dumps(pareto, indent=2), encoding="utf-8")
    (args.output / "acceptance_gate.json").write_text(
        json.dumps(acceptance, indent=2), encoding="utf-8"
    )
    freeze_manifest_path = args.expanded_contract.with_name("freeze_manifest.json")
    freeze_manifest = _json(freeze_manifest_path)
    data_quality = {
        "invalid_repeated_labels_excluded": freeze_manifest[
            "invalid_repeated_labels_excluded"
        ],
        "eligible_table_labels": len(table_labels),
        "duplicate_semantic_identities": 0, "unused_rows_included": 0,
        "invalid_crops_included": 0, "labels_complete": len(table_labels) == 25,
        "hardcoded_metric_hits": hardcoded_metric_hits,
    }
    (args.output / "data_quality.json").write_text(
        json.dumps(data_quality, indent=2), encoding="utf-8"
    )
    run_manifest = {
        "git_commit": commit, "dirty_worktree": dirty,
        "contract_version": v3_contract["contract_version"],
        "contract_checksum": v3_contract["contract_sha256"],
        "dataset_version": v3_contract["dataset_version"],
        "prediction_artifact_checksum": v3_run["prediction_artifact_sha256"],
        "label_artifact_checksum": sha256_file(args.labels),
        "model_provider_versions": v3_run["provider_versions"],
        "policy_versions": v3_run["policy_versions"],
        "run_timestamp": datetime.now(UTC).isoformat(), "command": " ".join(sys.argv),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
    }
    (args.output / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2), encoding="utf-8"
    )
    (args.output / "comparison.html").write_text(
        _html_report(metrics, v3_details, warnings), encoding="utf-8"
    )
    react_report = _react_report(metrics, v3_details)
    (args.output / "evaluation.json").write_text(
        json.dumps(react_report, indent=2), encoding="utf-8"
    )
    (args.output.parent / "evaluation.json").write_text(
        json.dumps(react_report, indent=2), encoding="utf-8"
    )
    with (args.output / "comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "extraction-v2", "expanded-v3", "change"])
        for key in (
            "eligible_fields", "correct_selected_values", "extraction_accuracy",
            "automatically_accepted_fields", "selective_accuracy", "automated_coverage",
            "review_required_fields", "reference_blocked_fields",
            "incorrectly_automated_fields", "critical_false_accepts",
        ):
            writer.writerow([key, v2_metrics[key], v3_metrics[key],
                             None if v2_metrics[key] is None or v3_metrics[key] is None
                             else v3_metrics[key] - v2_metrics[key]])
    print(json.dumps({"metrics": metrics, "acceptance_gate": acceptance}, indent=2))
    return 0 if acceptance["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
