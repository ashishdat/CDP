"""Publish pilot status without loading or exposing unauthorized reference data."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    report = {
        "provider_adapter": "AuthorizedJsonMemberProvider",
        "status": "AWAITING_AUTHORIZED_DATASET",
        "dataset_version": None,
        "records_loaded": 0,
        "policy_version": "reference-match-v1",
        "required_attributes": ["member_id_exact", "dob_exact", "name_similarity"],
        "contradiction_checks": ["address_or_zip"],
        "name_only_auto_accept": False,
        "evaluation_ground_truth_used": False,
        "audit_metadata": ["provider", "dataset_version", "policy_version", "decision"],
        "reference_values_persisted_in_ocr_logs": False,
    }
    output = Path("evaluation_results/reference_pilot_status.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
