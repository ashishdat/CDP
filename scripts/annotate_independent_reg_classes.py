#!/usr/bin/env python3
"""Audit cached REG page roles without exporting claim data or rewriting metrics.

Empty OCR, unknown pages and claim forms must never be marked irreducible.
Non-claim signatures remain candidates until page-role verification is supplied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from packages.recovery.independent_failures import NON_CLAIM_CANDIDATES, classify_page_text
from scripts.audit_independent_failures import latest_rows as read_latest_rows

ROOT400 = Path("evaluation_results/hackathon_400_remainder_independent_v13c")
ROOT600 = Path("evaluation_results/hackathon_600_independent_v13c")


def classify_text(text: str) -> str:
    role = classify_page_text(text)
    return "CLAIM_FORM" if role.value in {"CMS1500", "UB04", "CLAIM_FORM"} else (
        "OTHER" if role.value == "UNKNOWN" else role.value)


def latest_rows(ledger: Path) -> dict[str, dict]:
    if not ledger.is_file():
        return {}
    rows, _ = read_latest_rows(ledger)
    return {row["claim_id"]: row for row in rows}


def annotate_row(row: dict, text: str, *, text_available: bool) -> dict:
    role = classify_page_text(text)
    if not text_available:
        resolution = "MISSING_PAGE_TEXT_REQUIRES_REVIEW"
    elif role in NON_CLAIM_CANDIDATES:
        resolution = "NON_CLAIM_SIGNATURE_REQUIRES_VERIFICATION"
    elif role.value in {"CMS1500", "UB04", "CLAIM_FORM"}:
        resolution = "RECOVERABLE_FORM_REQUIRES_REGISTRATION_DIAGNOSIS"
    else:
        resolution = "INSUFFICIENT_EVIDENCE_REQUIRES_REVIEW"
    # Preserve the operational outcome; annotation is not acceptance evidence.
    updated = dict(row)
    updated.update(reg_class=classify_text(text) if text_available else "MISSING_OCR_EVIDENCE", reg_resolution=resolution,
                   reg_class_evidence={"source": "CACHED_PAGE_TEXT", "available": text_available,
                                       "sha256": hashlib.sha256(text.encode()).hexdigest() if text_available else None,
                                       "verified_non_claim": False},
                   reg_audit_version="independent-failure-recovery-v2")
    return updated


def write_annotations(root: Path, records: list[dict], ledger_digest: str) -> Path:
    """Publish a separate audit snapshot; never rewrite operational evidence.

    Consumers must compare ledger_sha256 with the current ledger before using
    this snapshot. A concurrent runner may make it stale, never authoritative.
    """
    target = root / "reg_annotations.json"
    payload = {"version": "independent-failure-recovery-v2",
               "ledger_sha256": ledger_digest, "operational_authority": False,
               "records": records}
    descriptor, temporary = tempfile.mkstemp(prefix=".reg_annotations-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2) + "\n")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, action="append")
    parser.add_argument("--output", type=Path, default=Path("docs/metrics/independent_reg_audit_v2.json"))
    parser.add_argument("--apply", action="store_true", help="Write reg_annotations.json audit snapshots; never modify results")
    args = parser.parse_args()
    records, classes = [], Counter()
    roots = args.run_root or [ROOT400, ROOT600]
    for root in roots:
        root = root.resolve()
        rows, ledger_digest = read_latest_rows(root / "results.jsonl")
        root_records = []
        for row in rows:
            if row.get("disposition") != "REGISTRATION_FAILED":
                continue
            claim = (root / "claims" / row["claim_id"]).resolve()
            if not claim.is_relative_to(root / "claims"):
                raise ValueError("Claim artifact path escapes the run directory")
            text_path = claim / "unstructured_reg/di_text.txt"
            available = text_path.is_file()
            text = text_path.read_text(encoding="utf-8", errors="replace") if available else ""
            updated = annotate_row(row, text, text_available=available)
            classes[updated["reg_class"]] += 1
            record = {"run_root": str(root), "claim_id": row["claim_id"],
                            "reg_class": updated["reg_class"], "reg_resolution": updated["reg_resolution"],
                            "evidence": updated["reg_class_evidence"]}
            records.append(record)
            root_records.append(record)
        if args.apply:
            write_annotations(root, root_records, ledger_digest)
    report = {"version": "independent-failure-recovery-v2", "applied": args.apply,
              "count": len(records), "reg_classes": dict(classes), "records": records,
              "cloud_calls": 0, "irreducible_claims_established": 0,
              "claim_page_denominator": None,
              "denominator_reason": "Requires verified page roles; registration failure is not proof of a non-claim page"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"count": len(records), "reg_classes": dict(classes), "applied": args.apply, "cloud_calls": 0}))


if __name__ == "__main__":
    main()
