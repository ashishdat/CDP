"""Audit saved independent-sample failures locally; never rerun OCR or cloud."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from packages.recovery.independent_failures import VERSION, analyze_failure


def acquisition_findings(claim: Path, row: dict) -> list[dict]:
    """Inspect saved acquisition decisions without emitting patient values."""
    from packages.extraction_recovery.cloud_stop_ladder import should_skip_all_cloud
    from packages.extraction_recovery.dob_confirmation import dob_reads_confirmed

    path = claim / 'ocr/OCRCandidates.json'
    if not path.is_file():
        return []
    ocr = json.loads(path.read_text(encoding='utf-8'))
    blockers = set(row.get('critical_blockers') or [])
    findings = []
    for field in ocr.get('fields') or []:
        name = field.get('field')
        if name not in blockers:
            continue
        skipped = (field.get('cloud_stop_ladder') or {}).get('skipped')
        finding = {'field_name': name, 'candidate_count': len(field.get('candidates') or []),
                   'recorded_cloud_skip': skipped,
                   'settled_under_current_acquisition_gate': should_skip_all_cloud(name, field)}
        if name == 'patient_dob':
            finding['independent_date_confirmation'] = dob_reads_confirmed(
                field.get('candidates'), field.get('attempts'))
        finding['premature_recorded_stop'] = (skipped == 'LOCALS_SETTLED'
            and not finding['settled_under_current_acquisition_gate'])
        findings.append(finding)
    return findings


def latest_rows(ledger: Path) -> tuple[list[dict], str]:
    payload = ledger.read_bytes()
    latest = {}
    lines = payload.decode("utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if index == len(lines) - 1 and not line.endswith("\n"):
            continue  # An uncommitted append is not a completed ledger record.
        row = json.loads(line)
        key = row.get("claim_id") or row.get("document")
        if not key:
            raise ValueError("Ledger row lacks document identity")
        latest[key] = row
    return list(latest.values()), hashlib.sha256(payload).hexdigest()


def audit(run_roots: list[Path], output: Path) -> dict:
    cohorts, cases = [], []
    for root in run_roots:
        root = root.resolve()
        rows, digest = latest_rows(root / "results.jsonl")
        counts = Counter()
        dispositions = Counter()
        blockers = Counter()
        acquisition_counts = Counter()
        categories = Counter()
        for row in rows:
            if not row.get("finished"):
                continue
            dispositions[str(row.get("disposition") or "UNKNOWN")] += 1
            claim = (root / "claims" / str(row.get("claim_id") or "")).resolve()
            if not claim.is_relative_to(root / "claims"):
                raise ValueError("Claim artifact path escapes the run directory")
            text_path = claim / "unstructured_reg/di_text.txt"
            text = text_path.read_text(encoding="utf-8", errors="replace") if text_path.is_file() else None
            from scripts.run_hackathon_1000_cascade import _registration_stage_diagnostics
            diagnosed = {**_registration_stage_diagnostics(claim / 'application'), **row}
            analysis = analyze_failure(diagnosed, page_text=text)
            categories[analysis['failure_category']] += 1
            for finding in analysis["findings"]:
                counts[finding["mechanism"]] += 1
            blockers.update(row.get("critical_blockers") or ())
            if analysis["findings"]:
                acquisition = acquisition_findings(claim, row)
                acquisition_counts.update(f['field_name'] for f in acquisition
                                          if f['premature_recorded_stop'])
                cases.append({"run_root": str(root), "claim_id": row.get("claim_id"),
                              "disposition": row.get("disposition"), "analysis": analysis,
                              "acquisition_findings": acquisition})
        completed = [r for r in rows if r.get('finished') and r.get('completed')]
        stp = sum(bool(r.get('true_stp')) for r in completed)
        hitl = sum(r.get('disposition') == 'HITL' for r in completed)
        selected = None
        runtime = root / 'benchmark_runtime.json'
        if runtime.is_file():
            selected = json.loads(runtime.read_text(encoding='utf-8')).get('sample_size')
        cohorts.append({"run_root": str(root), "ledger_sha256": digest,
                        "finished": sum(dispositions.values()), "dispositions": dict(dispositions),
                        "selected": selected,
                        "pending": selected - sum(dispositions.values()) if selected is not None else None,
                        "completed": len(completed), 'stp_count': stp, 'hitl_count': hitl,
                        'stp_rate_of_completed': stp / len(completed) if completed else None,
                        'hitl_rate_of_completed': hitl / len(completed) if completed else None,
                        'registration_fallback_hitl_count': sum(r.get('registration_ok') is False
                            and r.get('disposition') == 'HITL' for r in completed),
                        'premature_recorded_stops_by_field': dict(acquisition_counts),
                        "blockers": dict(blockers), "mechanisms": dict(counts)})
        cohorts[-1]['failure_category_counts'] = dict(categories)
    report = {"version": VERSION, "scope": "Saved ledger and cached text audit only",
              "cohorts": cohorts, "cases": cases,
              "mechanism_counts_can_overlap": True,
              "physical_causes_require_additional_evidence": True,
              "accuracy": None, "accuracy_status": "INDEPENDENT_ADJUDICATED_LABELS_REQUIRED",
              "acceptance_thresholds_changed": False, "cloud_calls": 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.run_root, args.output)
    print(json.dumps({"cohorts": len(report["cohorts"]), "failure_cases": len(report["cases"]),
                      "report": str(args.output), "cloud_calls": 0}))


if __name__ == "__main__":
    main()
