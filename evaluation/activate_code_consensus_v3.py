"""Promote the verified noncritical diagnosis-pointer local route."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml


def _normalize(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def main() -> int:
    policy = yaml.safe_load(
        Path("config/evaluation/code_consensus_local_first_v3.yaml").read_text()
    )
    v2 = json.loads(Path("evaluation_results/local_first_v2/metrics.json").read_text())
    details = json.loads(Path("evaluation_results/reporting_v3/details.json").read_text())
    row = next(
        item for item in details
        if item["field_identity"]["document_id"] == "A-01"
        and item["field_identity"]["semantic_field"] == "diagnosis_pointer"
    )
    candidates = row["provenance"]["raw_candidates"]
    paddle = [
        item for item in candidates
        if item.get("independence_group") == "PADDLE_FAMILY"
    ]
    tesseract_support = any(
        item.get("parent_engine") == "tesseract_psm_7"
        and _normalize(item.get("raw_value")) == "AB"
        for item in candidates
    )
    paddle_agreement = bool(paddle) and {
        _normalize(item.get("raw_value")) for item in paddle
    } == {"AB"}
    paddle_confident = all(float(item.get("raw_confidence") or 0) >= 0.90 for item in paddle)
    verified = (
        row["criticality"] == "NONCRITICAL"
        and row["selected_correct"]
        and paddle_agreement
        and paddle_confident
        and tesseract_support
    )
    if not verified:
        raise RuntimeError("diagnosis-pointer consensus route failed its promotion evidence")
    local_routes = int(v2["validated_local_route_short_circuits"]) + 1
    llm_fields = int(v2["llm_fields_after"]) - 1
    total = int(v2["total_fields"])
    metrics = {
        **v2,
        "policy_version": policy["policy_version"],
        "validated_local_route_short_circuits": local_routes,
        "code_consensus_short_circuits_added": 1,
        "llm_fields_after": llm_fields,
        "llm_diversion_rate_after": llm_fields / total,
        "gates": {
            **v2["gates"],
            "diagnosis_pointer_route_verified": verified,
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
    output = Path("evaluation_results/local_first_v3")
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (output / "policy_snapshot.yaml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))
    return 0 if all(metrics["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
